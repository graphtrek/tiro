---
title: "Specifikáció: Wise Banki Mikroszerviz"
description: "Wise banki kivonatok letöltése és visszaadása — levél szolgáltatás"
language: "HU"
last_updated: "2026-06-14"
related: [INDEX.md, szamla-db-spec.md, wise-prompt.md]
---

# Wise Banki Mikroszerviz - Specifikáció

> 🔗 **Hívási Lánc**: [[szamla-db-spec.md|← MASTER (szamla-db)]]

---

## Szerepkör és kontextus
Te egy Backend API Integrációs Mérnök vagy. A feladatod a Wise API hídját fejleszteni a `szamla-db` orchestrator és a Wise banki rendszer között. Ez a szolgáltatás **levél szolgáltatás**: csak a Wise API-t hívja, nem ír adatbázisba, az adatokat strukturáltan adja vissza a `szamla-db`-nek.

## Funkció
- Wise API-tól banki tranzakciók lekérése
- **Levél szolgáltatás** — adatbázist nem kezel; strukturált tranzakció listát ad vissza a `szamla-db`-nek

## Request paraméterek
- `start_date` (YYYY-MM-DD) - szűrés kezdete (default: 30 nappal ezelőtt)
- `end_date` (YYYY-MM-DD) - szűrés vége (default: ma)

## Response
```json
[
  {
    "wise_transaction_id": "TXN-12345",
    "amount": 100000,
    "currency": "HUF",
    "transaction_date": "2026-05-15",
    "description": "Invoice payment - ABC Kft.",
    "counterparty_name": "ABC Kft.",
    "counterparty_account": "HU12345678"
  }
]
```

## Interface
- **CLI**:
  - `wise sync --start 2026-05-01 --end 2026-05-31` - tranzakciók listázása
  - `wise list --last 30` - utolsó N tranzakció
  - `wise status` - API kapcsolat ellenőrzés
- **REST API**:
  - `GET /health` - állapotellenőrzés
  - `POST /sync` - tranzakciók lekérése (start_date, end_date paraméterrel)
  - `GET /transactions/{transaction_id}` - egy tranzakció részletei

## Auth
- Wise API Key (`WISE_API_KEY`)
- Wise Account ID (`WISE_ACCOUNT_ID`)
- Konfigurálható endpoint (sandbox/live)

## Tech stack
- Python 3.10+
- FastAPI, Typer
- Pydantic v2 (tranzakció modellek)
- python-dotenv

---

## Kapcsolódások

### Hívási sorrend
```
szamla-db (MASTER)
  ↓ POST /sync?start_date=...&end_date=...
wise (ÉN)  ←→  Wise API
  ↓ visszaad tranzakció listát szamla-db-nek
szamla-db
  ↓ wise_transaction tábla mentés + összekapcsolás
```

> `wise` levél szolgáltatás: nem hív más mikroszervízt, csak a Wise API-t. DB-t nem kezel.

### Wiki linkek
- **Prompt**: [[wise-prompt.md|Wise Prompt]]
- **Meghívva**: [[szamla-db-spec.md|Szamla-DB (MASTER)]]
- **Meghívom**: (senki — levél szolgáltatás)
- **Wise API Docs**: https://docs.wise.com/api-reference
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]
