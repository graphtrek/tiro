# invoice-core

Moneypenny pipeline microservice #4 (port 8004). Master orchestrator — calls **nav-invoice**, **invoice-file-filter**, and **wise**, merges the results, and persists everything to PostgreSQL.

Includes a full **web UI** (HTMX + Bootstrap + DataTables) served at `/ui/`.

## Running

```bash
cd invoice-core
uv sync

# Apply DB migrations (first time, and after updates)
uv run alembic upgrade head

# REST API + UI (port 8004)
python run_api.py
# or
uv run uvicorn invoice_core.api.main:app --host 0.0.0.0 --port 8004 --reload

# CLI
uv run invoice-core sync                        # full sync: NAV + PDF + Wise (last 30 days)
uv run invoice-core sync --start 2026-05-01 --end 2026-05-31
uv run invoice-core sync-nav                    # NAV only
uv run invoice-core sync-pdf                    # PDF only
uv run invoice-core sync-wise                   # Wise only
uv run invoice-core sync-match                  # match existing Wise txns to invoice files (no fetching)
uv run invoice-core report --month 2026-05      # full sync for one month + summary table

# Tests
uv run pytest tests/ -v
```

## Web UI

Open `http://localhost:8004/ui/` in a browser.

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/ui/` | KPI cards, recent invoices, recent Wise transactions, last sync status |
| Számlák | `/ui/invoices` | Invoice list — filterable by date, status, PDF, supplier; DataTable |
| Számla részlet | `/ui/invoices/{id}` | Invoice detail with supplier/customer cards, linked PDF, Wise transactions |
| PDF Fájlok | `/ui/invoice-files` | Invoice file list with linked invoice and supplier |
| Szállítók | `/ui/suppliers` | Supplier list with invoice stats |
| Szállító részlet | `/ui/suppliers/{id}` | Supplier detail with invoice and Wise DataTables |
| Vevők | `/ui/customers` | Customer list with invoice stats |
| Vevő részlet | `/ui/customers/{id}` | Customer detail with invoice and Wise DataTables |
| Wise tranzakciók | `/ui/transactions` | Transaction list — filterable by date, linked status, partner, amount |
| Sync | `/ui/sync` | Trigger sync with mode selection; sync log accordion |

**Tech stack**: Jinja2 SSR, HTMX 2.x (boost + partial swap + OOB), Bootstrap 5.3, DataTables 2.x — no separate build step, all assets from CDN.

Filter forms use `hx-trigger="change delay:300ms"` for live HTMX updates with URL push, so filtered views are bookmarkable.

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check |
| `POST` | `/api/v1/sync` | Full sync (NAV + PDF + Wise) |
| `POST` | `/api/v1/sync/nav` | Sync NAV invoices only |
| `POST` | `/api/v1/sync/pdf` | Sync PDF file index only |
| `POST` | `/api/v1/sync/wise` | Sync Wise transactions only |
| `POST` | `/api/v1/sync/match` | Match existing Wise transactions to invoice files (no fetching) |
| `GET`  | `/api/v1/invoices` | Invoice list (filter: `date_from`, `date_to`, `status`, `direction`) |
| `GET`  | `/api/v1/invoices/{invoice_number}` | Single invoice |
| `GET`  | `/api/v1/partners/suppliers` | Supplier list |
| `GET`  | `/api/v1/partners/customers` | Customer list |
| `GET`  | `/api/v1/transactions` | Wise transaction list |

### GET /health

```bash
curl http://localhost:8004/health
```

```json
{"status": "ok", "timestamp": "2026-06-16T10:00:00.000000"}
```

### POST /api/v1/sync

```bash
curl -X POST http://localhost:8004/api/v1/sync \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-05-01", "end_date": "2026-05-31"}'
```

```json
{
  "start_date": "2026-05-01",
  "end_date": "2026-05-31",
  "nav_invoices_synced": 12,
  "pdf_files_synced": 9,
  "wise_transactions_synced": 34,
  "wise_files_matched": 27,
  "errors": []
}
```

**Request fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `start_date` | `string` | 30 days ago | Filter start (`YYYY-MM-DD`) |
| `end_date` | `string` | today | Filter end (`YYYY-MM-DD`) |
| `sync_mode` | `string` | `full` | `full` / `nav_only` / `pdf_only` / `wise_only` / `match_only` |
| `clear_cache` | `bool` | `false` | Clear all downstream caches before syncing |

```bash
# Sync with cache cleared first
curl -X POST http://localhost:8004/api/v1/sync \
  -H "Content-Type: application/json" \
  -d '{"clear_cache": true}'
```

### GET /api/v1/invoices

```bash
# All invoices in a date range
curl "http://localhost:8004/api/v1/invoices?date_from=2026-05-01&date_to=2026-05-31"

# Unpaid inbound invoices only
curl "http://localhost:8004/api/v1/invoices?status=UNPAID&direction=INBOUND"
```

**Query parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `date_from` | `YYYY-MM-DD` | Filter by invoice date (inclusive) |
| `date_to` | `YYYY-MM-DD` | Filter by invoice date (inclusive) |
| `status` | `PAID` / `UNPAID` / `PARTIAL` | Filter by payment status |
| `direction` | `INBOUND` / `OUTBOUND` | Filter by invoice direction |

## CLI

### sync

```bash
uv run invoice-core sync [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
```

### sync-nav / sync-pdf / sync-wise / sync-match

```bash
uv run invoice-core sync-nav [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
uv run invoice-core sync-pdf [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
uv run invoice-core sync-wise [--clear-cache] [--json] [-v]
uv run invoice-core sync-match [--json] [-v]      # match existing Wise txns to invoice files
```

`sync-match` fetches nothing. It links unmatched `wise_transaction` records to
`invoice_file` rows (via transitive invoice link, payment reference, or scored
vendor/amount/date matching), then back-links any transaction that now shares an
`invoice_file` with an `invoice` to that invoice and marks it PAID.

### link

Manually link an invoice to a PDF file when automatic matching fails:

```bash
uv run invoice-core link <invoice_number> <filename>
# e.g.
uv run invoice-core link "87/2026" "2026-06-04_0020_GRAPHTREK_szamla.pdf"
```

### link-wise

Manually link a Wise transaction to a PDF file:

```bash
uv run invoice-core link-wise <wise_transaction_id> <filename>
# e.g.
uv run invoice-core link-wise "CARD-3867572380" "2026-06-02_0017_scaleway-invoice-2026-05.pdf"
```

### report

```bash
uv run invoice-core report --month 2026-05 [--clear-cache] [--json]
```

Runs a full sync for the given calendar month and prints a Rich summary table.

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_URL` | `jdbc:postgresql://localhost:5432/invoice` | PostgreSQL URL (JDBC format, converted automatically) |
| `DB_USER` | `invoice` | Database username |
| `DB_PWD` | `invoice` | Database password |
| `NAV_INVOICE_URL` | `http://localhost:8002` | nav-invoice service base URL |
| `INVOICE_FILE_FILTER_URL` | `http://localhost:8001` | invoice-file-filter service base URL |
| `WISE_URL` | `http://localhost:8003` | wise service base URL |
| `SYNC_TIMEOUT` | `300` | HTTP timeout in seconds for downstream calls |
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8004` | FastAPI port |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

The `DB_URL` field accepts the JDBC format already present in the project `.env`. The driver prefix (`jdbc:`) is stripped automatically and credentials are injected to produce a SQLAlchemy-compatible URL (`postgresql+psycopg2://user:pwd@host:port/db`).

## Database

PostgreSQL in production, SQLite in-memory for tests.

### Tables

| Table | Description |
|-------|-------------|
| `supplier` | Suppliers sourced from NAV invoice data |
| `customer` | Customers sourced from NAV invoice data |
| `invoice_file` | PDF files from invoice-file-filter: filename, filesystem path, and extracted word text |
| `invoice` | NAV invoices (`INBOUND` / `OUTBOUND`), linked to supplier, customer, and optionally invoice_file |
| `wise_transaction` | Wise transactions; linked to invoice, supplier, customer, and invoice_file |
| `sync_log` | One row per sync run: mode, counts, errors, start/finish timestamps |

### Alembic migrations

```bash
# Apply all pending migrations (run after uv sync and after pulling new changes)
uv run alembic upgrade head

# Generate a new migration after changing ORM models
uv run alembic revision --autogenerate -m "describe change"
```

## Code structure

```
src/invoice_core/
├── api/main.py              ← FastAPI app: REST endpoints + mounts UI router + static files
├── ui/router.py             ← UI endpoints (GET /ui/*, POST /ui/sync/trigger)
├── services/                ← Shared service layer used by both REST and UI routers
│   ├── dashboard_service.py ← KPI aggregations, recent data, sync log
│   ├── invoice_service.py   ← Invoice list/detail with joined supplier/customer/wise data
│   ├── partner_service.py   ← Supplier and customer list + detail
│   ├── transaction_service.py ← Wise transaction list with filters
│   └── invoice_file_service.py ← PDF file list
├── templates/               ← Jinja2 templates
│   ├── base.html            ← Layout: navbar + sidebar + main content blocks
│   ├── _macros.html         ← Reusable macros: payment_badge, amount_fmt, pdf_icon, …
│   ├── partials/            ← HTMX partial responses (no base.html extension)
│   └── *.html               ← Page templates
├── static/custom.css        ← HTMX indicator + sidebar + KPI styles
├── db.py                    ← SQLAlchemy ORM models + session; exports _enum_str helper
├── service.py               ← Sync orchestration (sync_nav, sync_pdf, sync_wise, sync_match)
├── models.py                ← Pydantic request/response schemas
├── config.py                ← Pydantic settings (reads .env); exports make_http_session factory
├── nav_client.py            ← HTTP client for nav-invoice service
├── pdf_client.py            ← HTTP client for invoice-file-filter service
└── wise_client.py           ← HTTP client for wise service
```

## Orchestration flow

```
invoice-core (this)
  ├── GET  nav-invoice:8002 /invoices?direction=OUTBOUND  → InvoiceDigest list
  │    GET  nav-invoice:8002 /invoices?direction=INBOUND   → InvoiceDigest list
  │         upsert supplier, customer, invoice (both directions)
  ├── POST invoice-file-filter:8001 /api/v1/invoices/extract → PDF file index (filename + path)
  │         upsert invoice_file; link to invoice
  ├── GET  wise:8003 /balance-statements       → TransactionSummary list
  │         upsert wise_transaction; link to invoice/supplier/customer
  └── match wise_transaction → invoice_file     (local DB pass, no HTTP)
```

## Linking strategies

### PDF → Invoice

For each unlinked `invoice` the service tries to match it against every `invoice_file`:

1. **Filename match** — normalised invoice number (separators `/ \ - _ .` → `-`) appears as a substring of the filename.
2. **Word search fallback** — searches the full extracted word list with the same normalised comparison.

Run `invoice-core link <invoice_number> <filename>` to create a manual link when both automatic strategies fail.

### Wise transaction → Invoice / Supplier / Customer

1. **Invoice** — exact match on `payment_reference` vs `invoice_number`, then separator-normalised fallback.
2. **Supplier / Customer from invoice** — reuses the linked invoice's `supplier_id` and `customer_id`.
3. **Counterparty name fallback** — case-insensitive match against `supplier.name` / `customer.name`.

### Wise transaction → invoice file

The `sync-match` step runs in three phases:

1. **Transitive** — reuse the file from an already-linked invoice.
2. **Authoritative reference** — a bank transfer with an invoice-like `payment_reference` must match a file that *contains* that reference; left unlinked if none found.
3. **Scored best-match** — for card payments, scores vendor name tokens + amount variants + date proximity; greedy 1:1 assignment above the confidence threshold.
4. **Invoice back-link** — after all file assignments, any `wise_transaction` that shares an `invoice_file` with an `invoice` (but has no `invoice_id` yet) is linked to that invoice and the invoice is marked PAID. Covers both file links just established and pre-existing ones from prior syncs.

Run `invoice-core link-wise <wise_transaction_id> <filename>` to create a manual link.

## Logs

Written to stdout and `logs/invoice-core.log`.

```
2026-06-17 10:00:01 INFO  invoice_core/nav_client.py:48  GET http://localhost:8002/invoices → 8 outbound + 4 inbound = 12 invoice(s) in 234ms
2026-06-17 10:00:02 INFO  invoice_core/service.py:154    sync_nav: 3 new invoice(s) from 12 digest(s)
2026-06-17 10:00:04 INFO  invoice_core/service.py:592    sync_match: 4 Wise transaction(s) linked to a file
2026-06-17 10:00:05 INFO  invoice_core/service.py:640    sync_all [full] 2026-05-18..2026-06-17: nav=3 pdf=2 wise=5 match=4 errors=0 in 4210ms
```

## Pipeline

```
invoice-core (MASTER, port 8004)
  ↓                    ↓                      ↓
nav-invoice :8002   invoice-file-filter :8001   wise :8003
                         ↓
                   attachment-downloader :8000
```
