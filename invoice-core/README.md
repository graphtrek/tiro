# invoice-core

Moneypenny pipeline microservice #4 (port 8004). Master orchestrator — calls **nav-invoice**, **invoice-file-filter**, and **wise**, merges the results, and persists everything to PostgreSQL.

## Running

```bash
cd invoice-core
uv sync

# REST API (port 8004)
python run_api.py
# or
uv run uvicorn invoice_core.api.main:app --host 0.0.0.0 --port 8004 --reload

# CLI
uv run invoice-core sync                        # full sync: NAV + PDF + Wise (last 30 days)
uv run invoice-core sync --start 2026-05-01 --end 2026-05-31
uv run invoice-core sync-nav                    # NAV only
uv run invoice-core sync-pdf                    # PDF only
uv run invoice-core sync-wise                   # Wise only
uv run invoice-core report --month 2026-05      # full sync for one month + summary table

# Tests
uv run pytest tests/ -v

# Alembic migrations (first-time setup)
uv run alembic init alembic
# → edit alembic/env.py (see Database section below)
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
```

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check |
| `POST` | `/api/v1/sync` | Full sync (NAV + PDF + Wise) |
| `POST` | `/api/v1/sync/nav` | Sync NAV invoices only |
| `POST` | `/api/v1/sync/pdf` | Sync PDF file index only |
| `POST` | `/api/v1/sync/wise` | Sync Wise transactions only |
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
  "errors": []
}
```

**Request fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `start_date` | `string` | 30 days ago | Filter start (`YYYY-MM-DD`) |
| `end_date` | `string` | today | Filter end (`YYYY-MM-DD`) |
| `sync_mode` | `string` | `full` | `full` / `nav_only` / `pdf_only` / `wise_only` |
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

# Outbound invoices only
curl "http://localhost:8004/api/v1/invoices?direction=OUTBOUND"
```

**Query parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `date_from` | `YYYY-MM-DD` | Filter by invoice date (inclusive) |
| `date_to` | `YYYY-MM-DD` | Filter by invoice date (inclusive) |
| `status` | `PAID` / `UNPAID` / `PARTIAL` | Filter by payment status |
| `direction` | `INBOUND` / `OUTBOUND` | Filter by invoice direction |

### GET /api/v1/invoices/{invoice_number}

```bash
curl http://localhost:8004/api/v1/invoices/INV-2026-042
```

## CLI

### sync

```bash
uv run invoice-core sync [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
```

### sync-nav / sync-pdf / sync-wise

```bash
uv run invoice-core sync-nav [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
uv run invoice-core sync-pdf [--start DATE] [--end DATE] [--clear-cache] [--json] [-v]
uv run invoice-core sync-wise [--clear-cache] [--json] [-v]
```

### report

```bash
uv run invoice-core report --month 2026-05 [--clear-cache] [--json]
```

Runs a full sync for the given calendar month and prints a Rich summary table.

### --clear-cache

Clears all downstream service caches before starting the sync:

| Service | Cache endpoint called |
|---|---|
| nav-invoice | `POST /cache/clear` |
| invoice-file-filter | `DELETE /api/v1/pdf/words/cache` |

Cache clearing is best-effort — if a service is unreachable the warning is logged and sync continues.

```bash
uv run invoice-core sync --clear-cache
uv run invoice-core sync-pdf --clear-cache --start 2026-06-01
```

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
| `invoice_file` | Raw PDF metadata from invoice-file-filter |
| `invoice` | NAV invoices (`INBOUND` / `OUTBOUND`), linked to supplier, customer, and optionally invoice_file |
| `wise_transaction` | Wise transactions, linked to supplier/customer/invoice where matched |

### Alembic setup

After `uv sync`, initialise Alembic once:

```bash
uv run alembic init alembic
```

Edit `alembic/env.py` — replace the metadata and engine wiring with:

```python
from invoice_core.db import Base, engine
target_metadata = Base.metadata

def run_migrations_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

Then generate and apply the initial migration:

```bash
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
```

## Orchestration flow

```
invoice-core (this)
  ├── GET  nav-invoice:8002 /invoices?direction=OUTBOUND  → InvoiceDigest list
  │    GET  nav-invoice:8002 /invoices?direction=INBOUND   → InvoiceDigest list
  │         upsert supplier, customer, invoice (both directions)
  ├── POST invoice-file-filter:8001 /api/v1/invoices/extract → PDF file index
  │         upsert invoice_file
  │         link to invoice: filename match → fallback to POST /api/v1/pdf/words word search
  └── GET  wise:8003 /balance-statements       → TransactionSummary list
            insert wise_transaction (idempotent); link by counterparty + payment_reference
```

## Logs

Written to stdout and `logs/invoice-core.log`.

```
2026-06-16 10:00:01 INFO  invoice_core/nav_client.py:48  GET http://localhost:8002/invoices → 8 outbound + 4 inbound = 12 invoice(s) in 234ms
2026-06-16 10:00:02 INFO  invoice_core/service.py:56     sync_nav: 3 new invoice(s) from 12 digest(s)
2026-06-16 10:00:05 INFO  invoice_core/service.py:125    sync_all [full] 2026-05-17..2026-06-16: nav=3 pdf=2 wise=5 errors=0 in 4210ms
```

## Pipeline

```
invoice-core (MASTER, port 8004)
  ↓                    ↓                      ↓
nav-invoice :8002   invoice-file-filter :8001   wise :8003
                         ↓
                   attachment-downloader :8000
```
