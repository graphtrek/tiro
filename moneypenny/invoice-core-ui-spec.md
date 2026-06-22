---
title: "Specifikáció: Invoice-Core Felhasználói Felület"
description: "HTMX/Jinja2/Bootstrap/DataTables alapú könyvelési áttekintő felület — shared service layer architektúrával"
language: "HU"
last_updated: "2026-06-22"
related: [invoice-core-ui-prompt.md, invoice-core-spec.md, vision-spec.md, invoice-file-filter-spec.md]
---

# Invoice-Core Felhasználói Felület — Specifikáció

> ⚠️ **Architektúra-váltás (2026-06-22)**: Az invoice-core UI **átköltözött a [[vision-spec.md|vision]] (port 8009) szervizbe**. Az invoice-core mostantól tiszta JSON REST backend — nem kezel Jinja2 sablonokat, statikus fájlokat vagy `/ui/` routert. Ez a spec a UI eredeti tervét dokumentálja; az aktuális implementációt a [[vision-spec.md|Vision Spec]] írja le.

> 🔗 **Kapcsolódás**: [[invoice-core-spec.md|Invoice-Core Spec]] | [[vision-spec.md|Vision Frontend Spec]]

---

## Szerepkör és kontextus

Te egy Full-Stack Python Fejlesztő vagy. A feladatod egy könyvelési áttekintő webes felhasználói felület elkészítése az `invoice-core` FastAPI szervizhez. A felület **szerver-oldali renderelésű** (SSR): Jinja2 sablonok + HTMX + Bootstrap + DataTables. Külön frontend framework (React, Vue, stb.) nem szükséges.

A cél: a könyvelő (és a cégvezető) egy böngészőből áttekinthesse a számlák, PDF fájlok, szállítók, vevők és Wise tranzakciók teljes képét, és lekérhesse az összefüggéseket közöttük.

---

## Tech Stack

| Réteg | Technológia | Megjegyzés |
|---|---|---|
| Sablonmotor | Jinja2 | FastAPI `Jinja2Templates` |
| Dinamikus frissítés | HTMX 2.x | CDN-ből |
| CSS keretrendszer | Bootstrap 5 | CDN-ből |
| Táblázat | DataTables 2.x | Bootstrap 5 integration, CDN-ből |
| Ikonok | Bootstrap Icons | CDN-ből |
| Backend | FastAPI (meglévő) | Új `/ui/` router prefix |

**Nincs külön build lépés** — minden CSS/JS CDN-ről töltődik.

---

## Architektúra — Shared Service Layer

A UI router **nem** lekérdez közvetlenül SQLAlchemy-n keresztül, és **nem** hívja a meglévő REST API-t belső HTTP-vel. Ehelyett egy közös `services/` réteg van, amelyet mind a REST router, mind a UI router használ.

**Miért?** Ha a UI-t később más technológiára (React, mobil app) kell átírni, a service réteg megmarad — az új UI a meglévő REST végpontokat hívja, amelyek ugyanezt a service réteget használják. Nincs üzleti logika duplikáció.

```
invoice_core/
├── services/                      ← SHARED — REST és UI egyaránt hívja
│   ├── dashboard_service.py       ← KPI aggregációk (COUNT, SUM)
│   ├── invoice_service.py         ← számla lekérések, szűrések
│   ├── partner_service.py         ← supplier + customer lekérések
│   ├── transaction_service.py     ← wise_transaction lekérések
│   └── invoice_file_service.py    ← invoice_file lekérések
│
├── api/
│   └── router.py                  ← meglévő REST végpontok → service-t hívják
│
├── ui/
│   └── router.py                  ← UI végpontok → ugyanazt a service-t hívják
│
├── templates/
│   ├── base.html
│   ├── _macros.html               ← Jinja2 makrók (badge, progress bar, stb.)
│   ├── partials/                  ← HTMX partial válaszok
│   │   ├── invoice_table.html
│   │   ├── supplier_table.html
│   │   ├── transaction_table.html
│   │   └── sync_result.html
│   ├── dashboard.html
│   ├── invoices.html
│   ├── invoice_detail.html
│   ├── invoice_files.html
│   ├── suppliers.html
│   ├── supplier_detail.html
│   ├── customers.html
│   ├── customer_detail.html
│   ├── transactions.html
│   └── sync.html
│
└── static/
    └── custom.css
```

### Service réteg felépítése

Minden service `AsyncSession`-t kap függőség-injektálással (`Depends(get_db)`), és Pydantic sémákat ad vissza — nem SQLAlchemy ORM objektumokat. Így a REST router és a UI router is típusbiztos adatot kap.

```python
# services/invoice_service.py
async def list_invoices(
    db: AsyncSession,
    date_from: date | None = None,
    date_to: date | None = None,
    payment_status: str | None = None,
    has_pdf: bool | None = None,
    supplier_name: str | None = None,
) -> list[InvoiceRow]: ...

# ui/router.py
@router.get("/invoices")
async def invoices_page(
    request: Request,
    filters: InvoiceFilters = Depends(),
    db: AsyncSession = Depends(get_db),
):
    rows = await invoice_service.list_invoices(db, **filters.model_dump())
    ...

# api/router.py (meglévő REST végpont — UGYANAZT a service-t hívja)
@router.get("/api/v1/invoices")
async def list_invoices_api(
    filters: InvoiceFilters = Depends(),
    db: AsyncSession = Depends(get_db),
):
    return await invoice_service.list_invoices(db, **filters.model_dump())
```

---

## HTMX Best Practices

### 1. Teljes oldal vs. partial válasz

Minden UI végpont megvizsgálja az `HX-Request` fejlécet. Ha HTMX kérés, csak a partial template-et adja vissza; ha normál navigáció, a teljes oldalt (`extends "base.html"`).

```python
# ui/router.py
@router.get("/invoices")
async def invoices_page(request: Request, ...):
    rows = await invoice_service.list_invoices(db, ...)
    template = (
        "partials/invoice_table.html"
        if request.headers.get("HX-Request")
        else "invoices.html"
    )
    return templates.TemplateResponse(template, {"request": request, "rows": rows})
```

### 2. Szűrők — `hx-trigger="change delay:300ms"`

A szűrők azonnal frissítik a táblázatot, debounce-szal a felesleges kérések elkerülésére:

```html
<!-- invoices.html -->
<form id="filter-form"
      hx-get="/ui/invoices"
      hx-trigger="change delay:300ms, input delay:500ms"
      hx-target="#table-container"
      hx-swap="innerHTML"
      hx-push-url="true">
  ...
</form>
<div id="table-container">
  {% include "partials/invoice_table.html" %}
</div>
```

`hx-push-url="true"` — a böngésző URL-je frissül a szűrőparaméterekkel, így a szűrt oldal megosztható/könyvjelzőzhető.

### 3. Navigáció — `hx-boost`

A `base.html`-ben `hx-boost="true"` az egész `<body>`-ra: a belső linkek HTMX AJAX kérésként viselkednek (csak a `<body>` tartalma cserélődik), de visszaesési lehetőség (JavaScript nélkül is működik):

```html
<!-- base.html -->
<body hx-boost="true">
  ...
</body>
```

### 4. Loading indicator — `htmx-indicator`

Minden HTMX kéréshez globális spinner a navbarban, CSS-szel vezérelve:

```html
<!-- base.html -->
<div id="global-spinner" class="htmx-indicator">
  <div class="spinner-border spinner-border-sm text-light" role="status"></div>
</div>
```

```css
/* custom.css */
.htmx-indicator { opacity: 0; transition: opacity 200ms ease-in; }
.htmx-request .htmx-indicator,
.htmx-request.htmx-indicator { opacity: 1; }
```

### 5. Sync — polling OOB swappal

A sync indítása után az eredmény egy külön `<div>`-be kerül, az oldalsáv számlaszámlálója Out-of-Band (OOB) cserével frissül ugyanabban a válaszban:

```html
<!-- partials/sync_result.html -->
<div id="sync-result">
  <!-- sync eredmény tartalom -->
</div>
<span id="invoice-count-badge" hx-swap-oob="true">{{ invoice_count }}</span>
```

---

## Jinja2 Best Practices

### Template öröklés

Minden oldal a `base.html`-t terjeszti ki, és a `{% block %}` rendszert használja:

```html
<!-- base.html -->
<!DOCTYPE html>
<html lang="hu">
<head>
  <title>{% block title %}Moneypenny{% endblock %}</title>
  <!-- Bootstrap, HTMX, DataTables CDN -->
</head>
<body hx-boost="true">
  {% include "_navbar.html" %}
  <div class="d-flex">
    {% include "_sidebar.html" %}
    <main class="flex-grow-1 p-4">
      {% block breadcrumb %}{% endblock %}
      {% block content %}{% endblock %}
    </main>
  </div>
</body>
</html>

<!-- invoices.html -->
{% extends "base.html" %}
{% block title %}Számlák — Moneypenny{% endblock %}
{% block content %}...{% endblock %}
```

### Makrók (`_macros.html`)

Újrafelhasználható UI elemek makróként, ne ismétlődő HTML-ként:

```html
<!-- _macros.html -->
{% macro payment_badge(status) %}
  {% set cfg = {
    "PAID":    ("bg-success", "Fizetve"),
    "UNPAID":  ("bg-danger",  "Fizetetlen"),
    "PARTIAL": ("bg-warning text-dark", "Részleges"),
  } %}
  <span class="badge {{ cfg[status][0] }}">{{ cfg[status][1] }}</span>
{% endmacro %}

{% macro confidence_bar(value) %}
  {% set color = "bg-success" if value > 0.8 else ("bg-warning" if value > 0.5 else "bg-danger") %}
  <div class="progress" style="min-width:80px">
    <div class="progress-bar {{ color }}" style="width:{{ (value * 100)|round(1) }}%">
      {{ "%.0f"|format(value * 100) }}%
    </div>
  </div>
{% endmacro %}

{% macro pdf_icon(has_pdf) %}
  {% if has_pdf %}
    <i class="bi bi-file-earmark-check text-success"></i>
  {% else %}
    <i class="bi bi-file-earmark-x text-secondary"></i>
  {% endif %}
{% endmacro %}

{% macro amount_fmt(value, currency="HUF") %}
  {{ "{:,.0f}".format(value) }} {{ currency }}
{% endmacro %}
```

Használat sablonban:

```html
{% from "_macros.html" import payment_badge, confidence_bar, pdf_icon, amount_fmt %}
...
<td>{{ payment_badge(row.payment_status) }}</td>
<td>{{ amount_fmt(row.amount_total) }}</td>
```

### Partial templates (HTMX válaszokhoz)

A `partials/` alkönyvtárban lévő sablonok **nem** terjesztik ki a `base.html`-t — csak a táblázat HTML-jét tartalmazzák. A főoldal `{% include %}`-kal beágyazza őket az első betöltéskor; HTMX kéréskor a végpont közvetlenül ezeket adja vissza.

---

## Bootstrap 5 Best Practices

### Layout

- Sidebar + fő tartalom: `d-flex` + `flex-grow-1` (nem grid)
- Kártyák: `card` + `card-body`, `shadow-sm`
- Responsive: `col-12 col-md-6 col-xl-4` a KPI kártyáknál

### DataTables konfiguráció

DataTables szerver-oldali rendezés/lapozás **nélkül** (az adatmennyiség belefér kliensoldali feldolgozásba):

```html
<table id="invoice-table" class="table table-hover table-sm">
  <thead>...</thead>
  <tbody>
    {% for row in rows %}...{% endfor %}
  </tbody>
</table>

<script>
  document.addEventListener("DOMContentLoaded", () => {
    new DataTable("#invoice-table", {
      language: { url: "//cdn.datatables.net/plug-ins/2.0.0/i18n/hu.json" },
      pageLength: 25,
      order: [[1, "desc"]],   // dátum szerint csökkenő
      columnDefs: [
        { targets: [4, 5, 6], className: "text-end" },  // összeg oszlopok jobbra
        { targets: [-1, -2], orderable: false },         // PDF/Wise ikon oszlopok
      ],
    });
  });
</script>
```

**HTMX + DataTables együttélés**: ha HTMX cseréli a táblázatot, a DataTables-t újra inicializálni kell. Megoldás: `htmx:afterSwap` eseményre figyelni:

```html
<script>
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.target.id === "table-container") {
      new DataTable("#invoice-table", { ... });
    }
  });
</script>
```

---

## Oldalak

### 1. Dashboard (`GET /ui/`)

**KPI kártyák** (`dashboard_service.get_kpis(db)`):
- Összes számla (db)
- Fizetetlen számlák (db + összeg HUF)
- Összekapcsolt PDF fájlok (db) vs. nem linkelt (db)
- Wise tranzakciók (db, utolsó 30 nap)
- Szállítók száma / Vevők száma

**Legutóbbi szinkronizálás**: utolsó sync időpontja és eredménye + `Sync indítása` gomb.

**Legutóbbi 10 számla**: Bootstrap `table-sm`, nem DataTable.

**Legutóbbi 5 Wise tranzakció**: dátum | összeg | partner | kapcsolt számla.

---

### 2. Számlák (`GET /ui/invoices`)

**DataTable oszlopok**:
| Mező | Forrás | Megjegyzés |
|---|---|---|
| Számlaszám | `invoice.invoice_number` | Link → `/ui/invoices/{id}` |
| Dátum | `invoice.invoice_date` | |
| Szállító | `supplier.name` | Link → `/ui/suppliers/{id}` |
| Vevő | `customer.name` | Link → `/ui/customers/{id}` |
| Nettó | `invoice.amount_net` | `amount_fmt` makró |
| ÁFA | `invoice.amount_vat` | |
| Bruttó | `invoice.amount_total` | |
| Státusz | `invoice.payment_status` | `payment_badge` makró |
| PDF | `invoice.invoice_file_id` | `pdf_icon` makró |
| Wise | `wise_transaction` count | ikon ha van |

**Szűrők** (`InvoiceFilters` Pydantic schema, `Depends()`-szel):
- `date_from` / `date_to` (date input)
- `payment_status` (select: mind / PAID / UNPAID / PARTIAL)
- `has_pdf` (select: mind / igen / nem)
- `supplier_name` (text)

---

### 3. Számla Részletek (`GET /ui/invoices/{id}`)

Bootstrap kétoszlopos grid:
- **Bal**: számlaszám, dátum, NAV ID, státusz badge, összeg táblázat
- **Jobb**: szállító kártya + vevő kártya (linkekkel)

**PDF szekció** (ha van `invoice_file_id`): fájlnév, raw értékek, `confidence_bar` makró.

**Wise szekció** (ha van kapcsolt tranzakció): DataTable.

---

### 4. PDF Fájlok (`GET /ui/invoice-files`)

**DataTable oszlopok**: fájlnév | kinyert számlaszám | szállító | összeg | pénznem | `confidence_bar` | kapcsolt számla | dátum

**Szűrők**: linkelt / nem linkelt | confidence küszöb

---

### 5–6. Szállítók (`GET /ui/suppliers`, `GET /ui/suppliers/{id}`)

**Lista DataTable**: név | adószám | számlák száma | fizetetlen | Wise tranzakciók | utolsó számla dátuma

**Részlet**: adatok + számlák DataTable + Wise tranzakciók DataTable

---

### 7–8. Vevők (`GET /ui/customers`, `GET /ui/customers/{id}`)

Ugyanolyan struktúra mint a Szállítóknál, `customer` táblával.

---

### 9. Wise Tranzakciók (`GET /ui/transactions`)

**DataTable oszlopok**: tranzakció ID | dátum | összeg + pénznem | leírás | referencia | partner | kapcsolt számla

**Szűrők** (`TransactionFilters` Pydantic schema):
- `date_from` / `date_to`
- `linked` (van / nincs kapcsolt számla / mind)
- `partner_name` (text)
- `amount_min` / `amount_max`

---

### 10. Sync (`GET /ui/sync`, `POST /ui/sync/trigger`)

```html
<form hx-post="/ui/sync/trigger"
      hx-target="#sync-result"
      hx-indicator="#sync-spinner"
      hx-swap="innerHTML"
      hx-disabled-elt="find button[type=submit]">
  <!-- date_from, date_to, sync_mode radio -->
  <button type="submit" class="btn btn-primary">Sync indítása</button>
</form>

<div id="sync-spinner" class="htmx-indicator my-3">
  <div class="spinner-border text-primary" role="status"></div>
  <span class="ms-2">Szinkronizálás folyamatban...</span>
</div>

<div id="sync-result"></div>
```

`hx-disabled-elt="find button[type=submit]"` — a gomb le van tiltva amíg a kérés fut, dupla kattintás ellen.

**Eredmény partial** (`partials/sync_result.html`): státusz badge, invoice_count, wise_transaction_count, hibák listája, időtartam. OOB swappal frissíti a sidebar számláló badge-et.

**Sync napló** (Bootstrap accordion): utolsó 10 futás — ehhez `sync_log` tábla szükséges az invoice-core DB-ben (id, started_at, finished_at, mode, invoice_count, wise_count, error_count).

---

## Formázási konvenciók

- **Összeg**: `{:,.0f} HUF` — ezres elválasztóval, `amount_fmt` makróval
- **Dátum**: `YYYY-MM-DD` (ISO)
- **Confidence**: `confidence_bar` makró — zöld >0.8, sárga 0.5–0.8, piros <0.5
- **Státusz badge**: `payment_badge` makró — PAID=`bg-success`, UNPAID=`bg-danger`, PARTIAL=`bg-warning text-dark`

---

## Implementációs sorrend

1. `services/` réteg — `dashboard_service`, `invoice_service`, `partner_service`, `transaction_service`, `invoice_file_service`
2. `base.html` + `_macros.html` + `_sidebar.html` (CDN-ek, `hx-boost`, globális spinner)
3. Dashboard (KPI kártyák, legutóbbi listák)
4. Számlák lista — szűrők HTMX debounce-szal, DataTables + `htmx:afterSwap` reinit
5. Számla részlet oldal
6. Wise tranzakciók lista
7. Szállítók + Vevők lista és részlet
8. PDF Fájlok lista
9. Sync oldal — form, spinner, OOB swap, sync_log tábla

---

## Kapcsolódások

### Wiki linkek
- **Prompt**: [[invoice-core-ui-prompt.md|Invoice-Core UI Prompt]]
- **Backend Spec**: [[invoice-core-spec.md|Invoice-Core Spec]]
- **Backend Prompt**: [[invoice-core-prompt.md|Invoice-Core Prompt]]
- **Wise adatok**: [[wise-spec.md|Wise Spec]]
- **PDF adatok**: [[invoice-file-filter-spec.md|Invoice-File-Filter Spec]]
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]
