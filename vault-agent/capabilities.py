"""The capabilities the vault agent is composed from.

Each Capability is a self-contained brick bundling instructions, tools, model
settings, and lifecycle hooks. `VaultCapability` is the heart of the program: it
binds one Obsidian vault's tools to the agent and loads its instructions from a
markdown file (`system_prompt.md` by default) so the prompt can be edited without
touching code.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from pydantic_ai import ModelSettings
from pydantic_ai.capabilities import AbstractCapability, Hooks
from pydantic_ai.toolsets import FunctionToolset

from obsidian_vault import Vault

# A shared audit trail the CLI prints after each turn (and tests assert against).
AUDIT: list[str] = []

# The system logger. Silent until setup_logging() wires it from LOG_LEVEL / LOG_FILE.
log = logging.getLogger("orbit")

# The vault's own tools, so a tool call can be labelled by where its answer comes from.
VAULT_TOOLS = {"search_vault", "read_note", "list_notes"}

DEFAULT_PROMPT_FILE = Path(__file__).resolve().parent / "system_prompt.md"
DEFAULT_LOG_FILE = Path(__file__).resolve().parent / "logs" / "agent.log"


def setup_logging() -> logging.Logger:
    """Configure the `orbit` logger from the environment. Idempotent.

    LOG_LEVEL (default INFO; set OFF/NONE to disable) sets verbosity; LOG_FILE
    (default logs/agent.log next to the scripts) is where the persistent log is
    written. Logs go to the file only, never stdout, so they never clutter the REPL.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    if level_name in {"OFF", "NONE", "DISABLED"}:
        log.disabled = True
        return log
    log.disabled = False
    log.setLevel(getattr(logging, level_name, logging.INFO))
    log.propagate = False
    if log.handlers:  # already wired up once this process
        return log
    log_file = os.environ.get("LOG_FILE", str(DEFAULT_LOG_FILE)).strip()
    if not log_file:
        log.addHandler(logging.NullHandler())
        return log
    try:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        log.addHandler(handler)
    except OSError as exc:  # a read-only dir mustn't crash the agent
        log.addHandler(logging.NullHandler())
        print(f"logging disabled (cannot write {log_file}): {exc}")
    return log


def _tool_source(name: str) -> str:
    """Label a tool call by its origin: the vault, the web, or some other tool."""
    if name in VAULT_TOOLS:
        return "vault"
    if "duckduckgo" in name or "web_search" in name or "web-search" in name:
        return "web"
    return "tool"


def detect_source(answer: str) -> str:
    """Best-effort read of the `Source:` label the model is asked to put first."""
    for line in answer.splitlines():
        stripped = line.strip().lstrip("*_# ").strip()
        if stripped.lower().startswith("source:"):
            return stripped.split(":", 1)[1].strip() or "unknown"
    return "unknown"


def log_interaction(question: str, answer: str, tools: list[str] | None = None) -> None:
    """Record one question, its answer, and where the answer came from."""
    log.info("Q: %s", question.replace("\n", " "))
    log.info(
        "A [source=%s | tools=%s]: %s",
        detect_source(answer),
        ", ".join(tools) if tools else "none",
        (answer or "").replace("\n", " "),
    )


class VaultCapability(AbstractCapability):
    """Answer from one Obsidian vault, and only from that vault.

    Bundles: instructions loaded from a markdown file + the vault's three tools
    + factual model settings. (Tool-call auditing/logging lives in `audit_hooks`,
    so it covers every tool, the vault's and web search alike.) A vault-specific
    prompt wins over the bundled one: if the vault root contains `system_prompt.md`,
    that file is used automatically.
    """

    def __init__(self, vault: Vault, prompt_file: str | Path | None = None) -> None:
        self.vault = vault
        if prompt_file is not None:
            self.prompt_file = Path(prompt_file).expanduser().resolve()
        else:
            in_vault = vault.root / "system_prompt.md"
            self.prompt_file = in_vault if in_vault.is_file() else DEFAULT_PROMPT_FILE
        if not self.prompt_file.is_file():
            raise ValueError(f"System prompt file not found: {self.prompt_file}")

    def get_instructions(self):
        prompt = self.prompt_file.read_text(encoding="utf-8")
        notes = ", ".join(e["note"] for e in self.vault.list_notes()[:60])
        return (
            f"{prompt}\n\n"
            f"## The vault\n\n"
            f"Vault: {self.vault.root.name}\n"
            f"Notes: {notes}"
        )

    def get_toolset(self):
        return FunctionToolset(
            tools=[self.vault.search_vault, self.vault.read_note, self.vault.list_notes]
        )

    def get_model_settings(self):
        # Answers should be grounded in the notes, not creative.
        return ModelSettings(temperature=0.0)


def audit_hooks() -> Hooks:
    """Lifecycle hooks without subclassing: time and log every tool call (the vault's
    and web search alike), then note when each run completes."""

    async def tool_execute(ctx, *, call, tool_def, args, handler):
        source = _tool_source(tool_def.name)
        start = time.perf_counter()
        try:
            result = await handler(args)
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            AUDIT.append(f"{source}: {tool_def.name}({dict(args)}) — failed after {elapsed:.1f} ms")
            log.warning(
                "%s: %s(%s) failed after %.1f ms: %s", source, tool_def.name, dict(args), elapsed, exc
            )
            raise
        elapsed = (time.perf_counter() - start) * 1000
        AUDIT.append(f"{source}: {tool_def.name}({dict(args)}) ⏱️ {elapsed:.1f} ms")
        log.info(
            "%s: %s(%s) ⏱️ %.1f ms → %s",
            source,
            tool_def.name,
            dict(args),
            elapsed,
            str(result).replace("\n", " ")[:200],
        )
        return result

    async def after_run(ctx, *, result):
        calls = sum(1 for a in AUDIT if "⏱️" in a or "failed after" in a)
        AUDIT.append(f"run-complete: {calls} tool call(s) recorded")
        log.info("run complete: %d tool call(s)", calls)
        return result

    return Hooks(after_run=after_run, tool_execute=tool_execute, id="audit-trail")
