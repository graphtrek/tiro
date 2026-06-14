---
title: "Specifikáció: NAV Online Számla Mikorszerviz"
description: "NAV Online Számla API integrációs mikroszerviz"
language: "HU"
last_updated: "2026-06-09"
related: [INDEX.md, szamla-db-spec.md, pdf-szamla-spec.md]
---

# NAV Online Számla Mikorszerviz - Specifikáció

> 🔗 **Hívási Lánc**: [[szamla-db-spec.md|← MASTER (szamla-db)]] **→** [[pdf-szamla-spec.md|PDF Feldolgozó →]]

---

## Szerepkör és kontextus
Te egy Backend API Integrációs Mérnök vagy. A feladatod a NAV Online Számla API hídjét fejleszteni a `szamla-db` orchestrator és a magyar fiskális hatóság között. Ez a szolgáltatás biztosítja, hogy a vállalati számlák naprakészen legyenek a NAV rendszerben regisztrálva, és az adatok konzisztenciája az egész Moneypenny rendszeren keresztül fenntartott legyen.

## Funkció
- NAV Online Számla API-tól számlák lekérdezése (query)
- **Levél szolgáltatás** — más mikroszervízt nem hív meg; eredményt ad vissza a `szamla-db`-nek

## API Integrációs pontok
- Számlák lekérdezése (számlaszám alapján)
- Lekérdezési adatok (keresési paraméterek)
- Számlastátusz lekérése

## Request paraméterek
- `invoice_number` - számlaszám
- `customer_tax_id` (optional) - vevő TAX ID
- `supplier_tax_id` (optional) - szállító TAX ID
- `invoice_date_from` (optional) - kezdő dátum
- `invoice_date_to` (optional) - végdátum

## Response
```json
{
  "success": true,
  "invoice": {
    "invoice_number": "2026-001",
    "invoice_date": "2026-05-01",
    "supplier_tax_id": "12345678-1-01",
    "customer_tax_id": "87654321-2-02",
    "amount_total": 100000,
    "amount_vat": 27000,
    "nav_status": "RECEIVED",
    "received_at": "2026-05-02T10:00:00Z"
  },
  "errors": []
}
```

## Interface
- **CLI**: 
  - `nav-szamla query --invoice-number 2026-001`
  - `nav-szamla search --supplier 12345678-1-01 --from 2026-05-01 --to 2026-05-31`
- **REST API**:
  - `GET /api/v1/invoices/{invoice_number}` - számlaszám alapján
  - `POST /api/v1/invoices/search` - szabad keresés
  - `GET /api/v1/invoices/status/{transaction_id}` - státusz

## Tech stack
- Python 3.10+
- FastAPI, Typer
- NAV Online Számla API (REST)
- SSL tanúsítvány (nav-szamla auth)

## Auth
- SSL tanúsítvány + privát kulcs
- Konfigurálható endpoint (test/prod)
- API rate limiting kezelés

---

## Kapcsolódások

### Hívási sorrend
```
szamla-db (MASTER)
  ↓ POST /invoices?... vagy GET /invoices/{szamlaszam}
nav-szamla (ÉN)  ←→  NAV Online Számla 3.0 API
  ↓ visszaad adatot szamla-db-nek
szamla-db (MASTER)
  ↓ (ezután hívja pdf-szamlát)
pdf-szamla → attachment-downloader
```

> `nav-szamla` levél szolgáltatás: nem hív más mikroszervízt, csak a NAV API-t.

### Wiki linkek
- **Prompt**: [[nav-számla-prompt.md|NAV Számla Prompt]]
- **Meghívva**: [[szamla-db-spec.md|Szamla-DB (MASTER)]]
- **Meghívom**: (senki — levél szolgáltatás)
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]
