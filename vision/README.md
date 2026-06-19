# vision

Moneypenny pipeline microservice #6 (port 8009). Read-only **ownership aggregator** — calls **invoice-core** and **SrcProfit** (IBKR), aggregates the data, and renders a startup-pitch landing page plus a live ownership dashboard.

No database, no CLI, no Alembic — pure aggregator with SSR templates.

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

## Pages

| Page | URL | Description |
|------|-----|-------------|
| Pitch | `/pitch` | Startup-pitch landing page (standalone dark theme) |
| Dashboard | `/dashboard` | KPI cards + 4 Chart.js charts (cash-flow, invoice status, IBKR, top suppliers) |
| Home | `/` | Redirects to dashboard |

Open `http://localhost:8009/pitch` or `http://localhost:8009/dashboard`.

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
│   ├── invoice_core.py        # GET /api/v1/invoices, /transactions, /partners/suppliers
│   └── srcprofit.py           # GET /api/summary, /api/portfolio (Basic auth; None on error)
├── services/
│   └── dashboard_service.py   # Aggregation: KPIs, cash-flow, supplier join, IBKR total
├── ui/
│   └── router.py              # /dashboard, /pitch, /
├── api/
│   └── main.py                # FastAPI app, /health, HTTP logging middleware
├── templates/
│   ├── base.html              # Bootswatch Yeti, Bootstrap Icons, HTMX 2.x
│   ├── _sidebar.html
│   ├── _macros.html
│   ├── home.html
│   ├── dashboard.html         # Chart.js 4.x charts
│   └── pitch.html             # Standalone startup pitch (does not extend base.html)
└── static/
    └── custom.css
```

**Data flow per request** (no caching):
1. `GET /dashboard` → `dashboard_service.get_dashboard_data()`
2. Three parallel-ish calls to invoice-core: invoices, transactions, suppliers
3. One optional call to SrcProfit: `/api/summary` + `/api/portfolio` (suppressed silently if unavailable)
4. Python-side aggregation → dataclasses → Jinja2 template

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
- **HTMX 2.x** + **Bootstrap 5 (Bootswatch Yeti)**
- **Chart.js 4.x** — loaded only in `dashboard.html` block scripts
- **requests** (synchronous) — consistent with all other workspace services
- **pydantic-settings** reading `.env`
