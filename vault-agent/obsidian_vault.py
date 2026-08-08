"""Read-only access to an Obsidian vault (a folder of wiki-linked markdown notes).

A `Vault` exposes exactly three operations, designed to be handed to an agent as
tools: list the notes, search across them, and read one note (or one section of a
long note). Only markdown files (`.md`) count as notes; attachments (PDFs, images,
...) are ignored. Notes reference each other with `[[wikilinks]]`; `read_note`
resolves the same targets Obsidian would (`[[Name]]`, `[[Name|alias]]`,
`[[Name#Heading]]`, with or without the `.md` extension, case-insensitive).

`graph()`/`graph_settings()` expose the same link network Obsidian's own Graph
View draws, for `graph_view.py` to render - not an agent tool (an LLM has no use
for x/y coordinates), just a second read-only view of the vault.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

# Physics/display defaults for the force-directed graph render, used whenever a
# vault has no .obsidian/graph.json (or one missing these keys) - copied from
# Obsidian's own factory defaults so an unconfigured vault still looks right.
DEFAULT_GRAPH_SETTINGS: dict[str, object] = {
    "showOrphans": True,
    "showArrow": False,
    "textFadeMultiplier": 0,
    "nodeSizeMultiplier": 1,
    "lineSizeMultiplier": 1,
    "centerStrength": 0.5,
    "repelStrength": 10,
    "linkStrength": 1,
    "linkDistance": 250,
}

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

# A file extension: a dot followed by a letter (so 'NAV 3.0' isn't one), then a few
# alphanumerics. Anything with such an extension that isn't .md is an attachment.
_ATTACHMENT_SUFFIX = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,9}$")


def _is_attachment_target(target: str) -> bool:
    """A wikilink target that names a non-markdown file (PDF, image, ...)."""
    t = target.strip()
    return bool(_ATTACHMENT_SUFFIX.search(t)) and not t.lower().endswith(NOTE_SUFFIXES)


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

    def _index_is_stale(self) -> bool:
        """True if a file this vault indexed no longer exists on disk - it was
        deleted by something other than write_note() (rm, Obsidian, Finder, ...)
        while the process was running."""
        return any(not path.exists() for path in set(self._index.values()))

    def _refresh_index(self) -> None:
        """Rebuild the index from scratch: drops entries for files that vanished
        and picks up any that appeared. Cheap and idempotent, so it is safe to call
        before every read/list/search - it only re-walks the tree, it never raises
        even if the vault is temporarily left with no notes at all."""
        self._index = {}
        self._build_index()

    def _ensure_fresh_index(self) -> None:
        """Refresh the index only when something has actually gone stale, so the
        common case (nothing changed) stays a cheap existence check instead of a
        full re-walk on every call."""
        if self._index_is_stale():
            self._refresh_index()

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
        self._ensure_fresh_index()
        return sorted(set(self._index.values()))

    # ------------------------------------------------------------------ tools

    def list_notes(self) -> list[dict[str, object]]:
        """List every note in the vault with its size and outgoing wikilinks.

        Returns one entry per note: its name (use this with read_note), its size in
        characters, and which other notes it links to.

        A note deleted from disk between the index refresh and this read (a race
        with something other than write_note() - rm, Obsidian, Finder, ...) is
        silently skipped rather than raising; the next call will no longer index it.
        """
        entries: list[dict[str, object]] = []
        for path in self._notes():
            text = _read_text_or_none(path)
            if text is None:
                continue
            links = sorted(
                {
                    t
                    for m in _WIKILINK.finditer(text)
                    if not _is_attachment_target(t := m.group(1).strip())
                }
            )
            entries.append(
                {
                    "note": path.relative_to(self.root).with_suffix("").as_posix(),
                    "chars": len(text),
                    "links_to": links,
                }
            )
        return entries

    def graph(self) -> dict[str, list[dict[str, object]]]:
        """The vault's link graph, the same one Obsidian's Graph View draws: every
        note is a node, plus one phantom node per wikilink target that resolves to
        no note (kept, not dropped - Obsidian shows these too unless hideUnresolved
        is set). Edges are deduplicated and undirected (Obsidian draws no
        arrowheads), one per unique note pair regardless of link count.

        Returns {"nodes": [{"id", "label", "resolved", "degree"}],
        "links": [{"source", "target"}]} - "id" is the note's vault-relative path
        without extension (matches list_notes' "note" field) for real notes, or the
        raw unresolved target text for phantom nodes.

        A note deleted from disk between the index refresh and this read (a race
        with something other than write_note()) is treated as having no outgoing
        links rather than raising.
        """
        notes = self._notes()
        ids = {path: path.relative_to(self.root).with_suffix("").as_posix() for path in notes}
        nodes: dict[str, dict[str, object]] = {
            nid: {"id": nid, "label": path.stem, "resolved": True} for path, nid in ids.items()
        }
        edges: set[tuple[str, str]] = set()
        for path in notes:
            src = ids[path]
            text = _read_text_or_none(path)
            if text is None:
                continue
            for m in _WIKILINK.finditer(text):
                target = m.group(1).strip()
                if not target or _is_attachment_target(target):
                    continue
                resolved = self._resolve(target)
                if resolved is not None:
                    dst = ids[resolved]
                else:
                    dst = target
                    nodes.setdefault(dst, {"id": dst, "label": target, "resolved": False})
                if dst != src:
                    edges.add(tuple(sorted((src, dst))))

        degree = dict.fromkeys(nodes, 0)
        for a, b in edges:
            degree[a] += 1
            degree[b] += 1
        for nid, node in nodes.items():
            node["degree"] = degree[nid]

        return {
            "nodes": list(nodes.values()),
            "links": [{"source": a, "target": b} for a, b in sorted(edges)],
        }

    def graph_settings(self) -> dict[str, object]:
        """Physics/display settings for the graph render: the vault's own
        `.obsidian/graph.json` (Obsidian writes this whenever the user tweaks the
        Graph View sliders) layered over DEFAULT_GRAPH_SETTINGS, so the rendered
        graph matches how this vault actually looks in Obsidian when it says so,
        and falls back sanely when it doesn't."""
        settings = dict(DEFAULT_GRAPH_SETTINGS)
        path = self.root / ".obsidian" / "graph.json"
        try:
            settings.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
        return settings

    def search_vault(self, query: str) -> list[dict[str, object]]:
        """Search all notes for the query terms and return the best-matching excerpts.

        Args:
            query: What to look for, as a few keywords (matched case-insensitively
                against note titles and bodies).

        A note deleted from disk between the index refresh and this read (a race
        with something other than write_note()) is silently skipped.
        """
        terms = [t for t in _key(query).split() if len(t) > 1]
        if not terms:
            return []
        scored: list[tuple[float, Path, str]] = []
        for path in self._notes():
            text = _read_text_or_none(path)
            if text is None:
                continue
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

        A note that has disappeared from disk since it was indexed (deleted by
        something other than write_note() - rm, Obsidian, Finder, ...) is treated
        the same as an unknown name instead of raising.
        """
        target = name.strip().strip("[]").split("|")[0].split("#")[0].strip()
        if _is_attachment_target(target):
            return (
                f"{target!r} is an attachment (PDF/image/...), not a markdown note. "
                "Only .md notes are part of this knowledge base — ignore links to attachments."
            )
        self._ensure_fresh_index()
        path = self._resolve(name)
        text = _read_text_or_none(path) if path is not None else None
        if text is None:
            if path is not None:  # was indexed but vanished between resolve and read
                self._refresh_index()
            known = ", ".join(p.stem for p in self._notes()[:40])
            return f"No note named {name!r} in this vault. Notes include: {known}"
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
        self._refresh_index()  # make the new note immediately searchable/readable
        return path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_text_or_none(path: Path) -> str | None:
    """`_read_text`, but tolerant of the file having disappeared from disk since
    it was indexed (deleted externally by rm/Obsidian/Finder while the app is
    running) - returns None instead of raising, so callers can drop the entry."""
    try:
        return _read_text(path)
    except OSError:
        return None


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
