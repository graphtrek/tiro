# Tiro — Invoice Automation Pipeline

A `uv`-based Python monorepo of microservices that automate invoice reconciliation for Hungarian businesses: downloads PDF invoice attachments from Gmail, cross-references them against the NAV Online Számla API, matches them with bank transactions, and presents everything in a web UI.

## Architecture

```
attachment-downloader (:8000)   invoice-file-filter (:8001)
        │                               │
        └───────────────┬───────────────┘
                        ▼
                  nav-invoice (:8002)
                        │
                        ▼
                  invoice-core (:8004)  ◄── bank (:8005) ◄── uploader (:8006)
                        │
                        ▼
                   vision (:8009)  ── login ──►  auth (:8007) ◄─► Google OAuth
```

| Service | Port | Purpose |
|---|---|---|
| `attachment-downloader` | 8000 | Downloads PDF attachments from Gmail |
| `invoice-file-filter` | 8001 | PDF text extraction + invoice keyword filtering |
| `nav-invoice` | 8002 | NAV Online Számla 3.0 REST/XML client |
| `invoice-core` | 8004 | Master orchestrator — PostgreSQL persistence, reconciliation, JSON REST API |
| `bank` | 8005 | Consolidated bank statement service (Erste + Wise CSV) |
| `uploader` | 8006 | Bank statement CSV upload into the bank service's storage |
| `auth` | 8007 | Central authentication — Google OAuth 2.0/OIDC login, RS256 JWT issuance + JWKS |
| `vision` | 8009 | Web frontend — consumes invoice-core REST API |

Each service is independent: its own `.venv`, `pyproject.toml`, and `.env`.

## Quick start

```bash
# 1. Install dependencies for a service
cd invoice-core && uv sync

# 2. Apply DB migrations (invoice-core only)
uv run alembic upgrade head

# 3. Start all services (separate terminals) — or just run ./start-all.sh
cd attachment-downloader && uv run uvicorn attachment_downloader.api.main:app --port 8000 --reload
cd invoice-file-filter   && python run_api.py   # :8001
cd nav-invoice           && python run_api.py   # :8002
cd invoice-core          && python run_api.py   # :8004
cd bank                  && python run_api.py   # :8005
cd uploader              && python run_api.py   # :8006
cd auth                  && python run_api.py   # :8007
cd vision                && python run_api.py   # :8009
```

Open the UI at **http://localhost:8009/ui/**

## Sync pipeline

Triggered via `POST /api/v1/sync` on invoice-core (or the Sync page in the UI):

1. **sync_nav** — fetches invoices from NAV Online Számla, upserts suppliers/customers/invoices
2. **sync_pdf** — fetches PDFs from Gmail via attachment-downloader + invoice-file-filter, links to invoices by filename/text
3. **sync_bank** — imports Erste + Wise transactions from the bank service, links to invoices via payment reference
4. **sync_match** — scores and links unmatched transactions to PDF files; back-links transactions to invoices via shared PDF

## Invoice features

- **Note** — free-text note per invoice, editable on the invoice detail page
- **Manual Fizetve** — manually mark an invoice as paid; the lock prevents sync from overwriting the status
- **Manual PDF link** — lock a PDF file to an invoice; sync will not re-assign it
- **Manual transaction link** — link/unlink bank transactions to invoices from the detail page

## Environment

Each service reads its own `.env` file. Copy `.env.example` as a starting point.

Key variables for `invoice-core`:

| Variable | Description |
|---|---|
| `DB_URL` | PostgreSQL JDBC URL (auto-converted to SQLAlchemy format) |
| `DB_USER` / `DB_PWD` | Database credentials |
| `NAV_INVOICE_URL` | URL of the nav-invoice service (default `:8002`) |
| `INVOICE_FILE_FILTER_URL` | URL of the invoice-file-filter service (default `:8001`) |
| `BANK_URL` | URL of the bank service (default `:8005`) |

Key variables for `nav-invoice`: `USERNAME`, `PASSWORD`, `LICENSE_KEY`, `CSERE_KEY`, `TAX_NUMBER`, `ENVIRONMENT`.

Key variables for `attachment-downloader`: place OAuth2 `credentials.json` in the project root; `token.json` is generated on first auth.

## Authentication

The `auth` service (:8007) handles Google OAuth 2.0 / OpenID Connect login and issues RS256 JWTs (15-min access + 30-day refresh, HttpOnly cookies). Every other service validates tokens locally against its JWKS; vision redirects browsers to `/login`, the backends return `401`.

**Currently disabled**: every service's `.env` has `AUTH_ENABLED=false`. To enable, configure `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `auth/.env`, run `uv run auth keygen` once, then flip `AUTH_ENABLED=true` per service. Details: `auth/README.md` and `doc/auth-service-spec.md`.

## Development

```bash
# Run tests
cd <service> && uv run pytest tests/ -v

# Lint / format
cd <service> && uv run ruff check src/ && uv run ruff format src/

# New DB migration (invoice-core)
cd invoice-core && uv run alembic revision -m "describe the change"
uv run alembic upgrade head
```
