# Moneypenny — Requirements

## Summary

Moneypenny automates invoice bookkeeping for a Hungarian business. It downloads invoice PDFs
from Gmail, cross-references them against the NAV (Hungarian tax authority) Online Számla API,
reconciles them against bank transactions from Erste and Wise, and presents the result — invoices,
suppliers, customers, bank transactions, dividends, tax payments — in a single web UI with a
one-click sync.

It is a `uv`-based Python monorepo of independent microservices, each with its own FastAPI REST
API and Typer/Click CLI, orchestrated by one master service (`invoice-core`) and fronted by one
web UI (`vision`). All state lives in a single PostgreSQL database owned by `invoice-core`; every
other service is either a leaf (talks to one external system, holds no DB) or a pure frontend.

## System architecture

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

| Service | Port | Role |
|---|---|---|
| `attachment-downloader` | 8000 | Downloads PDF invoice attachments from Gmail |
| `invoice-file-filter` | 8001 | Filters PDFs that look like invoices, extracts their text (+ OCR fallback) |
| `nav-invoice` | 8002 | NAV Online Számla 3.0 REST/XML client (technical-user auth) |
| `wise` | 8003 | Direct Wise API bank-statement sync — **on hold**, superseded by `bank` |
| `invoice-core` | 8004 | Master orchestrator: PostgreSQL persistence, reconciliation, JSON REST API |
| `bank` | 8005 | Consolidated bank-statement service — reads manually downloaded Erste + Wise CSVs |
| `uploader` | 8006 | Web upload of bank-statement CSVs into `bank`'s storage folder |
| `auth` | 8007 | Central authentication — Google OAuth 2.0/OIDC login, RS256 JWT issuance + JWKS |
| `vision` | 8009 | Web frontend — consumes the `invoice-core` REST API and SrcProfit (IBKR) |

Each service has its own `.venv`, `pyproject.toml`, FastAPI `api/`, and Typer/Click `cli/`. There
is no shared virtual environment. Configuration is one shared root `.env` (see
[Configuration](#configuration)).

## Functional requirements by service

### attachment-downloader — Gmail PDF ingestion

- Given a date range, fetch every Gmail message with PDF attachments in that range and save the
  PDFs to disk as `YYYY-MM-DD_NNNN_<sanitized-name>.pdf`; the counter resumes from the highest
  existing file rather than restarting.
- Expose the job as `POST /api/v1/jobs` (REST) and as a CLI command taking `--start`/`--end`.
- Cache job results with a TTL; expose `GET`/`DELETE /api/v1/cache` to inspect and clear it.
- Authenticate to Gmail via OAuth2 desktop flow: a `credentials.json` supplied by the user, a
  `token.json` generated and persisted on first successful login. Provider is pluggable
  (`providers/gmail/`, Outlook is a documented future provider) behind a common `EmailClient`
  protocol.
- Leaf service: no outbound calls to any other Moneypenny service, no database.

### invoice-file-filter — PDF triage and text extraction

- Fetch candidate PDFs from `attachment-downloader` for a date range (or a local directory) and
  decide which ones are invoices using configurable keyword matching (`INVOICE_KEYWORDS`).
- Extract full text from each matched PDF with `pdfplumber`; fall back to Tesseract OCR
  (`hun+eng`) when the PDF has no extractable text layer.
- Expose `POST /api/v1/invoices/extract` (batch extraction for a date range) and
  `POST /api/v1/pdf/words` (word-level extraction for a single file, used for invoice-number
  matching) plus an equivalent CLI (`process`, `words`, `cache-info`, `cache-clear`).
- The only consumer of `attachment-downloader`; the only producer of PDF text/word data for
  `invoice-core`.

### nav-invoice — NAV Online Számla client

- Authenticate to the NAV Online Számla 3.0 API (`/invoiceService/v3`) using technical-user
  credentials: SHA-512 password hashing, SHA3-512 request signing, AES-128 token decryption.
- Query invoices by date range and direction (`INBOUND`/`OUTBOUND`) via `queryInvoiceDigest` /
  `queryInvoiceData`, and taxpayer data via `queryTaxpayer`.
- Support outbound reporting (`manageInvoice`, `queryTransactionStatus`) for invoices this
  business issues, in addition to querying inbound invoices for reconciliation.
- Expose `/health`, `/auth/login`, `/invoices`, `/invoices/{szamlaszam}`, `/report`, `/settings`
  over REST, and equivalent `nav login | list | show` CLI commands.
- Support both NAV `test` and `production` environments via configuration, with an
  environment-specific endpoint the software's registered credentials are valid for.
- Leaf service with respect to the pipeline: called only by `invoice-core`; calls only the NAV
  API.

### bank — consolidated bank statements

- Read manually downloaded CSV bank statements for two banks — Erste (UTF-16, `,`-separated,
  Hungarian number/date formats) and Wise (UTF-8, `,`-separated) — from a shared storage
  directory (`storage/bank/balance-statements/{erste,wise}/`), and normalize both into one
  `BankTransaction` shape (id, date, amount, currency, direction, description, payment reference,
  counterparty name/account/IBAN, transaction type, category, balance, fees).
- Expose the available statement files (`GET /balance-statements[/{bank}]`), a single bank's
  latest statement with optional date/currency filters (`GET /balance-statement/{bank}`), a
  specific file (`GET /balance-statement/{bank}/{filename}`), and a consolidated Erste+Wise view
  sorted by date descending (`GET /balance-statement/all`) — this last endpoint is what
  `invoice-core` calls during sync.
- Mirror the same operations in a CLI (`status`, `list`, `import`, `statements`).
- Leaf service: reads only the local CSV folder, holds no database. Bank statement CSVs must be
  downloaded by hand from each bank's web portal — there is no bank API integration for either
  bank at present.

### uploader — bank-statement upload

- Give the operator a way to get CSV files into `bank`'s storage folder without shell access:
  accept a multipart file upload, detect the bank (Erste vs. Wise) from the filename or an
  explicit override, and write it into the correct subfolder, rejecting or optionally overwriting
  duplicates.
- Expose `GET /api/v1/files[/{bank}]`, `POST /api/v1/upload`, `DELETE /api/v1/files/{bank}/{filename}`,
  plus an equivalent CLI (`status`, `list`, `upload`, `delete`).
- Leaf service, filesystem-only, no database. Consumed exclusively by `vision`'s `/ui/upload`
  page — the upload UI itself lives in `vision`, not here.

### invoice-core — master orchestrator

- Own the single PostgreSQL database for the whole system (SQLite in-memory for tests), managed
  through Alembic migrations. Every other service is stateless with respect to this data.
- Run the four-stage sync pipeline, triggerable as a whole (`POST /api/v1/sync` / `invoice-core
  sync`) or stage by stage (`sync-nav`, `sync-pdf`, `sync-bank`, `sync-match`):
  1. **sync_nav** — call `nav-invoice`, upsert invoices, suppliers and customers.
  2. **sync_pdf** — call `invoice-file-filter` (→ `attachment-downloader`), upsert invoice-file
     records, and link each file to an invoice by invoice-number match in the filename, falling
     back to a full-text/word search inside the PDF.
  3. **sync_bank** — call `bank`'s consolidated endpoint, upsert bank transactions, link them to
     invoices via payment reference, and mark linked invoices as paid.
  4. **sync_match** — link any still-unmatched transactions to invoice files (transitive match →
     authoritative reference → scored vendor/amount/date match), then back-link any transaction
     that shares a file with an invoice to that invoice and mark it paid.
- Never let an automated sync stage overwrite a fact the user set by hand: an invoice manually
  marked paid, a PDF manually linked to an invoice, or a bank transaction manually linked to an
  invoice must stay as the user left it on every subsequent sync.
- Support a free-text note per invoice, editable from the invoice detail page and persisted
  independently of sync.
- Identify tax payments among bank transactions by matching the counterparty account against
  known NAV account numbers (ÁFA, SZJA, TAO, Szochó, TB, Bírság) plus HIPA and Iparkamara, and
  surface them as a tax report per month.
- Compute a dividend report from matched transactions/invoices.
- Expose a JSON REST API covering: dashboard summary; invoices (filterable by date, status,
  direction, `has_pdf`, `supplier_name`) and invoice detail; invoice files + PDF serving; supplier
  and customer list/summary/detail; bank transactions (filterable, with balances) and detail;
  manual link/unlink of PDFs and transactions to invoices; sync run logs; tax and dividend
  reports; and `POST`/`GET /api/v1/users` for login records forwarded from `auth`.
- Pure JSON backend — it must render no HTML and own no UI templates; all presentation is
  `vision`'s responsibility.

### auth — central authentication

- Authenticate users via Google OAuth 2.0 / OpenID Connect (authorization code + PKCE + state),
  restricted to an allow-list of emails and/or domains.
- On successful login, issue this system's own RS256 JWT pair (15-minute access token, 30-day
  refresh token) and set them as HttpOnly cookies (`mp_access_token`, `mp_refresh_token`,
  `SameSite=Lax`, `Secure` behind HTTPS); also accept refresh via `POST /auth/refresh` and
  presentation via `Authorization: Bearer`.
- Publish its public keys at `/.well-known/jwks.json` so every other service can verify tokens
  locally (cached JWKS client) without a network round-trip to `auth` on each request.
- Support refresh-token revocation via a file-based JTI denylist (`POST /auth/logout`,
  `auth revoke <jti>` CLI) — no database of its own.
- Best-effort report every successful login's profile + provider to `invoice-core`'s
  `POST /api/v1/users`, using the token just issued; a failure there must not fail the login.
- Expose public endpoints (`/health`, `/.well-known/jwks.json`, `/auth/providers`,
  `/auth/{provider}/login`, `/auth/{provider}/callback`, `/auth/refresh`, `/auth/verify`) and
  JWT-protected ones (`/auth/me`, `/auth/logout`, `/settings`), plus a CLI (`status`, `providers`,
  `verify`, `revoke`).
- Providers are pluggable behind a common protocol (`providers/base.py`), enabled via
  `ENABLED_PROVIDERS`; only Google is implemented today.

### Cross-service JWT protection

- Every backend service (`invoice-core`, `nav-invoice`, `invoice-file-filter`,
  `attachment-downloader`, `bank`, `uploader`) must carry its own copy of the JWT-verification
  module (`auth.py`, or `jwt_auth.py` in `nav-invoice`) wired in as an app-level dependency that
  protects every route except `GET /health`, toggled per service by `AUTH_ENABLED`.
- `attachment-downloader` is the one deliberate exception, always overriding back to
  `AUTH_ENABLED=false` (via `ATTACHMENT_DOWNLOADER_AUTH_ENABLED`) since it is only ever called by
  the `invoice-core` sync pipeline itself, never by a browser holding a user token.
- `vision` enforces auth via middleware instead of a route dependency: `/`, `/pitch`, `/login`,
  `/logout`, `/static/*`, `/health` stay public; every other page redirects an unauthenticated
  browser to `/login?next=…`, while unauthenticated API calls get `401` JSON. Its login page lists
  providers from `GET /auth/providers` and silently refreshes via `POST /auth/refresh` when a
  valid refresh cookie is present.
- `vision`, `invoice-core`, and `invoice-file-filter` must forward the caller's bearer token to
  the services they call downstream (token passthrough), so a chain of internal calls carries the
  original user's identity all the way to `invoice-core`.

### vision — web frontend

- Be the only service that renders HTML: consume the `invoice-core` REST API (and SrcProfit for
  portfolio data) and present every page a user interacts with. No database, no CLI.
- Provide the full set of `/ui/*` pages: Dashboard, Számlák (invoices), Szla Fájlok (invoice
  files), Szállítók (suppliers), Vevők (customers), Bank (transactions), Osztalék (dividends),
  Adók (taxes), Sync, and Upload (the CSV-upload page backed by `uploader`).
- Provide a vision-specific home/pitch page (`/`, with `/pitch` redirecting to it) and a
  `/dashboard` portfolio view built on SrcProfit/IBKR data, independent of the invoice pipeline.
- On the invoice detail page, let the user: edit the free-text note; manually mark/unmark an
  invoice as paid (locking it against sync overwriting the status); manually link/unlink a PDF
  file to the invoice (locking it against sync re-assignment); manually link/unlink bank
  transactions to the invoice.
- Trigger and monitor the sync pipeline from the Sync page, showing sync run history/logs.
- Serve PDFs by redirecting to `invoice-core`'s `/api/v1/invoice-files/{id}/pdf`, never proxying
  the bytes itself.

## Cross-cutting requirements

### Configuration

- All services read one shared root `.env` (copied from `.env.example`) via `pydantic-settings`;
  there is no per-service `.env` in normal operation. Docker Compose reads the same file
  (`env_file: ./.env`) for every container.
- Most settings are shared plain keys (`DB_USER`, `GOOGLE_CLIENT_ID`, `JWT_*`, NAV credentials,
  …). Keys that must legitimately differ per service (`API_PORT` always; `AUTH_ENABLED`,
  `LOG_LEVEL`, `REQUEST_TIMEOUT` for specific services) are overridable via a
  `<SERVICE>_<KEY>`-prefixed variable that each service's settings read first, falling back to
  the shared plain key.
- Every service must log to both stdout and its own `logs/<service>.log`.

### Persistence

- `invoice-core` is the single source of durable truth (PostgreSQL, Alembic-migrated). No other
  service may hold its own database; leaf services either call an external API (`nav-invoice`,
  `attachment-downloader`) or read/write plain files (`bank`, `uploader` against
  `storage/bank/balance-statements/`).

### Deployment

- The full system must be runnable as a set of Docker containers via `docker-compose.yml`:
  PostgreSQL, pgAdmin, `auth`, `attachment-downloader`, `nav-invoice`, `bank`, `uploader`,
  `invoice-file-filter`, `invoice-core`, `vision`, plus a log viewer (Dozzle) and an
  `oauth2-proxy` for perimeter auth in front of the compose stack.
  request-timeout/retry behavior is configured per service.
- The workspace must also run outside Docker for development: each service started individually
  (`uv run` / `python run_api.py`) or all at once via `./start-all.sh`.
- A devcontainer (`.devcontainer/`) must provide a ready-to-code environment including PostgreSQL
  and pgAdmin for contributors who don't run Docker Compose locally.
- An nginx config (`nginx/`) fronts the production deployment at its public domain.

### Look and feel

- The web UI (`vision`) uses Bootstrap (Yeti theme) + HTMX + DataTables, in Hungarian, consistent
  with the existing `/ui/*` pages — new pages should match this stack and language rather than
  introducing new UI frameworks.

## Out of scope / known limitations

- `wise` (direct Wise API sync, port 8003) is **on hold**: Wise's partner program isn't available
  to this business, so online balance-statement download doesn't work. `bank` (manually
  downloaded CSVs) is the supported path for both Erste and Wise data; `wise` should not be
  extended further while this holds.
- No bank API integration exists for Erste; statements are downloaded by hand from its web
  portal and uploaded via `uploader`.
- Authentication is fully implemented but **disabled by default** in every service's config
  (`AUTH_ENABLED=false`); enabling it requires configuring Google OAuth credentials in `auth` and
  running `auth keygen` once before flipping the flag workspace-wide.
- `moneypenny/` is a design wiki (Hungarian Obsidian vault: `*-spec.md` / `*-prompt.md`), not
  code — it documents intent and may lag the implementation; where the two disagree, the running
  code and `CLAUDE.md` are authoritative.
- Outlook as an `attachment-downloader` provider is a documented extension point, not built.

## Acceptance criteria

- Each service starts independently with its documented command, passes `uv run pytest tests/ -v`,
  and answers `GET /health` without authentication.
- `POST /api/v1/sync` on `invoice-core` (or the Sync page in `vision`) runs all four pipeline
  stages end-to-end against real or seeded data and completes without manual intervention.
- A manually set invoice note, paid flag, PDF link, or transaction link survives a subsequent
  sync unchanged.
- With `AUTH_ENABLED=true` end-to-end, an unauthenticated browser hitting any `vision` page other
  than the public set is redirected to `/login`, completes Google login, and reaches the original
  page; an unauthenticated API call to any protected backend route (other than `/health`) returns
  `401`.
- The whole stack starts via `docker-compose up` using only the root `.env`, with every service
  reachable on its documented port.
