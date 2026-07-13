# Obsidian Vault Agent — chat with any wiki-based knowledge base

A general-purpose CLI that answers questions from an **Obsidian vault**: a folder of
markdown notes that reference each other with `[[wikilinks]]`. Point it at any vault
and it searches the notes, follows the links between them, reads long notes section
by section, and cites its sources as wikilinks.

## How it works

The agent is composed from *capabilities* (Pydantic AI 2.0). `VaultCapability` is the
heart of it — one brick bundling the vault's tools, the model settings, and the
instructions, which are **loaded from a markdown file, not hardcoded**:

```python
agent = Agent(
    model,
    capabilities=[
        VaultCapability(vault),   # system_prompt.md + 3 vault tools + temp=0 + audit hook
        Thinking(effort="low"),
        audit_hooks(),
    ],
)
```

The vault tools:

| Tool | What it does |
|------|--------------|
| `search_vault(query)` | Keyword search across every note; returns the best notes with excerpts around the hits. |
| `read_note(name, section?)` | Reads a note by name or `[[wikilink]]` target (alias/heading forms resolve like in Obsidian). Long notes return a heading outline; pass a heading as `section` to read just that part. |
| `list_notes()` | Every note with its size and outgoing wikilinks — the vault's link graph. |

## The system prompt is a markdown file

The agent's behavior lives in [`system_prompt.md`](system_prompt.md) — edit it, no
code changes needed (`/reload` in the REPL picks up edits). Resolution order:

1. `SYSTEM_PROMPT=/path/to/prompt.md` (env or `.env`), if set
2. `system_prompt.md` **inside the vault**, if it exists — per-vault prompts
3. the bundled `system_prompt.md` next to the scripts

## Run it

```bash
uv sync

uv run python cli.py ~/backup/giro                  # interactive REPL against a vault
uv run python main.py ~/backup/giro "Mi az a GIROFix?"   # one question, non-interactive

uv run python cli.py                                # vault from VAULT_PATH/VAULT_NAME in .env
```

In `.env`, `VAULT_PATH` is the base directory holding all your vaults and `VAULT_NAME`
picks the active one (a `VAULT_PATH` pointing straight at a vault still works).

## Web terminal

The same REPL in the browser — a dark terminal page with the identical slash
commands, markdown-rendered answers, and the per-turn tools footer:

```bash
uv run python web.py                # serves http://127.0.0.1:8010
```

The vault comes from `VAULT_PATH`/`VAULT_NAME` in `.env` (same as the CLI);
`WEB_HOST`/`WEB_PORT` override the bind address. `/vault` and `/model` persist to
`.env` exactly like the CLI, so both frontends stay on the same configuration.
`/exit` is CLI-only — close the tab (the server keeps running); one turn runs at a
time, a second message while the agent is busy gets an explicit "turn already
running" warning.

Avoid `uvicorn --reload` while the Headroom proxy is enabled — every reload
respawns the proxy subprocess. `static/index.html` is re-read per request, so
frontend edits need no reload anyway; for backend work under `--reload` set
`HEADROOM=0`.

REPL commands: `/notes` (the vault's notes + link graph), `/read <note>`,
`/vault [name]` (list the vaults in the base dir, or switch to one — persists to
`.env`), `/model [name]` (list model providers, or switch between `local` and
`deepseek` — persists to `.env`), `/prompt`, `/reload`, `/clear`, `/help`, `/exit`.
After every answer the CLI shows a **vault tools used this turn** panel listing which
tools fired, the arguments passed, the elapsed time per call (⏱️ ms), and the active
model name — so you can see where the answer came from and how long each lookup took.

## Tests

```bash
uv run python test_agent.py            # unit tests: vault layer + wiring (no API)
uv run python test_agent.py --live     # + end-to-end checks against a real model
uv run python test_web.py              # web terminal: endpoints + dispatch (no API)
```

## Model / keys

Defaults to a local OpenAI-compatible server (LM Studio etc.) on
`http://localhost:1234/v1` with the `mlx-community-ornith-1.0-9b-bf16` model loaded —
no API key needed. `MODEL=local:<model-name>` picks a different local model; the name
must match one loaded in the server (`curl localhost:1234/v1/models`). Override the
endpoint with `LOCAL_LLM_URL=...`:

```bash
uv run python cli.py ~/vault                                       # local default
MODEL=local:qwen/qwen3-4b uv run python cli.py ~/vault             # other local model
```

Cloud models work too; keys load from a local `.env` and are never printed:

```bash
MODEL=openrouter:anthropic/claude-sonnet-4.6 uv run python main.py ~/vault "..."  # OPENROUTER_API_KEY
MODEL=anthropic:claude-sonnet-4-6 uv run python main.py ~/vault "..."             # ANTHROPIC_API_KEY
```

### Switching providers in the REPL

`/model` lists the named providers and marks the active one; `/model <name>` switches
between them, rebuilds the agent, and persists `MODEL` to `.env`:

- `local` — the local server above (default, no key).
- `deepseek` — the [DeepSeek API](https://api-docs.deepseek.com/), using
  `deepseek:deepseek-reasoner`. Needs `DEEPSEEK_API_KEY` in `.env`; override the model
  with `DEEPSEEK_MODEL=...` (e.g. `deepseek:deepseek-chat`).

```bash
you › /model deepseek     # switch to DeepSeek (persists MODEL to .env)
you › /model local        # switch back
```
