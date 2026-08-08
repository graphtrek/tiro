"""A web terminal for chatting with an Obsidian vault — the browser twin of cli.py.

    uv run python web.py                # serves http://127.0.0.1:8010
    uv run uvicorn web:app --port 8010  # same thing, explicit uvicorn

One page (static/index.html), one JSON API. The page posts raw input to
POST /api/message and the server dispatches it exactly like the REPL: the same
slash commands (/notes, /read, /vault, /model, ...), anything else is a question
for the vault. There is a single shared Session (this is a single-user local
tool); a second message sent while a turn is running gets HTTP 409.

Configure with WEB_HOST / WEB_PORT (defaults 127.0.0.1:8010) in .env.

Avoid `uvicorn --reload` while the Headroom proxy is enabled: every reload tears
down and respawns the proxy subprocess (a multi-second health poll each time).
static/index.html is re-read on every request anyway, so frontend edits need no
reload; for backend work under --reload set HEADROOM=0.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from rich.errors import MarkupError
from rich.text import Text

from capabilities import AUDIT, log, log_action, log_interaction, setup_logging
from cli import (
    ENV_FILE,
    Session,
    _extract_timings,
    _friendly_error,
    _list_vaults,
    _note_by_id,
    _persist_vault_choice,
    _prepare_save_note,
    _tool_elapsed,
    _tools_used,
    _update_env,
    _vault_base,
)
from graph_view import render_graph_html
from headroom_proxy import (
    ProxyManager,
    proxy_base_url,
    proxy_enabled,
    proxy_host,
    proxy_mode,
    proxy_port,
)
from main import MODEL, PROVIDERS, USAGE_LIMITS, missing_credentials, open_vault
from obsidian_vault import Vault

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The one conversation this server hosts, built in `lifespan`.
SESSION: Session | None = None

# One turn at a time: a second message while the agent runs gets a 409, it is
# not queued (queueing multi-minute local-model turns silently would be worse).
TURN_LOCK = threading.Lock()

HELP_MD = """\
**Commands**

| command | what it does |
|---|---|
| `/help` | show this help (also just `/`) |
| `/notes` | list the vault's notes and their wikilinks |
| `/graph` | open the vault's link graph in a new tab (like Obsidian's Graph View) |
| `/read <id\\|note>` | print a note by its `/notes` number or name (or its outline if it's long) |
| `/save-note <name> [--full]` | save the last answer (or the whole conversation with `--full`) to the vault |
| `/vault [name]` | list vaults in the base dir, or switch to one (persists to .env) |
| `/model [name]` | list model providers, or switch to one (persists to .env) |
| `/prompt` | show the system prompt file in use |
| `/reload` | rebuild the agent (picks up system_prompt.md edits) |
| `/clear` | clear the conversation history |

Anything else is a question for the vault. `/exit` is CLI-only — just close the tab.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global SESSION
    setup_logging()
    missing = missing_credentials(MODEL)
    if missing:  # fail fast at startup, like cli.run()
        raise RuntimeError(f"No API key found for {MODEL}: add {missing} to .env")

    proxy: ProxyManager | None = None
    if proxy_enabled():
        proxy = ProxyManager()
        status, error = proxy.ensure_safe(MODEL)
        if error is not None:
            log.warning("headroom proxy unavailable for %s: %s — running direct", MODEL, error)
        elif status.active:
            log.info(
                "headroom proxy %s on %s:%s · mode %s",
                "reused" if status.external else "started",
                proxy_host(),
                proxy_port(),
                proxy_mode(),
            )
        elif status.reason:
            log.warning("headroom proxy inactive: %s", status.reason)

    vault, _ = open_vault([])
    SESSION = Session(vault, proxy)
    log.info("web terminal ready: vault=%s model=%s", vault.root, SESSION.model)
    yield
    if proxy is not None:  # lifespan shutdown replaces the CLI's atexit hook
        proxy.stop()


app = FastAPI(title="Obsidian vault agent — web terminal", lifespan=lifespan)


class MessageIn(BaseModel):
    message: str


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/graph", include_in_schema=False)
def graph_page() -> HTMLResponse:
    """The vault's link graph as its own page - /graph in the terminal opens this
    in a new tab rather than rendering inline, so the force-directed canvas gets
    the full viewport instead of fighting the chat panel for space."""
    session = SESSION
    graph = session.vault.graph()
    html = render_graph_html(
        graph, session.vault.graph_settings(), session.vault.root.name, back_url="/"
    )
    return HTMLResponse(html)


@app.get("/api/status")
def status() -> dict:
    session = SESSION
    headroom = None
    if proxy_base_url() is not None:
        headroom = f"{proxy_host()}:{proxy_port()} · {proxy_mode()}"
    return {
        "vault": str(session.vault.root),
        "vault_name": session.vault.root.name,
        "notes": len(session.vault.list_notes()),
        "model": session.model,
        "prompt_file": str(session.vault_cap.prompt_file),
        "headroom": headroom,
    }


@app.post("/api/message")
def message(body: MessageIn):
    if not TURN_LOCK.acquire(blocking=False):
        return JSONResponse(
            status_code=409,
            content=_error("a turn is already running — wait for it to finish"),
        )
    try:
        text = body.message.strip()
        if not text:
            return _error("empty message")
        return dispatch(SESSION, text)
    finally:
        TURN_LOCK.release()


# --- dispatch: the REPL's command chain, returning JSON instead of panels ------------
#
# Every handled input returns one of three shapes (the page switches on "kind"):
#   {"kind": "answer", "markdown", "tools": [{"tool","args","ms"}], "model",
#    "wall_ms", "requests"}
#   {"kind": "info", "markdown", "status_changed", "open_graph"}
#     status_changed → refetch /api/status; open_graph → window.open("/graph")
#   {"kind": "error", "error"}


def dispatch(session: Session, text: str) -> dict:
    try:
        if text in {"/exit", "/quit"}:
            log_action("exit")
            return _error("/exit is CLI-only — close the tab, or /clear to reset the conversation")
        if text in {"/help", "/"}:
            log_action("help")
            return _info(HELP_MD)
        if text == "/notes":
            log_action("list_notes")
            return _notes(session)
        if text == "/graph":
            log_action("open_graph")
            graph = session.vault.graph()
            return _info(
                f"opened the graph view in a new tab — {len(graph['nodes'])} notes, "
                f"{len(graph['links'])} links",
                open_graph=True,
            )
        if text == "/read" or text.startswith("/read "):
            name = text[len("/read") :].strip()
            if not name:
                return _error("usage: /read <id | note name>")
            name = _note_by_id(session, name)
            log_action("read_note", name)
            return _info(session.vault.read_note(name))
        if text == "/save-note" or text.startswith("/save-note "):
            log_action("save_note", text[len("/save-note") :].strip())
            return _save_note(session, text[len("/save-note") :].strip())
        if text == "/prompt":
            log_action("view_prompt")
            prompt_file = session.vault_cap.prompt_file
            return _info(f"`{prompt_file}`\n\n---\n\n{prompt_file.read_text(encoding='utf-8')}")
        if text == "/reload":
            log_action("reload_agent")
            session.reload()
            return _info("agent rebuilt — system prompt re-read from disk", status_changed=True)
        if text == "/clear":
            log_action("clear_history")
            session.history = []
            return _info("conversation cleared")
        if text == "/vault" or text.startswith("/vault "):
            log_action("vault_cmd", text[len("/vault") :].strip())
            return _vault_cmd(session, text[len("/vault") :].strip())
        if text == "/model" or text.startswith("/model "):
            log_action("model_cmd", text[len("/model") :].strip())
            return _model_cmd(session, text[len("/model") :].strip())
        if text.startswith("/"):
            log_action("unknown_cmd", text)
            return _error(f"unknown command: {text.split()[0]} — /help lists commands")
        return _turn(session, text)
    except Exception as exc:
        log.error("dispatch failed for text %r: %s", text, exc, exc_info=True)
        return _error(_plain_error(exc))


def _info(markdown: str, status_changed: bool = False, open_graph: bool = False) -> dict:
    return {
        "kind": "info",
        "markdown": markdown,
        "status_changed": status_changed,
        "open_graph": open_graph,
    }


def _error(message: str) -> dict:
    return {"kind": "error", "error": message}


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _notes(session: Session) -> dict:
    rows = [f"**notes in {session.vault.root.name}**", "", "| # | note | chars | links to |", "|---:|---|---:|---|"]
    for i, entry in enumerate(session.vault.list_notes(), start=1):
        links = ", ".join(str(l) for l in entry["links_to"]) or "—"
        rows.append(f"| {i} | {_md_cell(entry['note'])} | {entry['chars']} | {_md_cell(links)} |")
    return _info("\n".join(rows))


def _save_note(session: Session, args: str) -> dict:
    result = _prepare_save_note(session, args)
    if not result["ok"]:
        message = result["message"]
        if result["kind"] == "write_error":
            message = f"save failed: {message}"
        return _error(message)
    return _info(f"saved the {result['source']} to **{result['note_name']}**\n\n`{result['path']}`")


def _vault_cmd(session: Session, name: str) -> dict:
    base = _vault_base(session)
    if not name:
        vaults = _list_vaults(base)
        if not vaults:
            return _info(f"no vaults found in {base}")
        rows = [f"**vaults in {base}**", "", "| vault | |", "|---|---|"]
        for vault_name in vaults:
            active = (base / vault_name).resolve() == session.vault.root
            rows.append(f"| {_md_cell(vault_name)} | {'● active' if active else ''} |")
        rows += ["", "usage: `/vault <name>`"]
        return _info("\n".join(rows))

    target = base / name
    if target.resolve() == session.vault.root:
        return _info(f"already on {name}")
    try:
        vault = Vault(target)
    except ValueError as exc:
        available = ", ".join(_list_vaults(base)) or "none"
        log.warning("vault switch to %r failed: %s", name, exc)
        return _error(f"vault switch failed: {exc}\n\nAvailable vaults: {available}")

    session.switch_vault(vault)
    lines = [f"switched to **{name}** — conversation cleared"]
    try:
        _persist_vault_choice(ENV_FILE, base, name)
    except OSError as exc:
        log.warning("couldn't persist vault choice %r to .env: %s", name, exc)
        lines.append(f"(switched for this session, but couldn't write .env: {exc})")
    return _info("\n\n".join(lines), status_changed=True)


def _model_cmd(session: Session, name: str) -> dict:
    if not name:
        rows = ["**model providers**", "", "| provider | model | |", "|---|---|---|"]
        for provider, spec in PROVIDERS.items():
            active = spec == session.model
            rows.append(f"| {provider} | {_md_cell(spec)} | {'● active' if active else ''} |")
        rows += ["", "usage: `/model <" + "|".join(PROVIDERS) + ">`"]
        return _info("\n".join(rows))

    spec = PROVIDERS.get(name)
    if spec is None:
        return _error(f"unknown provider: {name} — choose one of {', '.join(PROVIDERS)}")
    if spec == session.model:
        return _info(f"already on {name} ({spec})")

    missing = missing_credentials(spec)
    if missing:
        log.warning("model switch to %r failed: missing %s", name, missing)
        return _error(f"{name} needs {missing}. Add it to a local .env, then try again.")

    lines = []
    if session.proxy is not None:
        note = _apply_proxy_note(session.proxy, spec)
        if note:
            lines.append(note)
    session.switch_model(spec)
    lines.insert(0, f"switched to **{name}** ({spec})")
    try:
        _update_env(ENV_FILE, {"MODEL": spec})
    except OSError as exc:
        log.warning("couldn't persist model choice %r to .env: %s", spec, exc)
        lines.append(f"(switched for this session, but couldn't write .env: {exc})")
    return _info("\n\n".join(lines), status_changed=True)


def _apply_proxy_note(proxy: ProxyManager, spec: str) -> str:
    """cli._apply_proxy, returning a plain-text note instead of printing panels."""
    status, error = proxy.ensure_safe(spec)
    if error is not None:
        log.warning("headroom proxy unavailable for %s: %s", spec, error)
        return f"headroom proxy unavailable ({error}) — continuing without it, LLM calls go direct"
    if status.active:
        kind = "reusing" if status.external else "started"
        note = f" ({status.reason})" if status.reason else ""
        return f"headroom proxy {kind} on {proxy_host()}:{proxy_port()} · mode {proxy_mode()}{note}"
    return status.reason or ""


def _turn(session: Session, prompt: str) -> dict:
    audit_start = len(AUDIT)
    t0 = time.perf_counter()
    try:
        result = session.agent.run_sync(
            prompt, message_history=session.history, usage_limits=USAGE_LIMITS
        )
    except Exception as exc:  # noqa: BLE001 - keep the server alive on turn errors
        log.error("turn failed for prompt %r: %s", prompt, exc, exc_info=True)
        return _error(_plain_error(exc))
    wall_ms = (time.perf_counter() - t0) * 1000

    used = _tools_used(result.new_messages())
    timings = _extract_timings(AUDIT[audit_start:])
    tools = []
    for i, (tool, detail) in enumerate(used):
        ms = _tool_elapsed(tool, i, timings)
        tools.append({"tool": tool, "args": detail, "ms": round(ms, 1) if ms is not None else None})
    requests = result.usage.requests or 0

    log_interaction(prompt, result.output or "", sorted({tool for tool, _ in used}))
    session.history = result.all_messages()

    return {
        "kind": "answer",
        "markdown": result.output or "",
        "tools": tools,
        "model": session.model,
        "wall_ms": round(wall_ms),
        "requests": requests,
    }


def _plain_error(exc: Exception) -> str:
    """cli._friendly_error with its rich markup stripped for JSON transport."""
    text = _friendly_error(exc)
    try:
        return Text.from_markup(text).plain
    except MarkupError:  # raw exception text with stray brackets isn't valid markup
        return text


def main() -> None:
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("WEB_PORT", "8010"))
    except ValueError:
        port = 8010
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
