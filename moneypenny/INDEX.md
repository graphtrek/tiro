---
title: "Moneypenny - Projekt Index"
description: "Számlázási, banki és tulajdonosi AI mikorszervízek - wiki navigáció"
language: "HU"
last_updated: "2026-06-18"
---

# 📚 Moneypenny - Wiki Index

## Összefoglalás

A **Moneypenny** egy hat Python mikroszervizből álló pénzügyi automatizálási rendszer, amely a Graphtrek számlázási és vagyonkezelési folyamatát digitalizálja. A rendszer Gmail-fiókból tölti le a PDF számlamellékleteket, OCR/Regex segítségével kinyeri a metaadatokat, lekérdezi a számlák adatait a NAV Online Számla API-ból, letölti a Wise banki tranzakciókat, majd mindent egy PostgreSQL adatbázisba ment, szállítói, vevői és tranzakció adatokkal összekapcsolva. A **Vision** szerviz tulajdonosi dashboardon aggregálja az invoice-core és SrcProfit (IBKR) adatait.

| #   | Mikroszerviz            | Port | Szerep                                               |
| --- | ----------------------- | ---- | ---------------------------------------------------- |
| 5   | `invoice-core`          | 8004 | MASTER orchestrator – DB persistálás, reconciliation |
| 3   | `nav-invoice`           | 8002 | NAV Online Számla API lekérdezés                     |
| 2   | `invoice-file-filter`   | 8001 | PDF metaadat kinyerés (OCR/Regex)                    |
| 1   | `attachment-downloader` | 8000 | Gmail PDF mellékletek letöltése                      |
| 4   | `wise`                  | 8003 | Wise bankkivonatok feldolgozása (CSV import)         |
| 6   | `vision`                | 8009 | Tulajdonosi AI dashboard – invoice-core + SrcProfit aggregáció |

Belépési pont: `POST /api/v1/sync` → `invoice-core` (8004). Az 1–5. mikroszerviznek FastAPI REST interfésze és Typer/Click CLI-je is van. A `vision` (6.) csak UI szerviz, CLI nélkül.

---

## 🔗 Hívási Lánc (Szinkron)

```
MASTER ORCHESTRATOR
        ↓
    invoice-core
     (init)
      ├──────────────────┬──────────────────┐
      ↓                  ↓                  ↓
 nav-invoice         invoice-file-filter   wise
 (NAV API)               ↓             (Wise API)
                   attachment-downloader
                     (Gmail API)
      └──────────────────┴──────────────────┘
                         ↓
                   Merge + DB insert

--- független aggregátor ---

    vision (8009)
      ├── invoice-core REST API (olvas)
      └── SrcProfit API (olvas, IBKR)
```

> `invoice-core` mindhárom ágat közvetlenül hívja. `invoice-file-filter` → `attachment-downloader` lánc a PDF-letöltési ág. A `vision` külön, read-only aggregátor — nem része a sync láncnak.

---

## 📋 Mikorszervízek Wiki

### 4️⃣ MASTER - Számla Adatbázis
**[[invoice-core-spec.md|📄 Specifikáció]]** | **[[invoice-core-prompt.md|💭 Prompt]]** | **[[invoice-core-ui-prompt.md|🖥️ UI Prompt]]** | **[[invoice-core-ui-spec.md|🖥️ UI Spec]]**

- **Szerepe**: Orchestrator (szinkronizálás indítása)
- **Meghívja**: [[nav-invoice-spec.md|NAV API]], [[invoice-file-filter-spec.md|invoice-file-filter]], [[wise-spec.md|wise]]
- **Funkció**: Összes adat persistálása + partnerek kezelése
- **Output**: PostgreSQL DB (invoice, invoice_file, supplier, customer, wise_transaction)
- **REST**: `POST /api/v1/sync` → teljes szinkronizálás (NAV + PDF + Wise)

---

### 3️⃣ NAV Online Számla API
**[[nav-invoice-spec.md|📄 Specifikáció]]** | **[[nav-invoice-prompt.md|💭 Prompt]]**

- **Meghívva**: [[invoice-core-spec.md|invoice-core]] által
- **Meghívja**: (senki — csak a NAV API-t hívja)
- **Funkció**: NAV Online Számla lekérdezés (queryInvoiceDigest / queryInvoiceData)
- **Output**: NAV adatok (számlalista, supplier/customer info)
- **REST** (port 8002): `GET /health`, `POST /auth/login`, `GET /invoices`, `GET /invoices/{szamlaszam}`, `POST /report`, `POST /cache/clear`, `GET /settings`
- **CLI**: `nav login`, `nav list`, `nav show <szamlaszam>`, `nav report`, `nav cache-clear`

---

### 2️⃣ PDF Számla Feldolgozó
**[[invoice-file-filter-spec.md|📄 Specifikáció]]** | **[[invoice-file-filter-prompt.md|💭 Prompt]]**

- **Meghívva**: [[invoice-core-spec.md|invoice-core]] által
- **Meghívja**: [[attachment-downloader-spec.md|Gmail Letöltő]]
- **Funkció**: PDF metaadatok kinyerése (OCR/Regex)
- **Input**: attachment-downloader API (utolsó 30 nap)
- **Output**: Invoice metadata (szám, dátum, összeg, partner)
- **REST**: `POST /api/v1/invoices/extract`

---

### 1️⃣ Gmail PDF Letöltő
**[[attachment-downloader-spec.md|📄 Specifikáció]]** | **[[attachment-downloader-prompt.md|💭 Prompt]]**

- **Meghívva**: [[invoice-file-filter-spec.md|invoice-file-filter]] által
- **Funkció**: Email PDF mellékleteket letölt (provider architektúra; jelenleg: Gmail OAuth2)
- **Dátum szűrés**: YYYY-MM-DD intervallum
- **Output**: `./downloads/YYYY-MM-DD_NNNN_<fájlnév>.pdf`
- **REST** (port 8000, szinkron): `POST /api/v1/jobs`, `GET /api/v1/cache`, `DELETE /api/v1/cache`
- **CLI**: `attachment-downloader --start <date> --end <date> [--output <dir>] [--provider gmail]`

---

### 5️⃣ Wise Banki Mikroszerviz
**[[wise-spec.md|📄 Specifikáció]]** | **[[wise-prompt.md|💭 Prompt]]**

- **Meghívva**: [[invoice-core-spec.md|invoice-core]] által
- **Meghívja**: (senki — DB-t nem kezel)
- **Funkció**: Kézzel letöltött Wise kivonat CSV-k feldolgozása, strukturált tranzakció lista visszaadása
- **Input**: `balance-statements/` mappa CSV fájljai (fájlnév-séma: `statement_<balanceId>_<currency>_<from>_<to>.csv`)
- **Output**: `StatementImport` (JSON) — DB-t nem kezel
- **REST** (port 8003): `GET /health`, `GET /balance-statements`, `GET /balance-statements/{filename}`, `POST /sync` (egyelőre nem működik)
- **CLI**: `wise-szamla status`, `wise-szamla statements`, `wise-szamla import <filename>`, `wise-szamla sync`

---

### 6️⃣ Vision – Tulajdonosi AI Dashboard
**[[vision-spec.md|📄 Specifikáció]]** | **[[vision-prompt.md|💭 Prompt]]**

- **Meghívva**: (senki — böngészőből nyitják)
- **Meghívja**: [[invoice-core-spec.md|invoice-core]] REST API (olvas) + [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR, olvas)
- **Funkció**: Tulajdonosi szintű pénzügyi aggregátor — számlák, Wise tranzakciók, IBKR befektetések egy dashboardon
- **Saját DB**: nincs — read-only aggregátor
- **REST** (port 8009): `GET /health`, `GET /` (koncepcióoldal), `GET /dashboard` (KPI + diagramok)
- **CLI**: nincs

---

## 🎯 Projekt Áttekintés

```
Hívási Lánc (Szinkron):
┌──────────────────────────────────────────────────────┐
│  4. SZAMLA-DB (MASTER)                               │
│  ├─ Meghívja: nav-invoice                             │
│  ├─ Meghívja: invoice-file-filter                    |
│  ├─ Meghívja: wise                                   │
│  └─ Persistálás + Merge: DB                          │
└──────────────────────────────────────────────────────┘
         ↓                   ↓                        ↓
┌──────────────┐ ┌───────────────────---──---─┐  ┌────────────-──┐
│  3. NAV API  │ │  2. PDF FELDOLGOZÓ         │  │  5. WISE      │
│  ├─ NAV query│ │  ├─ PDF indexelés          │  │  ├─ Wise API  │
│  └─ Levél    │ │  └─ → attachment-downloader│  │  └─ Levél.    │
└──────────────┘ └─────────────────────------─┘  └─────────────-─┘
                           ↓
              ┌────────────────────────────┐
              │  1. GMAIL LETÖLTŐ (Végpont)│
              │  ├─ Email PDF letöltés     │
              │  └─ Output: PDF fájlok    │
              └────────────────────────────┘
```

---

## 📁 Fájl Navigáció

### Specifikációk
- **invoice-core**: [[invoice-core-spec.md|spec]] (MASTER orchestrator)
- **nav-invoice**: [[nav-invoice-spec.md|spec]] (NAV query)
- **invoice-file-filter**: [[invoice-file-filter-spec.md|spec]] (PDF extract)
- **attachment-downloader**: [[attachment-downloader-spec.md|spec]] (Gmail download)
- **wise**: [[wise-spec.md|spec]] (Bankkivonatok integráció)
- **vision**: [[vision-spec.md|spec]] (Tulajdonosi AI dashboard)

### Promptok
- **invoice-core**: [[invoice-core-prompt.md|prompt]] | [[invoice-core-ui-prompt.md|UI prompt]] | [[invoice-core-ui-spec.md|UI spec]]
- **nav-invoice**: [[nav-invoice-prompt.md|prompt]]
- **invoice-file-filter**: [[invoice-file-filter-prompt.md|prompt]]
- **attachment-downloader**: [[attachment-downloader-prompt.md|prompt]]
- **wise**: [[wise-prompt.md|prompt]]
- **vision**: [[vision-prompt.md|prompt]]

---

## 🔍 Hívási Sorrend Részletezve

```mermaid
flowchart TD
    C[Client] -->|sync| SD[invoice-core]
    SD -->|query| NAV[nav-invoice]
    NAV -->|digest| SD
    SD -->|extract| IFF[pdf-filter]
    IFF -->|jobs| AD[gmail]
    AD -->|files| IFF
    IFF -->|index| SD
    SD -->|statements| W[wise]
    W -->|import| SD
    SD -->|insert| DB[PostgreSQL]
    DB -->|result| C
```

### Initiation (Invoice-Core)
```
Client
  ↓
POST /api/v1/sync (invoice-core)
  └─ start_date: "2026-05-01" (default: last 30 days)
  └─ end_date: "2026-05-31"
```

### Chain Calls (Szinkron)
```
1. invoice-core.sync()
   ├─ nav_invoice.query(start_date, end_date)        [levél — csak NAV API]
   │   └─ GET /invoices?from_date=...&to_date=...&direction=OUTBOUND
   │   └─ Return: számlalista (InvoiceDigest[]), supplier/customer adatok
   ├─ invoice_file_filter.extract(start_date, end_date)
   │   └─ POST /api/v1/jobs → attachment_downloader [szinkron, Gmail API]
   │       └─ Return: {total_files, files: [{filename, saved_path, ...}]}
   └─ wise.balance_statements()                       [levél — CSV import]
       └─ GET /balance-statements                    → StatementImport (legfrissebb kivonat)

2. DB mentés:
   └─ Insert: invoice_file (minden PDF nyers adat)
   └─ Merge (words-alapú):
       └─ Minden NAV számlaszámhoz: GET /api/v1/invoices/search?words=<számlaszám>
   └─ Insert: supplier / customer (NAV adatok alapján)
   └─ Insert: invoice (invoice_file_id FK-val ha volt egyezés)
   └─ Insert: wise_transaction (idempotens: wise_transaction_id ellenőrzés)
       └─ supplier / customer létrehozás ha még nem létezik
       └─ invoice_id összekapcsolás összeg + dátum alapján
   └─ Return: Sync results
```

---

## 🚀 Fejlesztési Sorrend

1. **[[attachment-downloader-spec.md|Gmail Letöltő]]** - OAuth2, PDF API
2. **[[invoice-file-filter-spec.md|PDF Feldolgozó]]** - OCR/Regex, attachment-downloader integrálás
3. **[[nav-invoice-spec.md|NAV API]]** - NAV query, invoice-file-filter integrálás
4. **[[wise-spec.md|Wise Integráció]]** - CSV import, balance-statements végpont (invoice-core hívja)
5. **[[invoice-core-spec.md|Invoice-Core]]** - DB orchestration, reconciliation (utolsó: mindenkit integrál)
6. **[[vision-spec.md|Vision Dashboard]]** - read-only aggregátor (invoice-core + SrcProfit), Chart.js UI

---

## 📡 API Portok (Dev)

| Service               | Port | Endpoint                |
| --------------------- | ---- | ----------------------- |
| attachment-downloader | 8000 | `http://localhost:8000` |
| invoice-file-filter   | 8001 | `http://localhost:8001` |
| nav-invoice           | 8002 | `http://localhost:8002` |
| wise                  | 8003 | `http://localhost:8003` |
| invoice-core          | 8004 | `http://localhost:8004` |
| vision                | 8009 | `http://localhost:8009` |

---

## 🔐 Environment Variables

```bash
# invoice-core
INVOICE_CORE_URL=postgresql://user:pass@localhost/invoices
NAV_API_URL=http://localhost:8002
PDF_API_URL=http://localhost:8001
DEFAULT_DAYS_BACK=30

# nav-invoice
NAV_CERT_FILE=./cert.pem
NAV_KEY_FILE=./key.pem
PDF_API_URL=http://localhost:8001

# invoice-file-filter
ATTACHMENT_DOWNLOADER_URL=http://localhost:8000
DEFAULT_DAYS_BACK=30

# attachment-downloader
GMAIL_CREDENTIALS_FILE=./credentials.json
DEFAULT_OUTPUT_DIR=./downloads/

# wise
WISE_API_KEY=<wise-api-key>
WISE_ACCOUNT_ID=<wise-account-id>
DEFAULT_DAYS_BACK=30

# vision
INVOICE_CORE_URL=http://localhost:8004
SRCPROFIT_URL=https://srcprofit2.graphtrek.co
SRCPROFIT_USER=admin
SRCPROFIT_PASSWORD=<titkos>
```

---

## 📊 Adatfolyam

### Request → Response Lánc
```
1. Invoice-Core: POST /api/v1/sync
   ├─ (request params: start_date, end_date)
   │
   ├─ → NAV API: GET /invoices?from=...&to=...&direction=...  (invoice-core-tól)
   │       ↩ Return: [InvoiceDigest, ...]
   │
   └─ → PDF Feldolgozó: POST /api/v1/invoices/extract       (invoice-core-tól)
           ↓
         Gmail Letöltő: POST /api/v1/jobs                   (invoice-file-filter-tól)
           ↩ Return: {job_id, status}
         Gmail Letöltő: GET /api/v1/jobs/{job_id}
           ↩ Return: {downloaded_files: [...]}
         PDF szöveg indexelés (OCR/Regex)
           ↩ Return: letöltött PDF fájlok szövegindexe
   ↩
2. Invoice-Core ← Insert: invoice_file (minden PDF nyers adat)
   └─ Merge (words-alapú): minden NAV számlaszámhoz
         GET /api/v1/invoices/search?words=<számlaszám>      (invoice-core → invoice-file-filter)
           ↩ Return: {filename, invoice_file_id} vagy null
   └─ Insert: supplier / customer (NAV adatok alapján)
   └─ Insert: invoice (invoice_file_id FK-val ha volt egyezés)

3. Wise ág:
   └─ → Wise: GET /balance-statements                        (invoice-core-tól, paraméter nélkül)
         ↩ Return: StatementImport — mai naphoz legközelebbi kivonat tranzakciói
   └─ Insert: wise_transaction (idempotens: wise_transaction_id ellenőrzés)
   └─ Return: {sync_result, invoice_count, wise_transaction_count, errors}
```

---

## 🔗 Wiki Linkek Összefoglalása

### Service Links
- **MASTER**: [[invoice-core-spec.md|invoice-core]] → hívja → [[nav-invoice-spec.md|nav-invoice]] (levél)
- **MASTER**: [[invoice-core-spec.md|invoice-core]] → hívja → [[invoice-file-filter-spec.md|invoice-file-filter]]
- **PDF ág**: [[invoice-file-filter-spec.md|invoice-file-filter]] → hívja → [[attachment-downloader-spec.md|attachment-downloader]] (levél)
- **MASTER**: [[invoice-core-spec.md|invoice-core]] → hívja → [[wise-spec.md|wise]] (levél — csak Wise API)
- **AGGREGÁTOR**: [[vision-spec.md|vision]] → olvassa → [[invoice-core-spec.md|invoice-core]] REST API + SrcProfit

### Prompt Links
- [[invoice-core-prompt.md|Invoice-Core Prompt]]
- [[nav-invoice-prompt.md|NAV Invoice Prompt]]
- [[invoice-file-filter-prompt.md|PDF Feldolgozó Prompt]]
- [[attachment-downloader-prompt.md|Attachment Downloader Prompt]]
- [[wise-prompt.md|Wise Prompt]]
- [[vision-prompt.md|Vision Prompt]]

---

**Utolsó frissítés**: 2026-06-18
