---
title: "Specifikáció: Vision – Tulajdonosi AI Platform"
description: "High-level pénzügyi összesítő dashboard — invoice-core és SrcProfit adatok aggregálása tulajdonosi nézetbe"
type: "service-spec"
status: "tervezett"
port: 8009
language: "HU"
last_updated: "2026-06-18"
depends_on: [invoice-core-spec.md, srcprofit]
related: [INDEX.md, vision-prompt.md, invoice-core-spec.md, invoice-core-ui-spec.md]
tags: [vision, dashboard, ai-copilot, fastapi, jinja2]
---

# Vision – Tulajdonosi AI Platform — Specifikáció

> 🔗 **Adatforrások**: [[invoice-core-spec.md|Invoice-Core]] (port 8004) + [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR, külső)

---

## Szerepkör és kontextus

Te egy Full-Stack Python Fejlesztő vagy. A feladatod egy **read-only aggregátor mikroszerviz** elkészítése, amely egyetlen tulajdonosi dashboardon mutatja a pénzügyi helyzet teljeskörű képét. A szerviz **saját adatbázist nem kezel** — az invoice-core REST API-t és a SrcProfit szolgáltatást hívja, és az adatokat vizuálisan összesíti.

A célcsoport: tulajdonosok, akik több céget kezelnek, és egy képernyőn akarják látni a teljes vagyonképet. A szerviz az `invoice-core` UI mintájára épül (SSR: Jinja2 + HTMX + Bootstrap + Chart.js).

---

## Tech Stack

| Réteg | Technológia | Megjegyzés |
|---|---|---|
| Sablonmotor | Jinja2 | FastAPI `Jinja2Templates` |
| Dinamikus frissítés | HTMX 2.x | CDN-ből |
| CSS keretrendszer | Bootstrap 5 | CDN-ből |
| Diagramok | Chart.js 4.x | CDN-ből |
| Ikonok | Bootstrap Icons | CDN-ből |
| Backend | FastAPI | Port 8009 |
| HTTP kliens | httpx (async) | invoice-core és SrcProfit API hívásokhoz |

**Nincs saját DB, nincs build lépés** — minden CSS/JS CDN-ről töltődik.

---

## Architektúra

A Vision **levél aggregátor**: csak olvas, nem ír. Nincs Alembic, nincs SQLAlchemy.

```
vision/
├── src/vision/
│   ├── api/
│   │   └── main.py            ← FastAPI app (health, static mount)
│   ├── ui/
│   │   └── router.py          ← UI végpontok (/, /dashboard)
│   ├── clients/
│   │   ├── invoice_core.py    ← InvoiceCoreClient (httpx async)
│   │   └── srcprofit.py       ← SrcProfitClient (httpx async)
│   ├── services/
│   │   └── dashboard_service.py  ← aggregáció, KPI számítás
│   ├── templates/
│   │   ├── base.html
│   │   ├── _macros.html
│   │   ├── home.html          ← koncepcióoldal
│   │   └── dashboard.html     ← KPI kártyák + Chart.js diagramok
│   ├── static/
│   │   └── custom.css
│   ├── config.py              ← pydantic-settings
│   └── models.py              ← Pydantic response modellek
├── run_api.py
└── pyproject.toml
```

### Hívási lánc

```
Böngésző
   ↓ GET /dashboard
vision (8009)
   ├── GET http://invoice-core:8004/api/v1/invoices          → számlák
   ├── GET http://invoice-core:8004/api/v1/transactions      → Wise tranzakciók
   ├── GET http://invoice-core:8004/api/v1/partners/suppliers → szállítók
   └── GET https://srcprofit2.graphtrek.co/api/...           → IBKR portfólió
   ↓
dashboard_service.aggregate()
   ↓
dashboard.html (Chart.js + Bootstrap)
```

---

## Adatforrások

### invoice-core (port 8004)

| Adat | Endpoint | Megjegyzés |
|---|---|---|
| Számlák listája | `GET /api/v1/invoices` | szűrhető: dátum, státusz |
| Wise tranzakciók | `GET /api/v1/transactions` | bankszámla mozgások |
| Szállítók | `GET /api/v1/partners/suppliers` | partner adatok |
| Vevők | `GET /api/v1/partners/customers` | partner adatok |
| Szinkron indítása | — | nem hívja a Vision |

### SrcProfit (külső)

| Adat | Endpoint | Megjegyzés |
|---|---|---|
| IBKR portfólió | `GET /api/portfolio` | befektetési pozíciók |
| Egyenleg összesítő | `GET /api/summary` | teljes vagyonkép |

> **SrcProfit hitelesítés**: HTTP Basic auth (`admin` / `Girafhus2`) — tárolva a `.env`-ben (`SRCPROFIT_USER`, `SRCPROFIT_PASSWORD`).
> SrcProfit API endpointjait az integráció előtt ellenőrizni kell (nincs Swagger-spec a wikiben).

---

## Oldalak

### 1. Kezdőoldal (`GET /`)

Koncepcióoldal — a rendszer bemutatása potenciális ügyfeleknek.

**Tartalom:**
- Hero szekció: „Tulajdonosi AI Copilot" headline + alcím
- Mire válaszol a rendszer? (bulleted kérdések a prompt alapján)
- 6 funkcióblokk kártyán: Cash-flow forecast, Költségelemzés, Projekt profitabilitás, CFO Chat, Adóoptimalizálás, Tulajdonosi dashboard
- Árazási táblázat (Starter / Growth / Executive)
- CTA gomb: „Ugrás a Dashboard-ra" → `/dashboard`
- Külső linkek: [Invoice-Core UI](http://localhost:8004/ui/) | [SrcProfit](https://srcprofit2.graphtrek.co/)

---

### 2. Dashboard (`GET /dashboard`)

Tulajdonosi összesítő — chart-ok + KPI kártyák.

#### KPI kártyák (felső sor)

| Kártya | Forrás | Számítás |
|---|---|---|
| Fizetetlen számlák összege | invoice-core `/invoices` | `payment_status=UNPAID`, összeg HUF |
| Beérkező Wise tranzakciók (30 nap) | invoice-core `/transactions` | credit tranzakciók összege |
| Kapcsolt számlák aránya | invoice-core `/invoices` | `has_pdf=true` / összes (%) |
| IBKR portfólió értéke | srcprofit | teljes piaci érték |

#### Diagramok (Chart.js)

**1. Havi cash-flow (bar chart)**
- Forrás: invoice-core Wise tranzakciók
- X tengely: hónap (utolsó 6 hónap)
- Y tengely: bejövő vs. kimenő összeg HUF

**2. Számlák fizetési státusz (doughnut chart)**
- Forrás: invoice-core számlák
- Szegmensek: PAID (zöld) / UNPAID (piros) / PARTIAL (sárga)

**3. IBKR portfólió összetétel (doughnut chart)**
- Forrás: srcprofit
- Szegmensek: eszközosztályok / pozíciók

**4. Szállítók szerint kiadás (bar chart)**
- Forrás: invoice-core számlák + szállítók
- Top 10 szállító összeg szerint (nettó HUF)

#### Lefúrás linkek

Bootstrap kártya aljában:
- `→ Invoice-Core számlák` — `http://localhost:8004/ui/invoices`
- `→ Wise tranzakciók` — `http://localhost:8004/ui/transactions`
- `→ SrcProfit IBKR` — `https://srcprofit2.graphtrek.co/`

---

## REST Interface

```
GET  /health             → {"status": "ok", "version": "..."}
GET  /                   → home.html (koncepcióoldal)
GET  /dashboard          → dashboard.html (KPI + diagramok)
GET  /ui/                → redirect → /dashboard
```

**Nincs CLI** — a Vision csak böngészőből használt UI szerviz.

---

## Pydantic Modellek

```python
class CashFlowMonth(BaseModel):
    month: str          # "2026-05"
    income: float
    expense: float

class InvoiceKPI(BaseModel):
    total: int
    unpaid_count: int
    unpaid_amount: float
    linked_pdf_pct: float

class SrcProfitSummary(BaseModel):
    total_value: float
    currency: str
    positions: list[dict]

class DashboardData(BaseModel):
    invoice_kpi: InvoiceKPI
    cashflow_months: list[CashFlowMonth]
    top_suppliers: list[dict]
    srcprofit: SrcProfitSummary | None   # None ha srcprofit nem elérhető
```

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

1. `config.py` + `models.py` — Pydantic settings + response modellek
2. `clients/invoice_core.py` — httpx async kliens, invoice + transaction + partner hívások
3. `clients/srcprofit.py` — httpx async kliens (Basic auth), portfólió + summary
4. `services/dashboard_service.py` — aggregáció, cash-flow számítás, top-supplier ranking
5. `base.html` + `_macros.html` — Bootstrap CDN, HTMX, Chart.js, `hx-boost`
6. `home.html` — koncepcióoldal statikus tartalommal
7. `dashboard.html` — KPI kártyák + 4 Chart.js diagram
8. `ui/router.py` + `api/main.py` — FastAPI routing összekapcsolás
9. `run_api.py` — uvicorn belépési pont

---

## Kapcsolódások

### Wiki Linkek
- **Prompt**: [[vision-prompt.md|Vision Prompt]]
- **Fő adatforrás**: [[invoice-core-spec.md|Invoice-Core Spec]] → [[invoice-core-prompt.md|Invoice-Core Prompt]]
- **UI minta**: [[invoice-core-ui-spec.md|Invoice-Core UI Spec]] → [[invoice-core-ui-prompt.md|Invoice-Core UI Prompt]]
- **Külső adatforrás**: [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR befektetések)
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]
