"""Ask an Obsidian vault one question from the command line.

Run it:
    uv run python main.py /path/to/vault "your question"
    uv run python main.py "your question"          # vault from VAULT_PATH/VAULT_NAME (.env)

The interactive REPL lives in cli.py; this is the non-interactive entry point.

By default it expects a local OpenAI-compatible server (LM Studio etc.) running on
http://localhost:1234/v1 (override: LOCAL_LLM_URL) with the
mlx-community-ornith-1.0-9b-bf16 model loaded - no API key needed. Override the model
with MODEL=...; cloud models (e.g. MODEL=openrouter:anthropic/claude-sonnet-4.6) need
an OPENROUTER_API_KEY or ANTHROPIC_API_KEY, loaded from a local .env.

The system prompt is NOT hardcoded: it loads from system_prompt.md next to this file,
or from a system_prompt.md inside the vault itself, or from SYSTEM_PROMPT=<path>.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows consoles default to cp1252, which crashes on emoji the model emits.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Load credentials from a local .env (preferred) and the process environment.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
load_dotenv(override=False)

from pydantic_ai import Agent
from pydantic_ai.capabilities import Thinking, WebSearch
from pydantic_ai.usage import UsageLimits

from capabilities import AUDIT, VaultCapability, audit_hooks, log, log_interaction, setup_logging
from obsidian_vault import Vault

# Default expects a local OpenAI-compatible server (LM Studio etc.) on LOCAL_LLM_URL
# with this model loaded. Set MODEL=... to override (e.g. a cloud model).
DEFAULT_LOCAL_MODEL = "local:mlx-community-ornith-1.0-9b-bf16"

# Named model providers the REPL's /model command can switch between. "local" is the
# default (an OpenAI-compatible server, no key); "deepseek" hits the DeepSeek API
# (https://api-docs.deepseek.com/) and needs DEEPSEEK_API_KEY. Two extra local presets
# make it easy to switch between installed local models.
PROVIDERS = {
    "local": os.environ.get("LOCAL_MODEL", DEFAULT_LOCAL_MODEL),
    "gemma": os.environ.get("GEMMA_MODEL", "local:gemma-4-12B-it-bf16"),
    "ornith-uncensored": os.environ.get(
        "ORNITH_UNCENSORED_MODEL", "local:Ornith-1.0-9B-Uncensored-mlx-bf16"
    ),
    "deepseek": os.environ.get("DEEPSEEK_MODEL", "deepseek:deepseek-reasoner"),
}

MODEL = os.environ.get("MODEL", PROVIDERS["local"])

# Where "local:" models are served (LM Studio's default). Any OpenAI-compatible URL works.
LOCAL_LLM_URL = os.environ.get("LOCAL_LLM_URL", "http://localhost:1234/v1")
# API key sent to OpenAI-compatible local servers (some require a specific value,
# e.g. "test").
LOCAL_API_KEY = os.environ.get("LOCAL_API_KEY", "local")

# pydantic-ai caps model/tool round-trips per run() call at 50 by default; a vault
# question can need several search_vault/read_note calls before the model answers,
# so raise the ceiling (still finite, to catch a genuinely stuck agent). Override
# with REQUEST_LIMIT=... (an integer, or "none" for no limit).
_request_limit_env = os.environ.get("REQUEST_LIMIT", "200")
REQUEST_LIMIT = None if _request_limit_env.lower() == "none" else int(_request_limit_env)
USAGE_LIMITS = UsageLimits(request_limit=REQUEST_LIMIT)


def resolve_model(spec: str):
    """`local:<name>` targets an OpenAI-compatible server (LM Studio etc.) on LOCAL_LLM_URL.

    When a Headroom proxy is active (see headroom_proxy), every provider is routed
    through it instead: the model becomes an OpenAI-compatible client pointed at the
    proxy, which compresses each request and forwards it to the real upstream.
    """
    from headroom_proxy import proxy_api_key_for, proxy_base_url

    base_url = proxy_base_url()
    if base_url is not None:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        # Strip the provider prefix to get the upstream model name (e.g.
        # "openrouter:anthropic/claude" -> "anthropic/claude"); the proxy forwards
        # the key we send on to that provider.
        model_name = spec.split(":", 1)[1] if ":" in spec else spec
        return OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=proxy_api_key_for(spec) or "none"),
        )

    if spec.startswith("local:"):
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        # Some local servers validate the key (e.g. require "test").
        return OpenAIChatModel(
            spec.removeprefix("local:"),
            provider=OpenAIProvider(base_url=LOCAL_LLM_URL, api_key=LOCAL_API_KEY),
        )
    return spec


# Which env var each model spec needs before it can run. Maps a spec prefix to the
# variable name; used to warn early instead of failing mid-run on a missing key.
_KEY_BY_PREFIX = {
    "deepseek:": "DEEPSEEK_API_KEY",
    "openrouter:": "OPENROUTER_API_KEY",
    "anthropic:": "ANTHROPIC_API_KEY",
}


def missing_credentials(spec: str) -> str | None:
    """The name of the env var a model spec needs but doesn't have set, or None when
    it's ready to run. Local models need nothing; unknown cloud specs are assumed fine."""
    if spec.startswith("local:"):
        return None
    for prefix, env_var in _KEY_BY_PREFIX.items():
        if spec.startswith(prefix):
            return None if os.getenv(env_var) else env_var
    return None


def build_vault_agent(vault: Vault, model: str | None = None) -> tuple[Agent, VaultCapability]:
    """The vault agent: three bricks, zero constructor sprawl. `model` overrides MODEL."""
    setup_logging()
    vault_cap = VaultCapability(vault, prompt_file=os.environ.get("SYSTEM_PROMPT"))
    agent = Agent(
        resolve_model(model or MODEL),
        capabilities=[
            vault_cap,                # md-file instructions + 3 vault tools + temp=0
            Thinking(effort="high"),  # a built-in capability, snapped in as one line
            WebSearch(local="duckduckgo"),  # web search, DuckDuckGo fallback for non-native models
            audit_hooks(),            # lifecycle hooks, no subclass needed
        ],
    )
    return agent, vault_cap


def open_vault(args: list[str]) -> tuple[Vault, list[str]]:
    """Vault path from the first CLI arg if it's a directory, else VAULT_PATH/VAULT_NAME,
    else VAULT_PATH directly (legacy: VAULT_PATH pointing straight at a vault)."""
    if args and Path(args[0]).expanduser().is_dir():
        return Vault(args[0]), args[1:]
    base = os.environ.get("VAULT_PATH")
    if base:
        name = os.environ.get("VAULT_NAME")
        if name:
            target = Path(base).expanduser() / name
            if not target.is_dir():
                raise SystemExit(
                    f"VAULT_NAME={name!r} is not a directory under VAULT_PATH={base!r}."
                )
            return Vault(target), args
        return Vault(base), args
    raise SystemExit(
        "No vault given. Pass the vault directory as the first argument or set "
        "VAULT_PATH (base dir) and VAULT_NAME in .env, e.g.:\n"
        '  uv run python main.py ~/backup/giro "question"'
    )


def main() -> None:
    try:
        vault, rest = open_vault(sys.argv[1:])
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if not rest:
        raise SystemExit(
            'No question given, e.g.:\n  uv run python main.py ~/backup/giro "What is GIROFix?"\n'
            "For an interactive session use: uv run python cli.py <vault>"
        )

    question = " ".join(rest)
    agent, vault_cap = build_vault_agent(vault)

    print(f"model:  {MODEL}")
    print(f"vault:  {vault.root}  ({len(vault.list_notes())} notes)")
    print(f"prompt: {vault_cap.prompt_file}")
    print(f"\n>>> {question}")

    AUDIT.clear()
    try:
        result = agent.run_sync(question, usage_limits=USAGE_LIMITS)
    except Exception as exc:  # noqa: BLE001 - log before letting the process exit non-zero
        log.error("run failed for question %r: %s", question, exc, exc_info=True)
        raise
    print(result.output)

    tools = sorted({a.split(":", 1)[0] for a in AUDIT if "⏱️" in a or "failed after" in a})
    log_interaction(question, result.output, tools)

    if AUDIT:
        print("\n  tool calls this run:")
        for line in AUDIT:
            print(f"    - {line}")


if __name__ == "__main__":
    main()
