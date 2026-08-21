---
title: "Specifikáció: Invoice-Core Felhasználói Felület"
description: "HTMX/Jinja2/Bootstrap/DataTables alapú könyvelési áttekintő felület — shared service layer architektúrával"
language: "HU"
last_updated: "2026-08-09"
related: [invoice-core-ui-prompt.md, invoice-core-spec.md, vision-spec.md, invoice-file-filter-spec.md]
---

# Invoice-Core Felhasználói Felület — Specifikáció

> ✅ **Aktuális állapot (2026-08-09)**: Az invoice-core UI a [[vision-spec.md|vision]] (port 8009) szervizben fut. Az invoice-core tiszta JSON REST backend (port 8004) — nem kezel Jinja2 sablonokat, statikus fájlokat vagy `/ui/` routert. Ez a spec a **jelenlegi** UI-t dokumentálja: a vision `src/vision/ui/` routerei (`invoice_router.py`, `uploader_router.py`, `controlling_router.py`, `admin_router.py`) a `clients/invoice_core.py` REST kliensen keresztül fogyasztják az invoice-core API-t. Az egyes szervizek belső felépítését a [[vision-spec.md|Vision Spec]] és az [[invoice-core-spec.md|Invoice-Core Spec]] írja le.

> 🔗 **Kapcsolódás**: [[invoice-core-spec.md|Invoice-Core Spec]] | [[vision-spec.md|Vision Frontend Spec]]

---

## Szerepkör és kontextus

Te egy Full-Stack Python Fejlesztő vagy. A feladatod egy könyvelési áttekintő webes felhasználói felület elkészítése és karbantartása a **vision** FastAPI szervizben, amely az `invoice-core` REST API-ját (port 8004) fogyasztja. A felület **szerver-oldali renderelésű** (SSR): Jinja2 sablonok + HTMX + Bootstrap + DataTables. Külön frontend framework (React, Vue, stb.) nem szükséges.

A cél: a könyvelő (és a cégvezető) egy böngészőből áttekinthesse a számlák, PDF fájlok, szállítók, vevők és banki tranzakciók teljes képét, és lekérhesse az összefüggéseket közöttük — kiegészítve a controlling (projektek, timesheet, riportok) és admin (felhasználók, audit, tevékenység típusok) funkciókkal.

---

## Tech Stack

| Réteg | Technológia | Megjegyzés |
|---|---|---|
| Sablonmotor | Jinja2 | FastAPI `Jinja2Templates` |
| Dinamikus frissítés | HTMX 2.x | CDN-ből |
| CSS keretrendszer | Bootstrap 5.3 (Bootswatch Yeti) | CDN-ből, sötét/világos téma váltással (`data-bs-theme`) |
| Táblázat | DataTables 2.0.8 | Bootstrap 5 integration + Buttons (Excel/PDF/Print) + Responsive, CDN-ből |
| Diagramok | Chart.js 4.4.3 | CDN-ből (dashboard) |
| Ikonok | Bootstrap Icons + Font Awesome | CDN-ből |
| Segédkönyvtárak | jQuery 3.7.1, pdfmake, JSZip | DataTables export pluginokhoz |
| Backend | FastAPI (vision szerviz) | `/ui/` routerek, invoice-core REST :8004 |

**Nincs külön build lépés** — minden CSS/JS CDN-ről töltődik.

---

## Architektúra

A vision UI routerei **nem** lekérdeznek közvetlenül SQLAlchemy-n keresztül. Minden adathoz a `clients/invoice_core.py`-ban lévő `InvoiceCoreClient` REST kliensen keresztül jutnak (HTTP az invoice-core :8004 felé). A `dict_to_ns()` segédfüggvény a REST JSON válaszokat `SimpleNamespace` objektumokká alakítja, így a sablonok attribútum-eléréssel (`row.name`) dolgozhatnak.

**Miért?** Az invoice-core felelős az adatkezelésért és az üzleti logikáért; a UI csak megjelenít. Ha a UI-t később más technológiára (React, mobil app) kell átírni, az invoice-core REST végpontjai változatlanok maradnak. Nincs üzleti logika duplikáció a UI rétegben.

```
vision/src/vision/
├── api/
│   └── main.py                       ← FastAPI app, auth middleware (JWT), routerek beépítése
├── ui/
│   ├── router.py                     ← `/`, `/pitch`, `/login`, `/logout`, `/stop-impersonation`
│   ├── invoice_router.py             ← `/ui/*` — dashboard, számlák, PDF fájlok, partnerek, bank, osztalék, adók, sync, pickerek
│   ├── uploader_router.py            ← `/ui/upload*` — bankkivonat CSV feltöltés
│   ├── controlling_router.py         ← `/ui/controlling/*` — projektek, timesheet, riportok
│   ├── admin_router.py               ← `/ui/admin/*` — felhasználók, audit, tevékenység típusok
│   └── utils.py                      ← `dict_to_ns()`, `local_today()`
├── clients/
│   ├── invoice_core.py               ← InvoiceCoreClient → invoice-core REST :8004
│   ├── uploader.py                   ← UploaderClient → uploader REST :8006
│   └── srcprofit.py                  ← SrcProfit külső API
├── templates/
│   ├── base.html                     ← layout, CDN-ek, hx-boost, téma váltó
│   ├── _navbar.html                  ← felső navbar (felhasználó, impersonation badge, kijelentkezés)
│   ├── _sidebar.html                 ← oldalsáv navigáció (Pénzügy / Partnerek / Controlling / Admin)
│   ├── _macros.html                  ← Jinja2 makrók (badge, progress bar, stb.)
│   ├── login.html, pitch.html        ← belépés, bemutató oldal
│   ├── ui_dashboard.html             ← dashboard (KPI, timesheet, diagramok)
│   ├── invoices.html                 ← számla lista + tranzakció offcanvas
│   ├── invoice_detail.html           ← számla részlet
│   ├── invoice_files.html            ← PDF fájl lista
│   ├── suppliers.html / supplier_detail.html
│   ├── customers.html / customer_detail.html
│   ├── transactions.html             ← bank tranzakció lista
│   ├── dividend.html                 ← osztalékelőleg számítás
│   ├── adok.html                     ← adók (havi bontás + becslés)
│   ├── sync.html                     ← szinkronizálás
│   ├── upload.html                   ← bankkivonat feltöltés
│   ├── controlling_projects.html / controlling_timesheet.html / controlling_reports.html
│   ├── admin_users.html / admin_audit.html / admin_activity_types.html
│   └── partials/                     ← HTMX partial válaszok
│       ├── invoice_table.html, invoice_file_table.html, supplier_table.html, transaction_table.html
│       ├── transaction_detail.html, invoice_detail_modal.html
│       ├── sync_result.html, pending_sync_card.html
│       ├── picker_invoice_files.html, picker_invoices.html, picker_transactions.html, picker_partners.html
│       ├── timesheet_content.html, timesheet_form_error.html
│       └── upload_files.html
└── static/
    └── custom.css
```

### REST kliens réteg

```python
# ui/invoice_router.py
@router.get("/invoices")
def invoices_page(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    payment_status: str | None = None,
    has_pdf: str | None = None,
    supplier_name: str | None = None,
):
    client = _client()  # InvoiceCoreClient()
    rows = dict_to_ns(client.get_invoices(...))
    is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "partials/invoice_table.html" if is_partial else "invoices.html"
    return _resp(request, template, client, rows=rows)
```

Minden router-helper a `_resp(request, template, client, **kwargs)` függvényen keresztül renderel, így a partial/full-oldal váltás egy helyen van kezelve.

---

## HTMX Best Practices

### 1. Teljes oldal vs. partial válasz

Minden lista végpont megvizsgálja az `HX-Request` fejlécet, de **kizárja** az `HX-Boosted` kéréseket: ha HTMX kérés, csak a partial template-et adja vissza; ha normál navigáció vagy hx-boosted navigáció, a teljes oldalt (`extends "base.html"`).

```python
is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
template = "partials/invoice_table.html" if is_partial else "invoices.html"
```

### 2. Formok — `hx-push-url` és célzott swap

A számla részlet oldal formjai (`note`, `fizetve`, link/unlink műveletek) a `body`-t cserélik `hx-push-url="true"`-val, így az URL és a tartalom szinkronban marad:

```html
<!-- invoice_detail.html -->
<form hx-post="/ui/invoices/{{ invoice.id }}/note" hx-target="body" hx-push-url="true" class="m-0">
  <textarea name="note" class="form-control form-control-sm font-monospace" rows="3">{{ invoice.note or '' }}</textarea>
</form>
```

### 3. Navigáció — `hx-boost`

A `base.html`-ben `hx-boost="true"` az egész `<body>`-ra: a belső linkek HTMX AJAX kérésként viselkednek (csak a `<body>` tartalma cserélődik). A kritikus linkek (`/login`, `/logout`, `/stop-impersonation`, feltöltés letöltés linkek) `hx-boost="false"`-t kapnak, mert teljes navigációt igényelnek. Fontos: a könyvtárak a `<head>`-ben töltődnek, hogy hx-boost swap után **ne** futjanak újra (duplikált Bootstrap data-api handler-ek elkerülése).

```html
<!-- base.html -->
<body hx-boost="true">
  ...
</body>
```

### 4. Loading indicator — `htmx-indicator`

Minden HTMX kéréshez globális spinner a navbarban:

```html
<!-- _navbar.html -->
<div id="global-spinner" class="htmx-indicator">
  <div class="spinner-border spinner-border-sm" role="status">
    <span class="visually-hidden">Betöltés...</span>
  </div>
</div>
```

A form gombok `hx-disabled-elt="find button[type=submit]"`-tel le vannak tiltva futás közben (dupla kattintás ellen).

### 5. OOB swap — függőben lévő párosítás kártya

A sync eredmény válasza Out-of-Band (OOB) cserével frissíti a `#pending-sync-card`-ot ugyanabban a válaszban:

```html
<!-- partials/sync_result.html -->
<div id="sync-result">
  <!-- sync eredmény tartalom -->
</div>
<!-- OOB swap: frissíti a függőben lévő partner-párosítás kártyát -->
<div id="pending-sync-card" hx-swap-oob="true">
  {% include "partials/pending_sync_card.html" %}
</div>
```

### 6. Form siker — `HX-Redirect`

A timesheet create/update formok siker esetén `204` + `HX-Redirect` fejlécet adnak vissza ahelyett, hogy a választ swap-elnék: a DataTables Responsive kiterjesztés megbízhatatlanul inicializálódik újra swap után (eltűnnek a "dtr-inline collapsed" osztályok), ezért teljes oldalbetöltésre kényszerítik a böngészőt. Validációs hibánál viszont in-place re-render megy (`partials/timesheet_form_error.html` a modal saját hiba slotjába).

---

## Jinja2 Best Practices

### Template öröklés

Minden oldal a `base.html`-t terjeszti ki, és a `{% block %}` rendszert használja: `title`, `breadcrumb`, `content`, `scripts`.

```html
<!-- base.html -->
<!DOCTYPE html>
<html lang="hu" data-bs-theme="...">
<head>
  <title>{% block title %}Vision{% endblock %}</title>
  <!-- Bootstrap (Yeti), HTMX, DataTables, Chart.js CDN -->
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
  {% block scripts %}{% endblock %}
</body>
</html>
```

### Makrók (`_macros.html`)

Újrafelhasználható UI elemek makróként:

| Makró | Cél |
|---|---|
| `amount_fmt(value, currency)` | Összeg formázás ezres elválasztóval |
| `status_badge(status)` | Általános státusz badge |
| `payment_badge(status)` | Fizetési státusz (PAID/UNPAID/PARTIAL) |
| `confidence_bar(value)` | Confidence progress bar (PDF felismerés) |
| `pdf_icon(has_pdf)` | PDF jelenlét ikon |
| `bank_icon(count)` | Bank tranzakciók száma ikon |
| `direction_badge(direction)` | Számla/tranzakció irány (INBOUND/OUTBOUND, CREDIT/DEBIT) |

### Partial templates (HTMX válaszokhoz)

A `partials/` alkönyvtárban lévő sablonok **nem** terjesztik ki a `base.html`-t — csak a táblázat/eredmény HTML-jét tartalmazzák. A főoldal `{% include %}`-kal beágyazza őket az első betöltéskor; HTMX kéréskor a végpont közvetlenül ezeket adja vissza.

---

## Bootstrap 5 Best Practices

### Layout

- Sidebar + fő tartalom: offcanvas-lg sidebar + `flex-grow-1` main
- Kártyák: `card` + `card-body`, `shadow-sm`
- Responsive: `col-12 col-md-6` a részlet oldalakon, KPI kártyák `row-cols-*` gridben

### Téma váltás

A `base.html` fejlécében futó script a `localStorage('mp-theme')` alapján állítja be a `data-bs-theme` attribútumot (`dark`/`light`), a navbar gombja váltja. A Bootstrap 5.3 natív dark mode-ot használja a Bootswatch Yeti témával.

### DataTables konfiguráció

DataTables szerver-oldali rendezés/lapozás **nélkül** (az adatmennyiség belefér kliensoldali feldolgozásba), Responsive + Buttons (Excel/PDF/Print) kiterjesztéssel:

```html
<table id="invoice-table" class="table table-hover table-sm nowrap" style="width:100%">
  ...
</table>

<script>
  (function() {
    if ($.fn.DataTable && $.fn.DataTable.isDataTable("#invoice-table")) {
      $("#invoice-table").DataTable().destroy();
    }
    const dt = new DataTable("#invoice-table", {
      language: { url: "https://cdn.datatables.net/plug-ins/2.0.8/i18n/hu.json", emptyTable: "Nincs találat" },
      pageLength: 15,
      lengthMenu: [10, 15, 25, 50, 100],
      order: [[2, "desc"]],          // dátum szerint csökkenő
      responsive: true,
      autoWidth: false,
      columnDefs: [
        { targets: [5, 6, 7], className: "text-end" },   // összeg oszlopok jobbra
        { targets: [8, 9], orderable: false },           // PDF/Bank ikon oszlopok
      ],
    });
  })();
</script>
```

**HTMX + DataTables együttélés**: ha HTMX cseréli a táblázatot, a DataTables-t előbb `destroy()`-olni kell, majd újra inicializálni — minden tábla script IIFE-ben fut, és `isDataTable()` ellenőrzéssel kezdi, mert hx-boost esetén a `{% block scripts %}` újra fut minden body swap után.

---

## Oldalak

### 1. Dashboard (`GET /ui/`)

**KPI kártyák** (`kpis` — invoice-core dashboard végpontja):
- Összes számla (db) + kapcsolt PDF-ek száma
- Fizetetlen számlák (db + összeg HUF)
- Bank tranzakciók (db, elmúlt 30 nap)
- Partnerek (szállítók + vevők db)

**Timesheet szekció**:
- **Timesheet összesítő** — Chart.js diagram, napi/havi/éves váltóval (a teljes céges óraszám projekt-bontásban)
- **Legutóbbi timesheet bejegyzések** — utolsó 8 rekord: dátum | felhasználó | projekt | ügyfél | tevékenység | óra

**Bevétel vs Kiadás** — Chart.js diagram (utolsó 3/6/12 hónap), a `monthly_finance` adatokból.

**Top szállítók / Top vevők** — progress group kártyák (top 3 partner részesedéssel), linkek a partner listákra.

**Legutóbbi tranzakciók** — dátum | partner | típus (Jóváírás/Terhelés badge) | összeg (+/−) | kapcsolt számla link.

**Legutóbbi számlák** — legutóbbi 5: számlaszám | dátum | szállító | bruttó | státusz badge.

**Sync indítása** gomb → `/ui/sync`.

---

### 2. Számlák (`GET /ui/invoices`)

**Összesítő metrikák** (kliensoldalon számolva a DataTable soraiból): Számlák (db) | Bejövő | Kimenő | Fizetetlen — devizánként összesítve.

**DataTable oszlopok**:
| Mező | Forrás | Megjegyzés |
|---|---|---|
| Státusz | `invoice.payment_status` | `payment_badge` makró |
| Számlaszám | `invoice.invoice_number` | Link → `/ui/invoices/{id}`; zárolt mezőknél lakat ikon |
| Dátum | `invoice.invoice_date` | |
| Szállító | `supplier.name` | Link → `/ui/suppliers/{id}` |
| Vevő | `customer.name` | Link → `/ui/customers/{id}` |
| Nettó | `invoice.amount_net` | `amount_fmt` makró |
| ÁFA | `invoice.amount_vat` | |
| Bruttó | `invoice.amount_total` | |
| PDF | `invoice.invoice_file_id` | `pdf_icon` makró, hover preview |
| Bank | tranzakció count | ikon + db, offcanvas részlet |
| Irány | `invoice.direction` | `direction_badge` makró (INBOUND/OUTBOUND) |

**Zárolás jelzések**: a sorokon lakat ikon jelenik meg, ha `payment_status_locked` (manuálisan fizetve jelölve), `invoice_file_locked` (manuálisan kapcsolt PDF) vagy `has_manual_bank_link` (manuális bank kapcsolat).

**Szűrők** (URL query paraméterek, megosztható/könyvjelzőzhető linkekhez):
- `date_from` / `date_to`
- `payment_status` (PAID / UNPAID / PARTIAL)
- `has_pdf` (yes/no)
- `supplier_name` (text)

---

### 3. Számla Részletek (`GET /ui/invoices/{id}`, `GET /ui/invoices/{id}/modal`)

**Számla adatok kártya**: számlaszám, dátum, deviza, NAV művelet/típus/beérkezés, fizetési mód és határidő, státusz badge, irány, teljesítés dátuma, árfolyam, megjelenés.

**Fizetve jelölés**: a státusz melletti gomb `POST /ui/invoices/{id}/fizetve` — `locked=true` (PAID + `payment_status_locked`) vagy `locked=false` (zár feloldása).

**Szállító / Vevő kártyák** (linkekkel):
- Ha van kapcsolt partner: név + adószám + cím + bankszámla, leválasztás gomb (`POST /ui/invoices/{id}/supplier|customer/unlink`)
- Ha nincs: `Szállító/Vevő kapcsolása` gomb → **picker modal** (`GET /ui/picker/partners?kind=supplier|customer&invoice_id={id}`)
- NAV partner snapshotból előtöltött **új partner létrehozás és kapcsolás** form (`POST /ui/invoices/{id}/supplier|customer/create-and-link`)

**Tételek** táblázat (NAV enrichment) és **Áfa összesítő**.

**Megjegyzés** kártya: szabad szöveges `note` form (`POST /ui/invoices/{id}/note`).

**Kapcsolt PDF** kártya: fájlnév link (`/ui/invoice-files/{id}/pdf` új fülre), `Manuális` badge ha `invoice_file_locked`, leválasztás gomb, vagy `PDF kapcsolása` → picker (`GET /ui/picker/invoice-files?source_type=invoice&source_id={id}`).

**Bank tranzakciók** kártyák: minden kapcsolt tranzakcióhoz alapadatok (dátum, összeg, irány, egyenleg, leírás, referencia, típus, kategória) és partner adatok (név, számlaszám, IBAN, bankkód, cím) + leválasztás; `Tranzakció kapcsolása` gomb → picker (`GET /ui/picker/transactions?invoice_id={id}`).

**Modal nézet**: `GET /ui/invoices/{id}/modal` a `partials/invoice_detail_modal.html`-t adja vissza (kompakt összefoglaló a listákról nyitható gyorsnézethez).

---

### 4. PDF Fájlok (`GET /ui/invoice-files`, `GET /ui/invoice-files/{id}/pdf`, `DELETE /ui/invoice-files/{id}/delete`)

**DataTable oszlopok**: Fájlnév (hover preview) | Méret (KB) | Kapcsolt számla | Szállító | Összeg | Bank tranzakció | Szöveg (OCR) | Művelet (törlés).

**Szűrők**: `linked` (yes/no) query paraméter.

**PDF letöltés**: `/ui/invoice-files/{id}/pdf` — a vision proxyn keresztül adja vissza az invoice-core PDF-et (content-disposition továbbítással).

**Törlés**: `DELETE /ui/invoice-files/{id}/delete` HTMX kérés — a táblázat partial újrarenderelve.

---

### 5–6. Szállítók (`GET /ui/suppliers`, `POST /ui/suppliers`, `GET /ui/suppliers/{id}`, `POST /ui/suppliers/{id}`, `DELETE /ui/suppliers/{id}/delete`)

**Lista DataTable**: Név | Adószám | Számlák (db) | Fizetetlen (db) | Számla összeg | Bank (db) | Bank összeg | Utolsó számla.

**Új szállító modal** (`POST /ui/suppliers`): név, adószám, cím, email, telefon, IBAN, BBAN.

**Részlet** (`GET /ui/suppliers/{id}`):
- Adatok: név, adószám, cím, email, telefon, IBAN, BBAN, **Ismert bankszámlák** (`bank_accounts`), **Ismert nevek** (`known_names`)
- Módosítás modal (`POST /ui/suppliers/{id}`)
- Törlés (`DELETE /ui/suppliers/{id}/delete`) — letiltva, ha van kapcsolt számla/tranzakció
- Számlák DataTable + bank tranzakciók (offcanvas részlettel)

---

### 7–8. Vevők (`GET /ui/customers`, `POST /ui/customers`, `GET /ui/customers/{id}`, `POST /ui/customers/{id}`, `DELETE /ui/customers/{id}/delete`)

Ugyanolyan struktúra mint a Szállítóknál, `customer` táblával (fizetési határidő napokban + Ismert bankszámlák/nevek mezőkkel kiegészítve).

---

### 9. Bank tranzakciók (`GET /ui/transactions`, `GET /ui/transactions/{id}`)

**Egyenleg összesítő**: a `bank_balances` adatokból számolt teljes egyenleg.

**DataTable oszlopok**: Tranzakció ID | Dátum | Összeg | D/C | Kapcsolt számla | Partner | PDF | Referencia | Leírás.

A **partner oszlop** a tranzakció iránya szerint linkel: DEBIT → kapcsolt szállító, CREDIT → kapcsolt vevő; ha nincs partner, jelzi.

**Részlet**: `GET /ui/transactions/{id}` a `partials/transaction_detail.html`-t adja vissza a `#txOffcanvas` offcanvasba (HTMX AJAX-szal).

**Szűrők** (URL query paraméterek): `date_from` / `date_to`, `linked` (van/nincs kapcsolt számla), `partner_name`, `amount_min` / `amount_max`.

**Link/leválasztás műveletek** (HTMX formok):
- `POST /ui/transactions/{txn_id}/invoice-file/link|unlink`
- `POST /ui/transactions/{txn_id}/supplier|customer/link|unlink` és `create-and-link`
- `POST /ui/transactions/{txn_id}/invoices/{invoice_id}/link|unlink`

---

### 10. Osztalék (`GET /ui/dividend`)

Év választó formmal. **KPI kártyák**: Bevétel (kimenő számlák), Kiadás (bejövő számlák), Bruttó nyereség (TAO és HIPA kulcsokkal), Kivehető osztalékelőleg (nettó nyereség).

**Számítási táblázat**: Bevétel − Kiadás → Bruttó nyereség → TAO (bevétel alapú) → HIPA → **Kivehető osztalékelőleg (nettó nyereség)**.

**Nettó felvehető** kártyák: SZOCHO nélkül (SZJA levonással) és SZOCHO levonással.

---

### 11. Adók (`GET /ui/adok`)

Év választó formmal. **KPI kártyák** típusonként: NAV ÁFA, NAV Bírság, NAV SZJA, NAV Szochó, NAV TAO, NAV TB, HIPA, HIPA-Késedelmi, Iparkamara.

**Havi bontás** táblázat: hónap × adótípus pivot, típusonkénti és havi összesítőkkel.

**Becsült adók** táblázat (`tax_estimate` végpont): a hátralévő hónapokra becsült TAO/KIVA, HIPA, SZJA, SZOCHÓ — a ténylegesen befizetett hónapokat kihagyva, becsült bruttó bevétellel.

---

### 12. Sync (`GET /ui/sync`, `POST /ui/sync/trigger`)

**Függőben lévő párosítás kártya** (`partials/pending_sync_card.html`): hány számla/tranzakció vár még szállítóra/vevőre, az utolsó futástól függetlenül — linkekkel a Számlák / Bank oldalakra.

**Sync indítása form** (`hx-post="/ui/sync/trigger"`):
- `date_from` / `date_to` (date input)
- `sync_mode` radio: `full` (NAV + PDF + Bank + összekapcsolás), `nav_only`, `pdf_only`, `bank_only` (Erste + Wise CSV), `match_only`

**Eredmény partial** (`partials/sync_result.html`): NAV számla | PDF fájl | Bank tranzakció | PDF összekapcsolva számlálók, hibák/figyelmeztetések listája, időtartam. OOB swappal frissíti a függőben lévő párosítás kártyát.

**Sync napló** (Bootstrap accordion): utolsó futások — indítás ideje, mód badge, invoice/bank számlálók, hibák/figyelmeztetések száma, időtartam, befejezés ideje.

---

### 13. Feltöltés (`GET /ui/upload`, `POST /ui/upload/do`, `GET /ui/upload/files`, `GET /ui/upload/files/{bank}/{filename}/download`, `DELETE /ui/upload/files/{bank}/{filename}`)

**Bankkivonat CSV feltöltés** (Erste netbank): fájl kiválasztás, automatikus bank felismerés (kézi felülbírálással), `overwrite` opció létező fájl felülírásához.

**Eredmény**: HTMX partial a `#upload-result`-ba (feltöltve/felülírva + fájlnév, bank, méret), majd a fájllista automatikus frissítése (`hx-get="/ui/upload/files"`).

**Tárolt fájlok táblázat** (`partials/upload_files.html`): bank badge | fájlnév (letöltés link) | méret | dátum | törlés gomb (`hx-delete`).

---

### 14. Controlling — Projektek (`GET /ui/controlling/projects`, `POST /ui/controlling/projects`, `POST /ui/controlling/projects/{id}`, `DELETE /ui/controlling/projects/{id}`)

**Lista DataTable**: Project kód | Ügyfél | Project gazda | Típus badge (ÖTLET / SZÁMLÁZHATÓ / PreSales) | Kezdés dátuma | Státusz badge (Open/Closed) | Összesített óra | Művelet (módosítás/megtekintés/törlés).

**Projekt CRUD modalok** (létrehozás/módosítás/megtekintés):
- Ügyfél (customer FK, datalist keresővel)
- Azonosító / rövid név (`short_name`) — a project kód része
- Project gazda (owner)
- Státusz (OPEN / CLOSED)
- **Kezdés dátuma** (`start_date`, kötelező)
- **Típus** (`project_type`: OTLET / SZAMLAZHATO / PRESALES, kötelező)
- Sorszám (ügyfelenként növekvő, automatikus) + Project kód (előnézet, `{ügyfél} - {sorszám:03d} - {short_name}`)
- **Rögzítésre jogosultak** (`permitted_users` checkbox lista) — csak ők adhatnak timesheet rekordot a projekthez

A `project_week` szerver-számított (calendar week, az első rögzített bejegyzéshez horgonyozva) — nincs tárolva.

---

### 15. Controlling — Timesheet (`GET /ui/controlling/timesheet`, `POST /ui/controlling/timesheet`, `POST /ui/controlling/timesheet/{entry_id}`, `DELETE /ui/controlling/timesheet/{entry_id}`)

**Projekt szűrő** (`project_scope`): `permitted` (amelyikhez a felhasználó jogosult), `my` (saját rekordok), `all` — gombcsoporttal, hx-boost kikapcsolva (teljes navigáció).

**DataTable oszlopok**: Dátum | Felhasználó | Projekt | Hét (W#) | Tevékenység | Leírás | Résztvevők | Óra | Művelet (módosítás/törlés modalokkal).

**Új rekord modal** (és módosítás): Dátum (validálva — nem lehet jövőbeli, hétvégi stb.), Projekt (csak aktív + jogosult), Tevékenység típus (aktív típusok), Óra (0,5 órás lépések), Résztvevők, Leírás.

**Validáció**: hibák a modal saját hiba slotjába renderelődnek (`partials/timesheet_form_error.html`), siker esetén `HX-Redirect` a listára. A `timesheet_content.html` partial a táblázatot + modalokat tartalmazza.

---

### 16. Controlling — Riportok (`GET /ui/controlling/reports`)

**Riport típusok**: Projekt riport (heti + kumulált, tevékenység típusonkénti bontás, futó összeg) | Személy riport | Ügyfél riport | Tevékenység típus riport (soronkénti listák + Összesítés kártya pivot oszlopokkal).

**Szűrők**: `report_type`, `date_range` (projekt kezdete óta / aktuális hónap / aktuális hét / egyéni `date_from`–`date_to`), **ügyfél és projekt összekapcsolt szűrők** (a projekt választó csak az adott ügyfél projektjeit kínálja, `data-customer-id` alapján), `user_id`, tevékenység típus.

**Export** (DataTables Buttons): Excel / PDF / Nyomtatás — a ténylegesen szűrt/rendezett táblát exportálja; a nem-projekt riportoknál az Összesítés szekció is belekerül (`customizeData` a DOM-ból), a PDF egyedi stílust kap (`stylePdf` — márkaszín fejléc, zebra-csíkozás, összesítő sorok kiemelése, oldalszámos lábléc; hiba esetén try/catch-csel stílus nélküli PDF).

---

### 17. Admin — Felhasználók (`GET /ui/admin/users`, `POST /ui/admin/users/impersonate`)

**Felhasználó lista** (auth szerviz login rekordjai): kép | név | email | provider | utolsó belépés | regisztráció.

**Megszemélyesítés** (admin): minden sor mellett `Belépés ekként` gomb → `POST /ui/admin/users/impersonate` az auth szerviz `/auth/impersonate` végpontját proxyzza, és az új access token cookie-t állít be. A navbar sárga badge jelzi: `Megszemélyesítve — admin: {email}`, és `Vissza a saját fiókomba` gomb (`GET /stop-impersonation`) állítja vissza az admin identitást (a refresh cookie végig az adminé marad).

---

### 18. Admin — Audit napló (`GET /ui/admin/audit`)

**DataTable oszlopok**: Időpont | Felhasználó (impersonator jelzéssel) | Menü (page) | Rekord | Gomb (action badge: create/delete/update + label) | Részletek (method + path + **changes** — módosított mezők listája).

Minden jelentős UI művelet (linkelés, leválasztás, fizetve jelölés, partner létrehozás, stb.) audit rekordot ír `record`/`label`/`changes` mezőkkel, így visszakövethető ki mit és mikor változtatott.

---

### 19. Admin — Tevékenység típusok (`GET /ui/admin/activity-types`, `POST /ui/admin/activity-types`, `POST /ui/admin/activity-types/{id}`, `POST /ui/admin/activity-types/{id}/deactivate`, `DELETE /ui/admin/activity-types/{id}/delete`)

CRUD törzsadat a timesheet funkcióhoz: létrehozás/módosítás modal, inaktiválás (ha már használatban van), törlés (csak ha a használati szám 0).

---

### 20. Bejelentkezés (`GET /login`, `/logout`, `/stop-impersonation`)

**Login oldal** (`login.html`): provider-alapú belépés (Google OAuth az auth szervizen keresztül), `next` paraméter támogatással. Token nélkül elérhető végpontok: `/`, `/pitch`, `/login`, `/logout`, `/health`, `/static/*` — minden más érvényes JWT-t igényel.

**Kijelentkezés** (`/logout`): refresh token visszavonása az auth szerviznél + cookie törlés, majd átirányítás `/login`-ra.

**Kezdőlap** (`/`): standalone pitch/bemutató oldal (`pitch.html`, sötét téma, nem terjeszti ki a base.html-t); `/pitch` 308-assal erre irányít.

---

## Formázási konvenciók

- **Összeg**: `{:,.0f} HUF` — ezres elválasztóval, `amount_fmt` makróval (deviza paraméterrel)
- **Dátum**: `YYYY-MM-DD` (ISO)
- **Confidence**: `confidence_bar` makró — zöld >0.8, sárga 0.5–0.8, piros <0.5
- **Státusz badge**: `payment_badge` makró — PAID=`bg-success`, UNPAID=`bg-danger`, PARTIAL=`bg-warning text-dark`
- **Irány badge**: `direction_badge` — INBOUND/CREDIT pozitív, OUTBOUND/DEBIT negatív színnel
- **Zárolás**: lakat ikon a manuálisan zárolt mezőknél (`payment_status_locked`, `invoice_file_locked`, manuális bank link)

---

## Implementációs sorrend

1. `clients/invoice_core.py` — REST kliens réteg az invoice-core API-hoz (`InvoiceCoreClient`)
2. `base.html` + `_macros.html` + `_navbar.html` + `_sidebar.html` (CDN-ek, `hx-boost`, globális spinner, téma váltó)
3. Dashboard (KPI kártyák, diagramok, timesheet szekció, legutóbbi listák)
4. Számlák lista + részlet (DataTables, HTMX formok, picker modalok, link/unlink)
5. PDF fájlok lista + letöltés + törlés
6. Szállítók + Vevők lista és részlet (CRUD modalok, törlés védelem)
7. Bank tranzakciók lista + részlet offcanvas + linkelés
8. Osztalék + Adók riport oldalak
9. Sync oldal — form, spinner, OOB swap, sync napló, függőben lévő párosítás kártya
10. Feltöltés oldal (uploader szerviz kliens)
11. Controlling — projektek CRUD, timesheet CRUD (validációval), riportok exporttal
12. Admin — felhasználók (impersonation), audit napló, tevékenység típusok
13. Login/logout, JWT auth middleware, public path lista

---

## Kapcsolódások

### Wiki linkek
- **Prompt**: [[invoice-core-ui-prompt.md|Invoice-Core UI Prompt]]
- **Backend Spec**: [[invoice-core-spec.md|Invoice-Core Spec]]
- **Backend Prompt**: [[invoice-core-prompt.md|Invoice-Core Prompt]]
- **Vision Spec**: [[vision-spec.md|Vision Frontend Spec]]
- **Wise adatok**: [[wise-spec.md|Wise Spec]]
- **PDF adatok**: [[invoice-file-filter-spec.md|Invoice-File-Filter Spec]]
- **Projekt Index**: [[INDEX.md|Tiro Index]]
