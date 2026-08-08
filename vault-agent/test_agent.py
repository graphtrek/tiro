"""Validation for the Obsidian vault agent.

    uv run python test_agent.py            # unit tests only (no API calls, free)
    uv run python test_agent.py --live     # also run the end-to-end LLM checks

The unit tests build a throwaway vault in a temp dir and prove the vault layer and
the capability wiring; --live proves the composed agent actually answers from the
notes (needs a running model, and a vault via VAULT_PATH or the default temp one).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from obsidian_vault import MAX_NOTE_CHARS, Vault


def check(name: str, cond: bool) -> bool:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    return cond


def _raises(exc, fn) -> bool:
    """True if calling `fn` raises `exc` (a wrong or missing exception is a failure)."""
    try:
        fn()
    except exc:
        return True
    except Exception:  # noqa: BLE001 - the wrong exception type is still a failure
        return False
    return False


def make_vault(root: Path) -> Vault:
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "hidden.md").write_text("must be ignored", encoding="utf-8")
    (root / "INDEX.md").write_text(
        "# Index\n\nStart with [[Coffee Brewing|brewing]] or [[guides/Grinders#Burr]].\n",
        encoding="utf-8",
    )
    (root / "Coffee Brewing.md").write_text(
        "# Coffee Brewing\n\nUse a 1:16 ratio of coffee to water. See [[guides/Grinders]].\n"
        "Scan: ![[beans.pdf]] and [[Tasting Log.txt]].\n",
        encoding="utf-8",
    )
    (root / "guides").mkdir()
    (root / "guides" / "Grinders.md").write_text(
        "# Grinders\n\n## Burr\n\nBurr grinders are consistent.\n\n## Blade\n\n"
        + "Blade grinders are cheap. " * 2000,  # push the note past MAX_NOTE_CHARS
        encoding="utf-8",
    )
    (root / "Tasting Log.txt").write_text("Not a note: only .md files are notes.\n", encoding="utf-8")
    (root / "beans.pdf").write_bytes(b"%PDF-1.4 an attachment, not a note")
    return Vault(root)


def test_log_cleanup() -> bool:
    """Log file is always deleted at startup, even with LOG_LEVEL=OFF."""
    import logging
    import os

    from capabilities import DEFAULT_LOG_FILE, setup_logging

    ok = True

    # Create a log file first.
    log_file = DEFAULT_LOG_FILE
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("old log content\n", encoding="utf-8")

    # Clear any handlers from previous tests so setup_logging() treats this as
    # the first call of the process (the deletion only happens then).
    log = logging.getLogger("orbit")
    for handler in log.handlers[:]:
        log.removeHandler(handler)
    log.disabled = False

    old_level = os.environ.get("LOG_LEVEL")
    try:
        # With LOG_LEVEL=OFF, the log file should still be deleted.
        os.environ["LOG_LEVEL"] = "OFF"
        setup_logging()
        ok &= check("log file deleted with LOG_LEVEL=OFF", not log_file.exists())
    finally:
        if old_level is not None:
            os.environ["LOG_LEVEL"] = old_level
        else:
            os.environ.pop("LOG_LEVEL", None)

    return ok


def test_external_delete_recovery() -> bool:
    """DEF-014 regression: a note removed from disk by something other than
    Vault.write_note() (rm, Obsidian, Finder, ...) while the process is running
    must not crash list_notes/read_note/search_vault/graph with an uncaught
    FileNotFoundError - it should just drop out of the results, and the index
    should recover (or at least not wedge) on the very next read, with no
    restart needed."""
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "Keep.md").write_text("# Keep\n\nStays around.\n", encoding="utf-8")
        (root / "Gone.md").write_text("# Gone\n\nWill be deleted externally.\n", encoding="utf-8")
        vault = Vault(root)

        ok &= check(
            "both notes visible before deletion",
            {e["note"] for e in vault.list_notes()} == {"Keep", "Gone"},
        )

        (root / "Gone.md").unlink()  # simulate rm / Obsidian / Finder, not vault.write_note()

        ok &= check("list_notes doesn't raise after an external delete", not _raises(FileNotFoundError, vault.list_notes))
        ok &= check(
            "list_notes drops the deleted note",
            {e["note"] for e in vault.list_notes()} == {"Keep"},
        )

        ok &= check(
            "read_note doesn't raise after an external delete",
            not _raises(FileNotFoundError, lambda: vault.read_note("Gone")),
        )
        ok &= check("read_note reports the deleted note as unknown", "No note named" in vault.read_note("Gone"))

        ok &= check(
            "search_vault doesn't raise after an external delete",
            not _raises(FileNotFoundError, lambda: vault.search_vault("deleted externally")),
        )
        ok &= check(
            "search_vault no longer surfaces the deleted note",
            all(hit["note"] != "Gone" for hit in vault.search_vault("deleted externally")),
        )

        ok &= check("graph doesn't raise after an external delete", not _raises(FileNotFoundError, vault.graph))
        ok &= check("graph drops the deleted note", "Gone" not in {n["id"] for n in vault.graph()["nodes"]})

        # The index recovered: the surviving note is unaffected and keeps working.
        ok &= check("index recovers: Keep still reads fine", "Stays around" in vault.read_note("Keep"))
        ok &= check(
            "index recovers: it doesn't wedge - Keep still shows up in list_notes",
            {e["note"] for e in vault.list_notes()} == {"Keep"},
        )
    return ok


def unit_tests() -> bool:
    print("unit tests (no API):")
    ok = True

    with tempfile.TemporaryDirectory() as tmp:
        vault = make_vault(Path(tmp))

        notes = vault.list_notes()
        names = {e["note"] for e in notes}
        ok &= check("indexes notes recursively", names == {"INDEX", "Coffee Brewing", "guides/Grinders"})
        ok &= check("skips hidden dirs like .obsidian", "hidden" not in str(names))
        ok &= check("lists only .md files, not attachments", "Tasting Log" not in names and "beans" not in str(names))
        index = next(e for e in notes if e["note"] == "INDEX")
        ok &= check(
            "list_notes extracts wikilink targets (alias/heading stripped)",
            index["links_to"] == ["Coffee Brewing", "guides/Grinders"],
        )
        brewing = next(e for e in notes if e["note"] == "Coffee Brewing")
        ok &= check(
            "links_to drops attachment links but keeps note links",
            brewing["links_to"] == ["guides/Grinders"],
        )

        g = vault.graph()
        gnodes = {n["id"]: n for n in g["nodes"]}
        ok &= check("graph has one node per note", set(gnodes) == {"INDEX", "Coffee Brewing", "guides/Grinders"})
        ok &= check("graph node label is the basename", gnodes["guides/Grinders"]["label"] == "Grinders")
        ok &= check("graph nodes for real notes are resolved", all(n["resolved"] for n in gnodes.values()))
        gedges = {frozenset((l["source"], l["target"])) for l in g["links"]}
        ok &= check(
            "graph links alias/heading/plain wikilinks alike",
            gedges
            == {
                frozenset({"INDEX", "Coffee Brewing"}),
                frozenset({"INDEX", "guides/Grinders"}),
                frozenset({"Coffee Brewing", "guides/Grinders"}),
            },
        )
        ok &= check("graph drops attachment-only links (pdf/txt)", len(g["links"]) == 3)
        ok &= check("graph degree counts distinct linked notes", gnodes["INDEX"]["degree"] == 2)

        settings = vault.graph_settings()
        ok &= check(
            "graph_settings falls back to defaults with no .obsidian/graph.json",
            settings["linkDistance"] == 250 and settings["repelStrength"] == 10,
        )
        (vault.root / ".obsidian").mkdir(exist_ok=True)
        (vault.root / ".obsidian" / "graph.json").write_text(
            '{"linkDistance": 999, "showOrphans": false}', encoding="utf-8"
        )
        overridden = vault.graph_settings()
        ok &= check("graph_settings reads the vault's own graph.json", overridden["linkDistance"] == 999)
        ok &= check(
            "graph_settings keeps un-overridden defaults",
            overridden["repelStrength"] == 10 and overridden["showOrphans"] is False,
        )

        from graph_view import render_graph_html

        no_link = render_graph_html(g, settings, vault.root.name)
        ok &= check(
            "render_graph_html omits the back link by default (cli.py's file:// use)",
            '<a class="back"' not in no_link,
        )
        ok &= check(
            "render_graph_html hides the read-in-terminal icon with no back_url",
            "BACK_URL = null" in no_link,
        )
        with_link = render_graph_html(g, settings, vault.root.name, back_url="/")
        ok &= check(
            "render_graph_html adds a back link when given a back_url (web.py's use)",
            '<a class="back" href="/"' in with_link,
        )
        ok &= check(
            "render_graph_html embeds back_url for the read-in-terminal icon",
            'BACK_URL = "/"' in with_link and 'id="pRead"' in with_link,
        )
        from graph_view import TERMINAL_TAB_NAME

        ok &= check(
            "the back link opens a named tab, not the graph's own tab",
            f'target="{TERMINAL_TAB_NAME}"' in with_link and "noopener" in with_link,
        )
        ok &= check(
            "the read-in-terminal icon opens the same named tab (window.open, not location.href)",
            f'window.open(url, "{TERMINAL_TAB_NAME}"' in with_link
            and "window.location.href" not in with_link,
        )

        hits = vault.search_vault("coffee ratio")
        ok &= check("search finds the right note first", hits and hits[0]["note"] == "Coffee Brewing")
        ok &= check("search returns an excerpt with the hit", "1:16" in hits[0]["excerpt"])
        ok &= check("search returns nothing for gibberish", vault.search_vault("zzzqqq") == [])

        ok &= check("read_note resolves a plain name", "1:16" in vault.read_note("Coffee Brewing"))
        ok &= check("read_note resolves a [[wikilink|alias]]", "1:16" in vault.read_note("[[Coffee Brewing|brewing]]"))
        ok &= check("read_note resolves basename across folders", "Burr" in vault.read_note("Grinders", section="Burr"))
        ok &= check("read_note is case-insensitive", "1:16" in vault.read_note("coffee brewing"))
        ok &= check("read_note won't read a non-.md file", "No note named" in vault.read_note("Tasting Log"))
        ok &= check("unknown note lists alternatives", "Notes include" in vault.read_note("Nope"))
        pdf_reply = vault.read_note("beans.pdf")
        ok &= check("read_note refuses an attachment by name", "attachment" in pdf_reply and "%PDF" not in pdf_reply)
        wikilink_reply = vault.read_note("[[beans.pdf]]")
        ok &= check("read_note refuses an attachment wikilink", "attachment" in wikilink_reply and "%PDF" not in wikilink_reply)

        long_note = vault.read_note("guides/Grinders")
        ok &= check("long notes return an outline, not full text", "Blade" in long_note and len(long_note) < MAX_NOTE_CHARS)
        section = vault.read_note("guides/Grinders", section="Burr")
        ok &= check("section reads stop at the next same-level heading", "consistent" in section and "cheap" not in section)
        chunk2 = vault.read_note("guides/Grinders", section="chunk 2")
        ok &= check("long notes can be paged with 'chunk N'", chunk2.startswith("[Grinders — chunk 2/") and "cheap" in chunk2)

        # write_note saves a formatted note and re-indexes it in place.
        written = vault.write_note("My New Note", "The body of the note. See [[INDEX]].", model="test:model-x")
        ok &= check("write_note creates a .md file at the vault root", written == vault.root / "My New Note.md")
        saved = written.read_text(encoding="utf-8")
        ok &= check("write_note adds an # H1 heading from the name", saved.startswith("# My New Note\n"))
        ok &= check("write_note records the model in the title section", "model: test:model-x" in saved.split("\n\n", 2)[1])
        ok &= check("write_note records a save date-time in the title section", "Saved 20" in saved.split("\n\n", 2)[1])
        ok &= check("write_note keeps the body", "The body of the note" in saved)
        ok &= check("write_note re-indexes so read_note finds it", "The body of the note" in vault.read_note("My New Note"))
        ok &= check("write_note note appears in list_notes", any(e["note"] == "My New Note" for e in vault.list_notes()))
        vault.write_note("My New Note", "Replaced.")
        ok &= check("write_note overwrites an existing note", "Replaced." in vault.read_note("My New Note") and "The body of the note" not in vault.read_note("My New Note"))
        vault.write_note("Prewritten", "# Custom Title\n\nAlready has a heading.", model="test:model-x")
        prewritten = vault.read_note("Prewritten")
        ok &= check("write_note keeps an existing leading heading", prewritten.startswith("# Custom Title"))
        ok &= check("write_note adds metadata under an existing heading", "model: test:model-x" in prewritten and "Already has a heading." in prewritten)
        ok &= check("write_note rejects a blank name", _raises(ValueError, lambda: vault.write_note("   ", "x")))
        ok &= check("write_note rejects path separators", _raises(ValueError, lambda: vault.write_note("a/b", "x")))
        ok &= check("write_note rejects '..'", _raises(ValueError, lambda: vault.write_note("../escape", "x")))

        # The capability bundles the pieces it promises to.
        from capabilities import VaultCapability

        cap = VaultCapability(vault)
        ok &= check("instructions load from the md file", "search_vault" in (cap.get_instructions() or ""))
        ok &= check("instructions list the vault's notes", "Coffee Brewing" in cap.get_instructions())
        ok &= check("capability sets temperature=0", (cap.get_model_settings() or {}).get("temperature") == 0.0)
        tools = list(cap.get_toolset().tools.keys())
        ok &= check("capability exposes the three vault tools", set(tools) == {"search_vault", "read_note", "list_notes"})

        # A vault-local system_prompt.md wins over the bundled one.
        (vault.root / "system_prompt.md").write_text("Vault-local prompt. Use search_vault.", encoding="utf-8")
        local_cap = VaultCapability(Vault(vault.root))
        ok &= check("vault-local system_prompt.md takes precedence", "Vault-local prompt" in local_cap.get_instructions())

    ok &= test_log_cleanup()
    ok &= test_external_delete_recovery()
    ok &= vault_switching_tests()
    ok &= graph_tests()
    return ok


def graph_tests() -> bool:
    """Vault.graph() cases the main fixture doesn't hit: unresolved (phantom)
    targets, same-file heading self-links, and de-duping a link repeated twice."""
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "A.md").write_text(
            "[[B]] [[B]] [[#Some Heading]] [[Missing Note]]\n\n## Some Heading\n\ntext\n",
            encoding="utf-8",
        )
        (root / "B.md").write_text("# B\n\nno outgoing links\n", encoding="utf-8")
        vault = Vault(root)

        g = vault.graph()
        gnodes = {n["id"]: n for n in g["nodes"]}
        ok &= check("graph keeps a phantom node for an unresolved link", "Missing Note" in gnodes)
        ok &= check("phantom node is marked unresolved", gnodes["Missing Note"]["resolved"] is False)
        gedges = {frozenset((l["source"], l["target"])) for l in g["links"]}
        ok &= check(
            "graph edges: A-B (deduped) and A-Missing Note, no self-edge from #Heading",
            gedges == {frozenset({"A", "B"}), frozenset({"A", "Missing Note"})},
        )
        ok &= check("a link repeated twice still yields one edge", len(g["links"]) == 2)
        ok &= check("phantom node's degree counts its one link", gnodes["Missing Note"]["degree"] == 1)
    return ok


def vault_switching_tests() -> bool:
    """The /vault machinery: listing vaults, persisting the choice, resolving it."""
    import os

    from cli import _list_vaults, _persist_vault_choice
    from main import open_vault

    ok = True
    saved = {k: os.environ.get(k) for k in ("VAULT_PATH", "VAULT_NAME")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a").mkdir()
            (base / "a" / "note.md").write_text("# A\n", encoding="utf-8")
            (base / "b" / "sub").mkdir(parents=True)
            (base / "b" / "sub" / "note.md").write_text("# B\n", encoding="utf-8")
            (base / ".hidden").mkdir()
            (base / ".hidden" / "x.md").write_text("hidden", encoding="utf-8")
            (base / "empty").mkdir()
            (base / "c" / ".obsidian").mkdir(parents=True)
            (base / "c" / ".obsidian" / "only.md").write_text("hidden", encoding="utf-8")
            (base / "stray.txt").write_text("not a vault", encoding="utf-8")

            ok &= check("_list_vaults finds only real vaults", _list_vaults(base) == ["a", "b"])

            env_file = base / ".env"
            env_file.write_text(
                "# keep this comment\nVAULT_PATH=/old/giro\nMODEL=x\n", encoding="utf-8"
            )
            _persist_vault_choice(env_file, base, "b")
            content = env_file.read_text(encoding="utf-8")
            ok &= check("_persist rewrites VAULT_PATH in place", f"VAULT_PATH={base}" in content)
            ok &= check("_persist appends missing VAULT_NAME", "VAULT_NAME=b" in content)
            ok &= check("_persist keeps other lines", "# keep this comment" in content and "MODEL=x" in content)
            ok &= check("_persist updates os.environ", os.environ.get("VAULT_NAME") == "b")

            fresh = base / "fresh.env"
            _persist_vault_choice(fresh, base, "a")
            ok &= check("_persist creates a missing .env", "VAULT_NAME=a" in fresh.read_text(encoding="utf-8"))

            os.environ["VAULT_PATH"] = str(base)
            os.environ["VAULT_NAME"] = "a"
            vault, _ = open_vault([])
            ok &= check("open_vault resolves VAULT_PATH/VAULT_NAME", vault.root.name == "a")

            del os.environ["VAULT_NAME"]
            os.environ["VAULT_PATH"] = str(base / "a")
            vault, _ = open_vault([])
            ok &= check("open_vault still accepts a legacy direct VAULT_PATH", vault.root.name == "a")

            os.environ["VAULT_PATH"] = str(base)
            os.environ["VAULT_NAME"] = "nope"
            try:
                open_vault([])
                ok &= check("open_vault rejects a bad VAULT_NAME", False)
            except SystemExit:
                ok &= check("open_vault rejects a bad VAULT_NAME", True)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return ok


def live_tests() -> bool:
    print("live tests (real model):")
    import capabilities as caps
    from main import build_vault_agent

    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        vault = make_vault(Path(tmp))
        agent, _ = build_vault_agent(vault)

        caps.AUDIT.clear()
        r1 = agent.run_sync("What coffee-to-water ratio should I use?")
        ok &= check("grounds the answer in the note (1:16)", "1:16" in r1.output)
        ok &= check("searched or read the vault", any("vault:" in a for a in caps.AUDIT))

        caps.AUDIT.clear()
        r2 = agent.run_sync("What does the vault say about espresso machines?")
        ok &= check("does not invent notes for uncovered topics", "[[Espresso" not in r2.output)
    return ok


def main() -> None:
    passed = unit_tests()
    if "--live" in sys.argv:
        passed = live_tests() and passed
    print("\n", "ALL PASSED" if passed else "SOME FAILED")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
