---
title: "Moneypenny - Projekt Index"
description: "Számlázási és email feldolgozási mikorszervízek - wiki navigáció"
language: "HU"
last_updated: "2026-06-09"
---

# 📚 Moneypenny - Wiki Index

## Összefoglalás

A **Moneypenny** egy négy Python mikroszervizből álló számla-automatizálási rendszer, amely a Graphtrek számlázási folyamatát digitalizálja. A rendszer Gmail-fiókból tölti le a PDF számlamellékleteket, OCR/Regex segítségével kinyeri a metaadatokat, lekérdezi a számlák adatait a NAV Online Számla API-ból, majd mindent egy PostgreSQL adatbázisba ment, szállítói és vevői adatokkal összekapcsolva.

| #   | Mikroszerviz      | Port | Szerep                                               |
| --- | ----------------- | ---- | ---------------------------------------------------- |
| 4   | `szamla-db`       | 8003 | MASTER orchestrator – DB persistálás, reconciliation |
| 3   | `nav-szamla`      | 8002 | NAV Online Számla API lekérdezés                     |
| 2   | `pdf-szamla`      | 8001 | PDF metaadat kinyerés (OCR/Regex)                    |
| 1   | `graphtrek-email` | 8000 | Gmail PDF mellékletek letöltése                      |
| 5   | `wise`            | 8004 | Wise bankkivonatok letöltése és szinkronizálása      |

Belépési pont: `POST /api/v1/sync` → `szamla-db` (8003). Minden mikroszerviznek van FastAPI REST interfésze és Typer CLI-je is.

---

## 🔗 Hívási Lánc (Szinkron)

```
MASTER ORCHESTRATOR
        ↓
    szamla-db
     (init)
        ↓
 meghívja: nav-szamla
        ↓
 meghívja: pdf-szamla
        ↓
 meghívja: graphtrek-email
        ↓
    (végpont)
```

---

## 📋 Mikorszervízek Wiki

### 4️⃣ MASTER - Számla Adatbázis
**[[szamla-db-spec.md|📄 Specifikáció]]** | **[[szamla-db-prompt.md|💭 Prompt]]**

- **Szerepe**: Orchestrator (szinkronizálás indítása)
- **Meghívja**: [[nav-szamla-spec.md|NAV API]] (utolsó 30 nap)
- **Funkció**: Összes adat persistálása + partnerek kezelése
- **Output**: PostgreSQL DB (invoices, suppliers, customers)
- **REST**: `POST /api/v1/sync` → teljes szinkronizálás

---

### 3️⃣ NAV Online Számla API
**[[nav-szamla-spec.md|📄 Specifikáció]]** | **[[nav-számla-prompt.md|💭 Prompt]]**

- **Meghívva**: [[szamla-db-spec.md|szamla-db]] által
- **Meghívja**: [[pdf-szamla-spec.md|PDF Feldolgozó]]
- **Funkció**: NAV Online Számla lekérdezés
- **Output**: NAV adatok + supplier/customer info
- **REST**: `GET /api/v1/invoices/{invoice_number}`

---

### 2️⃣ PDF Számla Feldolgozó
**[[pdf-szamla-spec.md|📄 Specifikáció]]** | **[[pdf-szamla-prompt.md|💭 Prompt]]**

- **Meghívva**: [[nav-szamla-spec.md|nav-szamla]] által
- **Meghívja**: [[graphtrek-email-spec.md|Gmail Letöltő]]
- **Funkció**: PDF metaadatok kinyerése (OCR/Regex)
- **Input**: graphtrek-email API (utolsó 30 nap)
- **Output**: Invoice metadata (szám, dátum, összeg, partner)
- **REST**: `POST /api/v1/invoices/extract`

---

### 1️⃣ Gmail PDF Letöltő
**[[graphtrek-email-spec.md|📄 Specifikáció]]** | **[[graphtrek-email-prompt.md|💭 Prompt]]**

- **Meghívva**: [[pdf-szamla-spec.md|pdf-szamla]] által
- **Funkció**: Email PDF mellékleteket letölt
- **Dátum szűrés**: YYYY-MM-DD intervallum
- **Output**: `./downloads/YYYY-MM-DDD_filename.pdf`
- **REST**: `POST /api/v1/jobs` (async job)

---

### 5️⃣ Wise Bankkivonatok Integráció
**[[wise-spec.md|📄 Specifikáció]]** | **[[wise-prompt.md|💭 Prompt]]**

- **Szerepe**: Adatbeolvasási híd a Wise API és a [[szamla-db-spec.md|szamla-db]] között
- **Független belépési pont**: Saját `POST /sync` indítja (nem a szamla-db hívja)
- **Funkció**: Wise tranzakciók letöltése és közvetlen írás a `szamla-db` PostgreSQL példányába
- **Input**: Wise API (`start_date`/`end_date` dátumintervallum szűrés)
- **Mapolás**: összeg+pénznem → `invoices.amount_total`, partner → `suppliers`/`customers`, dátum → `invoices.invoice_date`
- **Idempotencia**: duplikátum-ellenőrzés beszúrás előtt
- **REST**: `GET /health`, `POST /sync`, `GET /transactions/{transaction_id}`
- **CLI**: `sync`, `list-transactions --last <n>`, `status`

---

## 🎯 Projekt Áttekintés

```
Hívási Lánc (Szinkron):
┌────────────────────────────────────────┐
│  4. SZAMLA-DB (MASTER)                 │
│  ├─ Meghívja: nav-szamla (30 nap)     │
│  └─ Persistálás: DB                    │
└────────────────────────────────────────┘
                  ↓
┌────────────────────────────────────────┐
│  3. NAV API                            │
│  ├─ NAV Online Számla query            │
│  ├─ Meghívja: pdf-szamla               │
│  └─ Output: NAV adatok                 │
└────────────────────────────────────────┘
                  ↓
┌────────────────────────────────────────┐
│  2. PDF FELDOLGOZÓ                     │
│  ├─ Metaadatok kinyerése               │
│  ├─ Meghívja: graphtrek-email (30 nap) │
│  └─ Output: Invoice metadata           │
└────────────────────────────────────────┘
                  ↓
┌────────────────────────────────────────┐
│  1. GMAIL LETÖLTŐ (Végpont)            │
│  ├─ Email PDF letöltés                 │
│  └─ Output: PDF fájlok                 │
└────────────────────────────────────────┘
```

---

## 📁 Fájl Navigáció

### Specifikációk
- **szamla-db**: [[szamla-db-spec.md|spec]] (MASTER orchestrator)
- **nav-szamla**: [[nav-szamla-spec.md|spec]] (NAV query)
- **pdf-szamla**: [[pdf-szamla-spec.md|spec]] (PDF extract)
- **graphtrek-email**: [[graphtrek-email-spec.md|spec]] (Gmail download)
- **wise**: [[wise-spec.md|spec]] (Bankkivonatok integráció)

### Promptok
- **szamla-db**: [[szamla-db-prompt.md|prompt]]
- **nav-szamla**: [[nav-számla-prompt.md|prompt]]
- **pdf-szamla**: [[pdf-szamla-prompt.md|prompt]]
- **graphtrek-email**: [[graphtrek-email-prompt.md|prompt]]
- **wise**: [[wise-prompt.md|prompt]]

---

## 🔍 Hívási Sorrend Részletezve

### Initiation (Szamla-DB)
```
Client
  ↓
POST /api/v1/sync (szamla-db)
  └─ start_date: "2026-05-01" (default: last 30 days)
  └─ end_date: "2026-05-31"
```

### Chain Calls (Szinkron)
```
1. szamla-db.sync()
   ├─ nav_szamla.query(start_date, end_date)
   │   └─ Létrehozza: suppliers/customers táblákat
   │   └─ pdf_szamla.extract()
   │       └─ graphtrek_email.jobs() meghívása
   │           └─ Gmail API query (PDF letöltés)
   │           └─ PDF-ek letöltése (30 nap)
   │       └─ PDF metadata kinyerés
   │       └─ Return: {invoice_number, supplier_tax_id, amount, ...}
   │   └─ Return: {nav_status, received_at, ...}
   └─ Merge: PDF + NAV adatok
   └─ Insert: invoices tábla (reconciliation)
   └─ Return: Sync results
```

---

## 🚀 Fejlesztési Sorrend

1. **[[graphtrek-email-spec.md|Gmail Letöltő]]** - OAuth2, PDF API
2. **[[pdf-szamla-spec.md|PDF Feldolgozó]]** - OCR/Regex, graphtrek-email integrálás
3. **[[nav-szamla-spec.md|NAV API]]** - NAV query, pdf-szamla integrálás
4. **[[szamla-db-spec.md|Szamla-DB]]** - DB orchestration, reconciliation
5. **[[wise-spec.md|Wise Integráció]]** - Wise API, közvetlen szamla-db PostgreSQL írás

---

## 📡 API Porток (Dev)

| Service         | Port | Endpoint                |
| --------------- | ---- | ----------------------- |
| graphtrek-email | 8000 | `http://localhost:8000` |
| pdf-szamla      | 8001 | `http://localhost:8001` |
| nav-szamla      | 8002 | `http://localhost:8002` |
| szamla-db       | 8003 | `http://localhost:8003` |
| wise            | 8004 | `http://localhost:8004` |

---

## 🔐 Environment Variables

```bash
# szamla-db
SZAMLA_DB_URL=postgresql://user:pass@localhost/invoices
NAV_API_URL=http://localhost:8002
PDF_API_URL=http://localhost:8001
DEFAULT_DAYS_BACK=30

# nav-szamla
NAV_CERT_FILE=./cert.pem
NAV_KEY_FILE=./key.pem
PDF_API_URL=http://localhost:8001

# pdf-szamla
GRAPHTREK_EMAIL_URL=http://localhost:8000
DEFAULT_DAYS_BACK=30

# graphtrek-email
GMAIL_CREDENTIALS_FILE=./credentials.json
DEFAULT_OUTPUT_DIR=./downloads/

# wise
WISE_API_KEY=<wise-api-key>
WISE_ACCOUNT_ID=<wise-account-id>
SZAMLA_DB_URL=postgresql://user:pass@localhost/invoices
DEFAULT_DAYS_BACK=30
```

---

## 📊 Adatfolyam

### Request → Response Lánc
```
1. Szamla-DB: POST /api/v1/sync
   ↓ (request params: start_date, end_date)
2. NAV API: GET /api/v1/invoices (szamla-db-tól)
   ↓
3. PDF Feldolgozó: POST /api/v1/invoices/extract (nav-szamla-tól)
   ↓
4. Gmail Letöltő: POST /api/v1/jobs (pdf-szamla-tól)
   ↓ (Response)
4. Gmail ← Return: {job_id, status}
   ↓
3. PDF Feldolgozó ← Hívja: GET /api/v1/jobs/{job_id}
   ├─ Return: {downloaded_files: [...]}
   └─ Extract metadata
   ↓
2. NAV API ← Return: {invoices: [...], pdf_metadata: {...}}
   ↓
1. Szamla-DB ← Return: Merge + DB insert
   └─ Return: {sync_result, invoices_count, errors}
```

---

## 🔗 Wiki Linkek Összefoglalása

### Service Links
- **MASTER**: [[szamla-db-spec.md|szamla-db]] → hívja → [[nav-szamla-spec.md|nav-szamla]]
- **Second**: [[nav-szamla-spec.md|nav-szamla]] → hívja → [[pdf-szamla-spec.md|pdf-szamla]]
- **Third**: [[pdf-szamla-spec.md|pdf-szamla]] → hívja → [[graphtrek-email-spec.md|graphtrek-email]]
- **Endpoint**: [[graphtrek-email-spec.md|graphtrek-email]] (No outgoing calls)
- **Alternate Source**: [[wise-spec.md|wise]] → közvetlenül írja a [[szamla-db-spec.md|szamla-db]] PostgreSQL-jét (önálló belépési pont)

### Prompt Links
- [[szamla-db-prompt.md|szamla-db-prompt.md]]
- [[nav-számla-prompt.md|nav-számla-prompt.md]]
- [[pdf-szamla-prompt.md|pdf-szamla-prompt.md]]
- [[graphtrek-email-prompt.md|graphtrek-email-prompt.md]]
- [[wise-prompt.md|wise-prompt.md]]

---

**Utolsó frissítés**: 2026-06-10
