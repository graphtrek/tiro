# AGENTS.md

## Core Workspace Principles
- **Multi-project scope**: This is a `uv`-based Python workspace. Each sub-project (`graphtrek-gmail/`, `nav-szamla/`, `moneypenny/`) has its own `pyproject.toml` and `.env`.
- **Isolated virtual environments**: **Every sub-project has its own `.venv` at `<project>/.venv`. There is NO shared/root venv.** Always use the target project's own environment for its commands — `cd <project>` then either `source .venv/bin/activate` or prefix with `uv run`. Never run a project's code from another project's venv or assume a workspace-wide environment.
- **Context Isolation**: Always `cd` into the specific project directory before running commands, syncing deps, or inspecting `.env` files.
- **Dependency management**: Use `cd <project> && uv sync` to install into that project's `.venv`, and `uv run <cmd>` to execute inside it. `pip install -e .` also works once the venv is activated.
- **Workspace meta**: Root holds `python-for-ai.code-workspace` (VS Code), `.env.example` (Scaleway inference defaults), and project-wide docs (this file, `CLAUDE.md`).

## moneypenny — Design Wiki (Obsidian)
- **Not code**: an Obsidian vault of `*-spec.md` (specifications) and `*-prompt.md` (generation prompts) plus `INDEX.md` (navigation). Written in Hungarian.
- **System described**: "Moneypenny" — an invoice-automation pipeline of five Python microservices, each with a FastAPI REST interface and a Typer/Click CLI:

  | # | Service | Port | Role |
  |---|---|---|---|
  | 4 | `szamla-db` | 8003 | MASTER orchestrator — DB persistence + reconciliation |
  | 3 | `nav-szamla` | 8002 | NAV Online Számla API query |
  | 2 | `pdf-szamla` | 8001 | PDF metadata extraction (OCR/Regex) |
  | 1 | `graphtrek-email` | 8000 | Gmail PDF attachment download |
  | 5 | `wise` | 8004 | Wise bank-statement download/sync (independent entry point) |

- **Call chain**: entry point `POST /api/v1/sync` on `szamla-db` (8003) → `nav-szamla` → `pdf-szamla` → `graphtrek-email`. `wise` is a separate source that writes directly into `szamla-db`'s PostgreSQL.
- **Implementation status**: `nav-szamla` and `graphtrek-gmail` (the `graphtrek-email` service) are the projects already built in this workspace; the others are specced in the wiki.

## nav-szamla — NAV Online Számla 3.0 client
- **Purpose**: Hungarian tax-authority (NAV) Online Számla 3.0 REST/XML client (`/invoiceService/v3`) using technical-user authentication (SHA-512 password hash, SHA3-512 signature, AES-128 token).
- **Layout**: core package `nav_szamla/` (`config`, `models`, `crypto`, `client`, `auth`, `query`, `reporting`), `api/` (FastAPI), `cli/` (Click CLI). `requires-python >=3.11`.
- **Run**:
  - API: `cd nav-szamla && uvicorn api.main:app --reload` (or `python -m api.main`), default port 8000.
  - CLI: `python -m cli.main login | list | show <invoice>` (installed as `nav` script).
  - Tests: `uv run pytest tests/ -v`. Lint/format: `uv run ruff check|format nav_szamla/ api/ cli/`.
- **Env** (`.env` from `.env.example`): `USERNAME`, `PASSWORD`, `LICENSE_KEY`, `CSERE_KEY`, `TAX_NUMBER`, `SOFTWARE_*`, `ENVIRONMENT` (`test`/`production`), optional `ENDPOINT_URL`, `API_HOST`/`API_PORT`, `LOG_LEVEL`.

## graphtrek-gmail — Gmail CLI + FastAPI
- **Purpose**: CLI and REST interface for Gmail (list/read/send/reply/trash/mark read-unread, labels) via Google OAuth2. Mirrors the `nav-szamla` structure; serves as the `graphtrek-email` service in the Moneypenny pipeline.
- **Layout**: package `graphtrek_gmail/` with `api/main.py` (FastAPI, Typer scripts), `cli/main.py`, `client/`, `config/`, `models/`. `requires-python >=3.9`.
- **Run**:
  - API: `cd graphtrek-gmail && uvicorn graphtrek_gmail.api.main:app --reload`.
  - CLI: `python -m graphtrek_gmail.cli.main <command>` (installed as `graphtrek-gmail` script).
- **Auth**: place OAuth2 desktop `credentials.json` in project root; `token.json` is generated on first auth. Configurable via `GOOGLE_CREDENTIALS_FILE` / `GOOGLE_TOKEN_FILE` in `.env`. These files are not committed.

## Conventions
- New microservices follow the `nav-szamla` pattern: a typed core package + parallel `api/` (FastAPI) and `cli/` (Click/Typer) entry points, `pydantic-settings` for `.env` config, `uv` for deps, `pytest` under `tests/`.
- Inference defaults (root `.env.example`): `SCALEWAY_BASE_URL`, `SCALEWAY_API_KEY`.
