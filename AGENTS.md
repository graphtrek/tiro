# AGENTS.md

## Core Workspace Principles
- **Multi-project scope**: This is a `uv`-based Python workspace. Each sub-project (`attachment-downloader/`, `nav-invoice/`, `moneypenny/`) has its own `pyproject.toml` and `.env`.
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
  | 3 | `nav-invoice` | 8002 | NAV Online Számla API query |
  | 2 | `invoice-file-filter` | 8001 | PDF metadata extraction (OCR/Regex) |
  | 1 | `attachment-downloader` | 8000 | Gmail PDF attachment download |
  | 5 | `wise` | 8004 | Wise bank-statement download/sync (independent entry point) |

- **Call chain**: entry point `POST /api/v1/sync` on `szamla-db` (8003) → `nav-invoice` → `invoice-file-filter` → `attachment-downloader`. `wise` is a separate source that writes directly into `szamla-db`'s PostgreSQL.
- **Implementation status**: `nav-invoice` and `attachment-downloader` are the projects already built in this workspace; the others are specced in the wiki.

## nav-invoice — NAV Online Számla 3.0 client
- **Purpose**: Hungarian tax-authority (NAV) Online Számla 3.0 REST/XML client (`/invoiceService/v3`) using technical-user authentication (SHA-512 password hash, SHA3-512 signature, AES-128 token).
- **Layout**: core package `nav_invoice/` (`config`, `models`, `crypto`, `client`, `auth`, `query`, `reporting`), `api/` (FastAPI), `cli/` (Click CLI). `requires-python >=3.11`.
- **Run**:
  - API: `cd nav-invoice && uvicorn api.main:app --reload` (or `python -m api.main`), default port 8000.
  - CLI: `python -m cli.main login | list | show <invoice>` (installed as `nav` script).
  - Tests: `uv run pytest tests/ -v`. Lint/format: `uv run ruff check|format nav_invoice/ api/ cli/`.
- **Env** (`.env` from `.env.example`): `USERNAME`, `PASSWORD`, `LICENSE_KEY`, `CSERE_KEY`, `TAX_NUMBER`, `SOFTWARE_*`, `ENVIRONMENT` (`test`/`production`), optional `ENDPOINT_URL`, `API_HOST`/`API_PORT`, `LOG_LEVEL`.

## attachment-downloader — Gmail CLI + FastAPI
- **Purpose**: CLI and REST interface for Gmail (list/read/send/reply/trash/mark read-unread, labels) via Google OAuth2. Mirrors the `nav-invoice` structure; serves as the `attachment-downloader` service in the Moneypenny pipeline.
- **Layout**: package `attachment_downloader/` with `api/main.py` (FastAPI), `cli/main.py`, `client.py`, `config.py`, `models.py`. `requires-python >=3.9`.
- **Run**:
  - API: `cd attachment-downloader && uvicorn attachment_downloader.api.main:app --reload`.
  - CLI: `python -m attachment_downloader.cli.main <command>` (installed as `attachment-downloader` script).
- **Auth**: place OAuth2 desktop `credentials.json` in project root; `token.json` is generated on first auth. Configurable via `GOOGLE_CREDENTIALS_FILE` / `GOOGLE_TOKEN_FILE` in `.env`. These files are not committed.

## Conventions
- New microservices follow the `nav-invoice` pattern: a typed core package + parallel `api/` (FastAPI) and `cli/` (Click/Typer) entry points, `pydantic-settings` for `.env` config, `uv` for deps, `pytest` under `tests/`.
- Inference defaults (root `.env.example`): `SCALEWAY_BASE_URL`, `SCALEWAY_API_KEY`.
