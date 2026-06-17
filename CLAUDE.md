# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a multi-project `uv`-based Python workspace. **Each sub-project has its own isolated virtual environment (`.venv`), `pyproject.toml`, and `.env`. There is NO shared/root virtual environment.**

> **IMPORTANT — always use the project's own venv.** Before running any Python, test, or dependency command, `cd` into the specific sub-project and use *that* project's environment — either activate it (`source .venv/bin/activate`) or prefix with `uv run`. Never run a project's code from another project's venv or assume a workspace-wide environment.

| Directory | Purpose |
|---|---|
| `moneypenny/` | Obsidian design wiki (Hungarian): specs + prompts for the Moneypenny pipeline |
| `nav-invoice/` | NAV Online Számla 3.0 REST/XML client (FastAPI + CLI), port 8002 |
| `attachment-downloader/` | Gmail PDF attachment downloader (FastAPI + CLI), port 8000 |
| `invoice-file-filter/` | PDF text extraction + invoice filtering (FastAPI + CLI), port 8001 |
| `invoice-core/` | Master orchestrator — PostgreSQL persistence + web UI (FastAPI + CLI), port 8004 |
| `wise/` | Wise bank-statement download/sync (FastAPI + CLI), port 8003 |

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
| 4 | `invoice-core` | 8004 | MASTER orchestrator — PostgreSQL persistence + reconciliation |
| 3 | `nav-invoice` | 8002 | NAV Online Számla API query |
| 2 | `invoice-file-filter` | 8001 | PDF metadata extraction (OCR/Regex) |
| 1 | `attachment-downloader` | 8000 | Gmail PDF attachment download |
| 5 | `wise` | 8003 | Wise bank-statement download/sync |

**Flow**: entry point `POST /api/v1/sync` on `invoice-core` → synchronously calls `nav-invoice` → `invoice-file-filter` → `attachment-downloader`. The pipeline downloads PDF invoice attachments from Gmail, extracts metadata, cross-references against the NAV Online Számla API, and persists everything (invoices, suppliers, customers) to PostgreSQL. `wise` is an independent entry point (own `POST /sync`) that writes Wise transactions directly into `invoice-core`'s PostgreSQL.

**Status**: All five microservices are fully implemented in this workspace.

## nav-invoice — NAV Online Számla 3.0 client

Hungarian tax-authority (NAV) Online Számla **3.0** REST/XML client (`/invoiceService/v3`) using technical-user (`technikai felhasználó`) authentication. `requires-python >=3.11`.

### Running

```bash
cd nav-invoice
uv sync

# REST API (port 8002)
python run_api.py
# or: uv run uvicorn nav_invoice.api.main:app --host 0.0.0.0 --port 8002 --reload

# CLI (installed as `nav` script)
uv run nav login                          # test tokenExchange
uv run nav list --from 2026-05-01 --to 2026-05-31 [--direction INBOUND] [--json]
uv run nav show <invoice_number>

# Tests / lint
uv run pytest tests/ -v
uv run ruff check src/
uv run ruff format src/
```

### Architecture
- `src/nav_invoice/` — core package:
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

## attachment-downloader — Gmail PDF attachment downloader

Downloads PDF attachments from Gmail for a given date range and exposes them via a REST API consumed by `invoice-file-filter`. `requires-python >=3.9`.

### Running

```bash
cd attachment-downloader
uv sync --extra gmail

# REST API (port 8000)
uv run uvicorn attachment_downloader.api.main:app --host 0.0.0.0 --port 8000 --reload

# CLI (installed as `attachment-downloader` script)
uv run attachment-downloader --start 2026-05-01 --end 2026-05-31
uv run attachment-downloader --start 2026-05-01 --end 2026-05-31 --output invoices

# Tests
uv run pytest tests/ -v
```

### Architecture
- `src/attachment_downloader/` — `api/main.py` (FastAPI: `POST /api/v1/jobs`, `GET/DELETE /api/v1/cache`), `cli/main.py` (Typer), `providers/gmail/client.py` (GmailClient), `base.py` (EmailClient Protocol), `config.py`, `models.py`, `cache.py`.
- Files saved as `YYYY-MM-DD_NNNN_<sanitized>.pdf`. Counter resumes across runs.

### Auth
Place OAuth2 desktop `credentials.json` in the project root; `token.json` is generated on first successful auth. Override paths via `GOOGLE_CREDENTIALS_FILE` / `GOOGLE_TOKEN_FILE` in `.env`. Neither credential file is committed.

## invoice-file-filter — PDF extraction + invoice filtering

Calls attachment-downloader, selects PDFs that are invoices by keyword matching, extracts text (pdfplumber + optional Tesseract OCR fallback) and exposes the result. `requires-python >=3.11`.

### Running

```bash
cd invoice-file-filter
uv sync

# REST API (port 8001)
python run_api.py
# or: uv run uvicorn invoice_file_filter.api.main:app --host 0.0.0.0 --port 8001 --reload

# CLI (installed as `invoice-file-filter` script)
uv run invoice-file-filter process --start 2026-05-01 --end 2026-05-31
uv run invoice-file-filter process --local --output-dir ./downloads
uv run invoice-file-filter words invoice.pdf

# Tests
uv run pytest tests/ -v
```

### Architecture
- `src/invoice_file_filter/` — `api/main.py` (FastAPI: `POST /api/v1/invoices/extract`, `POST /api/v1/pdf/words`), `cli/main.py` (Typer), `service.py`, `client.py` (calls attachment-downloader), `config.py`, `models.py`.
- System deps required for OCR: `brew install poppler tesseract tesseract-lang` (macOS).

### Environment
`ATTACHMENT_DOWNLOADER_URL`, `OUTPUT_DIR`, `INVOICE_KEYWORDS` (JSON array), `OCR_ENABLED`, `OCR_LANGUAGE` (`hun+eng`), `API_HOST`/`API_PORT`, `LOG_LEVEL`.

## invoice-core — master orchestrator

Orchestrates the full pipeline: fetches NAV invoices, PDF files, Wise transactions, reconciles everything, and persists to PostgreSQL. Includes a full web UI (HTMX + Bootstrap + DataTables) at `/ui/`. `requires-python >=3.11`.

### Running

```bash
cd invoice-core
uv sync
uv run alembic upgrade head   # apply DB migrations (first time + after updates)

# REST API + UI (port 8004)
python run_api.py
# or: uv run uvicorn invoice_core.api.main:app --host 0.0.0.0 --port 8004 --reload

# CLI (installed as `invoice-core` script)
uv run invoice-core sync                                # full sync (last 30 days)
uv run invoice-core sync --start 2026-05-01 --end 2026-05-31
uv run invoice-core sync-nav | sync-pdf | sync-wise | sync-match
uv run invoice-core report --month 2026-05
uv run invoice-core link <invoice_number> <filename>
uv run invoice-core link-wise <wise_transaction_id> <filename>

# Tests
uv run pytest tests/ -v
```

### Architecture
- `src/invoice_core/` — `api/main.py` (FastAPI REST), `ui/router.py` (HTMX UI at `/ui/`), `services/` (dashboard, invoice, partner, transaction, invoice_file), `templates/` (Jinja2), `service.py` (sync orchestration), `db.py` (SQLAlchemy ORM), `models.py`, `config.py`, `nav_client.py`, `pdf_client.py`, `wise_client.py`.
- DB: PostgreSQL in production, SQLite in-memory for tests. Migrations via Alembic.

### Sync pipeline and linking logic
1. **sync_nav** — upserts NAV invoices, suppliers, customers.
2. **sync_pdf** — upserts InvoiceFile records; links invoices to files by invoice number in filename or PDF text.
3. **sync_wise** — upserts WiseTransaction records; links to invoices via `payment_reference`; marks linked invoices PAID.
4. **sync_match** — links unmatched transactions to files (transitive → authoritative reference → scored); then back-links any transaction sharing a file with an invoice to that invoice and marks it PAID.

### Environment
`DB_URL` (JDBC format, auto-converted), `DB_USER`, `DB_PWD`, `NAV_INVOICE_URL` (`:8002`), `INVOICE_FILE_FILTER_URL` (`:8001`), `WISE_URL` (`:8003`), `SYNC_TIMEOUT`, `API_HOST`/`API_PORT` (8004), `LOG_LEVEL`.

## wise — Wise bank-statement service

Downloads Wise balance statements via the Wise API and exposes structured transactions as JSON. Leaf service — calls only the Wise API, holds no DB. `requires-python >=3.11`.

### Running

```bash
cd wise
uv sync

# REST API (port 8003)
python run_api.py
# or: uv run uvicorn wise_szamla.api.main:app --host 0.0.0.0 --port 8003 --reload

# CLI (installed as `wise-szamla` script)
uv run wise-szamla status
uv run wise-szamla balances
uv run wise-szamla sync --start 2026-05-01 --end 2026-05-31 [--currency HUF] [--json]
uv run wise-szamla balance-statements [--from DATE] [--currency HUF] [--json]
uv run wise-szamla import statement_<id>_<currency>_<from>_<to>.csv

# Tests
uv run pytest tests/ -v
```

### Architecture
- `src/wise_szamla/` — `api/main.py` (FastAPI: `POST /sync`, `GET /balance-statements`, `GET /balances`, etc.), `cli/main.py` (Typer), `client.py` (WiseClient — Bearer auth + retry), `sync.py`, `csv_import.py` (manual CSV fallback), `config.py`, `models.py`.
- SCA required for balance-statement download: generate RSA keypair, upload public key to Wise dashboard, set `WISE_SCA_PRIVATE_KEY_PATH` in `.env`. Manual CSV download (`balance-statements/`) is the fallback.

### Environment
`WISE_API_KEY`, `WISE_PROFILE_ID`, `WISE_ACCOUNT_CURRENCY` (default `EUR`), `WISE_SANDBOX`, `WISE_SCA_PRIVATE_KEY_PATH`, `BALANCE_STATEMENTS_DIR`, `API_HOST`/`API_PORT` (8003), `LOG_LEVEL`, `REQUEST_TIMEOUT`, `MAX_RETRIES`.
