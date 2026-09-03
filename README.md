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
| `uploader` | 8006 | Bank statement CSV + PDF upload into the bank service's storage |
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

## Other UI features

- **Vacation requests** — request/approve/track vacation, persisted in invoice-core (`/ui/controlling/vacation`)
- **Fizetés Calculator** — payment/salary calculator with saved state (`/ui/fizetes-kalkulator`)
- **PDF bank statements** — upload/browse/download Erste + Wise statement PDFs via uploader (`/ui/bank-statements`), separate from the CSV import under `/ui/upload`
- **Read-only / anonymized roles** — accounts outside `ALLOWED_EMAILS`/`ALLOWED_DOMAINS` get a read-only UI; unlisted verified accounts additionally see anonymized names/amounts on financial pages

## Environment

Configuration is a single **shared root `.env`** (copy `.env.example` to `.env` at the repo root) — every service's `config.py` points there instead of a per-service `.env`, and Docker Compose reads the same file for every container. Most keys are shared plain names (`DB_USER`, `GOOGLE_CLIENT_ID`, `JWT_*`, ...). A few keys genuinely differ per service — `API_PORT` always, plus `AUTH_ENABLED`/`LOG_LEVEL`/`REQUEST_TIMEOUT` for one exception service each — those use a `<SERVICE>_<KEY>` prefixed override (e.g. `NAV_INVOICE_API_PORT`) that falls back to the shared plain key.

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

The `auth` service (:8007) handles Google OAuth 2.0 / OpenID Connect login and issues RS256 JWTs (15-min access + 1-day refresh, HttpOnly cookies). Every other service validates tokens locally against its JWKS; vision redirects browsers to `/login`, the backends return `401`. The RS256 keypair regenerates in-memory on every `auth` process restart, rotating the JWKS `kid` and invalidating every previously issued token workspace-wide — everyone must log in again after a restart.

Login maps the email to a `(role, anonymized)` pair via `resolve_access()`: `ALLOWED_EMAILS`/`ALLOWED_DOMAINS` → `read_write`; `READONLY_EMAILS`/`READONLY_DOMAINS` → `read_only` with real data; any other verified account → `read_only` with `anonymized: true` (invoice-core masks names/amounts on its financial-data GET endpoints for that tier). `BLOCKED_EMAILS`/`BLOCKED_DOMAINS` reject login outright.

**Currently enabled** (`AUTH_ENABLED=true` in the shared root `.env`) for every service except `attachment-downloader`, which overrides back to `false` (leaf service, no user token). To (re)configure, set `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in the root `.env`, run `uv run auth keygen` once in `auth/`, then toggle `AUTH_ENABLED` as needed. Details: `auth/README.md` and `doc/auth-service-spec.md`.

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
