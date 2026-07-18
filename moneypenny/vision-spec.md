---
title: "Specifikáció: Vision – Frontend"
description: "Teljes Moneypenny webes frontend — invoice-core REST API fogyasztása, SSR UI + tulajdonosi portfólió dashboard"
type: "service-spec"
status: "megvalósítva"
port: 8009
language: "HU"
last_updated: "2026-07-18"
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
│   ├── invoice_core.py        ← InvoiceCoreClient — invoice-core összes /api/v1/* végpontja (incl. szállító/vevő CRUD, sync/pending)
│   └── srcprofit.py           ← SrcProfitClient — /api/summary, /api/portfolio (Basic auth)
├── services/
│   └── dashboard_service.py   ← /dashboard aggregáció: KPI-k, cash-flow, top szállítók, IBKR total
├── ui/
│   ├── router.py              ← Vision saját oldalak: /, /pitch, /dashboard
│   ├── invoice_router.py      ← Invoice-core UI oldalak: összes /ui/* (36 route)
│   ├── admin_router.py        ← Admin oldalak: /ui/admin/users, /ui/admin/activity-types (valós adat, invoice-core CRUD-ot hív)
│   ├── controlling_router.py  ← Controlling oldalak: /ui/controlling/projects + /timesheet (valós adat, invoice-core CRUD-ot hív) + /reports (valós adat, invoice-core GET /api/v1/reports/timesheet-t hív)
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
│   ├── admin_users.html       ← Admin: bejelentkezett felhasználók listája
│   ├── admin_activity_types.html ← Admin: tevékenység típusok CRUD (HTMX form-okkal)
│   ├── controlling_projects.html ← Controlling: projektek CRUD (HTMX form-okkal, kliens-oldali sorszám/kód előnézettel)
│   ├── controlling_timesheet.html ← Controlling: saját timesheet rekordok CRUD (HTMX form-okkal, kliens-oldali projekt hét előnézettel)
│   ├── controlling_reports.html  ← Controlling: riportok — valós szűrők + 4 riporttípus (projekt heti+kumulált, személy, ügyfél, tevékenység típus), DataTables Buttons export (Excel/PDF/Print)
│   └── partials/              ← HTMX részleges válaszok (nem terjesztik ki base.html-t)
│       ├── invoice_table.html
│       ├── supplier_table.html
│       ├── transaction_table.html
│       ├── transaction_detail.html
│       ├── invoice_file_table.html
│       ├── sync_result.html
│       └── pending_sync_card.html    ← állandó "függőben lévő párosítás" számláló, sync.html-ba include-olva + OOB frissítve minden sync futás után
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
| Szállító létrehozás | `POST /api/v1/partners/suppliers` | — |
| Szállító módosítás | `PUT /api/v1/partners/suppliers/{id:int}` | — |
| Szállító törlés | `DELETE /api/v1/partners/suppliers/{id:int}` | — |
| Vevőlista | `GET /api/v1/partners/customers` | — |
| Vevő részlet | `GET /api/v1/partners/customers/{id:int}` | — |
| Vevő létrehozás | `POST /api/v1/partners/customers` | — |
| Vevő módosítás | `PUT /api/v1/partners/customers/{id:int}` | — |
| Vevő törlés | `DELETE /api/v1/partners/customers/{id:int}` | — |
| Bank tranzakció lista | `GET /api/v1/transactions` | `date_from`, `date_to`, `linked`, `partner_name`, `amount_min`, `amount_max` |
| Egyenlegek | `GET /api/v1/transactions/balances` | — |
| Tranzakció részlet | `GET /api/v1/transactions/{id:int}` | — |
| Szinkron naplók | `GET /api/v1/sync/logs` | `limit` |
| Szinkron indítás | `POST /api/v1/sync` | `start_date`, `end_date`, `sync_mode` |
| Függőben lévő párosítások | `GET /api/v1/sync/pending` | — (állandó számláló, nem az utolsó futástól függ) |
| Osztalék kimutatás | `GET /api/v1/reports/dividend` | `year`, `kiva_rate` |
| Adó kimutatás | `GET /api/v1/reports/tax` | `year` |
| Felhasználók | `GET /api/v1/users` | — |
| Tevékenység típusok | `GET /api/v1/activity-types` | — |
| Tevékenység típus létrehozás | `POST /api/v1/activity-types` | — |
| Tevékenység típus módosítás | `PUT /api/v1/activity-types/{id}` | — |
| Tevékenység típus törlés | `DELETE /api/v1/activity-types/{id}` | — |
| Projektek | `GET /api/v1/projects` | — |
| Projekt létrehozás | `POST /api/v1/projects` | — |
| Projekt módosítás | `PUT /api/v1/projects/{id}` | — |
| Projekt törlés | `DELETE /api/v1/projects/{id}` | — |
| Timesheet rekordok | `GET /api/v1/timesheet-entries` | `user_id` (kötelező) |
| Timesheet rekord létrehozás | `POST /api/v1/timesheet-entries` | — |
| Timesheet rekord módosítás | `PUT /api/v1/timesheet-entries/{id}` | `user_id` (kötelező) |
| Timesheet rekord törlés | `DELETE /api/v1/timesheet-entries/{id}` | `user_id` (kötelező) |
| Timesheet riport | `GET /api/v1/reports/timesheet` | `report_type` (`project`\|`person`\|`customer`\|`activity_type`, kötelező), `date_from`, `date_to`, `customer_id`, `project_id`, `user_id`, `activity_type_id` — `project_id` kötelező, ha `report_type=project` |

### SrcProfit (külső)

| Adat | Endpoint | Megjegyzés |
|---|---|---|
| IBKR portfólió | `GET /api/portfolio` | befektetési pozíciók |
| Egyenleg összesítő | `GET /api/summary` | teljes vagyonkép |

> **SrcProfit hitelesítés**: HTTP Basic auth — tárolva a `.env`-ben (`SRCPROFIT_USER`, `SRCPROFIT_PASSWORD`). Ha a SrcProfit nem elérhető, a dashboard szilárdan tűri a hibát (None visszatérés).

---

## Oldalak

### Invoice-Core UI oldalak (`/ui/*` — 36 route)

| Oldal | URL | Leírás |
|---|---|---|
| Dashboard | `/ui/` | KPI kártyák, legutóbbi számlák, tranzakciók, szinkron státusz |
| Számlák | `/ui/invoices` | Számlalista — szűrhető dátum, státusz, PDF, szállító szerint; DataTable |
| Számla részlet | `/ui/invoices/{id}` | Számla részletei szállítói/vevői kártyákkal, PDF link, bank tranzakciók |
| PDF Fájlok | `/ui/invoice-files` | PDF fájl lista linkelt számlával és szállítóval |
| Szállítók | `/ui/suppliers` | Szállítólista számla statisztikákkal; "Új szállító" létrehozás modal |
| Szállító részlet | `/ui/suppliers/{id}` | Szállító részletei számla és bank DataTable-ekkel; módosítás modal + törlés (letiltva, ha van kapcsolt számla/tranzakció) |
| Vevők | `/ui/customers` | Vevőlista számla statisztikákkal; "Új vevő" létrehozás modal |
| Vevő részlet | `/ui/customers/{id}` | Vevő részletei számla és bank DataTable-ekkel; módosítás modal + törlés (letiltva, ha van kapcsolt számla/tranzakció) |
| Bank tranzakciók | `/ui/transactions` | Tranzakció lista — szűrhető dátum, linked státusz, partner, összeg szerint |
| Osztalék | `/ui/dividend` | Éves osztalék/adó kalkuláció: bevétel, kiadás, KIVA, SZJA, SZOCHO — havi bontás |
| Adók | `/ui/adok` | Adófizetési pivot hónap és típus szerint (NAV ÁFA, SZJA, TAO, Szochó, TB, Bírság, HIPA, Iparkamara) |
| Sync | `/ui/sync` | Szinkron indítás mód-választással; szinkron napló accordion; állandó "függőben lévő partner-párosítás" kártya (hány számla/tranzakció vár még szállítóra/vevőre, az utolsó futástól függetlenül) |
| PDF letöltés | `/ui/invoice-files/{id}/pdf` | `RedirectResponse` → invoice-core `/api/v1/invoice-files/{id}/pdf` |

**UI tech**: Jinja2 SSR, HTMX 2.x (boost + partial swap + OOB), Bootstrap 5.3 (Bootswatch Yeti), DataTables 2.x — nincs build lépés.

Filter formok HTMX partial frissítéssel működnek (szűrt nézetek nem reloadolják az egész oldalt).

### Admin oldalak (`/ui/admin/*` — valós adat, nem mockup)

| Oldal | URL | Leírás |
|---|---|---|
| Felhasználók | `/ui/admin/users` | Bejelentkezett felhasználók listája (auth szerviz login rekordjai) |
| Tevékenység típusok | `/ui/admin/activity-types` | CRUD törzsadat a timesheet funkcióhoz — létrehozás/módosítás modal, törlés csak ha a használati szám 0 (jelenleg mindig 0, a UI-n még nincs kötve a `timesheet_entry` adatokhoz), egyébként inaktiválás |

### Controlling oldalak (`/ui/controlling/*`)

| Oldal | URL | Leírás |
|---|---|---|
| Projektek | `/ui/controlling/projects` | Projektek CRUD — valós adat. Ügyfél (customer FK), ügyfelenként növekvő sorszám, automatikusan összeállított project kód (`{ügyfél} - {sorszám:03d} - {short_name}`), gazda, aktív/lezárt státusz, és rögzítésre jogosultak checkbox lista (kik adhatnak timesheet rekordot — a Timesheet oldal ezt ténylegesen ellenőrzi). Az "Összesített ráfordítás (óra)" oszlop egyelőre `0` placeholder — még nincs kötve a `timesheet_entry` adatokhoz |
| Timesheet | `/ui/controlling/timesheet` | Saját timesheet rekordok CRUD — valós adat. Dátum, Projekt (datalist, csak aktív és a bejelentkezett felhasználó számára jogosult projektek), Ügyfél/Project gazda/Projekt hét mezők a kiválasztott projektből származó, csak-olvasható előnézetek (a `project_week` szerver-számított, nincs tárolva), Tevékenység típus (aktív típusokból), 0,5 órás lépésű Óra select, szabad szöveges Résztvevők és Tevékenység leírás. A bejelentkezett felhasználó azonosítása JWT `email` claim alapján történik, a `client.get_users()` listában keresve egyezést (nincs dedikált "ki vagyok" végpont). A mockupban szereplő "Zárolás" gomb látható, de letiltott — nincs még admin/role fogalom, ami gátolná |
| Riportok | `/ui/controlling/reports` | Valós adat — 4 riporttípus a `timesheet_entry` felett: Projekt riport (heti + kumulált, tevékenység típusonkénti bontással, futó összeggel), Személy riport, Ügyfél riport, Tevékenység típus riport (a személy/ügyfél riport ugyanazt a csoportosító+pivot logikát használja; a tevékenység típus riportnak nincs pivot oszlopa). Szűrők: dátumtartomány (projekt kezdete óta / aktuális hónap / aktuális hét / egyéni), ügyfél, projekt, személy, tevékenység típus. Projekt riportnál projekt hiányában automatikusan az első projekt kerül kiválasztásra. Export (Excel/PDF/Nyomtatás) kliens-oldali DataTables Buttons-szal — a ténylegesen szűrt/rendezett táblát exportálja. A "Mentés sablonként" és a mockupban szereplő külön "Heti export" (Excel heti blokk szerkezet) riporttípus továbbra sincs megvalósítva |

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
POST /ui/suppliers       → létrehozás (HTMX, teljes oldal swap)
GET  /ui/suppliers/{id}  → supplier_detail.html
POST /ui/suppliers/{id}  → módosítás (HTMX, teljes oldal swap)
DELETE /ui/suppliers/{id}/delete → törlés (HTMX, HX-Redirect → /ui/suppliers sikeres törlésnél)
GET  /ui/customers       → customers.html
POST /ui/customers       → létrehozás (HTMX, teljes oldal swap)
GET  /ui/customers/{id}  → customer_detail.html
POST /ui/customers/{id}  → módosítás (HTMX, teljes oldal swap)
DELETE /ui/customers/{id}/delete → törlés (HTMX, HX-Redirect → /ui/customers sikeres törlésnél)
GET  /ui/transactions    → transactions.html
GET  /ui/dividend        → dividend.html
GET  /ui/adok            → adok.html
GET  /ui/sync            → sync.html
POST /ui/sync/trigger    → sync_result.html (HTMX partial + OOB badge frissítés)
GET  /ui/admin/users             → admin_users.html
GET  /ui/admin/activity-types    → admin_activity_types.html
POST /ui/admin/activity-types    → létrehozás (HTMX, teljes oldal swap)
POST /ui/admin/activity-types/{id} → módosítás (HTMX, teljes oldal swap)
DELETE /ui/admin/activity-types/{id}/delete → törlés (HTMX, teljes oldal swap)
GET  /ui/controlling/projects    → controlling_projects.html
POST /ui/controlling/projects    → létrehozás (HTMX, teljes oldal swap)
POST /ui/controlling/projects/{id} → módosítás (HTMX, teljes oldal swap)
DELETE /ui/controlling/projects/{id} → törlés (HTMX, teljes oldal swap)
GET  /ui/controlling/timesheet   → controlling_timesheet.html
POST /ui/controlling/timesheet   → létrehozás (HTMX, teljes oldal swap)
POST /ui/controlling/timesheet/{id} → módosítás (HTMX, teljes oldal swap)
DELETE /ui/controlling/timesheet/{id} → törlés (HTMX, teljes oldal swap)
GET  /ui/controlling/reports     → controlling_reports.html (valós adat; query: report_type, date_range, date_from, date_to, customer_id, project_id, user_id, activity_type_id)
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
