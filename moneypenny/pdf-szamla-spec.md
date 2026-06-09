---
title: "Specifikáció: PDF Számla Feldolgozó Mikroszerviz"
description: "PDF számlákból metaadatokat kinyerő mikroszerviz"
language: "HU"
last_updated: "2026-06-09"
related: [INDEX.md, nav-szamla-spec.md, graphtrek-email-spec.md]
---

# PDF Számla Feldolgozó Mikroszerviz - Specifikáció

> 🔗 **Hívási Lánc**: [[nav-szamla-spec.md|← NAV API]] **→** [[graphtrek-email-spec.md|Gmail Letöltő →]]

---

## Funkció
- **Meghívja: graphtrek-email** (utolsó 30 nap default)
- Letöltött PDF fájlokból számlákat kiválogatja
- Számla metaadatokat nyeri ki (OCR/szabályok)
- Meghívott a nav-szamla által

## Kimeneti metaadatok
```json
{
  "filename": "2026-05-001_szamla.pdf",
  "invoice_number": "2026-001",
  "invoice_date": "2026-05-01",
  "supplier_name": "ABC Kft.",
  "supplier_tax_id": "12345678-1-01",
  "customer_name": "XYZ Bt.",
  "customer_tax_id": "87654321-2-02",
  "amount_total": 100000,
  "amount_vat": 27000,
  "currency": "HUF",
  "payment_due": "2026-05-31",
  "confidence": 0.95
}
```

## Input (opciók)
- `start_date` (optional) - szűrés kezdete (default: 30 nappal ezelőtt)
- `end_date` (optional) - szűrés vége (default: ma)
- `output_dir` (optional) - PDF könyvtár (default: ./downloads/)
- Batch feldolgozás támogatás

## API hívások
- graphtrek-email API: `GET /api/v1/jobs?status=completed` → PDF-ek letöltésének lekérdezése
- Letöltött PDF-ek feldolgozása az output_dir-ből

## Interface
- **CLI**: 
  - `pdf-szamla process` (utolsó 30 nap, default)
  - `pdf-szamla process --start 2026-05-01 --end 2026-05-31`
  - `pdf-szamla process --output-dir /path/to/pdfs/`
- **REST API**:
  - `POST /api/v1/invoices/extract` - metaadatok kinyerése (graphtrek-email integrációval)
  - `POST /api/v1/invoices/extract-batch` - batch feldolgozás
  - `GET /api/v1/invoices` - feldolgozási történet

## Tech stack
- Python 3.10+
- FastAPI, Typer
- PyPDF2/pdfplumber (PDF parse)
- Regex/spaCy (adatkinyerés)
- Tesseract OCR (opcionális: beszkennelt PDF)

## Logika
1. PDF-t megnyitja
2. Szöveg kinyerése
3. Regex/szabályok: számlaszám, dátum, összeg, TAX ID
4. Metaadatok JSON-ként
5. Confidence score kalkulálása

---

## Kapcsolódások

### Hívási sorrend
```
szamla-db (MASTER)
  ↓ meghívja
nav-szamla
  ↓ meghívja
pdf-szamla (ÉN)
  ↓ meghívja
graphtrek-email
```

### Wiki linkek
- **Prompt**: [[pdf-szamla-prompt.md|PDF Szamla Prompt]]
- **Meghívva**: [[nav-szamla-spec.md|NAV API]]
- **Meghívom**: [[graphtrek-email-spec.md|Gmail Letöltő]]
  - graphtrek-email meghívása (POST /api/v1/jobs)
  - utolsó 30 nap default paraméterrel
- **MASTER Orchestrator**: [[szamla-db-spec.md|Szamla-DB]]
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]
