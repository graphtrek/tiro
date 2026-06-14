---
title: "Specifikáció: Számla Adatbázis Mikroszerviz"
description: "Számlákat és partnereket kezelő adatbázis mikroszerviz (MASTER orchestrator)"
language: "HU"
last_updated: "2026-06-09"
related: [INDEX.md, nav-szamla-spec.md]
---

# Számla Adatbázis Mikroszerviz - Specifikáció

> 🔗 **Hívási Lánc**: **←** [[nav-szamla-spec.md|NAV API]]

---

## Szerepkör és kontextus
Te egy Backend Orchestrációs Mérnök vagy. A feladatod a Moneypenny automata számlázási rendszer szíveként koordináld a mikroszervizek összes interakcióját. Ez a szolgáltatás a kritikus adatbázis hub, amely garantálja a szállító, vevő és számlainformációk konzisztenciáját a teljes rendszerben, biztosítva az idempotenciát és az adatintegritást.

## Funkció (MASTER HUB)
- **Meghívja: nav-szamla** (NAV lekérdezés — levél szolgáltatás, csak NAV API-t hívja)
- **Meghívja: pdf-szamla** (PDF feldolgozás — az meghívja graphtrek-emailt)
- Vevő és szállító táblákat létrehozza nav-szamla adatai alapján
- pdf-szamla visszaadott adatait külön `invoice_file` táblában tárolja
- `invoice_file` rekordokat összeköti az `invoice` táblával (words-alapú számlaszám egyezés)
- Teljes invoice-supplier-customer összekapcsolás

## Request paraméterek
- `start_date` (optional) - szűrés kezdete (default: 30 nappal ezelőtt)
- `end_date` (optional) - szűrés vége (default: ma)
- `sync_mode` (optional) - sync típusa (full|nav_only|pdf_only)

## Táblák
### invoice (számlák)
- id (PK)
- invoice_number (nav_szamla-tól)
- invoice_date
- supplier_id (FK → supplier)
- customer_id (FK → customer)
- amount_net, amount_vat, amount_total
- payment_status (PAID|UNPAID|PARTIAL)
- nav_transaction_id
- invoice_file_id (FK → invoice_file, nullable: ha nincs PDF egyezés)
- created_at, updated_at

### invoice_file (pdf-szamla visszaadott adatok)
- id (PK)
- filename
- invoice_number_raw (PDF-ből kinyert számlaszám)
- invoice_date_raw
- supplier_name_raw
- supplier_tax_id_raw
- customer_name_raw
- customer_tax_id_raw
- amount_total_raw
- amount_vat_raw
- currency
- payment_due_raw
- confidence (0.0-1.0: OCR/kinyerés biztonsági szintje)
- created_at, updated_at

### supplier (szállítók)
- id (PK)
- name
- tax_id
- address, email, phone
- bank_account
- created_at, updated_at

### customer (vevők)
- id (PK)
- name
- tax_id
- address, email, phone
- payment_terms
- created_at, updated_at

## Logika (Orchestration)
1. **szamla-db iniciál** → sorban:
   - **nav-szamla** meghívása (GET /invoices?from=...&to=...&direction=...)
     - nav-szamla csak a NAV API-t hívja, visszaad: számlalista, supplier/customer adatok
   - **pdf-szamla** meghívása (POST /api/v1/invoices/extract)
     - pdf-szamla meghívja graphtrek-emailt (Gmail PDF letöltés)
     - visszaad: letöltött PDF fájlok szövegindexe
2. **Merge** (words-alapú kereséssel):
   - Minden nav-szamla számlaszámhoz: `GET /api/v1/invoices/search?words=<számlaszám>`
     → pdf-szamla megkeresi, melyik PDF fájl tartalmazza a számlaszám szövegét
   - Egyezés esetén a PDF metaadatait (összeg, partner, dátum) linkeli a NAV rekordhoz
3. **DB mentés**:
   - `invoice_file`: pdf-szamla nyers visszaadott adatai (minden PDF rekord)
   - `supplier` / `customer`: partner adatok (nav-szamla alapján)
   - `invoice`: NAV számlák, `invoice_file_id` FK-val ha volt words-egyezés

## Interface
- **CLI**:
  - `szamla-db sync` - teljes szinkronizálás (NAV + PDF)
  - `szamla-db sync-nav` - NAV adatok szinkronizálása
  - `szamla-db sync-pdf` - PDF adatok szinkronizálása
  - `szamla-db report --month 2026-05` - havi kimutatás
- **REST API**:
  - `POST /api/v1/sync` - teljes szinkronizálás
  - `POST /api/v1/sync/nav` - NAV adatok szinkronizálása
  - `POST /api/v1/sync/pdf` - PDF adatok szinkronizálása
  - `GET /api/v1/invoices` - számlalista (szűrés: dátum, partner, status)
  - `GET /api/v1/invoices/{invoice_number}` - egy számla adatai
  - `GET /api/v1/partners/suppliers` - szállítólist
  - `GET /api/v1/partners/customers` - vevőlista

## Tech stack
- Python 3.10+
- FastAPI, Typer, SQLAlchemy
- PostgreSQL (vagy SQLite dev)
- Pydantic

## Adatbázis
- PostgreSQL (prod) vagy SQLite (dev)
- Migrációk: Alembic

## Kapcsolódások

### Hívási sorrend
```
szamla-db (MASTER)
  ├─ meghívja: nav-szamla ←→ NAV Online Számla 3.0 API
  │   (levél szolgáltatás — nem hív tovább)
  │
  └─ meghívja: pdf-szamla
                   ↓ meghívja
             graphtrek-email ←→ Gmail API
                   (levél szolgáltatás)
```

### Wiki linkek
- **Prompt**: [[szamla-db-prompt.md|Szamla-DB Prompt]]
- **MASTER Orchestrator**: Ez a szerviz
- **Meghívja**: [[nav-szamla-spec.md|NAV API Specifikáció]]
  - NAV lekérdezés: `GET /invoices`, `GET /invoices/{szamlaszam}`
  - 30 nap default paraméterrel
- **Meghívja**: [[pdf-szamla-spec.md|PDF Feldolgozó Specifikáció]]
  - PDF letöltés + indexelés: `POST /api/v1/invoices/extract`
  - Words keresés: `GET /api/v1/invoices/search?words=<számlaszám>` (melyik PDF fájl tartalmazza a szót)
  - pdf-szamla maga hívja graphtrek-emailt a PDF letöltéshez
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]
