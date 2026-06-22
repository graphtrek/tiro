---
title: "Specifikáció: Vision – Frontend"
description: "Teljes Moneypenny webes frontend — invoice-core REST API fogyasztása, SSR UI + tulajdonosi portfólió dashboard"
type: "service-spec"
status: "megvalósítva"
port: 8009
language: "HU"
last_updated: "2026-06-22"
depends_on: [invoice-core-spec.md, srcprofit]
related: [INDEX.md, vision-prompt.md, invoice-core-spec.md]
tags: [vision, frontend, fastapi, jinja2, htmx, bootstrap, datatables]
---

# Vision – Frontend — Specifikáció

> 🔗 **Adatforrások**: [[invoice-core-spec.md|Invoice-Core]] (port 8004) REST API + [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR, külső)

---

## Szerepkör és kontextus

A Vision a Moneypenny rendszer **teljes webes frontendja**. Az `invoice-core` (8004) **tiszta JSON REST backend** — saját UI-t nem szolgáltat. A Vision fogyasztja az invoice-core összes REST API végpontját, és SSR Jinja2 sablonokkal kiszolgálja az összes Moneypenny UI oldalt (`/ui/*`). Emellett saját tulajdonosi portfólió dashboardot (`/dashboard`) is tartalmaz, amely az invoice-core-t és a SrcProfit (IBKR) adatait aggregálja.

**Nincs saját DB, nincs Alembic, nincs CLI** — tiszta frontend aggregátor.

---

## Tech Stack

| Réteg | Technológia | Megjegyzés |
|---|---|---|
| Sablonmotor | Jinja2 | FastAPI `Jinja2Templates` |
| Dinamikus frissítés | HTMX 2.x | CDN-ből; `hx-boost` az összes oldalon |
| CSS keretrendszer | Bootstrap 5.3 (Bootswatch Yeti) | CDN-ből |
| Táblázat | DataTables 2.x | Bootstrap 5 integration, CDN-ből |
| Diagramok | Chart.js 4.x | CDN-ből (csak `/dashboard`-on) |
| Ikonok | Bootstrap Icons | CDN-ből |
| Backend | FastAPI | Port 8009 |
| HTTP kliens | requests (szinkron) | Konzisztens a workspace többi szerviziével |

**Nincs build lépés** — minden CSS/JS CDN-ről töltődik.

---

## Architektúra

```
src/vision/
├── config.py                  ← pydantic-settings (.env)
├── models.py                  ← dataclasses: InvoiceKPI, CashFlowMonth, SupplierBar, DashboardData
├── clients/
│   ├── invoice_core.py        ← InvoiceCoreClient — invoice-core összes /api/v1/* végpontja
│   └── srcprofit.py           ← SrcProfitClient — /api/summary, /api/portfolio (Basic auth)
├── services/
│   └── dashboard_service.py   ← /dashboard aggregáció: KPI-k, cash-flow, top szállítók, IBKR total
├── ui/
│   ├── router.py              ← Vision saját oldalak: /, /pitch, /dashboard
│   ├── invoice_router.py      ← Invoice-core UI oldalak: összes /ui/* (15 route)
│   └── utils.py               ← dict_to_ns() — JSON dict → SimpleNamespace, ISO dátum auto-parse
├── api/
│   └── main.py                ← FastAPI app, /health, HTTP logging middleware
├── templates/
│   ├── base.html              ← Bootswatch Yeti + Bootstrap Icons + jQuery + DataTables + HTMX
│   ├── _navbar.html           ← Navbar + HTMX globális spinner
│   ├── _sidebar.html          ← Összes nav link: vision oldalak + /ui/* linkek + invoice-count badge
│   ├── _macros.html           ← payment_badge, amount_fmt, direction_badge, pdf_icon, bank_icon, …
│   ├── home.html              ← Redirect → /dashboard
│   ├── dashboard.html         ← Vision portfólió dashboard (Chart.js 4.x)
│   ├── pitch.html             ← Standalone startup pitch (nem terjeszti ki base.html-t)
│   ├── ui_dashboard.html      ← Invoice-core stílusú dashboard (KPI kártyák, legutóbbi számlák)
│   ├── invoices.html          ← Számlalista
│   ├── invoice_detail.html    ← Számla részletei
│   ├── invoice_files.html     ← PDF fájl lista
│   ├── suppliers.html         ← Szállítólista
│   ├── supplier_detail.html   ← Szállító részletei
│   ├── customers.html         ← Vevőlista
│   ├── customer_detail.html   ← Vevő részletei
│   ├── transactions.html      ← Bank tranzakció lista
│   ├── dividend.html          ← Osztalék/adó kalkuláció
│   ├── adok.html              ← Adófizetési pivot
│   ├── sync.html              ← Sync vezérlőpult
│   └── partials/              ← HTMX részleges válaszok (nem terjesztik ki base.html-t)
│       ├── invoice_table.html
│       ├── supplier_table.html
│       ├── transaction_table.html
│       ├── transaction_detail.html
│       ├── invoice_file_table.html
│       └── sync_result.html
└── static/
    └── custom.css             ← HTMX indicator + sidebar + KPI + DataTables stílusok
```

### dict_to_ns() segédfüggvény

Az invoice-core REST API JSON dict-eket ad vissza. A Jinja2 sablonok pont-szintaxissal (`row.invoice_number`) és `datetime.strftime()` hívásokkal dolgoznak. A `dict_to_ns()` áthidalja a különbséget:

```python
def dict_to_ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: dict_to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [dict_to_ns(i) for i in obj]
    return _parse_leaf(obj)  # ISO 8601 stringeket datetime objektummá alakítja
```

---

## Adatforrások

### invoice-core (port 8004) — teljes endpoint lista

| Adat | Endpoint | Szűrők |
|---|---|---|
| Dashboard összesítő | `GET /api/v1/dashboard` | — |
| Számlák száma | `GET /api/v1/invoices/count` | — |
| Számlalista | `GET /api/v1/invoices` | `date_from`, `date_to`, `status`, `direction`, `has_pdf`, `supplier_name` |
| Számla részlet (PK) | `GET /api/v1/invoices/{id:int}` | — |
| PDF fájl lista | `GET /api/v1/invoice-files` | `linked=yes/no` |
| PDF fájl kiszolgálás | `GET /api/v1/invoice-files/{id:int}/pdf` | — |
| Szállítólista | `GET /api/v1/partners/suppliers` | — |
| Szállítói statisztikák | `GET /api/v1/partners/suppliers/summary` | — |
| Szállító részlet | `GET /api/v1/partners/suppliers/{id:int}` | — |
| Vevőlista | `GET /api/v1/partners/customers` | — |
| Vevő részlet | `GET /api/v1/partners/customers/{id:int}` | — |
| Bank tranzakció lista | `GET /api/v1/transactions` | `date_from`, `date_to`, `linked`, `partner_name`, `amount_min`, `amount_max` |
| Egyenlegek | `GET /api/v1/transactions/balances` | — |
| Tranzakció részlet | `GET /api/v1/transactions/{id:int}` | — |
| Szinkron naplók | `GET /api/v1/sync/logs` | `limit` |
| Szinkron indítás | `POST /api/v1/sync` | `start_date`, `end_date`, `sync_mode` |
| Osztalék kimutatás | `GET /api/v1/reports/dividend` | `year`, `kiva_rate` |
| Adó kimutatás | `GET /api/v1/reports/tax` | `year` |

### SrcProfit (külső)

| Adat | Endpoint | Megjegyzés |
|---|---|---|
| IBKR portfólió | `GET /api/portfolio` | befektetési pozíciók |
| Egyenleg összesítő | `GET /api/summary` | teljes vagyonkép |

> **SrcProfit hitelesítés**: HTTP Basic auth — tárolva a `.env`-ben (`SRCPROFIT_USER`, `SRCPROFIT_PASSWORD`). Ha a SrcProfit nem elérhető, a dashboard szilárdan tűri a hibát (None visszatérés).

---

## Oldalak

### Invoice-Core UI oldalak (`/ui/*` — 15 route)

| Oldal | URL | Leírás |
|---|---|---|
| Dashboard | `/ui/` | KPI kártyák, legutóbbi számlák, tranzakciók, szinkron státusz |
| Számlák | `/ui/invoices` | Számlalista — szűrhető dátum, státusz, PDF, szállító szerint; DataTable |
| Számla részlet | `/ui/invoices/{id}` | Számla részletei szállítói/vevői kártyákkal, PDF link, bank tranzakciók |
| PDF Fájlok | `/ui/invoice-files` | PDF fájl lista linkelt számlával és szállítóval |
| Szállítók | `/ui/suppliers` | Szállítólista számla statisztikákkal |
| Szállító részlet | `/ui/suppliers/{id}` | Szállító részletei számla és bank DataTable-ekkel |
| Vevők | `/ui/customers` | Vevőlista számla statisztikákkal |
| Vevő részlet | `/ui/customers/{id}` | Vevő részletei számla és bank DataTable-ekkel |
| Bank tranzakciók | `/ui/transactions` | Tranzakció lista — szűrhető dátum, linked státusz, partner, összeg szerint |
| Osztalék | `/ui/dividend` | Éves osztalék/adó kalkuláció: bevétel, kiadás, KIVA, SZJA, SZOCHO — havi bontás |
| Adók | `/ui/adok` | Adófizetési pivot hónap és típus szerint (NAV ÁFA, SZJA, TAO, Szochó, TB, Bírság, HIPA, Iparkamara) |
| Sync | `/ui/sync` | Szinkron indítás mód-választással; szinkron napló accordion |
| PDF letöltés | `/ui/invoice-files/{id}/pdf` | `RedirectResponse` → invoice-core `/api/v1/invoice-files/{id}/pdf` |

**UI tech**: Jinja2 SSR, HTMX 2.x (boost + partial swap + OOB), Bootstrap 5.3 (Bootswatch Yeti), DataTables 2.x — nincs build lépés.

Filter formok HTMX partial frissítéssel működnek (szűrt nézetek nem reloadolják az egész oldalt).

### Vision saját oldalak

| Oldal | URL | Leírás |
|---|---|---|
| Portfólió dashboard | `/dashboard` | KPI kártyák + 4 Chart.js diagram (cash-flow, számla státusz, IBKR portfólió, top szállítók) |
| Pitch | `/pitch` | Startup pitch oldal (standalone sötét téma, nem terjeszti ki base.html-t) |
| Home | `/` | Redirect → `/dashboard` |

### `/dashboard` — Portfólió Dashboard részletei

#### KPI kártyák

| Kártya | Forrás | Számítás |
|---|---|---|
| Fizetetlen számlák összege | invoice-core `/api/v1/invoices` | `status=UNPAID` összeg HUF |
| Beérkező tranzakciók (30 nap) | invoice-core `/api/v1/transactions` | credit tranzakciók összege |
| Kapcsolt számlák aránya | invoice-core `/api/v1/invoices` | `has_pdf=true` / összes (%) |
| IBKR portfólió értéke | srcprofit | teljes piaci érték |

#### Chart.js diagramok

1. **Havi cash-flow (bar)** — invoice-core tranzakciók; X: hónap (utolsó 6), Y: bejövő vs. kimenő HUF
2. **Számlák státusz (doughnut)** — PAID (zöld) / UNPAID (piros) / PARTIAL (sárga)
3. **IBKR portfólió összetétel (doughnut)** — srcprofit eszközosztályok/pozíciók
4. **Top szállítók kiadás (bar)** — top 10 szállító nettó HUF összeg szerint

#### Lefúrás linkek

- `→ Számlák` — `http://localhost:8009/ui/invoices`
- `→ Bank tranzakciók` — `http://localhost:8009/ui/transactions`
- `→ SrcProfit IBKR` — `https://srcprofit2.graphtrek.co/`

---

## REST Interface

```
GET  /health             → {"status": "ok", "timestamp": "..."}
GET  /                   → home.html (redirect → /dashboard)
GET  /dashboard          → dashboard.html (portfólió KPI + Chart.js)
GET  /pitch              → pitch.html (standalone)
GET  /ui/                → ui_dashboard.html (invoice-core stílusú dashboard)
GET  /ui/invoices        → invoices.html
GET  /ui/invoices/{id}   → invoice_detail.html
GET  /ui/invoice-files   → invoice_files.html
GET  /ui/invoice-files/{id}/pdf → RedirectResponse → invoice-core PDF
GET  /ui/suppliers       → suppliers.html
GET  /ui/suppliers/{id}  → supplier_detail.html
GET  /ui/customers       → customers.html
GET  /ui/customers/{id}  → customer_detail.html
GET  /ui/transactions    → transactions.html
GET  /ui/dividend        → dividend.html
GET  /ui/adok            → adok.html
GET  /ui/sync            → sync.html
POST /ui/sync/trigger    → sync_result.html (HTMX partial + OOB badge frissítés)
```

**Nincs CLI** — a Vision csak böngészőből használt UI szerviz.

---

## Environment (`.env`)

```bash
# invoice-core kapcsolat
INVOICE_CORE_URL=http://localhost:8004

# SrcProfit kapcsolat
SRCPROFIT_URL=https://srcprofit2.graphtrek.co
SRCPROFIT_USER=admin
SRCPROFIT_PASSWORD=<titkos>

# Vision szerviz
API_HOST=0.0.0.0
API_PORT=8009
LOG_LEVEL=INFO
REQUEST_TIMEOUT=10
```

---

## Implementációs sorrend

1. `config.py` + `models.py` — pydantic-settings + response dataclasses
2. `clients/invoice_core.py` — requests sync kliens, összes invoice-core REST endpoint
3. `clients/srcprofit.py` — requests sync kliens (Basic auth), portfólió + summary
4. `ui/utils.py` — `dict_to_ns()` helper
5. `services/dashboard_service.py` — aggregáció, cash-flow számítás, top szállítók ranking
6. `base.html` + `_macros.html` + `_sidebar.html` + `_navbar.html` — Bootstrap CDN, HTMX, DataTables, Chart.js, `hx-boost`
7. `ui/invoice_router.py` — mind a 15 `/ui/*` route, `InvoiceCoreClient` hívásokkal
8. `templates/ui_dashboard.html` + invoice-core sablonok másolata — invoice-core `templates/` → vision `templates/`
9. `ui/router.py` — Vision saját oldalak: `/dashboard`, `/pitch`, `/`
10. `api/main.py` — FastAPI app, mindkét router csatolása

---

## Kapcsolódások

### Wiki Linkek
- **Prompt**: [[vision-prompt.md|Vision Prompt]]
- **Fő adatforrás (REST backend)**: [[invoice-core-spec.md|Invoice-Core Spec]]
- **Külső adatforrás**: [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR befektetések)
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]
