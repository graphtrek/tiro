"""An interactive REPL for chatting with an Obsidian vault.

    uv run python cli.py /path/to/vault
    uv run python cli.py                # vault from VAULT_PATH/VAULT_NAME (.env)

VAULT_PATH is the base directory holding all vaults and VAULT_NAME picks the
active one; /vault <name> switches vaults at runtime and persists the choice.

The agent answers only from the vault's notes, follows [[wikilinks]] between them,
and cites the notes it used. After every answer the CLI prints which vault tools
fired, so you can see where the answer came from.

By default it expects a local OpenAI-compatible server (LM Studio etc.) running on
http://localhost:1234/v1 (override: LOCAL_LLM_URL) with the
mlx-community-ornith-1.0-9b-bf16 model loaded - no API key needed. Override the model
with MODEL=...; cloud models (e.g. MODEL=openrouter:anthropic/claude-sonnet-4.6) need
OPENROUTER_API_KEY or ANTHROPIC_API_KEY in a local .env.

The system prompt loads from system_prompt.md (or a vault-local system_prompt.md,
or SYSTEM_PROMPT=<path>) - edit the md file, then /reload to pick it up.
"""

from __future__ import annotations

import atexit
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

try:
    import readline  # noqa: F401 - importing it is what enables line editing
except ImportError:  # Windows: the console does its own line editing
    readline = None

# Windows consoles default to cp1252, which can't encode the box-drawing and bullet
# glyphs rich emits - force UTF-8 on the streams before anything prints.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
load_dotenv(override=False)

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from capabilities import AUDIT, VaultCapability, log, log_interaction, setup_logging
from headroom_proxy import (
    HeadroomError,
    ProxyManager,
    proxy_base_url,
    proxy_enabled,
    proxy_host,
    proxy_mode,
    proxy_port,
)
from main import MODEL, PROVIDERS, USAGE_LIMITS, build_vault_agent, missing_credentials, open_vault
from obsidian_vault import Vault

console = Console()

HISTORY_FILE = Path.home() / ".obsidian_vault_agent_history"


def _setup_line_editing() -> str:
    """Enable arrow keys (cursor movement + persistent input history) and return
    the prompt string.

    The prompt must be passed to input() itself - not printed beforehand - or
    readline miscalculates its width and arrow keys misbehave. Colour codes are
    wrapped in \\001/\\002 so readline doesn't count them as printable, but
    macOS's libedit doesn't understand those markers, so there the prompt stays
    plain.
    """
    if readline is None:
        return "you › "
    try:
        readline.read_history_file(HISTORY_FILE)
    except OSError:
        pass
    readline.set_history_length(1000)
    atexit.register(_save_history)
    libedit = getattr(readline, "backend", "") == "editline" or "libedit" in (
        readline.__doc__ or ""
    )
    return "you › " if libedit else "\001\x1b[1;36m\002you ›\001\x1b[0m\002 "


def _save_history() -> None:
    try:
        readline.write_history_file(HISTORY_FILE)
    except OSError:
        pass


TOOL_STYLE = {
    "search_vault": "cyan",
    "read_note": "green",
    "list_notes": "yellow",
}

HELP = """\
[bold]Commands[/bold]
  [cyan]/help[/cyan]           show this help (also just [cyan]/[/cyan])
  [cyan]/notes[/cyan]          list the vault's notes and their wikilinks
  [cyan]/read <note>[/cyan]    print a note (or its outline if it's long)
  [cyan]/save-note <name>[/cyan]  save the last answer to the vault (add [cyan]--full[/cyan] for the whole conversation)
  [cyan]/vault \\[name][/cyan]   list vaults in the base dir, or switch to one (persists to .env)
    [cyan]/model \\[name][/cyan]   list model providers, or switch to one — [cyan]local[/cyan]/[cyan]gemma[/cyan]/[cyan]ornith-uncensored[/cyan]/[cyan]deepseek[/cyan] (persists to .env)
  [cyan]/prompt[/cyan]         show the system prompt file in use
  [cyan]/reload[/cyan]         rebuild the agent (picks up system_prompt.md edits)
  [cyan]/clear[/cyan]          clear the conversation history
  [cyan]/exit[/cyan]           quit (also: Ctrl-D / Ctrl-C)
Anything else is a question for the vault.
"""

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _vault_base(session: Session) -> Path:
    """The directory holding all vaults: VAULT_PATH when it's a base dir, else the
    current vault's parent (covers explicit-path launches and a legacy .env where
    VAULT_PATH points straight at a vault)."""
    env = os.environ.get("VAULT_PATH")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir() and p != session.vault.root:
            return p
    return session.vault.root.parent


def _list_vaults(base: Path) -> list[str]:
    """Names of subdirs of `base` that hold at least one .md outside hidden dirs
    (the same files Vault would index), sorted."""
    vaults = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if any(
            not any(part.startswith(".") for part in p.relative_to(d).parts)
            for p in d.rglob("*.md")
        ):
            vaults.append(d.name)
    return vaults


def _update_env(env_file: Path, updates: dict[str, str]) -> None:
    """Rewrite the given keys in .env in place, preserving every other line; append
    missing keys, create the file if absent. Also updates os.environ, since
    load_dotenv(override=False) won't re-read a changed file."""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    for key, value in updates.items():
        pattern = re.compile(rf"\s*(export\s+)?{key}\s*=")
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
        os.environ[key] = value
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _persist_vault_choice(env_file: Path, base: Path, name: str) -> None:
    """Persist the active vault (VAULT_PATH/VAULT_NAME) to .env."""
    _update_env(env_file, {"VAULT_PATH": str(base), "VAULT_NAME": name})


class Session:
    """One vault, one agent, one running conversation."""

    def __init__(self, vault: Vault, proxy: ProxyManager | None = None) -> None:
        self.vault = vault
        self.proxy = proxy
        self.model = MODEL
        self.history: list[ModelMessage] = []
        self.reload()

    def reload(self) -> None:
        self.agent: Agent
        self.vault_cap: VaultCapability
        self.agent, self.vault_cap = build_vault_agent(self.vault, self.model)

    def switch_vault(self, vault: Vault) -> None:
        self.vault = vault
        self.history = []  # the old conversation was about the old vault
        self.reload()

    def switch_model(self, spec: str) -> None:
        self.model = spec
        self.reload()


def _apply_proxy(proxy: ProxyManager, spec: str) -> None:
    """Point the proxy at `spec`'s provider (starting/restarting as needed) and
    report the result. On failure the CLI keeps running with a direct connection."""
    try:
        status = proxy.ensure(spec)
    except HeadroomError as exc:
        log.warning("headroom proxy unavailable for %s: %s", spec, exc)
        console.print(
            Panel(
                f"{exc}\n\n[dim]continuing without the proxy \u2014 LLM calls go direct[/dim]",
                title="[red]Headroom proxy unavailable[/red]",
                border_style="red",
            )
        )
        return
    if status.active:
        note = f" [dim]({status.reason})[/dim]" if status.reason else ""
        kind = "reusing" if status.external else "started"
        console.print(
            f"[green]headroom proxy {kind}[/green] on "
            f"[bold]{proxy_host()}:{proxy_port()}[/bold] \u00b7 mode [bold]{proxy_mode()}[/bold]{note}"
        )
    elif status.reason:
        console.print(f"[yellow]{status.reason}[/yellow]")


def _shutdown(session: Session) -> None:
    """Stop the Headroom proxy we started, if any."""
    if session.proxy is not None:
        session.proxy.stop()


def run() -> int:
    setup_logging()  # wire up the log file before anything else can fail
    missing = missing_credentials(MODEL)
    if missing:
        log.error("missing credentials for %s: %s not set", MODEL, missing)
        console.print(
            Panel(
                f"[bold red]No API key found for {MODEL}.[/bold red]\n\n"
                f"Add [cyan]{missing}[/cyan] to a local [cyan].env[/cyan], then run again.\n"
                "Or use a local OpenAI-compatible server (no key needed): "
                "[cyan]MODEL=local:<model-name>[/cyan] on http://localhost:1234/v1.",
                title="Missing configuration",
                border_style="red",
            )
        )
        return 1

    proxy: ProxyManager | None = None
    if proxy_enabled():
        proxy = ProxyManager()
        _apply_proxy(proxy, MODEL)
        atexit.register(proxy.stop)

    try:
        vault, _ = open_vault(sys.argv[1:])
        session = Session(vault, proxy)
    except SystemExit as exc:
        log.error("failed to open vault: %s", exc)
        console.print(f"[bold red]{exc}[/bold red]")
        return 1
    except Exception as exc:  # noqa: BLE001 - surface any build error cleanly
        log.error("failed to open vault: %s", exc, exc_info=True)
        console.print(f"[bold red]Failed to open vault:[/bold red] {exc}")
        return 1

    _print_banner(session)
    _chat_loop(session)
    return 0


def _print_banner(session: Session) -> None:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(justify="right", style="dim")
    grid.add_column()
    grid.add_row("vault", f"[bold]{session.vault.root}[/bold]")
    grid.add_row("notes", f"[bold]{len(session.vault.list_notes())}[/bold]")
    grid.add_row("model", f"[bold]{session.model}[/bold]")
    grid.add_row("prompt", f"[bold]{session.vault_cap.prompt_file}[/bold]")
    if proxy_base_url() is not None:
        grid.add_row(
            "headroom", f"[bold]{proxy_host()}:{proxy_port()}[/bold] \u00b7 mode {proxy_mode()}"
        )
    console.print(
        Panel(
            grid,
            title=f"[bold magenta]Obsidian vault chat — {session.vault.root.name}[/bold magenta]",
            subtitle="[dim]/help for commands[/dim]",
            border_style="magenta",
        )
    )


def _chat_loop(session: Session) -> None:
    input_prompt = _setup_line_editing()
    while True:
        try:
            print()
            prompt = input(input_prompt).strip()
        except (EOFError, KeyboardInterrupt):
            _shutdown(session)
            console.print("\n[dim]bye[/dim]")
            return

        if not prompt:
            continue
        if prompt in {"/exit", "/quit"}:
            _shutdown(session)
            console.print("[dim]bye[/dim]")
            return
        if prompt in {"/help", "/"}:
            console.print(Panel(HELP, border_style="cyan", title="help"))
            continue
        if prompt == "/notes":
            _print_notes(session)
            continue
        if prompt == "/read" or prompt.startswith("/read "):
            name = prompt[len("/read") :].strip()
            if not name:
                console.print("[dim]usage: /read <note name>[/dim]")
                continue
            console.print(Panel(Markdown(session.vault.read_note(name)), title=name))
            continue
        if prompt == "/save-note" or prompt.startswith("/save-note "):
            _handle_save_note(session, prompt[len("/save-note") :].strip())
            continue
        if prompt == "/prompt":
            console.print(
                Panel(
                    Markdown(session.vault_cap.prompt_file.read_text(encoding="utf-8")),
                    title=str(session.vault_cap.prompt_file),
                )
            )
            continue
        if prompt == "/reload":
            session.reload()
            console.print("[dim]agent rebuilt — system prompt re-read from disk[/dim]")
            _print_banner(session)
            continue
        if prompt == "/clear":
            session.history = []
            console.print("[dim]conversation cleared[/dim]")
            continue
        if prompt == "/vault" or prompt.startswith("/vault "):
            _handle_vault_command(session, prompt[len("/vault") :].strip())
            continue
        if prompt == "/model" or prompt.startswith("/model "):
            _handle_model_command(session, prompt[len("/model") :].strip())
            continue
        if prompt.startswith("/"):
            # A typo like /valut must never reach the model as a question.
            console.print(
                f"[red]unknown command: {prompt.split()[0]}[/red] — [dim]/help lists commands[/dim]"
            )
            continue

        _handle_turn(session, prompt)


def _print_notes(session: Session) -> None:
    table = Table(title=f"notes in {session.vault.root.name}", border_style="blue")
    table.add_column("note", style="bold")
    table.add_column("chars", justify="right", style="dim")
    table.add_column("links to", style="dim")
    for entry in session.vault.list_notes():
        links = ", ".join(str(l) for l in entry["links_to"]) or "—"
        table.add_row(str(entry["note"]), str(entry["chars"]), links)
    console.print(table)


def _handle_save_note(session: Session, args: str) -> None:
    """`/save-note <name> [--full]`: write the last answer (or the whole conversation
    with --full) to the current vault as a formatted note."""
    tokens = args.split()
    full = False
    name_parts: list[str] = []
    for token in tokens:
        if token in {"--full", "-f"}:
            full = True
        else:
            name_parts.append(token)
    name = " ".join(name_parts).strip()

    if not name:
        console.print("[dim]usage: /save-note <name> [--full][/dim]")
        return
    if not session.history:
        console.print("[yellow]nothing to save yet — ask a question first[/yellow]")
        return

    content = _full_conversation(session.history) if full else _last_answer(session.history)
    if not content.strip():
        what = "conversation" if full else "answer"
        console.print(f"[yellow]no {what} text to save[/yellow]")
        return

    try:
        path = session.vault.write_note(name, content, model=session.model)
    except (ValueError, OSError) as exc:
        log.warning("save-note %r failed: %s", name, exc)
        console.print(Panel(str(exc), title="[red]save failed[/red]", border_style="red"))
        return

    note_name = path.relative_to(session.vault.root).as_posix()[:-3]
    source = "whole conversation" if full else "last answer"
    console.print(
        Panel(
            f"saved the {source} to [bold]{note_name}[/bold]\n[dim]{path}[/dim]",
            title="[bold green]note saved[/bold green]",
            border_style="green",
        )
    )


def _last_answer(history: list[ModelMessage]) -> str:
    """The text of the most recent assistant answer (thinking and tool calls skipped)."""
    for msg in reversed(history):
        if not isinstance(msg, ModelResponse):
            continue
        text = "\n".join(
            part.content for part in msg.parts if isinstance(part, TextPart) and part.content
        )
        if text.strip():
            return text
    return ""


def _full_conversation(history: list[ModelMessage]) -> str:
    """The whole exchange as markdown: each user prompt under `## You`, each assistant
    answer under `## Assistant` (system prompts, tool calls and thinking are skipped)."""
    blocks: list[str] = []
    for msg in history:
        if isinstance(msg, ModelRequest):
            prompts = [
                part.content
                for part in msg.parts
                if isinstance(part, UserPromptPart) and isinstance(part.content, str)
            ]
            for prompt in prompts:
                if prompt.strip():
                    blocks.append(f"## You\n\n{prompt.strip()}")
        elif isinstance(msg, ModelResponse):
            text = "\n".join(
                part.content for part in msg.parts if isinstance(part, TextPart) and part.content
            )
            if text.strip():
                blocks.append(f"## Assistant\n\n{text.strip()}")
    return "\n\n".join(blocks)


def _handle_vault_command(session: Session, name: str) -> None:
    base = _vault_base(session)
    if not name:
        vaults = _list_vaults(base)
        if not vaults:
            console.print(f"[yellow]no vaults found in {base}[/yellow]")
            return
        table = Table(title=f"vaults in {base}", border_style="blue")
        table.add_column("vault", style="bold")
        table.add_column("", style="dim")
        for vault_name in vaults:
            active = (base / vault_name).resolve() == session.vault.root
            table.add_row(vault_name, "● active" if active else "")
        console.print(table)
        console.print("[dim]usage: /vault <name>[/dim]")
        return

    target = base / name
    if target.resolve() == session.vault.root:
        console.print(f"[dim]already on {name}[/dim]")
        return
    try:
        vault = Vault(target)
    except ValueError as exc:
        available = ", ".join(_list_vaults(base)) or "none"
        log.warning("vault switch to %r failed: %s", name, exc)
        console.print(
            Panel(
                f"{exc}\n\nAvailable vaults: [cyan]{available}[/cyan]",
                title="[red]vault switch failed[/red]",
                border_style="red",
            )
        )
        return

    session.switch_vault(vault)
    try:
        _persist_vault_choice(ENV_FILE, base, name)
    except OSError as exc:
        log.warning("couldn't persist vault choice %r to .env: %s", name, exc)
        console.print(f"[yellow]switched for this session, but couldn't write .env: {exc}[/yellow]")
    console.print(f"[dim]switched to {name} — conversation cleared[/dim]")
    _print_banner(session)


def _handle_model_command(session: Session, name: str) -> None:
    if not name:
        table = Table(title="model providers", border_style="blue")
        table.add_column("provider", style="bold")
        table.add_column("model", style="dim")
        table.add_column("", style="dim")
        for provider, spec in PROVIDERS.items():
            active = spec == session.model
            table.add_row(provider, spec, "● active" if active else "")
        console.print(table)
        console.print("[dim]usage: /model <" + "|".join(PROVIDERS) + ">[/dim]")
        return

    spec = PROVIDERS.get(name)
    if spec is None:
        console.print(
            f"[red]unknown provider: {name}[/red] — [dim]choose one of "
            f"{', '.join(PROVIDERS)}[/dim]"
        )
        return
    if spec == session.model:
        console.print(f"[dim]already on {name} ({spec})[/dim]")
        return

    missing = missing_credentials(spec)
    if missing:
        log.warning("model switch to %r failed: missing %s", name, missing)
        console.print(
            Panel(
                f"[bold red]{name} needs {missing}.[/bold red]\n\n"
                f"Add [cyan]{missing}[/cyan] to a local [cyan].env[/cyan], then try again.",
                title="[red]model switch failed[/red]",
                border_style="red",
            )
        )
        return

    if session.proxy is not None:
        _apply_proxy(session.proxy, spec)
    session.switch_model(spec)
    try:
        _update_env(ENV_FILE, {"MODEL": spec})
    except OSError as exc:
        log.warning("couldn't persist model choice %r to .env: %s", spec, exc)
        console.print(f"[yellow]switched for this session, but couldn't write .env: {exc}[/yellow]")
    console.print(f"[dim]switched to {name} ({spec})[/dim]")
    _print_banner(session)


def _friendly_error(exc: Exception) -> str:
    """Translate known local-server failure modes into an actionable message.

    Some local OpenAI-compatible servers (e.g. LM Studio's MLX runtime) answer
    with HTTP 200 but an error-shaped JSON body when they reject a request —
    pydantic-ai then fails to validate it as a ChatCompletion and raises a wall
    of "Input should be a valid string/list" errors that hide the real cause.
    """
    text = str(exc)
    if "prefill_memory_exceeded" in text or "Prefill context too large" in text:
        return (
            "[bold]local model rejected the prompt: not enough memory for this context.[/bold]\n\n"
            "The prompt (vault context + tools + history) is too large for the model's "
            "memory guard. Try:\n"
            "  • asking a narrower question, or [cyan]/clear[/cyan] to drop conversation history\n"
            "  • raising the memory guard ceiling / setting it to \"aggressive\" in LM Studio\n"
            "  • switching to a smaller local model, e.g. [cyan]/model local[/cyan]\n"
            "  • freeing system memory and retrying"
        )
    if "validation errors for ChatCompletion" in text:
        return (
            "[bold]local model returned an error instead of a completion.[/bold]\n\n"
            f"{text}"
        )
    return text


def _handle_turn(session: Session, prompt: str) -> None:
    audit_start = len(AUDIT)
    t0 = time.perf_counter()
    try:
        with console.status("[magenta]reading the vault…[/magenta]", spinner="dots"):
            result = session.agent.run_sync(
                prompt, message_history=session.history, usage_limits=USAGE_LIMITS
            )
    except Exception as exc:  # noqa: BLE001 - keep the REPL alive on errors
        log.error("turn failed for prompt %r: %s", prompt, exc, exc_info=True)
        console.print(Panel(_friendly_error(exc), title="[red]error[/red]", border_style="red"))
        return
    elapsed_s = time.perf_counter() - t0

    console.print(
        Panel(
            Markdown(result.output or "_[no text output]_"),
            title=f"[bold green]{session.vault.root.name}[/bold green]",
            border_style="green",
        )
    )

    used = _tools_used(result.new_messages())
    timings = _extract_timings(AUDIT[audit_start:])
    requests = result.usage.requests or 0
    console.print(_render_used(used, timings, session.model, elapsed_s, requests))

    log_interaction(prompt, result.output or "", sorted({tool for tool, _ in used}))

    session.history = result.all_messages()


def _tools_used(new_messages: list[ModelMessage]) -> list[tuple[str, str]]:
    """Which vault tools this turn's answer came from, in call order."""
    used: list[tuple[str, str]] = []
    thought = False
    for msg in new_messages:
        if not isinstance(msg, ModelResponse):
            continue
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                used.append((part.tool_name, _fmt_args(part)))
            elif isinstance(part, ThinkingPart) and getattr(part, "content", None):
                thought = True
    if thought:
        used.append(("thinking", "reasoned before answering"))
    return used


def _extract_timings(audit_entries: list[str]) -> list[float | None]:
    """Parse per-call elapsed ms from AUDIT entries produced by audit_hooks."""
    timings: list[float | None] = []
    for entry in audit_entries:
        if entry.startswith("run-complete"):
            continue
        if "⏱️" in entry:
            try:
                ms = float(entry.split("⏱️")[1].strip().split()[0])
                timings.append(ms)
            except (ValueError, IndexError):
                timings.append(None)
        elif "failed after" in entry:
            try:
                ms = float(entry.split("failed after")[1].strip().split()[0])
                timings.append(ms)
            except (ValueError, IndexError):
                timings.append(None)
    return timings


def _render_used(
    used: list[tuple[str, str]],
    timings: list[float | None],
    model: str,
    elapsed_s: float = 0.0,
    requests: int = 0,
) -> Panel:
    body = Table.grid(padding=(0, 2))
    body.add_column()
    body.add_column(style="dim")
    body.add_column(style="dim")
    if used:
        for i, (tool, detail) in enumerate(used):
            style = TOOL_STYLE.get(tool, "magenta")
            elapsed = timings[i] if (tool != "thinking" and i < len(timings)) else None
            elapsed_str = f"⏱️ {elapsed:.0f} ms" if elapsed is not None else ""
            body.add_row(Text(f"▪ {tool}", style=f"bold {style}"), detail, elapsed_str)
    else:
        body.add_row(Text("▪ answered from conversation context, no tools", style="dim"), "", "")
    elapsed_str = f"{elapsed_s:.1f}s" if elapsed_s >= 1 else f"{elapsed_s * 1000:.0f}ms"
    trips_str = f"{requests} round-trip" + ("s" if requests != 1 else "")
    return Panel(
        body,
        title=(
            f"[bold]vault tools used this turn[/bold]"
            f" · [italic cyan]{model}[/italic cyan]"
            f" · [italic cyan]⏱️ {elapsed_str} · {trips_str}[/italic cyan]"
        ),
        title_align="left",
        border_style="blue",
    )


def _fmt_args(part: ToolCallPart) -> str:
    args = getattr(part, "args", None)
    if isinstance(args, dict):
        rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    else:
        rendered = str(args or "")
    return rendered if len(rendered) <= 90 else rendered[:87] + "…"


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
