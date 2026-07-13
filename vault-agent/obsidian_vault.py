"""Read-only access to an Obsidian vault (a folder of wiki-linked markdown notes).

A `Vault` exposes exactly three operations, designed to be handed to an agent as
tools: list the notes, search across them, and read one note (or one section of a
long note). Only markdown files (`.md`) count as notes; attachments (PDFs, images,
...) are ignored. Notes reference each other with `[[wikilinks]]`; `read_note`
resolves the same targets Obsidian would (`[[Name]]`, `[[Name|alias]]`,
`[[Name#Heading]]`, with or without the `.md` extension, case-insensitive).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

# Only these file types are notes; anything else in the vault is an attachment.
NOTE_SUFFIXES = (".md",)

# Notes longer than this come back as a heading outline instead of full text,
# so a 500 KB regulation dump doesn't flood the model's context.
MAX_NOTE_CHARS = 24_000

# How much text to show around each search hit, and how many hits to return.
SNIPPET_CHARS = 300
MAX_RESULTS = 5

_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _key(s: str) -> str:
    """Case- and Unicode-normalization-insensitive comparison key. macOS stores
    filenames NFD-decomposed while typed queries are usually NFC; without this,
    'Ü' from the keyboard never matches 'Ü' from the filesystem."""
    return unicodedata.normalize("NFC", s).casefold()


class Vault:
    """One Obsidian vault rooted at a directory of .md files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"Vault path is not a directory: {self.root}")
        self._index: dict[str, Path] = {}
        self._build_index()
        if not self._index:
            raise ValueError(f"No markdown notes found in vault: {self.root}")

    # ---------------------------------------------------------------- indexing

    def _build_index(self) -> None:
        """Map note names to files. Wikilinks use the basename, so index both the
        basename and the vault-relative path (Obsidian disambiguates the same way)."""
        for path in sorted(p for p in self.root.rglob("*") if p.suffix.lower() in NOTE_SUFFIXES):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            if any(part.startswith(".") for part in rel.parts):
                continue  # .obsidian, .trash, .claude, ...
            self._index.setdefault(_key(rel.with_suffix("").as_posix()), path)
            self._index.setdefault(_key(path.stem), path)

    def _resolve(self, name: str) -> Path | None:
        """Resolve a note name or wikilink target to a file, like Obsidian would."""
        target = name.strip().strip("[]")
        target = target.split("|")[0].split("#")[0].strip()
        for suffix in NOTE_SUFFIXES:
            if target.lower().endswith(suffix):
                target = target[: -len(suffix)]
                break
        return self._index.get(_key(target))

    def _notes(self) -> list[Path]:
        return sorted(set(self._index.values()))

    # ------------------------------------------------------------------ tools

    def list_notes(self) -> list[dict[str, object]]:
        """List every note in the vault with its size and outgoing wikilinks.

        Returns one entry per note: its name (use this with read_note), its size in
        characters, and which other notes it links to.
        """
        entries: list[dict[str, object]] = []
        for path in self._notes():
            text = _read_text(path)
            links = sorted({m.group(1).strip() for m in _WIKILINK.finditer(text)})
            entries.append(
                {
                    "note": path.relative_to(self.root).with_suffix("").as_posix(),
                    "chars": len(text),
                    "links_to": links,
                }
            )
        return entries

    def search_vault(self, query: str) -> list[dict[str, object]]:
        """Search all notes for the query terms and return the best-matching excerpts.

        Args:
            query: What to look for, as a few keywords (matched case-insensitively
                against note titles and bodies).
        """
        terms = [t for t in _key(query).split() if len(t) > 1]
        if not terms:
            return []
        scored: list[tuple[float, Path, str]] = []
        for path in self._notes():
            text = _read_text(path)
            haystack = _key(f"{path.stem}\n{text}")
            hits = {t: haystack.count(t) for t in terms}
            matched = [t for t, n in hits.items() if n]
            if not matched:
                continue
            # Notes matching more distinct terms first; total frequency breaks ties.
            score = len(matched) * 1000 + sum(hits.values())
            scored.append((score, path, text))
        scored.sort(key=lambda s: s[0], reverse=True)

        results = []
        for _, path, text in scored[:MAX_RESULTS]:
            results.append(
                {
                    "note": path.relative_to(self.root).with_suffix("").as_posix(),
                    "excerpt": _excerpt(text, terms),
                }
            )
        return results

    def read_note(self, name: str, section: str = "") -> str:
        """Read a note by name or wikilink target, e.g. 'INDEX' or '[[GIROFix_Csatlakozas]]'.

        Args:
            name: The note's name as shown by list_notes/search_vault, or a wikilink
                target copied from another note.
            section: Optional part of a long note to read: a heading, or 'chunk N'
                to page through the raw text.

        Long notes return a heading outline instead of full text; pass one of the
        listed headings (or 'chunk N') as `section` to read that part.
        """
        path = self._resolve(name)
        if path is None:
            known = ", ".join(p.stem for p in self._notes()[:40])
            return f"No note named {name!r} in this vault. Notes include: {known}"
        text = _read_text(path)
        n_chunks = (len(text) + MAX_NOTE_CHARS - 1) // MAX_NOTE_CHARS

        if section:
            chunk = re.fullmatch(r"(?:chunk|part)\s*(\d+)", section.strip(), re.IGNORECASE)
            if chunk:
                i = min(max(int(chunk.group(1)), 1), n_chunks)
                start = (i - 1) * MAX_NOTE_CHARS
                return (
                    f"[{path.stem} — chunk {i}/{n_chunks}]\n"
                    + text[start : start + MAX_NOTE_CHARS]
                )
            body = _section(text, section)
            if body is None:
                return (
                    f"No heading matching {section!r} in {path.stem!r}. "
                    f"Outline:\n{_outline(text)}"
                )
            return body if len(body) <= MAX_NOTE_CHARS else body[:MAX_NOTE_CHARS] + "\n[truncated]"

        if len(text) > MAX_NOTE_CHARS:
            return (
                f"{path.stem!r} is long ({len(text)} chars). Pass a heading below as "
                f"`section` to read that part, or 'chunk 1'…'chunk {n_chunks}' to page "
                f"through the raw text:\n{_outline(text)}"
            )
        return text

    def write_note(self, name: str, content: str, model: str | None = None) -> Path:
        """Write `content` to a note named `name` at the vault root, then re-index.

        The note follows the vault's format: an `# <name>` H1 heading, a metadata line
        recording the save date-time (and `model` when given), then the content (a
        heading already at the start of `content` is used in place of the generated
        one). An existing note of the same name is overwritten. Returns the file written.

        The name is used as the filename stem, so it may not be empty or contain path
        separators or `..` (notes are always written to the vault root, never outside).
        """
        stem = name.strip().removesuffix(".md").strip()
        if not stem:
            raise ValueError("Note name is empty.")
        if "/" in stem or "\\" in stem or ".." in stem or Path(stem).is_absolute():
            raise ValueError(f"Invalid note name (no path separators or '..'): {name!r}")

        meta = f"*Saved {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        meta += f" · model: {model}*" if model else "*"

        body = content.strip("\n")
        if re.match(r"^\s*#\s", body):
            heading, _, rest = body.partition("\n")
            body = f"{heading.rstrip()}\n\n{meta}\n\n{rest.lstrip(chr(10))}"
        else:
            body = f"# {stem}\n\n{meta}\n\n{body}"
        path = self.root / f"{stem}.md"
        path.write_text(body.rstrip("\n") + "\n", encoding="utf-8")
        self._build_index()  # make the new note immediately searchable/readable
        return path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _outline(text: str) -> str:
    lines = [f"{'  ' * (len(m.group(1)) - 1)}- {m.group(2)}" for m in _HEADING.finditer(text)]
    return "\n".join(lines) if lines else "(no headings)"


def _section(text: str, heading: str) -> str | None:
    """Return the body under the first heading matching `heading` (case-insensitive
    substring), up to the next heading of the same or higher level."""
    matches = list(_HEADING.finditer(text))
    want = _key(heading.strip().lstrip("#").strip())
    for i, m in enumerate(matches):
        if want in _key(m.group(2)):
            level = len(m.group(1))
            end = len(text)
            for nxt in matches[i + 1 :]:
                if len(nxt.group(1)) <= level:
                    end = nxt.start()
                    break
            return text[m.start() : end].strip()
    return None


def _excerpt(text: str, terms: list[str]) -> str:
    """A few windows of context around the first hits of distinct terms."""
    # NFC first so offsets line up with the displayed text even on NFD sources.
    text = unicodedata.normalize("NFC", text)
    lower = text.casefold()
    spans: list[tuple[int, int]] = []
    for term in terms:
        pos = lower.find(term)
        if pos < 0:
            continue
        start = max(0, pos - SNIPPET_CHARS // 2)
        end = min(len(text), pos + SNIPPET_CHARS // 2)
        # Merge with the previous window if they overlap.
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        elif len(spans) < 3:
            spans.append((start, end))
    parts = [text[a:b].strip() for a, b in spans]
    return " […] ".join(parts)
