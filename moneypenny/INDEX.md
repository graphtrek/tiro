---
title: "Moneypenny - Projekt Index"
description: "Számlázási, banki és tulajdonosi AI mikorszervízek - wiki navigáció"
language: "HU"
last_updated: "2026-06-24"
---

# 📚 Moneypenny - Wiki Index

## Összefoglalás

A **Moneypenny** egy hat Python mikroszervizből álló pénzügyi automatizálási rendszer, amely a Graphtrek számlázási és vagyonkezelési folyamatát digitalizálja. A rendszer Gmail-fiókból tölti le a PDF számlamellékleteket, OCR/Regex segítségével kinyeri a metaadatokat, lekérdezi a számlák adatait a NAV Online Számla API-ból, letölti az Erste és Wise banki tranzakciókat, majd mindent egy PostgreSQL adatbázisba ment, szállítói, vevői és tranzakció adatokkal összekapcsolva. A **Vision** szerviz tulajdonosi dashboardon aggregálja az invoice-core és SrcProfit (IBKR) adatait.

| #   | Mikroszerviz            | Port | Szerep                                                                     |
| --- | ----------------------- | ---- | -------------------------------------------------------------------------- |
| 5   | `invoice-core`          | 8004 | MASTER orchestrator – DB persistálás, reconciliation (tiszta REST backend) |
| 3   | `nav-invoice`           | 8002 | NAV Online Számla API lekérdezés                                           |
| 2   | `invoice-file-filter`   | 8001 | PDF metaadat kinyerés (OCR/Regex)                                          |
| 1   | `attachment-downloader` | 8000 | Gmail PDF mellékletek letöltése                                            |
| 4   | `bank`                  | 8005 | Erste + Wise CSV konszolidáció – egységes bankkivonat API                  |
| 7   | `uploader`              | 8006 | CSV bankkivonat feltöltés a bank storage mappájába; UI a vision-ben        |
| 6   | `vision`                | 8009 | Frontend – teljes webes UI + SrcProfit (IBKR) aggregáció                  |

Belépési pont (szinkron): `POST /api/v1/sync` → `invoice-core` (8004). Az 1–5. mikroszerviznek FastAPI REST interfésze és Typer/Click CLI-je is van. A `vision` (6.) a frontend szerviz: fogyasztja az invoice-core REST API-t, és kiszolgálja az összes UI oldalt (`/ui/*`). CLI nélkül.

---

## 🔗 Hívási Lánc (Szinkron)

```
MASTER ORCHESTRATOR
        ↓
    invoice-core
     (init)
      ├──────────────────┬──────────────────┐
      ↓                  ↓                  ↓
 nav-invoice         invoice-file-filter   bank
 (NAV API)               ↓             (Erste+Wise CSV)
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

> `invoice-core` mindhárom ágat közvetlenül hívja. `invoice-file-filter` → `attachment-downloader` lánc a PDF-letöltési ág. A `vision` a frontend szerviz — fogyasztja az invoice-core REST API-t, kiszolgálja az összes UI oldalt; nem része a sync láncnak.

---

## 📋 Mikorszervízek Wiki

### 4️⃣ MASTER - Számla Adatbázis
**[[invoice-core-spec.md|📄 Specifikáció]]** | **[[invoice-core-prompt.md|💭 Prompt]]** | **[[invoice-core-ui-prompt.md|🖥️ UI Prompt]]** | **[[invoice-core-ui-spec.md|🖥️ UI Spec]]**

- **Szerepe**: Orchestrator (szinkronizálás indítása)
- **Meghívja**: [[nav-invoice-spec.md|NAV API]], [[invoice-file-filter-spec.md|invoice-file-filter]], [[bank-spec.md|bank]]
- **Funkció**: Összes adat persistálása + partnerek kezelése
- **Output**: PostgreSQL DB (invoice, invoice_file, supplier, customer, bank_transaction)
- **REST**: `POST /api/v1/sync` → teljes szinkronizálás (NAV + PDF + Bank)

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

### 4️⃣ Bank Konszolidált Kivonat Mikroszerviz
**[[bank-spec.md|📄 Specifikáció]]** | **[[bank-prompt.md|💭 Prompt]]**

- **Meghívva**: [[invoice-core-spec.md|invoice-core]] által
- **Meghívja**: (senki — CSV fájlokat olvas, DB-t nem kezel)
- **Funkció**: Erste és Wise kézzel letöltött CSV kivonatok egységes feldolgozása, konszolidált tranzakció lista visszaadása
- **Input**: `balance-statements/erste/` és `balance-statements/wise/` mappa CSV fájljai
- **Output**: `BankStatement` / `ConsolidatedStatement` (JSON) — DB-t nem kezel
- **REST** (port 8005): `GET /health`, `GET /balance-statements`, `GET /balance-statement/{bank}`, `GET /balance-statement/all`
- **CLI**: `bank status`, `bank list`, `bank import <filename>`, `bank statements`

---

### 7️⃣ Uploader – Bankkivonat Feltöltő
**[[uploader-spec.md|📄 Specifikáció]]** | **[[uploader-promp.md|💭 Prompt]]**

- **Meghívva**: böngészőből, a vision `/ui/upload` oldalán keresztül
- **Meghívja**: (senki — csak fájlrendszert kezel)
- **Funkció**: Erste / Wise CSV bankkivonatok feltöltése, bankdetektálás fájlnévből, mentés a bank szerviz storage mappájába
- **Saját DB**: nincs — leaf szerviz, fájlrendszer I/O
- **REST** (port 8006): `GET /health`, `GET /api/v1/files`, `POST /api/v1/upload`, `DELETE /api/v1/files/{bank}/{filename}`
- **CLI**: `uploader status`, `uploader list`, `uploader upload <fájl>`, `uploader delete`

---

### 6️⃣ Vision – Frontend
**[[vision-spec.md|📄 Specifikáció]]** | **[[vision-prompt.md|💭 Prompt]]**

- **Meghívva**: (senki — böngészőből nyitják)
- **Meghívja**: [[invoice-core-spec.md|invoice-core]] REST API (olvas) + [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR, olvas)
- **Funkció**: Teljes Moneypenny frontend — az összes `/ui/*` oldalt kiszolgálja, fogyasztja az invoice-core REST API-t; plusz saját tulajdonosi portfólió dashboard (Chart.js, IBKR)
- **Saját DB**: nincs — tiszta frontend, read-only aggregátor
- **REST** (port 8009): `GET /health`, `GET /` (koncepcióoldal), `GET /dashboard` (portfólió), `GET /ui/*` (összes Moneypenny UI oldal)
- **CLI**: nincs

---

## 🎯 Projekt Áttekintés

```
Hívási Lánc (Szinkron):
┌──────────────────────────────────────────────────────┐
│  4. SZAMLA-DB (MASTER)                               │
│  ├─ Meghívja: nav-invoice                             │
│  ├─ Meghívja: invoice-file-filter                    |
│  ├─ Meghívja: bank                                   │
│  └─ Persistálás + Merge: DB                          │
└──────────────────────────────────────────────────────┘
         ↓                   ↓                        ↓
┌──────────────┐ ┌───────────────────---──---─┐  ┌────────────-──┐
│  3. NAV API  │ │  2. PDF FELDOLGOZÓ         │  │  4. BANK      │
│  ├─ NAV query│ │  ├─ PDF indexelés          │  │  ├─ Erste CSV │
│  └─ Levél    │ │  └─ → attachment-downloader│  │  └─ Wise CSV  │
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
- **bank**: [[bank-spec.md|spec]] (Erste + Wise CSV konszolidáció)
- **uploader**: [[uploader-spec.md|spec]] (CSV feltöltés a bank storage mappájába)
- **vision**: [[vision-spec.md|spec]] (Tulajdonosi AI dashboard)

### Promptok
- **invoice-core**: [[invoice-core-prompt.md|prompt]] | [[invoice-core-ui-prompt.md|UI prompt]] | [[invoice-core-ui-spec.md|UI spec]]
- **nav-invoice**: [[nav-invoice-prompt.md|prompt]]
- **invoice-file-filter**: [[invoice-file-filter-prompt.md|prompt]]
- **attachment-downloader**: [[attachment-downloader-prompt.md|prompt]]
- **bank**: [[bank-prompt.md|prompt]]
- **uploader**: [[uploader-promp.md|prompt]]
- **vision**: [[vision-prompt.md|prompt]]

---

## 🔍 Hívási Sorrend Részletezve

```mermaid
flowchart TD
    C[Client] -->|POST /api/v1/sync| SD[invoice-core :8004]
    SD -->|GET /invoices| NAV[nav-invoice :8002]
    NAV -->|InvoiceDigest| SD
    SD -->|POST /api/v1/invoices/extract| IFF[invoice-file-filter :8001]
    IFF -->|POST /api/v1/jobs| AD[attachment-downloader :8000]
    AD -->|PDF fájlok| IFF
    IFF -->|extracted metadata| SD
    SD -->|GET /balance-statement/all| BK[bank :8005]
    BK -->|ConsolidatedStatement| SD
    SD -->|upsert| DB[(PostgreSQL)]
    DB -->|SyncResult| C

    B[Böngésző] -->|GET /ui/upload| V[vision :8009]
    V -->|POST /api/v1/upload| UP[uploader :8006]
    UP -->|write CSV| FS[(balance-statements/erste/ wise/)]
    BK -->|read CSV| FS
```

### Szinkronizálási lánc (invoice-core vezérli)

**Belépési pont:**
```
Client
  ↓
POST /api/v1/sync (invoice-core :8004)
  └─ start_date: "2026-05-01" (default: last 30 days)
  └─ end_date: "2026-05-31"
```

**Lépések (szinkron, sorrendben):**
```
1. sync_nav — NAV Online Számla lekérdezés
   └─ nav-invoice: GET /invoices?from_date=...&to_date=...&direction=OUTBOUND
       └─ Return: InvoiceDigest[], supplier/customer adatok
   └─ DB: upsert invoice, supplier, customer

2. sync_pdf — Gmail PDF mellékletek letöltése + metaadat kinyerés
   └─ invoice-file-filter: POST /api/v1/invoices/extract
       └─ attachment-downloader: POST /api/v1/jobs  [szinkron, Gmail OAuth2]
           └─ Return: {total_files, files: [{filename, saved_path, ...}]}
       └─ OCR/Regex feldolgozás
       └─ Return: extracted invoice metadata
   └─ DB: upsert invoice_file; link invoice ↔ file számlaszám alapján

3. sync_bank — Bankkivonatok beolvasása
   └─ bank: GET /balance-statement/all  [levél — balance-statements/ CSV-ket olvas]
       └─ Return: ConsolidatedStatement (Erste + Wise tranzakciók)
   └─ DB: upsert bank_transaction (idempotens: transaction_id); link invoice ↔ transaction

4. sync_match — Kereszt-összekapcsolás
   └─ Tranzakció → invoice_file → invoice lánc meghatározása
   └─ Linked invoice → PAID státusz beállítás
```

### Uploader lánc (felhasználó indítja, szinkrontól független)

```
Böngésző
  ↓
GET /ui/upload  (vision :8009)
  └─ UploaderClient.list_files() → GET /api/v1/files  (uploader :8006)
  └─ Render: upload.html (drag & drop + fájllista)

Feltöltés:
  ↓
POST /ui/upload/do  (vision)
  └─ UploaderClient.upload_file(bytes, filename)
      └─ POST /api/v1/upload  (uploader :8006)
          ├─ Bankdetektálás: statement_* → wise | dátummintás → erste
          ├─ Fájl mentés: balance-statements/{bank}/{filename}.csv
          └─ Return: UploadResult {filename, bank, saved_path, size_bytes, overwritten}
  └─ HTMX partial frissítés: GET /ui/upload/files → fájllista újratöltése

Törlés:
  ↓
DELETE /ui/upload/files/{bank}/{filename}  (vision)
  └─ DELETE /api/v1/files/{bank}/{filename}  (uploader :8006)
      └─ Fájl törlése a storage-ból

Megjegyzés: Az uploader által mentett CSV fájlokat a bank szerviz olvassa
be automatikusan a következő sync_bank híváskor.
```

---

## 🚀 Fejlesztési Sorrend

1. **[[attachment-downloader-spec.md|Gmail Letöltő]]** - OAuth2, PDF API
2. **[[invoice-file-filter-spec.md|PDF Feldolgozó]]** - OCR/Regex, attachment-downloader integrálás
3. **[[nav-invoice-spec.md|NAV API]]** - NAV query, invoice-file-filter integrálás
4. **[[bank-spec.md|Bank Integráció]]** - CSV import, balance-statements végpont (invoice-core hívja)
5. **[[invoice-core-spec.md|Invoice-Core]]** - DB orchestration, reconciliation (utolsó: mindenkit integrál)
6. **[[vision-spec.md|Vision Frontend]]** - teljes UI frontend (invoice-core REST API + SrcProfit), HTMX + Bootstrap + Chart.js

---

## 📡 API Portok (Dev)

| Service               | Port | Endpoint                |
| --------------------- | ---- | ----------------------- |
| attachment-downloader | 8000 | `http://localhost:8000` |
| invoice-file-filter   | 8001 | `http://localhost:8001` |
| nav-invoice           | 8002 | `http://localhost:8002` |
| bank                  | 8005 | `http://localhost:8005` |
| uploader              | 8006 | `http://localhost:8006` |
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

# bank
BALANCE_STATEMENTS_DIR=./balance-statements

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

3. Bank ág:
   └─ → Bank: GET /balance-statement/all                      (invoice-core-tól, paraméter nélkül)
         ↩ Return: ConsolidatedStatement — Erste + Wise tranzakciók
   └─ Insert: bank_transaction (idempotens: transaction_id ellenőrzés)
   └─ Return: {sync_result, invoice_count, bank_transaction_count, errors}
```

---

## 🔗 Wiki Linkek Összefoglalása

### Service Links
- **MASTER**: [[invoice-core-spec.md|invoice-core]] → hívja → [[nav-invoice-spec.md|nav-invoice]] (levél)
- **MASTER**: [[invoice-core-spec.md|invoice-core]] → hívja → [[invoice-file-filter-spec.md|invoice-file-filter]]
- **PDF ág**: [[invoice-file-filter-spec.md|invoice-file-filter]] → hívja → [[attachment-downloader-spec.md|attachment-downloader]] (levél)
- **MASTER**: [[invoice-core-spec.md|invoice-core]] → hívja → [[bank-spec.md|bank]] (levél — Erste + Wise CSV)
- **FRONTEND**: [[vision-spec.md|vision]] → olvassa → [[invoice-core-spec.md|invoice-core]] REST API + SrcProfit; kiszolgálja az összes `/ui/*` oldalt

### Prompt Links
- [[invoice-core-prompt.md|Invoice-Core Prompt]]
- [[nav-invoice-prompt.md|NAV Invoice Prompt]]
- [[invoice-file-filter-prompt.md|PDF Feldolgozó Prompt]]
- [[attachment-downloader-prompt.md|Attachment Downloader Prompt]]
- [[bank-prompt.md|Bank Prompt]]
- [[vision-prompt.md|Vision Prompt]]

---

**Utolsó frissítés**: 2026-06-24
