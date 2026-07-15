# invoice-core

Moneypenny pipeline microservice #4 (port 8004). Master orchestrator — calls **nav-invoice**, **invoice-file-filter**, and **bank**, merges the results, and persists everything to PostgreSQL.

Pure **JSON REST backend** — no server-side HTML rendering. The web UI lives in the **vision** service (port 8009) which calls this REST API.

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
uv run invoice-core sync                        # full sync: NAV + PDF + Bank (last 30 days)
uv run invoice-core sync --start 2026-05-01 --end 2026-05-31
uv run invoice-core sync-nav                    # NAV only
uv run invoice-core sync-pdf                    # PDF only
uv run invoice-core sync-bank                   # Bank only
uv run invoice-core sync-match                  # match existing bank txns to invoice files (no fetching)
uv run invoice-core report --month 2026-05      # full sync for one month + summary table

# Tests
uv run pytest tests/ -v
```

## REST API

CORS is enabled for `http://localhost:8009` (vision frontend).

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check |
| `GET`  | `/api/v1/dashboard` | Combined dashboard data: kpis, recent invoices/transactions, top suppliers, last sync |
| `POST` | `/api/v1/sync` | Full sync (NAV + PDF + Bank) |
| `POST` | `/api/v1/sync/nav` | Sync NAV invoices only |
| `POST` | `/api/v1/sync/pdf` | Sync PDF file index only |
| `POST` | `/api/v1/sync/bank` | Sync bank transactions only |
| `POST` | `/api/v1/sync/match` | Match existing bank transactions to invoice files (no fetching) |
| `GET`  | `/api/v1/sync/logs` | Recent sync log entries (query: `limit`) |
| `GET`  | `/api/v1/invoices/count` | Total invoice count `{"count": n}` |
| `GET`  | `/api/v1/invoices` | Invoice list (filter: `date_from`, `date_to`, `status`, `direction`, `has_pdf`, `supplier_name`) |
| `GET`  | `/api/v1/invoices/{invoice_id:int}` | Invoice detail by integer PK (includes linked bank transactions) |
| `GET`  | `/api/v1/invoices/{invoice_number}` | Invoice by invoice number string |
| `GET`  | `/api/v1/invoice-files` | Invoice file list (filter: `linked` = `yes`/`no`; `filename` = substring search) |
| `GET`  | `/api/v1/invoice-files/{file_id:int}/pdf` | Serve PDF file inline |
| `GET`  | `/api/v1/partners/suppliers` | Supplier list |
| `GET`  | `/api/v1/partners/suppliers/summary` | Aggregate supplier stats |
| `GET`  | `/api/v1/partners/suppliers/{supplier_id:int}` | Supplier detail with invoices and transactions |
| `GET`  | `/api/v1/partners/customers` | Customer list |
| `GET`  | `/api/v1/partners/customers/{customer_id:int}` | Customer detail with invoices and transactions |
| `GET`  | `/api/v1/transactions` | Bank transaction list (filter: `date_from`, `date_to`, `linked`, `partner_name`, `amount_min`, `amount_max`); each row includes `invoice_ids: list[int]` and `invoice_numbers: list[str]` |
| `GET`  | `/api/v1/transactions/balances` | Latest balance per bank |
| `GET`  | `/api/v1/transactions/{transaction_id:int}` | Transaction detail; includes `invoice_ids: list[int]` and `invoice_numbers: list[str]` (may contain multiple entries for split-payment transactions) |
| `GET`  | `/api/v1/reports/dividend` | Annual dividend/tax calculation (query: `year`, `kiva_rate`) |
| `GET`  | `/api/v1/reports/tax` | Tax payment report by month and type (query: `year`) |
| `PUT`  | `/api/v1/invoices/{invoice_id}/invoice-file` | Manually link an invoice to a PDF file — sets `invoice_file_locked=True`; body: `{"invoice_file_id": int}` |
| `DELETE` | `/api/v1/invoices/{invoice_id}/invoice-file` | Remove manual PDF link from an invoice — clears `invoice_file_locked` so auto-sync may re-link |
| `PUT`  | `/api/v1/transactions/{txn_id}/invoice-file` | Manually link a bank transaction to a PDF file — sets `invoice_file_locked=True`; body: `{"invoice_file_id": int}` |
| `DELETE` | `/api/v1/transactions/{txn_id}/invoice-file` | Remove manual PDF link from a bank transaction — clears `invoice_file_locked` |
| `PUT`  | `/api/v1/invoices/{invoice_id}/transactions/{txn_id}` | Add a bank transaction to an invoice's payment set (M2M, `manual=True`) |
| `DELETE` | `/api/v1/invoices/{invoice_id}/transactions/{txn_id}` | Remove a bank transaction from an invoice's payment set |

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
  "bank_transactions_synced": 34,
  "bank_files_matched": 27,
  "errors": []
}
```

**Request fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `start_date` | `string` | 30 days ago | Filter start (`YYYY-MM-DD`) |
| `end_date` | `string` | today | Filter end (`YYYY-MM-DD`) |
| `sync_mode` | `string` | `full` | `full` / `nav_only` / `pdf_only` / `bank_only` / `match_only` |
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
| `has_pdf` | `true` / `false` | Filter by PDF presence |
| `supplier_name` | string | Case-insensitive supplier name filter |

## CLI

### sync

```bash
uv run invoice-core sync [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
```

### sync-nav / sync-pdf / sync-bank / sync-match

```bash
uv run invoice-core sync-nav [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
uv run invoice-core sync-pdf [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
uv run invoice-core sync-bank [--clear-cache] [--json] [-v]
uv run invoice-core sync-match [--json] [-v]      # match existing bank txns to invoice files
```

`sync-match` fetches nothing. It links unmatched `bank_transaction` records to
`invoice_file` rows (via transitive invoice link, payment reference, or scored
vendor/amount/date matching), then back-links any transaction that now shares an
`invoice_file` with an `invoice` to that invoice and recomputes its payment status
(PAID / PARTIAL / UNPAID based on the sum of linked transaction amounts).

### link / link-bank (legacy CLI)

Low-level CLI shortcuts that write a link directly without setting `invoice_file_locked`. Because the lock flag is not set, the next auto-sync may overwrite the link. Prefer the REST API (or vision UI) for permanent manual links.

```bash
uv run invoice-core link <invoice_number> <filename>
uv run invoice-core link-bank <transaction_id> <filename>
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
| `BANK_URL` | `http://localhost:8005` | bank service base URL |
| `SYNC_TIMEOUT` | `300` | HTTP timeout in seconds for downstream calls |
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8004` | FastAPI port |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `TAX_ACCOUNTS` | *(see below)* | JSON object mapping bank account numbers to display labels for the Adók page |
| `AUTH_ENABLED` | `true` *(currently `false` in `.env`)* | JWT validation on/off |
| `AUTH_SERVICE_URL` | `http://localhost:8007` | Central auth service base URL (JWKS) |

`TAX_ACCOUNTS` defaults to all NAV (ÁFA, Bírság, SZJA, Szochó, TAO, TB), HIPA, HIPA-Késedelmi, and Iparkamara accounts. Override in `.env` as a single-line JSON string:

```
TAX_ACCOUNTS={"10032000-01076868-00000000":"NAV ÁFA","12001008-00272513-00100005":"HIPA"}
```

The `DB_URL` field accepts the JDBC format already present in the project `.env`. The driver prefix (`jdbc:`) is stripped automatically and credentials are injected to produce a SQLAlchemy-compatible URL (`postgresql+psycopg2://user:pwd@host:port/db`).

## Authentication (JWT)

With `AUTH_ENABLED=true`, every endpoint except `GET /health` requires a valid JWT issued by the central **auth** service (:8007) after a Google login. The token arrives as an `Authorization: Bearer <token>` header or an `mp_access_token` HttpOnly cookie (vision forwards it automatically); validation is local (RS256 signature against the `/.well-known/jwks.json` public keys + `exp`/`aud`/`iss`) — no per-request network call to the auth service. Without a token the response is `401 Unauthorized`.

The incoming Bearer token is passed through to downstream calls (nav-invoice, invoice-file-filter, bank) via `TokenPassthrough` in `src/invoice_core/auth.py`. Note: the `invoice-core sync` **CLI** carries no user token, so keep `AUTH_ENABLED=false` on the leaf services if you use it. Spec: `../moneypenny/auth-service-spec.md`.

## Database

PostgreSQL in production, SQLite in-memory for tests.

### Tables

| Table | Description |
|-------|-------------|
| `supplier` | Suppliers sourced from NAV invoice data |
| `customer` | Customers sourced from NAV invoice data |
| `invoice_file` | PDF files from invoice-file-filter: filename, filesystem path, and extracted word text |
| `invoice` | NAV invoices (`INBOUND` / `OUTBOUND`), linked to supplier, customer, and optionally invoice_file; `invoice_file_locked` (bool) — when `True`, auto-sync skips re-assigning `invoice_file_id` |
| `invoice_bank_transaction` | Junction table — many-to-many link between `invoice` and `bank_transaction`; `manual` (bool) — `True` for rows created via the manual link API |
| `bank_transaction` | Bank transactions (Erste + Wise CSV via bank service); linked to supplier, customer, and invoice_file; connected to invoices via the junction table; `invoice_file_locked` (bool) — when `True`, auto-sync skips re-assigning `invoice_file_id` |
| `sync_log` | One row per sync run: mode, counts, errors, start/finish timestamps |

### Alembic migrations

```bash
# Apply all pending migrations (run after uv sync and after pulling new changes)
uv run alembic upgrade head

# Generate a new migration after changing ORM models
uv run alembic revision --autogenerate -m "describe change"
```

**Migration history (recent):**

| Revision | Description |
|----------|-------------|
| `f5g6h7i8j9k0` | invoice↔bank_transaction M2M junction table |
| `g6h7i8j9k0l1` | Manual link fields: `invoice_file_locked` on `invoice` and `bank_transaction`; `manual` on `invoice_bank_transaction` |

## Code structure

```
src/invoice_core/
├── api/main.py              ← FastAPI app: all REST endpoints + CORS for vision (port 8009)
├── services/                ← Service layer called by REST endpoints
│   ├── dashboard_service.py ← KPI aggregations, recent data, sync log
│   ├── invoice_service.py   ← Invoice list/detail with joined supplier/customer/bank data
│   ├── partner_service.py   ← Supplier and customer list + detail
│   ├── transaction_service.py ← Bank transaction list with filters
│   ├── invoice_file_service.py ← PDF file list
│   ├── dividend_service.py  ← Annual dividend/tax calculation (KIVA, SZJA, SZOCHO)
│   └── tax_service.py       ← Tax payment report: filters bank transactions by NAV/HIPA/Iparkamara account numbers
├── db.py                    ← SQLAlchemy ORM models + session; exports _enum_str helper
├── service.py               ← Sync orchestration (sync_nav, sync_pdf, sync_bank, sync_match)
├── models.py                ← Pydantic request/response schemas
├── config.py                ← Pydantic settings (reads .env); exports make_http_session factory
├── nav_client.py            ← HTTP client for nav-invoice service
├── pdf_client.py            ← HTTP client for invoice-file-filter service
└── bank_client.py           ← HTTP client for bank service
```

## Orchestration flow

```
invoice-core (this)
  ├── GET  nav-invoice:8002 /invoices?direction=OUTBOUND  → InvoiceDigest list
  │    GET  nav-invoice:8002 /invoices?direction=INBOUND   → InvoiceDigest list
  │         upsert supplier, customer, invoice (both directions)
  ├── POST invoice-file-filter:8001 /api/v1/invoices/extract → PDF file index (filename + path)
  │         upsert invoice_file; link to invoice
  ├── GET  bank:8005 /balance-statement/all               → ConsolidatedStatement (Erste + Wise CSV)
  │         upsert bank_transaction; link to invoice/supplier/customer
  └── match bank_transaction → invoice_file               (local DB pass, no HTTP)
```

## Linking strategies

### PDF → Invoice

For each unlinked `invoice` the service tries to match it against every `invoice_file`:

1. **Filename match** — normalised invoice number (separators `/ \ - _ .` → `-`) appears as a substring of the filename.
2. **Word search fallback** — searches the full extracted word list with the same normalised comparison.

Use the vision UI (lock badge + "PDF kapcsolása" button on the invoice detail page) or `PUT /api/v1/invoices/{id}/invoice-file` to create a permanent manual link that survives future syncs.

### Bank transaction → Invoice / Supplier / Customer

1. **Invoice** — exact match on `payment_reference` vs `invoice_number`, then separator-normalised fallback.
2. **Supplier / Customer from invoice** — reuses the linked invoice's `supplier_id` and `customer_id`.
3. **Counterparty name fallback** — case-insensitive match against `supplier.name` / `customer.name`.

### Bank transaction → invoice file

The `sync-match` step runs in three phases:

1. **Transitive** — reuse the file from an already-linked invoice.
2. **Authoritative reference** — a bank transfer with an invoice-like `payment_reference` must match a file that *contains* that reference; left unlinked if none found.
3. **Scored best-match** — for card payments, scores vendor name tokens + amount variants + date proximity; greedy 1:1 assignment above the confidence threshold.
4. **Invoice back-link** — after all file assignments, any `bank_transaction` that shares an `invoice_file` with an `invoice` (but is not yet linked to that invoice) is added to the invoice's payment set via the `invoice_bank_transaction` junction. The invoice's payment status is then recomputed as PAID (sum of linked amounts ≥ invoice total), PARTIAL (partial coverage), or UNPAID (none). Covers file links just established and pre-existing ones from prior syncs.

Because the invoice ↔ bank transaction relationship is many-to-many, a single invoice can be settled by multiple bank transfers (installments), and a single bank transfer can be linked to multiple invoices (split payments). Payment status is always derived from the sum of the linked transaction amounts at read time or after each sync pass.

Use the vision UI (transaction offcanvas → "PDF kapcsolása" button) or `PUT /api/v1/transactions/{id}/invoice-file` to create a permanent manual link that survives future syncs.

### Manual linking

When automatic strategies can't establish the correct relationship, all three link types (invoice↔PDF, transaction↔PDF, invoice↔transaction) can be set manually via the REST API or the vision UI. Manual links are protected from being overwritten by subsequent sync runs.

**Lock semantics:**

| Action | `invoice_file_locked` after | Effect on auto-sync |
|--------|----------------------------|---------------------|
| Manual link (`PUT`) | `True` | Sync skips re-assigning `invoice_file_id` for this record |
| Manual unlink (`DELETE`) | `False` | Sync may auto-link again on the next run |
| Never touched (default) | `False` | Sync behaves as normal |

Invoice↔transaction M2M rows are never removed by sync, so manual M2M links are always preserved automatically. The `manual` flag on junction rows is an audit marker shown as a lock badge in the vision UI.

## Logs

Written to stdout and `logs/invoice-core.log`.

```
2026-06-17 10:00:01 INFO  invoice_core/nav_client.py:48  GET http://localhost:8002/invoices → 8 outbound + 4 inbound = 12 invoice(s) in 234ms
2026-06-17 10:00:02 INFO  invoice_core/service.py:154    sync_nav: 3 new invoice(s) from 12 digest(s)
2026-06-17 10:00:04 INFO  invoice_core/service.py:592    sync_match: 4 bank transaction(s) linked to a file
2026-06-17 10:00:05 INFO  invoice_core/service.py:640    sync_all [full] 2026-05-18..2026-06-17: nav=3 pdf=2 bank=5 match=4 errors=0 in 4210ms
```

## Pipeline

```
invoice-core (MASTER, port 8004)
  ↓                    ↓                      ↓
nav-invoice :8002   invoice-file-filter :8001   bank :8005
                         ↓
                   attachment-downloader :8000
```
