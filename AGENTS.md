# AGENTS.md

## Core Workspace Principles
- **Multi-project scope**: This is a `uv`-based Python workspace. Each sub-project has its own `pyproject.toml`, `.env`, and isolated `.venv`.
- **Isolated virtual environments**: **Every sub-project has its own `.venv` at `<project>/.venv`. There is NO shared/root venv.** Always use the target project's own environment — `cd <project>` then either `source .venv/bin/activate` or prefix with `uv run`. Never cross-use environments.
- **Context Isolation**: Always `cd` into the specific project directory before running commands, syncing deps, or inspecting `.env` files.
- **Dependency management**: `cd <project> && uv sync` installs into that project's `.venv`; `uv run <cmd>` executes inside it.
- **Workspace meta**: Root holds `python-for-ai.code-workspace` (VS Code), `.env.example` (Scaleway inference defaults), and project-wide docs (this file, `CLAUDE.md`).

## moneypenny — Design Wiki (Obsidian)
- **Not code**: an Obsidian vault of `*-spec.md` (specifications) and `*-prompt.md` (generation prompts) plus `INDEX.md` (navigation). Written in Hungarian.
- **System described**: "Moneypenny" — an invoice-automation pipeline of five Python microservices, each with a FastAPI REST interface and a Typer/Click CLI:

  | # | Service | Port | Role |
  |---|---|---|---|
  | 4 | `invoice-core` | 8004 | MASTER orchestrator — DB persistence + reconciliation + web UI |
  | 3 | `nav-invoice` | 8002 | NAV Online Számla API query |
  | 2 | `invoice-file-filter` | 8001 | PDF metadata extraction (OCR/Regex) |
  | 1 | `attachment-downloader` | 8000 | Gmail PDF attachment download |
  | 5 | `wise` | 8003 | Wise bank-statement download/sync (independent entry point) |

- **Call chain**: `POST /api/v1/sync` on `invoice-core` (8004) → `nav-invoice` (8002) → `invoice-file-filter` (8001) → `attachment-downloader` (8000). `wise` (8003) is a separate leaf that serves transaction data to `invoice-core`.
- **Implementation status**: All five microservices are fully implemented in this workspace.

## nav-invoice — NAV Online Számla 3.0 client
- **Purpose**: Hungarian tax-authority (NAV) Online Számla 3.0 REST/XML client (`/invoiceService/v3`) using technical-user authentication (SHA-512 password hash, SHA3-512 signature, AES-128 token).
- **Layout**: core package `src/nav_invoice/` (`config`, `models`, `crypto`, `client`, `auth`, `query`, `reporting`), `api/` (FastAPI, port 8002), `cli/` (Click CLI). `requires-python >=3.11`.
- **Run**:
  - API: `cd nav-invoice && python run_api.py` (port 8002).
  - CLI: `uv run nav login | list [--from DATE --to DATE] [--direction INBOUND] [--json] | show <invoice>`.
  - Tests: `uv run pytest tests/ -v`. Lint/format: `uv run ruff check|format src/`.
- **Env** (`.env` from `.env.example`): `USERNAME`, `PASSWORD`, `LICENSE_KEY`, `CSERE_KEY`, `TAX_NUMBER`, `SOFTWARE_*`, `ENVIRONMENT` (`test`/`production`), optional `ENDPOINT_URL`, `API_HOST`/`API_PORT`, `LOG_LEVEL`, `CACHE_TTL_SECONDS`.

## attachment-downloader — Gmail PDF attachment downloader
- **Purpose**: Downloads PDF attachments from Gmail for a given date range. Leaf service consumed by `invoice-file-filter`. Supports multiple providers (Gmail implemented; Outlook planned).
- **Layout**: `src/attachment_downloader/` with `api/main.py` (FastAPI: `POST /api/v1/jobs`, `GET/DELETE /api/v1/cache`), `cli/main.py` (Typer), `providers/gmail/client.py` (GmailClient), `base.py` (EmailClient Protocol), `cache.py` (TTL cache). `requires-python >=3.9`.
- **Run**:
  - API: `cd attachment-downloader && uv run uvicorn attachment_downloader.api.main:app --port 8000 --reload`.
  - CLI: `uv run attachment-downloader --start DATE --end DATE [--output subdir] [--provider gmail]`.
  - Tests: `uv run pytest tests/ -v`.
- **Auth**: place OAuth2 desktop `credentials.json` in project root; `token.json` generated on first auth. Configurable via `GOOGLE_CREDENTIALS_FILE` / `GOOGLE_TOKEN_FILE` in `.env`. Not committed.
- **Files**: saved as `YYYY-MM-DD_NNNN_<sanitized>.pdf`; counter resumes from highest existing file.

## invoice-file-filter — PDF extraction + invoice filtering
- **Purpose**: Calls attachment-downloader to get PDFs, detects invoices by keyword matching, extracts text (pdfplumber + Tesseract OCR fallback), and returns file metadata + word list for `invoice-core`.
- **Layout**: `src/invoice_file_filter/` with `api/main.py` (FastAPI: `POST /api/v1/invoices/extract`, `POST /api/v1/pdf/words`), `cli/main.py` (Typer: `process`, `words`, `cache-info`, `cache-clear`), `service.py`, `client.py`. `requires-python >=3.11`.
- **Run**:
  - API: `cd invoice-file-filter && python run_api.py` (port 8001).
  - CLI: `uv run invoice-file-filter process [--start DATE] [--end DATE] [--local] [--json]`.
  - System deps for OCR: `brew install poppler tesseract tesseract-lang` (macOS).
  - Tests: `uv run pytest tests/ -v`.
- **Env**: `ATTACHMENT_DOWNLOADER_URL`, `OUTPUT_DIR`, `INVOICE_KEYWORDS`, `OCR_ENABLED`, `OCR_LANGUAGE`, `API_HOST`/`API_PORT` (8001), `LOG_LEVEL`.

## invoice-core — master orchestrator
- **Purpose**: Orchestrates the full pipeline (NAV → PDF → Wise), reconciles results, persists everything to PostgreSQL. Includes a full HTMX + Bootstrap web UI at `/ui/`. `requires-python >=3.11`.
- **Layout**: `src/invoice_core/` — `api/main.py` (FastAPI REST), `ui/router.py` (web UI), `services/` (dashboard, invoice, partner, transaction, invoice_file), `templates/` (Jinja2 + HTMX partials), `service.py` (sync orchestration), `db.py` (SQLAlchemy ORM), `models.py`, `config.py`, `nav_client.py`, `pdf_client.py`, `wise_client.py`.
- **Run**:
  - DB: `cd invoice-core && uv run alembic upgrade head` (PostgreSQL; SQLite in-memory for tests).
  - API + UI: `python run_api.py` (port 8004). Open `http://localhost:8004/ui/`.
  - CLI: `uv run invoice-core sync [--start DATE] [--end DATE]` · `sync-nav` · `sync-pdf` · `sync-wise` · `sync-match` · `report --month YYYY-MM` · `link <invoice> <file>` · `link-wise <txn_id> <file>`.
  - Tests: `uv run pytest tests/ -v`.
- **Sync pipeline**:
  1. `sync_nav` — upsert NAV invoices, suppliers, customers.
  2. `sync_pdf` — upsert InvoiceFile records; link invoices to files (filename match → word search fallback).
  3. `sync_wise` — upsert WiseTransactions; link to invoices via `payment_reference`; mark PAID.
  4. `sync_match` — link unmatched transactions to files (transitive → authoritative reference → scored vendor/amount/date); back-link any transaction sharing a file with an invoice to that invoice and mark it PAID.
- **Env**: `DB_URL` (JDBC, auto-converted), `DB_USER`, `DB_PWD`, `NAV_INVOICE_URL` (`:8002`), `INVOICE_FILE_FILTER_URL` (`:8001`), `WISE_URL` (`:8003`), `SYNC_TIMEOUT`, `API_HOST`/`API_PORT` (8004), `LOG_LEVEL`.

## wise — Wise bank-statement service
- **Purpose**: Fetches Wise balance statements via the Wise API and returns structured transactions as JSON. Leaf service — calls only the Wise API, holds no DB.
- **Layout**: `src/wise_invoice/` — `api/main.py` (FastAPI: `POST /sync`, `GET /balance-statements`, `GET /balances`, `GET /profiles`, `GET /settings`), `cli/main.py` (Typer: `status`, `balances`, `sync`, `statements`, `balance-statements`, `import`), `client.py` (Bearer auth + retry), `sync.py`, `csv_import.py` (manual CSV fallback). `requires-python >=3.11`.
- **Run**:
  - API: `cd wise && python run_api.py` (port 8003).
  - CLI: `uv run wise-invoice sync [--start DATE] [--end DATE] [--currency HUF] [--json]`.
  - Tests: `uv run pytest tests/ -v`.
- **SCA**: balance-statement download requires an RSA keypair registered in Wise. Generate with `openssl genrsa`, upload public key in Wise dashboard, set `WISE_SCA_PRIVATE_KEY_PATH` in `.env`. Manual CSV download to `balance-statements/` is the fallback.
- **Env**: `WISE_API_KEY`, `WISE_PROFILE_ID`, `WISE_ACCOUNT_CURRENCY`, `WISE_SANDBOX`, `WISE_SCA_PRIVATE_KEY_PATH`, `BALANCE_STATEMENTS_DIR`, `API_HOST`/`API_PORT` (8003), `LOG_LEVEL`, `REQUEST_TIMEOUT`, `MAX_RETRIES`.

## Conventions
- New microservices follow the `nav-invoice` / `invoice-core` pattern: a typed core package under `src/` + parallel `api/` (FastAPI) and `cli/` (Click/Typer) entry points, `pydantic-settings` for `.env` config, `uv` for deps, `pytest` under `tests/`.
- Inference defaults (root `.env.example`): `SCALEWAY_BASE_URL`, `SCALEWAY_API_KEY`.
