# vision

Moneypenny pipeline microservice #6 (port 8009). **Frontend** for the entire Moneypenny system — calls **invoice-core** (port 8004) REST API and **SrcProfit** (IBKR), and renders all web UI pages.

No database, no CLI, no Alembic — pure aggregator and frontend with SSR templates.

## Running

```bash
cd vision
uv sync

cp .env.example .env   # fill in SRCPROFIT_PASSWORD if needed

# REST API + UI (port 8009)
python run_api.py
# or
uv run uvicorn vision.api.main:app --host 0.0.0.0 --port 8009 --reload

# Tests
uv run pytest tests/ -v
```

> **invoice-core must be running** on port 8004 for the `/ui/*` pages to work.

## Pages

### Invoice-core UI pages (served at `/ui/*`)

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/ui/` | KPI cards, recent invoices, recent bank transactions, last sync status |
| Számlák | `/ui/invoices` | Invoice list — filterable by date, status, PDF, supplier; DataTable |
| Számla részlet | `/ui/invoices/{id}` | Invoice detail with supplier/customer cards, linked PDF, bank transactions |
| PDF Fájlok | `/ui/invoice-files` | Invoice file list with linked invoice and supplier |
| Szállítók | `/ui/suppliers` | Supplier list with invoice stats |
| Szállító részlet | `/ui/suppliers/{id}` | Supplier detail with invoice and bank DataTables |
| Vevők | `/ui/customers` | Customer list with invoice stats |
| Vevő részlet | `/ui/customers/{id}` | Customer detail with invoice and bank DataTables |
| Bank tranzakciók | `/ui/transactions` | Transaction list — filterable by date, linked status, partner, amount |
| Osztalék | `/ui/dividend` | Annual dividend/tax calculation: revenue, expenses, KIVA, SZJA, SZOCHO — monthly breakdown |
| Adók | `/ui/adok` | Tax payments view: pivot by month and tax type (NAV ÁFA, SZJA, TAO, Szochó, TB, Bírság, HIPA, Iparkamara) |
| Sync | `/ui/sync` | Trigger sync with mode selection; sync log accordion |

**Tech stack for UI pages**: Jinja2 SSR, HTMX 2.x (boost + partial swap + OOB), Bootstrap 5.3 (Bootswatch Yeti), DataTables 2.x — no build step, all assets from CDN.

Filter forms use HTMX partial updates so filtered views stay responsive without full page reloads.

### Vision-specific pages

| Page | URL | Description |
|------|-----|-------------|
| Portfólió | `/dashboard` | KPI cards + 4 Chart.js charts (cash-flow, invoice status, IBKR holdings, top suppliers) |
| Pitch | `/pitch` | Startup-pitch landing page (standalone dark theme, no sidebar) |
| Home | `/` | Redirects to dashboard |

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check — `{"status": "ok", "timestamp": "..."}` |

All UI is served from the same FastAPI app (Jinja2 SSR, no separate frontend build).

## Architecture

```
src/vision/
├── config.py                  # Pydantic-settings (.env)
├── models.py                  # Dataclasses: InvoiceKPI, CashFlowMonth, SupplierBar, DashboardData
├── clients/
│   ├── invoice_core.py        # Full client for invoice-core REST API (all /api/v1/* endpoints)
│   └── srcprofit.py           # GET /api/summary, /api/portfolio (Basic auth; None on error)
├── services/
│   └── dashboard_service.py   # Aggregation for /dashboard: KPIs, cash-flow, supplier join, IBKR total
├── ui/
│   ├── router.py              # Vision-specific routes: /dashboard, /pitch, /
│   ├── invoice_router.py      # Invoice-core UI routes: all /ui/* (15 routes)
│   └── utils.py               # dict_to_ns() — converts API JSON dicts to SimpleNamespace for dot-access
├── api/
│   └── main.py                # FastAPI app, /health, HTTP logging middleware
├── templates/
│   ├── base.html              # Bootswatch Yeti + Bootstrap Icons + jQuery + DataTables + HTMX
│   ├── _navbar.html           # Navbar with theme toggle + HTMX spinner
│   ├── _sidebar.html          # All nav links: vision pages + all /ui/* links
│   ├── _macros.html           # payment_badge, amount_fmt, direction_badge, pdf_icon, bank_icon, …
│   ├── home.html              # Redirect to /dashboard
│   ├── dashboard.html         # Vision portfolio dashboard (Chart.js 4.x charts)
│   ├── pitch.html             # Standalone startup pitch (does not extend base.html)
│   ├── ui_dashboard.html      # Invoice-core style dashboard (KPI cards, recent invoices)
│   ├── invoices.html          # Invoice list page
│   ├── invoice_detail.html    # Invoice detail
│   ├── invoice_files.html     # PDF file list
│   ├── suppliers.html         # Supplier list
│   ├── supplier_detail.html   # Supplier detail
│   ├── customers.html         # Customer list
│   ├── customer_detail.html   # Customer detail
│   ├── transactions.html      # Bank transaction list
│   ├── dividend.html          # Dividend/tax calculation report
│   ├── adok.html              # Tax payments pivot
│   ├── sync.html              # Sync control panel
│   └── partials/              # HTMX partial responses (no base.html extension)
│       ├── invoice_table.html
│       ├── supplier_table.html
│       ├── transaction_table.html
│       ├── transaction_detail.html
│       ├── invoice_file_table.html
│       └── sync_result.html
└── static/
    └── custom.css             # HTMX indicator + sidebar + KPI + DataTables styles
```

**Data flow for `/ui/*` pages** (no caching):
1. Vision route handler called
2. `InvoiceCoreClient` fetches data from invoice-core REST API (`http://localhost:8004`)
3. `dict_to_ns()` converts JSON dicts → `SimpleNamespace` objects (with ISO datetime auto-parsing)
4. Jinja2 template rendered with dot-notation context

**Data flow for `/dashboard`** (no caching):
1. `dashboard_service.get_dashboard_data()` called
2. Calls invoice-core: `/api/v1/invoices`, `/api/v1/transactions`, `/api/v1/partners/suppliers`
3. Optional call to SrcProfit: `/api/summary` + `/api/portfolio` (silently suppressed if unavailable)
4. Python-side aggregation → dataclasses → Jinja2 + Chart.js JSON context

## Environment (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `INVOICE_CORE_URL` | `http://localhost:8004` | invoice-core base URL |
| `SRCPROFIT_URL` | `https://srcprofit2.graphtrek.co` | SrcProfit base URL |
| `SRCPROFIT_USER` | `admin` | Basic auth user |
| `SRCPROFIT_PASSWORD` | _(empty)_ | Basic auth password |
| `API_HOST` | `0.0.0.0` | Uvicorn bind host |
| `API_PORT` | `8009` | Uvicorn bind port |
| `LOG_LEVEL` | `INFO` | Python log level |
| `REQUEST_TIMEOUT` | `10` | HTTP client timeout (seconds) |

## Tech stack

- **FastAPI** + **Jinja2** SSR — no separate JS build
- **HTMX 2.x** + **Bootstrap 5 (Bootswatch Yeti)** + **DataTables 2.x** — for invoice-core UI pages
- **Chart.js 4.x** — loaded only in `/dashboard` block scripts
- **requests** (synchronous) — consistent with all other workspace services
- **pydantic-settings** reading `.env`
