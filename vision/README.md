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

### Admin pages (`/ui/admin/*` — real data, not mockups)

| Page | URL | Description |
|------|-----|-------------|
| Felhasználók (Users) | `/ui/admin/users` | List of logged-in users (login records from the auth service) |
| Tevékenység típusok (Activity types) | `/ui/admin/activity-types` | CRUD master data for the Timesheet feature — create/edit modal; delete is only offered when the usage count is 0 (currently always 0 — the check isn't wired to `timesheet_entry` yet), otherwise the row is deactivated instead |

### Controlling pages (`/ui/controlling/*`)

| Page | URL | Description |
|------|-----|-------------|
| Projektek (Projects) | `/ui/controlling/projects` | CRUD for projects — real data. Client (customer FK), auto-incrementing per-customer sequence number, auto-composed project code (`{customer} - {seq:03d} - {short_name}`), owner, active/closed status, and permitted-users checkboxes (who may log time on the project — enforced by the Timesheet page). Hours-worked column is still hardcoded `0` — not yet wired to `timesheet_entry` |
| Timesheet | `/ui/controlling/timesheet` | CRUD for the logged-in user's own timesheet entries — real data. Date, Projekt (datalist restricted to active projects the user owns or is permitted on), Ügyfél/Project gazda/Projekt hét shown as read-only previews derived from the selected project (`project_week` is server-computed, not stored), Tevékenység típus (from active activity types), 0.5-hour-step óra select, free-text Résztvevők and Tevékenység description. "Zárolás" (week lock) button is present but disabled — no admin/role concept exists yet to gate it |
| Riportok (Reports) | `/ui/controlling/reports` | Static mockup — no backend yet |

### Vision-specific pages

| Page | URL | Description |
|------|-----|-------------|
| Portfólió | `/dashboard` | KPI cards + 4 Chart.js charts (cash-flow, invoice status, IBKR holdings, top suppliers) |
| Home / Pitch | `/` | Startup-pitch landing page (standalone dark theme, no sidebar); `/pitch` redirects here |
| Login | `/login` | NiceAdmin-style login page — provider buttons from the auth service (`GET /auth/providers`), silent re-login via refresh cookie |
| Logout | `/logout` | Revokes the refresh token at the auth service, clears cookies, redirects to `/login` |

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
│   ├── admin_router.py        # Admin pages: /ui/admin/users, /ui/admin/activity-types (real data, calls invoice-core CRUD)
│   ├── controlling_router.py  # Controlling pages: /ui/controlling/projects + /timesheet (real data, calls invoice-core CRUD), reports (static mockup)
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
│   ├── admin_users.html       # Admin: logged-in users list
│   ├── admin_activity_types.html # Admin: activity types CRUD (HTMX forms)
│   ├── controlling_projects.html # Controlling: projects CRUD (HTMX forms, client-side code/sequence preview)
│   ├── controlling_timesheet.html # Controlling: own timesheet entries CRUD (HTMX forms, client-side project-week preview)
│   ├── controlling_reports.html  # Controlling: reports — static mockup
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
| `AUTH_ENABLED` | `true` *(currently `false` in `.env`)* | JWT protection of the UI on/off |
| `AUTH_SERVICE_URL` | `http://localhost:8007` | Central auth service base URL (JWKS, login, logout) |
| `JWT_AUDIENCE` | `moneypenny` | Expected `aud` claim |
| `JWT_ISSUER` | `auth-service` | Expected `iss` claim |
| `INVOICE_CORE_URL` | `http://localhost:8004` | invoice-core base URL |
| `SRCPROFIT_URL` | `https://srcprofit2.graphtrek.co` | SrcProfit base URL |
| `SRCPROFIT_USER` | `admin` | Basic auth user |
| `SRCPROFIT_PASSWORD` | _(empty)_ | Basic auth password |
| `API_HOST` | `0.0.0.0` | Uvicorn bind host |
| `API_PORT` | `8009` | Uvicorn bind port |
| `LOG_LEVEL` | `INFO` | Python log level |
| `REQUEST_TIMEOUT` | `10` | HTTP client timeout (seconds) |

## Authentication (JWT)

With `AUTH_ENABLED=true`, a middleware protects every route except `/`, `/pitch`, `/login`, `/logout`, `/static/*`, and `/health`:

- **Browser requests** (`Accept: text/html`) without a valid token are redirected to `/login?next=<original URL>`.
- **API requests** get `401` JSON.
- Tokens are accepted as an `Authorization: Bearer` header or the `mp_access_token` HttpOnly cookie set by the auth service (:8007) after Google login. Validation is local (RS256 against the auth service's JWKS, cached 1h).
- The incoming Bearer token is forwarded to invoice-core/uploader calls (`TokenPassthrough` in `src/vision/auth.py`).
- The navbar shows the logged-in user (name/avatar from JWT claims) with a logout button.
- The login page silently calls `POST /auth/refresh` (credentials included), so an expired 15-minute access token renews without a Google round-trip while the 30-day refresh cookie is valid.

Spec: `../moneypenny/auth-service-spec.md`.

## Tech stack

- **FastAPI** + **Jinja2** SSR — no separate JS build
- **HTMX 2.x** + **Bootstrap 5 (Bootswatch Yeti)** + **DataTables 2.x** — for invoice-core UI pages
- **Chart.js 4.x** — loaded only in `/dashboard` block scripts
- **requests** (synchronous) — consistent with all other workspace services
- **pydantic-settings** reading `.env`
