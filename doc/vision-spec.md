---
title: "Specifikáció: Vision – Frontend"
description: "Teljes Moneypenny webes frontend — invoice-core REST API fogyasztása, SSR UI + tulajdonosi portfólió dashboard"
type: "service-spec"
status: "megvalósítva"
port: 8009
language: "HU"
last_updated: "2026-08-09"
depends_on: [invoice-core-spec.md, auth-service-spec.md, uploader-spec.md, srcprofit]
related: [INDEX.md, vision-prompt.md, invoice-core-spec.md]
tags: [vision, frontend, fastapi, jinja2, htmx, bootstrap, datatables]
---

# Vision – Frontend — Specifikáció

> 🔗 **Adatforrások**: [[invoice-core-spec.md|Invoice-Core]] (port 8004) REST API + [[auth-service-spec.md|Auth Service]] (port 8007, JWT) + [[uploader-spec.md|Uploader]] (port 8006, bankkivonat fájlok) + [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR, külső)

---

## Szerepkör és kontextus

A Vision a Moneypenny rendszer **teljes webes frontendja**. Az `invoice-core` (8004) **tiszta JSON REST backend** — saját UI-t nem szolgáltat. A Vision fogyasztja az invoice-core REST API végpontjait, és SSR Jinja2 sablonokkal kiszolgálja a Moneypenny UI oldalait (`/ui/*`): dashboard, számlák, partnerek, bank, adók, sync, controlling (projektek/timesheet/riportok), admin (felhasználók/tevékenység típusok/audit) és fájlfeltöltés.

Emellett a Vision felel az **autentikációért is**: minden `/ui/*` oldal a központi auth szerviz (8007) RS256 JWT-jét igényli (HttpOnly cookie vagy Bearer fejléc), a belépés provider-alapú (`/login`). A JWT-t kérésenként lokálisan ellenőrzi az auth szerviz JWKS kulcsaival, és a beérkező token **továbbítja** (token passthrough) a hívott upstream szervizeknek (invoice-core, uploader). Admin felhasználók más felhasználóként léphetnek be (impersonation).

**Nincs saját DB, nincs Alembic, nincs CLI** — tiszta frontend aggregátor.

---

## Tech Stack

| Réteg | Technológia | Megjegyzés |
|---|---|---|
| Sablonmotor | Jinja2 | FastAPI `Jinja2Templates` |
| Dinamikus frissítés | HTMX 2.x | CDN-ből; `hx-boost` az összes oldalon |
| CSS keretrendszer | Bootstrap 5.3 (Bootswatch Yeti) | CDN-ből; sötét/világos téma váltás (`data-bs-theme`, `localStorage` `mp-theme`) |
| Táblázat | DataTables 2.x | Bootstrap 5 integration + Responsive + Buttons (Excel/PDF/Print), CDN-ből |
| Diagramok | Chart.js 4.x | CDN-ből (`/ui/` dashboard: timesheet + bevétel/kiadás) |
| Ikonok | Bootstrap Icons | CDN-ből |
| Backend | FastAPI | Port 8009 |
| HTTP kliens | requests (szinkron) | Konzisztens a workspace többi szerviziével; token passthrough auth |
| Auth | JWT (RS256) + JWKS | auth szerviz (8007) kulcsai, `PyJWKClient` cache-sel (1 óra TTL) |

**Nincs build lépés** — minden CSS/JS CDN-ről töltődik.

---

## Architektúra

```
src/vision/
├── config.py                  ← pydantic-settings — a workspace gyökér .env-jéből olvas (közös env)
├── auth.py                    ← JWT validálás (RS256, JWKS), extract_token, current_token ContextVar, TokenPassthrough
├── models.py                  ← dataclassok (InvoiceKPI, CashFlowMonth, …) — korábbi dashboard service réteg maradványa, jelenleg nincs importálva
├── clients/
│   ├── invoice_core.py        ← InvoiceCoreClient — invoice-core összes /api/v1/* végpontja (CRUD, sync/pending, audit-log, tax-estimate, link/unlink, X-Audit-Label)
│   ├── srcprofit.py           ← SrcProfitClient — /api/summary, /api/portfolio (Basic auth)
│   └── uploader.py            ← UploaderClient — /api/v1/upload, /api/v1/files (port 8006)
├── ui/
│   ├── router.py              ← Auth + home oldalak: /, /pitch, /login, /logout, /stop-impersonation
│   ├── invoice_router.py      ← Invoice-core UI oldalak: /ui/* (49 route, incl. /ui/ dashboard)
│   ├── admin_router.py        ← Admin oldalak: /ui/admin/users (+ impersonate), /ui/admin/activity-types, /ui/admin/audit
│   ├── controlling_router.py  ← Controlling oldalak: /ui/controlling/projects + /timesheet + /reports (valós adat, invoice-core CRUD-ot hív)
│   ├── uploader_router.py     ← Feltöltés oldalak: /ui/upload (+ /do, /files, letöltés, törlés)
│   └── utils.py               ← dict_to_ns() (JSON dict → SimpleNamespace, ISO dátum auto-parse), local_today(), current_user()
├── api/
│   └── main.py                ← FastAPI app, /health, JWT auth middleware, HTTP logging middleware
├── templates/
│   ├── base.html              ← Bootswatch Yeti + Bootstrap Icons + jQuery + DataTables (+Buttons/Responsive) + HTMX; sötét/világos téma; htmx:beforeSwap/init.dt DataTables újra-inicializálás kezelés
│   ├── _navbar.html           ← Felhasználói menü, megszemélyesítés banner + „Vissza a saját fiókomba" gomb, téma váltó, kijelentkezés, HTMX globális spinner
│   ├── _sidebar.html          ← Összes nav link: Home, Dashboard, Számlák, Partnerek, Controlling, Admin (users/activity-types/audit/sync/upload)
│   ├── _macros.html           ← payment_badge, amount_fmt, direction_badge, pdf_icon, bank_icon, …
│   ├── pitch.html             ← Startup pitch — ez lett a home oldal (`/`), nem terjeszti ki base.html-t
│   ├── login.html             ← Provider-alapú belépés (auth szerviz gombjai) + silent refresh
│   ├── ui_dashboard.html      ← Dashboard (KPI kártyák, timesheet chart + legutóbbi bejegyzések, bevétel/kiadás chart, top szállítók/vevők, legutóbbi tranzakciók/számlák, utolsó szinkron)
│   ├── invoices.html          ← Számlalista
│   ├── invoice_detail.html    ← Számla részletei
│   ├── invoice_files.html     ← PDF fájl lista
│   ├── suppliers.html         ← Szállítólista
│   ├── supplier_detail.html   ← Szállító részletei (bank_accounts, known_names)
│   ├── customers.html         ← Vevőlista
│   ├── customer_detail.html   ← Vevő részletei (bank_accounts, known_names)
│   ├── transactions.html      ← Bank tranzakció lista
│   ├── dividend.html          ← Osztalék/adó kalkuláció
│   ├── adok.html              ← Adófizetési pivot + Becsült adók
│   ├── sync.html              ← Sync vezérlőpult
│   ├── upload.html            ← Bankkivonat feltöltés (bank detektálás előnézet, felülírás)
│   ├── admin_users.html       ← Admin: felhasználók listája + megszemélyesítés gomb (adminoknak)
│   ├── admin_activity_types.html ← Admin: tevékenység típusok CRUD (HTMX form-okkal)
│   ├── admin_audit.html       ← Admin: audit napló (changes oszlop, megszemélyesítő badge)
│   ├── controlling_projects.html ← Controlling: projektek CRUD (start_date, project_type, first_entry_date, owner-gating)
│   ├── controlling_timesheet.html ← Controlling: timesheet shell oldal → partials/timesheet_content.html
│   ├── controlling_reports.html  ← Controlling: riportok — valós szűrők + 4 riporttípus, fejléc-sáv, heti alakulás chart, stílusozott PDF export, DataTables Buttons export
│   └── partials/              ← HTMX részleges válaszok (nem terjesztik ki base.html-t)
│       ├── invoice_table.html
│       ├── invoice_detail_modal.html ← számla szerkesztés modal (megjegyzés, fizetési státusz zárolás, …)
│       ├── supplier_table.html
│       ├── transaction_table.html
│       ├── transaction_detail.html   ← tranzakció offcanvas (PDF/számla/partner kapcsolás)
│       ├── invoice_file_table.html
│       ├── picker_partners.html      ← szállító/vevő picker + beágyazott „új partner létrehozása és kapcsolása" mini-form
│       ├── picker_invoice_files.html ← PDF fájl picker (számlához és tranzakcióhoz is)
│       ├── picker_invoices.html      ← számla picker (tranzakcióhoz)
│       ├── picker_transactions.html  ← tranzakció picker (számlához)
│       ├── sync_result.html
│       ├── pending_sync_card.html    ← állandó „függőben lévő párosítás" számláló, sync.html-ba include-olva + OOB frissítve
│       ├── timesheet_content.html    ← timesheet tábla + modálok + projekt hét előnézet (naptári hetek)
│       ├── timesheet_form_error.html ← validációs hiba partial a modál hibaslotjába
│       └── upload_files.html         ← feltöltött fájlok táblázata (HTMX)
└── static/
    └── custom.css             ← HTMX indicator + sidebar + KPI + DataTables + dashboard stílusok
```

### dict_to_ns() segédfüggvény

Az invoice-core REST API JSON dict-eket ad vissza. A Jinja2 sablonok pont-szintaxissal (`row.invoice_number`) és `datetime.strftime()` hívásokkal dolgoznak. A `dict_to_ns()` áthidalja a különbséget — az ISO 8601 timestamp stringeket naiv UTC-ként értelmezi, majd **Europe/Budapest** helyi időre konvertálja, hogy a sablonoknak ne kelljen időzónával foglalkozniuk:

```python
def dict_to_ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: dict_to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [dict_to_ns(i) for i in obj]
    return _parse_leaf(obj)  # ISO 8601 stringeket datetime objektummá alakítja (UTC → helyi)
```

Társai a `ui/utils.py`-ban: `local_today()` (budapesti üzleti dátum a szűrő-alapertekhez) és `current_user()` (a JWT `email` claim alapján megkeresi az invoice-core `users` táblájában a felhasználót — az auth szerviz minden belépéskor upserteli).

---

## Adatforrások

### invoice-core (port 8004) — a Vision által fogyasztott endpointok

| Adat | Endpoint | Szűrők |
|---|---|---|
| Dashboard összesítő (KPI-k) | `GET /api/v1/dashboard` | — (kpis, recent_invoices, recent_transactions, last_sync, top_suppliers/customers, monthly_finance) |
| Számlalista | `GET /api/v1/invoices` | `date_from`, `date_to`, `status`, `direction`, `has_pdf`, `supplier_name` |
| Számla részlet (PK) | `GET /api/v1/invoices/{id:int}` | — (tartalmazza a `detail`/`lines`/`vat_summary` NAV enrichment mezőket is) |
| Számla módosítás | `PATCH /api/v1/invoices/{id:int}` | `note`, `payment_status`, `payment_status_locked` („Fizetve" zárolás) |
| Számla–PDF kapcsolás | `PUT/DELETE /api/v1/invoices/{id}/invoice-file` | — |
| Számla–szállító kapcsolás | `PUT/DELETE /api/v1/invoices/{id}/supplier` | — |
| Számla–vevő kapcsolás | `PUT/DELETE /api/v1/invoices/{id}/customer` | — |
| Számla–tranzakció kapcsolás (M2M) | `PUT/DELETE /api/v1/invoices/{id}/transactions/{txn_id}` | — |
| PDF fájl lista | `GET /api/v1/invoice-files` | `linked=yes/no`, `filename` |
| PDF fájl módosítás/törlés | `PATCH /api/v1/invoice-files/{id:int}` | `is_deleted=true` (fájl törlése) |
| PDF fájl kiszolgálás | `GET /api/v1/invoice-files/{id:int}/pdf` | — (Vision proxyzza, nem redirect) |
| Szállítólista | `GET /api/v1/partners/suppliers` | — |
| Szállítói statisztikák | `GET /api/v1/partners/suppliers/summary` | — |
| Szállító részlet | `GET /api/v1/partners/suppliers/{id:int}` | — (tartalmazza `bank_accounts`, `known_names`) |
| Szállító létrehozás/módosítás/törlés | `POST/PUT/DELETE /api/v1/partners/suppliers[/{id:int}]` | — |
| Vevőlista | `GET /api/v1/partners/customers` | — |
| Vevő részlet | `GET /api/v1/partners/customers/{id:int}` | — (tartalmazza `bank_accounts`, `known_names`) |
| Vevő létrehozás/módosítás/törlés | `POST/PUT/DELETE /api/v1/partners/customers[/{id:int}]` | — |
| Bank tranzakció lista | `GET /api/v1/transactions` | `date_from`, `date_to`, `linked`, `partner_name`, `amount_min`, `amount_max` |
| Egyenlegek | `GET /api/v1/transactions/balances` | — |
| Tranzakció részlet | `GET /api/v1/transactions/{id:int}` | — |
| Tranzakció–PDF kapcsolás | `PUT/DELETE /api/v1/transactions/{id}/invoice-file` | — |
| Tranzakció–szállító/vevő kapcsolás | `PUT/DELETE /api/v1/transactions/{id}/supplier\|customer` | — |
| Szinkron naplók | `GET /api/v1/sync/logs` | `limit` |
| Szinkron indítás | `POST /api/v1/sync` | `start_date`, `end_date`, `sync_mode` |
| Függőben lévő párosítások | `GET /api/v1/sync/pending` | — (állandó számláló, nem az utolsó futástól függ) |
| Osztalék kimutatás | `GET /api/v1/reports/dividend` | `year`, `kiva_rate`, `hipa_rate` |
| Adó kimutatás | `GET /api/v1/reports/tax` | `year` |
| Adó-előrejelzés (becsült adók) | `GET /api/v1/reports/tax-estimate` | `year` |
| Felhasználók | `GET /api/v1/users` | — (name, email, provider, `last_login_at`, picture) |
| Audit napló | `GET /api/v1/audit-log` | `user_email`, `page`, `date_from`, `date_to`, `limit` |
| Tevékenység típusok | `GET /api/v1/activity-types` | — |
| Tevékenység típus létrehozás/módosítás/törlés | `POST/PUT/DELETE /api/v1/activity-types[/{id}]` | — |
| Projektek | `GET /api/v1/projects` | — (tartalmazza `start_date`, `project_type`, `first_entry_date`, `permitted_user_ids`) |
| Projekt létrehozás/módosítás/törlés | `POST/PUT/DELETE /api/v1/projects[/{id}]` | — |
| Timesheet rekordok | `GET /api/v1/timesheet-entries` | `user_id` (opcionális — opcionális felhasználó-szűrés) |
| Timesheet rekord létrehozás | `POST /api/v1/timesheet-entries` | — |
| Timesheet rekord módosítás/törlés | `PUT/DELETE /api/v1/timesheet-entries/{id}` | `user_id` (kötelező query param) |
| Timesheet riport | `GET /api/v1/reports/timesheet` | `report_type` (`project`\|`person`\|`customer`\|`activity_type`, kötelező), `date_from`, `date_to`, `customer_id`, `project_id`, `user_id`, `activity_type_id` |

> A módosító hívások (PATCH/PUT/POST/DELETE) `X-Audit-Label` fejlécet küldenek a felhasználó által kattintott gomb/menüpont emberi olvasható nevével (percent-encoded) — ebből készül az audit napló „Gomb" oszlopa.

### SrcProfit (külső)

| Adat | Endpoint | Megjegyzés |
|---|---|---|
| IBKR portfólió | `GET /api/portfolio` | befektetési pozíciók |
| Egyenleg összesítő | `GET /api/summary` | teljes vagyonkép |

> **SrcProfit hitelesítés**: HTTP Basic auth — tárolva a `.env`-ben (`SRCPROFIT_USER`, `SRCPROFIT_PASSWORD`). Ha a SrcProfit nem elérhető, a dashboard szilárdan tűri a hibát (None visszatérés).

### Uploader (port 8006) — bankkivonat fájlok

| Adat | Endpoint | Megjegyzés |
|---|---|---|
| Fájl feltöltés | `POST /api/v1/upload` | multipart `file` + `bank` (opcionális) + `overwrite` |
| Fájllista | `GET /api/v1/files` | tárolt fájlok bank/bázis szerint |
| Fájl törlés | `DELETE /api/v1/files/{bank}/{filename}` | — |
| Fájl letöltés | `GET /api/v1/files/{bank}/{filename}/download` | Vision redirecteli |

### Auth szerviz (port 8007) — belépés és megszemélyesítés

| Adat | Endpoint | Megjegyzés |
|---|---|---|
| Belépési provider-ök | `GET /auth/providers` | login gombok (nem elérhető → Google fallback) |
| Kijelentkezés | `POST /auth/logout` | refresh token visszavonása + cookie törlés |
| Token frissítés | `POST /auth/refresh` | silent refresh (`login.html`) + `/stop-impersonation` |
| Megszemélyesítés | `POST /auth/impersonate` | admin → másik felhasználó access tokenje (JSON: `email`) |
| JWKS | `GET /.well-known/jwks.json` | RS256 aláírás-ellenőrzés (PyJWKClient cache) |

---

## Oldalak

### Invoice-Core UI oldalak (`/ui/*` — 49 route)

| Oldal | URL | Leírás |
|---|---|---|
| Dashboard | `/ui/` | KPI kártyák, timesheet összesítő chart + legutóbbi timesheet bejegyzések, bevétel vs kiadás chart, top szállítók/vevők, legutóbbi tranzakciók és számlák, utolsó szinkron státusz; „Sync indítása" gomb |
| Számlák | `/ui/invoices` | Számlalista — szűrhető dátum, fizetési státusz, PDF, szállító szerint; DataTable (HTMX partial frissítés) |
| Számla részlet | `/ui/invoices/{id}` | Számla részletei szállítói/vevői kártyákkal, PDF link, bank tranzakciók, teljes NAV enrichment (tételsorok, ÁFA összesítő, kategória/teljesítés dátuma/pénznem); megjegyzés mentés, „Fizetve" zárolás/feloldás; kézi kapcsolások picker modálokból: szállító/vevő (link/unlink + beágyazott „új partner létrehozása és kapcsolása" form, ami a NAV partner snapshotból előtöltve kínálja a még nem létező partnert), PDF fájl, bank tranzakció (M2M) |
| PDF Fájlok | `/ui/invoice-files` | PDF fájl lista linkelt számlával és szállítóval; `linked` szűrő; fájl törlés (PATCH `is_deleted`) |
| PDF letöltés | `/ui/invoice-files/{id}/pdf` | **Proxy**: lekéri az invoice-core-tól és továbbítja a bájtokat (content-disposition átadással) — nem redirect |
| Szállítók | `/ui/suppliers` | Szállítólista számla statisztikákkal; „Új szállító" létrehozás modal |
| Szállító részlet | `/ui/suppliers/{id}` | Szállító részletei számla és bank DataTable-ekkel; **ismert bankszámlák (`bank_accounts`) és ismert nevek (`known_names`) megjelenítése**; módosítás modal + törlés (letiltva, ha van kapcsolt számla/tranzakció) |
| Vevők | `/ui/customers` | Vevőlista számla statisztikákkal; „Új vevő" létrehozás modal |
| Vevő részlet | `/ui/customers/{id}` | Vevő részletei számla és bank DataTable-ekkel; **ismert bankszámlák (`bank_accounts`) és ismert nevek (`known_names`) megjelenítése**; módosítás modal + törlés (letiltva, ha van kapcsolt számla/tranzakció) |
| Bank tranzakciók | `/ui/transactions` | Tranzakció lista — szűrhető dátum, linked státusz, partner, összeg szerint; bank egyenlegek kártyák; a partner oszlop a tranzakció iránya szerint a kapcsolt szállítóra (DEBIT) vagy vevőre (CREDIT) linkel, illetve „nincs partner" jelzést ad; tranzakció részlet offcanvas (PDF/számla/partner kapcsolás) |
| Osztalék | `/ui/dividend` | Éves osztalék/adó kalkuláció: bevétel, kiadás, KIVA, SZJA, SZOCHO — havi bontás (`year` query) |
| Adók | `/ui/adok` | Adófizetési pivot hónap és típus szerint (NAV ÁFA, SZJA, TAO, Szochó, TB, Bírság, HIPA, Iparkamara) + **„Becsült adók"** tábla (a `tax-estimate` riportból, csak a még nem telt hónapokra, a „Havi bontás"-ban ténylegesen aktív adónemekre vetítve) |
| Sync | `/ui/sync` | Szinkron indítás mód-választással; szinkron napló accordion; állandó „függőben lévő partner-párosítás" kártya (hány számla/tranzakció vár még szállítóra/vevőre, az utolsó futástól függetlenül) |

**UI tech**: Jinja2 SSR, HTMX 2.x (boost + partial swap + OOB), Bootstrap 5.3 (Bootswatch Yeti, sötét/világos váltás), DataTables 2.x (+ Responsive, + Buttons export) — nincs build lépés.

Filter formok HTMX partial frissítéssel működnek (szűrt nézetek nem reloadolják az egész oldalt).

### Admin oldalak (`/ui/admin/*` — valós adat, nem mockup)

| Oldal | URL | Leírás |
|---|---|---|
| Felhasználók | `/ui/admin/users` | Felhasználók listája (név, email, provider, utolsó belépés `last_login_at`, regisztráció, profil kép); DataTable. **Adminoknak** (az `ADMIN_EMAILS` listában szereplő email) soronkénti **„Belépés e felhasználóként"** gomb → `/ui/admin/users/impersonate` proxizza az auth szerviz `/auth/impersonate` végpontját és beállítja a kapott access cookie-t (a refresh cookie az admin sajátja marad, így a `/stop-impersonation` sima refresh-szel visszaáll) |
| Tevékenység típusok | `/ui/admin/activity-types` | CRUD törzsadat a timesheet funkcióhoz — létrehozás/módosítás modal, inaktiválás (használat esetén), törlés |
| Audit | `/ui/admin/audit` | Felhasználói módosítások naplója: időpont, felhasználó (+ **megszemélyesítő badge**, ha admin nevében történt), oldal, rekord, „Gomb" badge (az `X-Audit-Label` alapján, create/update/delete színkóddal), részletek: `method path` + **`changes` mezőnkénti diff lista** (régi → új). DataTables Responsive a részletoszlopokhoz beállított prioritással |

### Controlling oldalak (`/ui/controlling/*`)

| Oldal | URL | Leírás |
|---|---|---|
| Projektek | `/ui/controlling/projects` | Projektek CRUD — valós adat. Ügyfél (customer FK), ügyfelenként növekvő sorszám, automatikusan összeállított project kód (`{ügyfél} - {sorszám:03d} - {short_name}`), gazda, aktív/lezárt státusz, **kezdés dátuma (`start_date`)**, **projekt típus (`project_type`: Ötlet / Számlázható / PreSales, színes badge)** és rögzítésre jogosultak checkbox lista. Az első rögzített bejegyzés dátuma (`first_entry_date`) is megjelenik (a projekt hét számítás horgonya). Csak a projekt gazdája szerkesztheti a kezdés dátumát/típust (owner-gating) |
| Timesheet | `/ui/controlling/timesheet` | Saját timesheet rekordok CRUD — valós adat, HTMX partial (`timesheet_content.html`). **Projekt scope szűrő: Engedélyezett projektek / Saját projektek / Összes projekt** (`project_scope` query). Dátum, Projekt (csak aktív és a felhasználó számára jogosult projektek), Ügyfél/Project gazda/Projekt hét mezők a kiválasztott projektből származó, csak-olvasható előnézetek. A **Projekt hét naptári hetek szerint** számítódik (hétfő–vasárnap), a projekt első rögzített bejegyzéséhez rögzítve (W1) — a kliens-oldali előnézet és a szerver ugyanazzal a logikával számol. Tevékenység típus (aktív típusokból), 0,5 órás lépésű Óra select, szabad szöveges Résztvevők és Tevékenység leírás. **Dátum validáció**: hiba esetén a hibaüzenet a modál saját hibaslotjába (`#ts-error-new` / `#ts-error-edit-{id}`) kerül, a modál nyitva marad; siker esetén HX-Redirect a listára (a DataTables Responsive újra-inicializálási hibáinak elkerülésére). Csak a bejelentkezett felhasználó saját rekordjai szerkeszthetők/törölhetők. A felhasználó azonosítása JWT `email` claim alapján történik (`current_user()`), a `client.get_users()` listában keresve egyezést |
| Riportok | `/ui/controlling/reports` | Valós adat — 4 riporttípus a `timesheet_entry` felett: Projekt riport (heti + kumulált, tevékenység típusonkénti bontással, futó összeggel, **Heti alakulás chart**), Személy riport, Ügyfél riport, Tevékenység típus riport. Az utóbbi három soronkénti listát mutat (Dátum, Nap, Hét, Résztvevők, **Leírás**, Óra, plusz Személy/Ügyfél/Tevékenység típus oszlop a riporttípustól függően), a tábla alatt egy külön „Összesítés" kártyával (tevékenység típusonkénti pivot oszlopokkal). Fejléc-sáv minden riportnál: Projekt / Ügyfél / Személy / Tevékenység típus / Időszak. Szűrők: dátumtartomány (projekt kezdete óta / aktuális hónap / aktuális hét / egyéni), ügyfél, projekt, személy, tevékenység típus — **az ügyfél és a projekt választó dinamikusan össze van kötve** (projekt választó csak az adott ügyfél projektjeit kínálja). Projekt riportnál projekt hiányában automatikusan az első projekt kerül kiválasztásra; az időtartam alapján a heti statisztika granularitása napi/havi/éves lehet. Export (Excel/PDF/Nyomtatás) kliens-oldali DataTables Buttons-szal — a ténylegesen szűrt/rendezett táblát exportálja, a fejléc-sávot (`messageTop`) és az Összesítés szekciót is (`exportOptions.customizeData`, a DOM-ból olvasva). **A PDF export a bejegyzés-részlet helyett az Összesítés táblát helyezi előtérbe** (projekt riportnál a heti táblát), egyedi stílussal (`customize` callback: márkaszín fejléc/cím, zebra-csíkozás, kiemelt összesítő sorok, lábléc oldalszámmal); a stílusozás try/catch-csel védett, hiba esetén sima PDF-et exportál |

### Feltöltés (`/ui/upload` — uploader szerviz)

| Oldal | URL | Leírás |
|---|---|---|
| Feltöltés | `/ui/upload` | Bankkivonat (CSV) feltöltés az uploader szervizre (8006): fájl választás kliens-oldali **bank detektálási előnézettel**, opcionális bank felülírás, „létező fájl felülírása" checkbox; HTMX feltöltés eredmény alerttel, alatta a tárolt fájlok táblázata (letöltés/törlés gombokkal) |

### Auth és Vision saját oldalak

| Oldal | URL | Leírás |
|---|---|---|
| Home | `/` | **pitch.html** — a startup pitch lett a kezdőoldal (standalone sötét téma, nem terjeszti ki base.html-t) |
| Pitch | `/pitch` | 308 redirect → `/` |
| Belépés | `/login` | Provider-alapú belépés: az auth szerviz `/auth/providers` gombjai (nem elérhető → Google fallback), `next` visszairányítás, silent refresh fetch |
| Kijelentkezés | `/logout` | Refresh token visszavonása az auth szerviznél + cookie-k törlése → `/login` |
| Megszemélyesítés vége | `/stop-impersonation` | Sima `/auth/refresh` az admin saját refresh cookie-jával → az access token visszaáll az admin identitására → `/ui/` |

> A navbar minden oldalon mutatja a bejelentkezett felhasználót, megszemélyesítés esetén sárga **„Megszemélyesítve — admin: …"** banner + „Vissza a saját fiókomba" gomb.

### `/ui/` — Dashboard részletei

A dashboard KPI-jei és listái az invoice-core `GET /api/v1/dashboard` válaszából jönnek (a Vision nem számol aggregációt), a timesheet adatok a `GET /api/v1/timesheet-entries`-ből.

#### KPI kártyák

| Kártya | Forrás | Tartalom |
|---|---|---|
| Összes számla | invoice-core `/api/v1/dashboard` (kpis) | `total_invoices` + kapcsolt PDF-ek száma (`linked_pdfs`) |
| Fizetetlen számla | ugyanaz | `unpaid_invoices` darab + `unpaid_amount` HUF |
| Bank tranzakció | ugyanaz | `recent_bank_count` (elmúlt 30 nap) |
| Partnerek | ugyanaz | `supplier_count` szállító + `customer_count` vevő |

#### Chart.js diagramok

1. **Timesheet összesítő (stacked bar)** — céges összóraszám idővonalon, projektenkénti bontásban; **Napi / Havi / Éves** váltó; a projekt→sorozat hozzárendelés az összesített óraszám szerint rangsorolt (top 7 projekt + „Egyéb"), a teljes idősor az első timesheet bejegyzéstől fut (nincs görgetőablak)
2. **Bevétel vs Kiadás (bar)** — utolsó 3/6/12 hónap váltó; `monthly_finance` alapján

#### Top partnerek és listák

- **Top szállítók / Top vevők** — progress-list kártyák (arány + összeg), névre kattintva a partner részlet oldal
- **Legutóbbi tranzakciók** és **legutóbbi számlák** — full-width táblák; **legutóbbi timesheet bejegyzések** (dátum, felhasználó, projekt, ügyfél, tevékenység, óra)
- **Utolsó szinkron** státusz + „Sync indítása" gomb (`/ui/sync`)

#### Lefúrás linkek

- `→ Számlák` — `http://localhost:8009/ui/invoices`
- `→ Bank tranzakciók` — `http://localhost:8009/ui/transactions`
- `→ Timesheet` — `http://localhost:8009/ui/controlling/timesheet`
- `→ Sync indítása` — `http://localhost:8009/ui/sync`

---

## REST Interface

A teljes route-térkép (76 UI route + `/health`; a zárójelben a kezelő router):

```
GET    /health                                     → {"status": "ok", "timestamp": "..."}

# Auth + home (ui/router.py)
GET    /                                           → pitch.html (standalone home)
GET    /pitch                                      → 308 redirect → /
GET    /login                                      → login.html (query: next, error)
GET    /logout                                     → logout (refresh visszavonás + cookie törlés) → /login
GET    /stop-impersonation                         → access cookie visszaállítása az adminra → /ui/

# Dashboard + invoice-core UI (ui/invoice_router.py — 49 route)
GET    /ui/                                        → ui_dashboard.html
GET    /ui/invoices                                → invoices.html / partials/invoice_table.html (query: date_from, date_to, payment_status, has_pdf, supplier_name)
GET    /ui/invoices/{id:int}                       → invoice_detail.html
GET    /ui/invoices/{id:int}/modal                 → partials/invoice_detail_modal.html
POST   /ui/invoices/{id}/note                      → megjegyzés mentése (PATCH /api/v1/invoices/{id})
POST   /ui/invoices/{id}/fizetve                   → Fizetve jelölés / zár feloldása (form: locked=true|false)
POST   /ui/invoices/{id}/invoice-file/link         → PDF kapcsolása
POST   /ui/invoices/{id}/invoice-file/unlink       → PDF leválasztása
POST   /ui/invoices/{id}/supplier/link             → szállító kapcsolása
POST   /ui/invoices/{id}/supplier/unlink           → szállító leválasztása
POST   /ui/invoices/{id}/supplier/create-and-link  → új szállító létrehozása + kapcsolása
POST   /ui/invoices/{id}/customer/link             → vevő kapcsolása
POST   /ui/invoices/{id}/customer/unlink           → vevő leválasztása
POST   /ui/invoices/{id}/customer/create-and-link  → új vevő létrehozása + kapcsolása
POST   /ui/invoices/{id}/transactions/{txn_id}/link    → bank tranzakció kapcsolása (M2M)
POST   /ui/invoices/{id}/transactions/{txn_id}/unlink  → bank tranzakció leválasztása
GET    /ui/invoice-files                           → invoice_files.html (query: linked)
GET    /ui/invoice-files/{id:int}/pdf              → PDF proxy (bájtok + content-disposition átadás)
DELETE /ui/invoice-files/{id:int}/delete           → fájl törlés (PATCH is_deleted; partial frissítés)
GET    /ui/suppliers                               → suppliers.html / partials/supplier_table.html
POST   /ui/suppliers                               → létrehozás
GET    /ui/suppliers/{id:int}                      → supplier_detail.html
POST   /ui/suppliers/{id:int}                      → módosítás
DELETE /ui/suppliers/{id:int}/delete               → törlés (HX-Redirect → /ui/suppliers siker esetén)
GET    /ui/customers                               → customers.html
POST   /ui/customers                               → létrehozás
GET    /ui/customers/{id:int}                      → customer_detail.html
POST   /ui/customers/{id:int}                      → módosítás
DELETE /ui/customers/{id:int}/delete               → törlés (HX-Redirect → /ui/customers siker esetén)
GET    /ui/transactions                            → transactions.html / partials/transaction_table.html (query: date_from, date_to, linked, partner_name, amount_min, amount_max)
GET    /ui/transactions/{id:int}                   → partials/transaction_detail.html (offcanvas)
POST   /ui/transactions/{id}/invoice-file/link     → PDF kapcsolása
POST   /ui/transactions/{id}/invoice-file/unlink   → PDF leválasztása
POST   /ui/transactions/{id}/supplier/link         → szállító kapcsolása
POST   /ui/transactions/{id}/supplier/unlink       → szállító leválasztása
POST   /ui/transactions/{id}/supplier/create-and-link → új szállító létrehozása + kapcsolása
POST   /ui/transactions/{id}/customer/link         → vevő kapcsolása
POST   /ui/transactions/{id}/customer/unlink       → vevő leválasztása
POST   /ui/transactions/{id}/customer/create-and-link → új vevő létrehozása + kapcsolása
POST   /ui/transactions/{id}/invoices/{invoice_id}/link   → számla kapcsolása (M2M, tranzakció oldalról)
POST   /ui/transactions/{id}/invoices/{invoice_id}/unlink → számla leválasztása
GET    /ui/picker/partners                         → partials/picker_partners.html (query: kind=supplier|customer, source_type, source_id, invoice_id)
GET    /ui/picker/invoice-files                    → partials/picker_invoice_files.html (query: source_type, source_id)
GET    /ui/picker/invoices                         → partials/picker_invoices.html (query: txn_id)
GET    /ui/picker/transactions                     → partials/picker_transactions.html (query: invoice_id)
GET    /ui/dividend                                → dividend.html (query: year)
GET    /ui/adok                                    → adok.html (query: year)
GET    /ui/sync                                    → sync.html
POST   /ui/sync/trigger                            → partials/sync_result.html (HTMX + OOB badge frissítés)

# Feltöltés (ui/uploader_router.py)
GET    /ui/upload                                  → upload.html
POST   /ui/upload/do                               → feltöltés eredmény alert (HTMX partial)
GET    /ui/upload/files                            → partials/upload_files.html (HTMX)
GET    /ui/upload/files/{bank}/{filename}/download → redirect → uploader letöltés
DELETE /ui/upload/files/{bank}/{filename}          → fájl törlés (HTMX)

# Admin (ui/admin_router.py)
GET    /ui/admin/users                             → admin_users.html
POST   /ui/admin/users/impersonate                 → megszemélyesítés (auth szerviz proxy; form: email) → /ui/
GET    /ui/admin/audit                             → admin_audit.html
GET    /ui/admin/activity-types                    → admin_activity_types.html
POST   /ui/admin/activity-types                    → létrehozás
POST   /ui/admin/activity-types/{id}               → módosítás
POST   /ui/admin/activity-types/{id}/deactivate    → inaktiválás
DELETE /ui/admin/activity-types/{id}/delete        → törlés

# Controlling (ui/controlling_router.py)
GET    /ui/controlling/projects                    → controlling_projects.html
POST   /ui/controlling/projects                    → létrehozás
POST   /ui/controlling/projects/{id}               → módosítás
DELETE /ui/controlling/projects/{id}               → törlés
GET    /ui/controlling/timesheet                   → controlling_timesheet.html / partials/timesheet_content.html (query: project_scope=permitted|my|all)
POST   /ui/controlling/timesheet                   → létrehozás (hiba → partials/timesheet_form_error.html a modálba; siker → HX-Redirect)
POST   /ui/controlling/timesheet/{id}              → módosítás (ugyanaz a válasz-szerződés)
DELETE /ui/controlling/timesheet/{id}              → törlés (hiba → teljes oldal re-render; siker → HX-Redirect)
GET    /ui/controlling/reports                     → controlling_reports.html (query: report_type, date_range, date_from, date_to, customer_id, project_id, user_id, activity_type_id)
```

**Nincs CLI** — a Vision csak böngészőből használt UI szerviz. Minden route (a `_PUBLIC_PATHS` halmazon kívül: `/`, `/pitch`, `/login`, `/logout`, `/health`, `/favicon.ico`, `/static/*`) érvényes JWT-t igényel; hiányában böngészős kérés → redirect `/login`, HTMX kérés → 401 + `HX-Redirect`, API kérés → 401 JSON.

---

## Environment (`.env`)

A Vision a **workspace gyökér közös `.env` fájljából** olvas (pydantic-settings, `extra="ignore"`):

```bash
# Auth (JWT — minden /ui/* oldal védett; teszthez kikapcsolható)
AUTH_ENABLED=true
JWT_AUDIENCE=moneypenny
JWT_ISSUER=auth-service
AUTH_SERVICE_URL=http://localhost:8007
AUTH_PUBLIC_URL=http://localhost:8007   # böngészőből elérhető auth URL (Docker hostname esetén felülírni)
ADMIN_EMAILS=                            # vesszővel elválasztott emailek — megszemélyesítés gomb (UX, nem biztonsági határ)
COOKIE_SECURE=false

# Upstream szervizek
INVOICE_CORE_URL=http://localhost:8004
UPLOADER_URL=http://localhost:8006

# SrcProfit kapcsolat
SRCPROFIT_URL=https://srcprofit2.graphtrek.co
SRCPROFIT_USER=admin
SRCPROFIT_PASSWORD=<titkos>

# Vision szerviz
VISION_API_PORT=8009        # alias: API_PORT
LOG_LEVEL=INFO
REQUEST_TIMEOUT=10
```

A log stream + fájl (`logs/vision.log`) formátummal; a JWT validálás certifi-alapú TLS trust store-t használ a JWKS lekéréshez.

---

## Implementációs sorrend

1. `config.py` + `auth.py` — pydantic-settings (közös workspace `.env`) + JWT/JWKS validálás, token passthrough
2. `clients/invoice_core.py` + `clients/uploader.py` + `clients/srcprofit.py` — requests sync kliensek, token továbbadással
3. `ui/utils.py` — `dict_to_ns()`, `local_today()`, `current_user()`
4. `base.html` + `_macros.html` + `_sidebar.html` + `_navbar.html` — Bootstrap CDN, HTMX, DataTables, Chart.js, `hx-boost`, sötét/világos téma
5. `ui/invoice_router.py` — a `/ui/*` oldalak (49 route), `InvoiceCoreClient` hívásokkal, HTMX partial szűrőkkel
6. `ui/controlling_router.py` — projektek + timesheet + riportok (valós invoice-core CRUD)
7. `ui/admin_router.py` — felhasználók (+ impersonation), tevékenység típusok, audit napló
8. `ui/uploader_router.py` — bankkivonat feltöltés oldal
9. `ui/router.py` — auth oldalak (`/login`, `/logout`, `/stop-impersonation`) + home (`/` → pitch)
10. `api/main.py` — FastAPI app, auth middleware, mindkét router csatolása, `/health`

---

## Kapcsolódások

### Wiki Linkek
- **Prompt**: [[vision-prompt.md|Vision Prompt]]
- **Fő adatforrás (REST backend)**: [[invoice-core-spec.md|Invoice-Core Spec]]
- **Autentikáció**: [[auth-service-spec.md|Auth Service Spec]]
- **Bankkivonat fájlok**: [[uploader-spec.md|Uploader Spec]]
- **Külső adatforrás**: [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR befektetések)
- **Projekt Index**: [[INDEX.md|Moneypenny Index]]
