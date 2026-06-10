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
- **Meghívja: nav-szamla** (utolsó 30 nap default paraméterrel)
- nav-szamla → meghívja pdf-szamláta
- pdf-szamla → meghívja graphtrek-emailt
- Vevő és szállító táblákat létrehozza nav-szamla adatai alapján
- PDF-ből nyert metaadatokat összeköti nav-szamla táblákkal
- Teljes invoice-supplier-customer összekapcsolás

## Request paraméterek
- `start_date` (optional) - szűrés kezdete (default: 30 nappal ezelőtt)
- `end_date` (optional) - szűrés vége (default: ma)
- `sync_mode` (optional) - sync típusa (full|nav_only|pdf_only)

## Táblák
### invoices (számlák)
- id (PK)
- invoice_number (nav_szamla-tól)
- invoice_date
- supplier_id (FK)
- customer_id (FK)
- amount_net, amount_vat, amount_total
- payment_status (PAID|UNPAID|PARTIAL)
- nav_transaction_id
- pdf_metadata (JSON: pdf-szamla-tól)
- pdf_confidence (0.0-1.0: PDF feldolgozás biztonsági szintje)
- created_at, updated_at

### suppliers (szállítók)
- id (PK)
- name
- tax_id
- address, email, phone
- bank_account
- created_at, updated_at

### customers (vevők)
- id (PK)
- name
- tax_id
- address, email, phone
- payment_terms
- created_at, updated_at

## Logika (Orchestration)
1. **szamla-db iniciál** → meghívja nav-szamláta (utolsó 30 nap)
2. **nav-szamla** → meghívja pdf-szamláta
3. **pdf-szamla** → meghívja graphtrek-emailt
4. **graphtrek-email** → PDF-ek letöltése
5. **Válasz lánc** (visszafelé):
   - PDF metaadatok → nav-szamla
   - NAV adatok + PDF → szamla-db
6. **DB mentés**:
   - Suppliers/Customers (partner adatok)
   - Invoices (számlák)
   - Reconciliation (PDF + NAV merge)

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
  ↓ meghívja
nav-szamla
  ↓ meghívja
pdf-szamla
  ↓ meghívja
graphtrek-email
```

### Wiki linkek
- **Prompt**: [[szamla-db-prompt.md|Szamla-DB Prompt]]
- **MASTER Orchestrator**: Ez a szerviz
- **Meghívja**: [[nav-szamla-spec.md|NAV API Specifikáció]]
  - NAV API meghívása (GET /api/v1/invoices + search)
  - 30 nap default paraméterrel
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]
