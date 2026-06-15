# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a multi-project `uv`-based Python workspace. **Each sub-project has its own isolated virtual environment (`.venv`), `pyproject.toml`, and `.env`. There is NO shared/root virtual environment.**

> **IMPORTANT — always use the project's own venv.** Before running any Python, test, or dependency command, `cd` into the specific sub-project and use *that* project's environment — either activate it (`source .venv/bin/activate`) or prefix with `uv run`. Never run a project's code from another project's venv or assume a workspace-wide environment.

| Directory | Purpose |
|---|---|
| `moneypenny/` | Obsidian design wiki (Hungarian): specs + prompts for an invoice-automation microservice pipeline |
| `nav-invoice/` | NAV Online Számla 3.0 REST/XML client (FastAPI + CLI) |
| `attachment-downloader/` | Gmail CLI + FastAPI interface (Google OAuth2) |

Root files: `python-for-ai.code-workspace` (VS Code workspace + launch configs), `.env.example` (Scaleway inference defaults: `SCALEWAY_BASE_URL`, `SCALEWAY_API_KEY`), `AGENTS.md`, this file.

### Dependency & run conventions
- Each project's `.venv` lives at `<project>/.venv` and is the only environment you should use for that project's commands.
- Install: `cd <project> && uv sync` (creates/updates `<project>/.venv`; or `pip install -e .` after activating it).
- Run a command in the project's env: `cd <project> && uv run <cmd>`, or `source <project>/.venv/bin/activate` first.
- Each service exposes both a **FastAPI** app under `api/` and a **CLI** (Click/Typer) under `cli/`, backed by a typed core package. Config via `pydantic-settings` reading `.env`. Tests under `tests/` (`uv run pytest`).

## moneypenny — design wiki (not code)

An Obsidian vault, written in Hungarian, that specs the **"Moneypenny"** invoice-automation system. Files: `*-spec.md` (specifications), `*-prompt.md` (code-generation prompts), `INDEX.md` (navigation hub, uses `[[wikilinks]]`).

Describes five Python microservices, each with a FastAPI REST interface and a Typer/Click CLI:

| # | Service | Port | Role |
|---|---|---|---|
| 4 | `szamla-db` | 8003 | MASTER orchestrator — PostgreSQL persistence + reconciliation |
| 3 | `nav-invoice` | 8002 | NAV Online Számla API query |
| 2 | `invoice-file-filter` | 8001 | PDF metadata extraction (OCR/Regex) |
| 1 | `attachment-downloader` | 8000 | Gmail PDF attachment download |
| 5 | `wise` | 8004 | Wise bank-statement download/sync |

**Flow**: entry point `POST /api/v1/sync` on `szamla-db` → synchronously calls `nav-invoice` → `invoice-file-filter` → `attachment-downloader`. The pipeline downloads PDF invoice attachments from Gmail, extracts metadata, cross-references against the NAV Online Számla API, and persists everything (invoices, suppliers, customers) to PostgreSQL. `wise` is an independent entry point (own `POST /sync`) that writes Wise transactions directly into `szamla-db`'s PostgreSQL.

**Status**: `nav-invoice` and `attachment-downloader` are implemented in this workspace; `invoice-file-filter`, `szamla-db`, and `wise` are specced only.

## nav-invoice — NAV Online Számla 3.0 client

Hungarian tax-authority (NAV) Online Számla **3.0** REST/XML client (`/invoiceService/v3`) using technical-user (`technikai felhasználó`) authentication. `requires-python >=3.11`.

### Running

```bash
cd nav-invoice
uv sync

# REST API (default port 8000)
uvicorn api.main:app --reload         # or: python -m api.main

# CLI (installed as `nav` script)
python -m cli.main login              # test tokenExchange
python -m cli.main list --from 2026-05-01 --to 2026-05-31 [--direction INBOUND] [--json]
python -m cli.main show <invoice_number>

# Tests / lint
uv run pytest tests/ -v
uv run ruff check  nav_invoice/ api/ cli/
uv run ruff format nav_invoice/ api/ cli/
```

### Architecture
- `nav_invoice/` — core package:
  - `config.py` — Pydantic settings (`.env`)
  - `models.py` — data models
  - `crypto.py` — SHA-512 password hash, SHA3-512 request signature, AES-128 token decryption
  - `client.py` — REST client + XML envelope construction
  - `auth.py` — `tokenExchange` (login)
  - `query.py` — `queryInvoiceDigest` / `queryInvoiceData` / `queryTaxpayer`
  - `reporting.py` — `manageInvoice` / `queryTransactionStatus`
- `api/main.py` — FastAPI endpoints (`/health`, `/auth/login`, `/invoices`, `/invoices/{szamlaszam}`, `/report`, `/settings`)
- `cli/main.py` — Click CLI

### Environment (`.env` from `.env.example`)
`USERNAME`, `PASSWORD`, `LICENSE_KEY` (XML signKey), `CSERE_KEY` (XML exchangeKey, 16 chars), `TAX_NUMBER` (8 digits), `SOFTWARE_*` (software registration block required in every request), `ENVIRONMENT` (`test`/`production`), optional `ENDPOINT_URL` override, `API_HOST`/`API_PORT`, `LOG_LEVEL`.

## attachment-downloader — Gmail CLI + FastAPI

CLI and REST interface for Gmail (list / read / send / reply / trash / mark read-unread / labels) via Google OAuth2. Mirrors the `nav-invoice` structure and serves as the `attachment-downloader` service in the Moneypenny pipeline. `requires-python >=3.9`.

### Running

```bash
cd attachment-downloader
uv sync

# REST API
uvicorn attachment_downloader.api.main:app --reload

# CLI (installed as `attachment-downloader` script)
python -m attachment_downloader.cli.main list
python -m attachment_downloader.cli.main read   <email_id>
python -m attachment_downloader.cli.main send   --to <addr> --subject <s> --body <b>
python -m attachment_downloader.cli.main reply  <email_id> <body>
python -m attachment_downloader.cli.main trash  <email_id>
python -m attachment_downloader.cli.main mark-read|mark-unread <email_id>
```

### Architecture
- `attachment_downloader/` — `api/main.py` (FastAPI), `cli/main.py` (Typer), `client/client.py` (Gmail API wrapper), `config/config.py` (settings), `models/models.py`.
- API endpoints: `GET /emails`, `GET /emails/{id}`, `POST /emails/send`, `POST /emails/{id}/reply`, `POST /emails/{id}/trash`, `POST /emails/{id}/read`, `POST /emails/{id}/unread`, `GET /labels`.

### Auth
Place OAuth2 desktop `credentials.json` in the project root; `token.json` is generated on first successful auth. Override paths via `GOOGLE_CREDENTIALS_FILE` / `GOOGLE_TOKEN_FILE` in `.env`. Neither credential file is committed.
