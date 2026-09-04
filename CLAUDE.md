# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a multi-project `uv`-based Python workspace. **Each sub-project has its own isolated virtual environment (`.venv`) and `pyproject.toml`. There is NO shared/root virtual environment.**

> **IMPORTANT — always use the project's own venv.** Before running any Python, test, or dependency command, `cd` into the specific sub-project and use *that* project's environment — either activate it (`source .venv/bin/activate`) or prefix with `uv run`. Never run a project's code from another project's venv or assume a workspace-wide environment.

**Configuration is a single shared root `.env`** (copied from root `.env.example`) — every service's `config.py` (and duplicated `auth.py`/`jwt_auth.py` modules) points its `pydantic-settings` `env_file` there instead of a per-service `.env`. This is also the file Docker Compose reads (`env_file: ./.env` for every container). Most keys are shared plain names (`DB_USER`, `GOOGLE_CLIENT_ID`, `JWT_*`, NAV credentials, ...). A handful of keys genuinely differ per service — `API_PORT` always, plus `AUTH_ENABLED`/`LOG_LEVEL`/`REQUEST_TIMEOUT` for one exception service each — those use a `<SERVICE>_<KEY>` prefixed override (e.g. `NAV_INVOICE_API_PORT`, `ATTACHMENT_DOWNLOADER_AUTH_ENABLED`) that each service's Settings field reads first via a pydantic `validation_alias`, falling back to the shared plain key (which is also what Docker Compose's per-container `environment:` blocks set).

| Directory | Purpose |
|---|---|
| `doc/` | Obsidian design wiki (Hungarian): specs + prompts for the Tiro pipeline |
| `nav-invoice/` | NAV Online Számla 3.0 REST/XML client (FastAPI + CLI), port 8002 |
| `attachment-downloader/` | Gmail PDF attachment downloader (FastAPI + CLI), port 8000 |
| `invoice-file-filter/` | PDF text extraction + invoice filtering (FastAPI + CLI), port 8001 |
| `invoice-core/` | Master orchestrator — PostgreSQL persistence, pure JSON REST backend (FastAPI + CLI), port 8004 |
| `bank/` | Consolidated bank statement service — Erste + Wise CSV, port 8005 |
| `vision/` | Frontend — serves all web UI by consuming invoice-core REST API + SrcProfit (FastAPI), port 8009 |
| `auth/` | Central authentication — Google OAuth 2.0/OIDC login + RS256 JWT issuance (FastAPI + CLI), port 8007 |

Root files: `python-for-ai.code-workspace` (VS Code workspace + launch configs), `.env.example` (Scaleway inference defaults: `SCALEWAY_BASE_URL`, `SCALEWAY_API_KEY`), `AGENTS.md`, this file.

### Dependency & run conventions
- Each project's `.venv` lives at `<project>/.venv` and is the only environment you should use for that project's commands.
- Install: `cd <project> && uv sync` (creates/updates `<project>/.venv`; or `pip install -e .` after activating it).
- Run a command in the project's env: `cd <project> && uv run <cmd>`, or `source <project>/.venv/bin/activate` first.
- Each service exposes both a **FastAPI** app under `api/` and a **CLI** (Click/Typer) under `cli/`, backed by a typed core package. Config via `pydantic-settings` reading the shared root `.env`. Tests under `tests/` (`uv run pytest`).

## doc — design wiki (not code)

An Obsidian vault, written in Hungarian, that specs the **"Tiro"** invoice-automation system. Files: `*-spec.md` (specifications), `*-prompt.md` (code-generation prompts), `INDEX.md` (navigation hub, uses `[[wikilinks]]`).

Describes four Python microservices, each with a FastAPI REST interface and a Typer/Click CLI:

| # | Service | Port | Role |
|---|---|---|---|
| 4 | `invoice-core` | 8004 | MASTER orchestrator — PostgreSQL persistence + reconciliation |
| 3 | `nav-invoice` | 8002 | NAV Online Számla API query |
| 2 | `invoice-file-filter` | 8001 | PDF metadata extraction (OCR/Regex) |
| 1 | `attachment-downloader` | 8000 | Gmail PDF attachment download |

**Flow**: entry point `POST /api/v1/sync` on `invoice-core` → synchronously calls `nav-invoice` → `invoice-file-filter` → `attachment-downloader`. The pipeline downloads PDF invoice attachments from Gmail, extracts metadata, cross-references against the NAV Online Számla API, and persists everything (invoices, suppliers, customers) to PostgreSQL. Bank reconciliation is handled separately by the `bank/` service (Erste + Wise CSV import), which writes transactions directly into `invoice-core`'s PostgreSQL.

**Status**: All four microservices are fully implemented in this workspace.

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

### Environment (shared root `.env`)
`USERNAME`, `PASSWORD`, `LICENSE_KEY` (XML signKey), `CSERE_KEY` (XML exchangeKey, 16 chars), `TAX_NUMBER` (8 digits), `SOFTWARE_*` (software registration block required in every request), `ENVIRONMENT` (`test`/`production`), optional `ENDPOINT_URL` override, `API_HOST`/`NAV_INVOICE_API_PORT`, `LOG_LEVEL`.

## attachment-downloader — Gmail PDF attachment downloader

Downloads PDF attachments from Gmail for a given date range and exposes them via a REST API consumed by `invoice-file-filter`. `requires-python >=3.9`.

### Running

```bash
cd attachment-downloader
uv sync

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

**Under Docker**, both files are read from `attachment-downloader/secrets/` instead (the compose `environment:` block overrides the two path vars, and the whole directory — not the individual files — is bind-mounted to `/app/secrets`). Copy both files onto the host there *before* `docker compose up`: the OAuth browser flow cannot run inside the container, so `token.json` has to be minted on a machine with a browser. Mounting the files individually is what caused `IsADirectoryError: /app/token.json` — Docker auto-creates a *directory* for a missing bind-mount source.

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

Orchestrates the full pipeline: fetches NAV invoices, PDF files, bank transactions, reconciles everything, and persists to PostgreSQL. Pure **JSON REST backend** — the web UI lives in `vision/`. `requires-python >=3.11`.

### Running

```bash
cd invoice-core
uv sync
uv run alembic upgrade head   # apply DB migrations (first time + after updates)

# REST API (port 8004)
python run_api.py
# or: uv run uvicorn invoice_core.api.main:app --host 0.0.0.0 --port 8004 --reload

# CLI (installed as `invoice-core` script)
uv run invoice-core sync                                # full sync (last 30 days)
uv run invoice-core sync --start 2026-05-01 --end 2026-05-31
uv run invoice-core sync-nav | sync-pdf | sync-bank | sync-match
uv run invoice-core report --month 2026-05
uv run invoice-core link <invoice_number> <filename>
uv run invoice-core link-bank <transaction_id> <filename>

# Tests
uv run pytest tests/ -v
```

### Architecture
- `src/invoice_core/` — `api/main.py` (FastAPI REST, CORS for vision), `services/` (dashboard, invoice, partner, transaction, invoice_file, dividend, tax), `service.py` (sync orchestration), `db.py` (SQLAlchemy ORM), `models.py`, `config.py`, `nav_client.py`, `pdf_client.py`, `bank_client.py`, `anonymize.py` (masks names/amounts for the JWT `anonymized: true` tier — see below).
- DB: PostgreSQL in production, SQLite in-memory for tests. Migrations via Alembic.
- **Anonymized read-only tier**: when `request.state.user["anonymized"]` is `True` (set by `require_auth` from the JWT — see `auth`'s tiering below), the financial-data GET endpoints (dashboard, invoices, partners, transactions, tax/tax-estimate, dividend) run their response through `anonymize()` before returning: supplier/customer/counterparty names and identifiers become deterministic fake values, and every monetary amount is scaled by a deterministic per-entity factor — real data never leaves the service for that tier. `role == "read_only"` alone does *not* trigger this — the trusted `READONLY_EMAILS`/`READONLY_DOMAINS` tier is also `read_only` but keeps real data.
- **REST API endpoints**: `/api/v1/dashboard` · `/api/v1/invoices` (with `has_pdf`, `supplier_name` filters) · `/api/v1/invoice-files` + PDF serve · supplier/customer detail · transaction detail + balances · `/api/v1/sync/logs` · `/api/v1/reports/tax` + dividend · `/api/v1/users` (POST upsert + GET list — login records from `auth`, keyed by provider+sub).

### Sync pipeline and linking logic
1. **sync_nav** — upserts NAV invoices, suppliers, customers.
2. **sync_pdf** — upserts InvoiceFile records; links invoices to files by invoice number in filename or PDF text.
3. **sync_bank** — upserts BankTransaction records (Erste + Wise CSV via bank service); links to invoices via `payment_reference`; marks linked invoices PAID.
4. **sync_match** — links unmatched transactions to files (transitive → authoritative reference → scored); then back-links any transaction sharing a file with an invoice to that invoice and marks it PAID.

### Environment
`DB_URL` (JDBC format, auto-converted), `DB_USER`, `DB_PWD`, `NAV_INVOICE_URL` (`:8002`), `INVOICE_FILE_FILTER_URL` (`:8001`), `BANK_URL` (`:8005`), `SYNC_TIMEOUT`, `API_HOST`/`API_PORT` (8004), `LOG_LEVEL`.

## vision — frontend

Serves all web UI for the Tiro system by consuming the `invoice-core` REST API (port 8004) and `SrcProfit` (IBKR). No database. `requires-python >=3.11`.

### Running

```bash
cd vision
uv sync

# REST API + UI (port 8009)
python run_api.py
# or: uv run uvicorn vision.api.main:app --host 0.0.0.0 --port 8009 --reload

# Tests
uv run pytest tests/ -v
```

### Architecture
- `src/vision/` — `api/main.py` (FastAPI), `ui/router.py` (vision-only home page `/` — the pitch page; `/pitch` redirects to `/`), `ui/invoice_router.py` (all `/ui/*` routes — mirrors invoice-core's former UI), `ui/utils.py` (`dict_to_ns()` — converts API JSON dicts to `SimpleNamespace` with datetime parsing), `clients/invoice_core.py` (full REST client for invoice-core), `clients/srcprofit.py` (IBKR aggregator), `templates/` (Jinja2 — Bootstrap Yeti + HTMX + DataTables), `static/`.
- **Web UI pages** (all `/ui/*`): Dashboard · Számlák · Szla Fájlok · Szállítók · Vevők · Bank · Osztalék · Adók · Sync. Plus the vision-specific home page `/` (pitch).
- PDF files are served by invoice-core at `/api/v1/invoice-files/{id}/pdf`; vision redirects to that URL.

### Environment
`INVOICE_CORE_URL` (`:8004`), `SRCPROFIT_URL`, `SRCPROFIT_USER`, `SRCPROFIT_PASSWORD`, `API_HOST`/`API_PORT` (8009), `LOG_LEVEL`, `REQUEST_TIMEOUT`.

## auth — central authentication microservice

Google OAuth 2.0 / OpenID Connect login (authorization code + PKCE + state). Login is open to any verified Google account unless blocked (`BLOCKED_EMAILS`/`BLOCKED_DOMAINS`); `resolve_access()` maps the email to a `(role, anonymized)` pair — `ALLOWED_EMAILS`/`ALLOWED_DOMAINS` → `read_write`; `READONLY_EMAILS`/`READONLY_DOMAINS` → `read_only`, real data; any other verified account → `read_only`, `anonymized: true`. Both `role` and `anonymized` are embedded as JWT claims. Issues its own **RS256 JWT** pair (access 15 min, refresh 1 day). The RS256 keypair is regenerated in-memory on every `auth` process startup (not the persisted `auth keygen` files), so a restart rotates the JWKS `kid` and invalidates every previously issued token workspace-wide — every user must log in again after a restart. Only this service talks to Google — every other service validates JWTs **locally** against `/.well-known/jwks.json` (PyJWKClient cache, no per-request network call). Leaf service, no DB of its own (refresh-token revocation is a file-based jti denylist) — on every successful login it best-effort POSTs the user's profile + provider to `invoice-core`'s `/api/v1/users` (using the freshly-issued access token), which is the only service in the workspace holding a database. Spec: `doc/auth-service-spec.md`. `requires-python >=3.11`.

### Running

```bash
cd auth
uv sync
uv run auth keygen              # RS256 keypair into keys/ (gitignored) — required once

# REST API (port 8007)
python run_api.py
# or: uv run uvicorn auth_service.api.main:app --host 0.0.0.0 --port 8007 --reload

# CLI (installed as `auth` script)
uv run auth status | providers | verify <token> | revoke <jti>

# Tests
uv run pytest tests/ -v
```

### Architecture
- `src/auth_service/` — `config.py`, `models.py` (UserInfo, TokenPair, ProviderInfo, JWTClaims), `jwt_service.py` (RS256 issue/verify + JWKS + keygen), `providers/` (`base.py` AuthProvider Protocol, `google.py`; registry in `__init__.py`, enable via `ENABLED_PROVIDERS`), `invoice_core_client.py` (posts login records to invoice-core's `/api/v1/users`, best-effort), `service.py` (login flow, whitelist, refresh, revoke), `api/main.py`, `cli/main.py`.
- **Endpoints**: public — `/health`, `/.well-known/jwks.json`, `/auth/providers`, `/auth/{provider}/login?next=`, `/auth/{provider}/callback`, `POST /auth/refresh`, `POST /auth/verify`; JWT-protected — `/auth/me`, `POST /auth/logout`, `/settings`.
- Browser gets HttpOnly `mp_access_token` + `mp_refresh_token` cookies (SameSite=Lax; `COOKIE_SECURE=true` behind HTTPS); services also accept `Authorization: Bearer`.

### Environment (shared root `.env`)
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_URL`, `JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`, `ACCESS_TOKEN_TTL`/`REFRESH_TOKEN_TTL`, `JWT_AUDIENCE`/`JWT_ISSUER`, `ALLOWED_EMAILS`/`ALLOWED_DOMAINS` (→ `read_write`), `READONLY_EMAILS`/`READONLY_DOMAINS` (→ `read_only`, real data — trusted external accounts), `BLOCKED_EMAILS`/`BLOCKED_DOMAINS` (rejected outright), `ENABLED_PROVIDERS`, `COOKIE_SECURE`, `VISION_URL`, `API_HOST`/`AUTH_API_PORT` (8007), `LOG_LEVEL`.

### JWT protection in the other services
- Every backend service (invoice-core, nav-invoice, invoice-file-filter, attachment-downloader, bank, uploader) has a copied `auth.py` module (`jwt_auth.py` in nav-invoice — its `auth.py` is the NAV tokenExchange) wired as an app-level dependency; only `GET /health` is public. Toggle per service with `AUTH_ENABLED` in the shared root `.env`.
- **`AUTH_ENABLED=true` is the current state for every service except `attachment-downloader`**, which overrides back to `false` via `ATTACHMENT_DOWNLOADER_AUTH_ENABLED=false` — it's a leaf service hit by the `invoice-core sync` CLI (no user token). Flip the shared `AUTH_ENABLED` to `false` workspace-wide if Google OAuth isn't configured yet in `auth`'s section of the root `.env`.
- vision uses a middleware instead: public `/`, `/pitch`, `/login`, `/logout`, `/static/*`, `/health`; other pages redirect browsers to `/login?next=…` (API calls get 401 JSON). The login page (NiceAdmin-style, provider buttons from `GET /auth/providers`) silently refreshes via `POST /auth/refresh` when a valid refresh cookie exists.
- Token passthrough: vision and invoice-core (and invoice-file-filter → attachment-downloader) forward the incoming Bearer token to downstream services via a `TokenPassthrough` requests-auth hook + `current_token` ContextVar.

