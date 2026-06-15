---
title: "Specifikáció: Számla Adatbázis Mikroszerviz"
description: "Számlákat és partnereket kezelő adatbázis mikroszerviz (MASTER orchestrator)"
language: "HU"
last_updated: "2026-06-09"
related: [INDEX.md, nav-invoice-spec.md, wise-spec.md]
---

# Számla Adatbázis Mikroszerviz - Specifikáció

> 🔗 **Hívási Lánc**: **←** [[nav-invoice-spec.md|NAV API]]

---

## Szerepkör és kontextus
Te egy Backend Orchestrációs Mérnök vagy. A feladatod a Moneypenny automata számlázási rendszer szíveként koordináld a mikroszervizek összes interakcióját. Ez a szolgáltatás a kritikus adatbázis hub, amely garantálja a szállító, vevő és számlainformációk konzisztenciáját a teljes rendszerben, biztosítva az idempotenciát és az adatintegritást.

## Funkció (MASTER HUB)
- **Meghívja: nav-invoice** (NAV lekérdezés — csak a NAV API-t hívja)
- **Meghívja: invoice-file-filter** (PDF feldolgozás — az meghívja attachment-downloadert)
- **Meghívja: wise** (pénzügyi tranzakciók lekérése)
- Vevő és szállító táblákat létrehozza nav-invoice adatai alapján
- invoice-file-filter visszaadott adatait külön `invoice_file` táblában tárolja
- `invoice_file` rekordokat összeköti az `invoice` táblával (words-alapú számlaszám egyezés)
- wise tranzakciókat `wise_transaction` táblában tárolja, összeköti `supplier`/`customer`/`invoice` táblákkal
- Teljes invoice-supplier-customer-wise_transaction összekapcsolás

## Request paraméterek
- `start_date` (optional) - szűrés kezdete (default: 30 nappal ezelőtt)
- `end_date` (optional) - szűrés vége (default: ma)
- `sync_mode` (optional) - sync típusa (full|nav_only|pdf_only|wise_only)

## Táblák
### invoice (számlák)
- id (PK)
- invoice_number (nav_invoice-tól)
- invoice_date
- supplier_id (FK → supplier)
- customer_id (FK → customer)
- amount_net, amount_vat, amount_total
- payment_status (PAID|UNPAID|PARTIAL)
- nav_transaction_id
- invoice_file_id (FK → invoice_file, nullable: ha nincs PDF egyezés)
- created_at, updated_at

### invoice_file (invoice-file-filter visszaadott adatok)
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

### wise_transaction (Wise pénzügyi tranzakciók)
- id (PK)
- wise_transaction_id (külső azonosító, idempotencia)
- amount
- currency
- transaction_date
- description
- supplier_id (FK → supplier, nullable)
- customer_id (FK → customer, nullable)
- invoice_id (FK → invoice, nullable)
- created_at, updated_at

## Logika (Orchestration)
1. **invoice-core iniciál** → sorban:
   - **nav-invoice** meghívása (GET /invoices?from=...&to=...&direction=...)
     - nav-invoice csak a NAV API-t hívja, visszaad: számlalista, supplier/customer adatok
   - **invoice-file-filter** meghívása (POST /api/v1/invoices/extract)
     - invoice-file-filter meghívja attachment-downloadert (Gmail PDF letöltés)
     - visszaad: letöltött PDF fájlok szövegindexe
2. **Merge** (words-alapú kereséssel):
   - Minden nav-invoice számlaszámhoz: `GET /api/v1/invoices/search?words=<számlaszám>`
     → invoice-file-filter megkeresi, melyik PDF fájl tartalmazza a számlaszám szövegét
   - Egyezés esetén a PDF metaadatait (összeg, partner, dátum) linkeli a NAV rekordhoz
3. **DB mentés**:
   - `invoice_file`: invoice-file-filter nyers visszaadott adatai (minden PDF rekord)
   - `supplier` / `customer`: partner adatok (nav-invoice alapján)
   - `invoice`: NAV számlák, `invoice_file_id` FK-val ha volt words-egyezés

4. **Wise szinkron** (független a NAV/PDF ágaktól):
   - **wise** meghívása: `GET /balance-statements` (paraméter nélkül)
     → visszaad: `StatementImport` — a mai naphoz legközelebbi `to_date`-tel rendelkező CSV tranzakciói
   - `wise_transaction` mentése (idempotens: `wise_transaction_id` duplikátum-ellenőrzés)
   - `supplier` / `customer` létrehozás ha még nem létezik (Wise partner adatok alapján)
   - `invoice_id` összekapcsolás összeg + dátum alapján (ha van egyező NAV számla)
   > **Megjegyzés**: a `POST /sync` (élő Wise API hívás) egyelőre nem működik — a CSV import az aktív integrációs út.

## Interface
- **CLI**:
  - `invoice-core sync` - teljes szinkronizálás (NAV + PDF + Wise)
  - `invoice-core sync-nav` - NAV adatok szinkronizálása
  - `invoice-core sync-pdf` - PDF adatok szinkronizálása
  - `invoice-core sync-wise` - Wise tranzakciók szinkronizálása
  - `invoice-core report --month 2026-05` - havi kimutatás
- **REST API**:
  - `POST /api/v1/sync` - teljes szinkronizálás
  - `POST /api/v1/sync/nav` - NAV adatok szinkronizálása
  - `POST /api/v1/sync/pdf` - PDF adatok szinkronizálása
  - `POST /api/v1/sync/wise` - Wise tranzakciók szinkronizálása
  - `GET /api/v1/invoices` - számlalista (szűrés: dátum, partner, status)
  - `GET /api/v1/invoices/{invoice_number}` - egy számla adatai
  - `GET /api/v1/partners/suppliers` - szállítólista
  - `GET /api/v1/partners/customers` - vevőlista
  - `GET /api/v1/transactions` - Wise tranzakciók listája

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

### Wiki linkek
- **Prompt**: [[invoice-core-prompt.md|Invoice-Core Prompt]]
- **MASTER Orchestrator**: Ez a szerviz
- **Meghívja**: [[nav-invoice-spec.md|NAV API Specifikáció]]
  - NAV lekérdezés: `GET /invoices`, `GET /invoices/{szamlaszam}`
  - 30 nap default paraméterrel
- **Meghívja**: [[invoice-file-filter-spec.md|PDF Feldolgozó Specifikáció]]
  - PDF letöltés + indexelés: `POST /api/v1/invoices/extract`
  - Words keresés: `GET /api/v1/invoices/search?words=<számlaszám>` (melyik PDF fájl tartalmazza a szót)
  - invoice-file-filter maga hívja attachment-downloadert a PDF letöltéshez
- **Meghívja**: [[wise-spec.md|Wise Integráció Specifikáció]]
  - `GET /balance-statements` (paraméter nélkül) — legfrissebb kivonat tranzakciói
  - Levél szolgáltatás — DB-t nem kezel (`POST /sync` egyelőre nem működik)
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]
