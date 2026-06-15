---
title: "Specifikáció: Wise Banki Mikroszerviz"
description: "Wise banki kivonatok letöltése és visszaadása strukturált JSON-ként"
language: "HU"
last_updated: "2026-06-15"
related: [INDEX.md, szamla-db-spec.md, wise-prompt.md]
---

# Wise Banki Mikroszerviz - Specifikáció

> 🔗 **Hívási Lánc**: [[szamla-db-spec.md|← MASTER (szamla-db)]]

---

## Szerepkör és kontextus
Te egy Backend API Integrációs Mérnök vagy. A feladatod a Wise bankkivonatok feldolgozásának hídját fejleszteni a `szamla-db` orchestrator és a Wise rendszer között. Ez a szolgáltatás nem ír adatbázisba, az adatokat strukturáltan adja vissza a `szamla-db`-nek.

## Funkció
- Wise webfelületről **kézzel letöltött** kivonat CSV-ket (`balance-statements/` mappa) dolgoz fel
- Adatbázist nem kezel; strukturált tranzakció listát ad vissza a `szamla-db`-nek
- A `POST /sync` (élő Wise API hívás) egyelőre nem működik — a `szamla-db` a `/balance-statements` végpontot használja

## Request paraméterek (`GET /balance-statements`)
- `from` (YYYY-MM-DD, optional) — csak ettől a dátumtól adatot tartalmazó fájlok
- `to` (YYYY-MM-DD, optional) — csak eddig a dátumig adatot tartalmazó fájlok
- `currency` (optional) — pénznem szűrő (pl. HUF)
- Szűrő nélkül: a legfrissebb CSV fájl tranzakcióit adja vissza

## Response (`StatementImport`)
```json
{
  "filename": "statement_25546267_HUF_2026-05-19_2026-06-02.csv",
  "balance_id": 25546267,
  "currency": "HUF",
  "from_date": "2026-05-19",
  "to_date": "2026-06-02",
  "fetched": 3,
  "transactions": [
    {
      "wise_transaction_id": "TRANSFER-11111111",
      "type": "CREDIT",
      "transaction_date": "2026-05-20 10:30:00",
      "date": "2026-05-20",
      "amount": "150000.00",
      "currency": "HUF",
      "description": "Átutalás: INV-2026-42",
      "counterparty_name": "ACME Kft.",
      "counterparty_account": "HU12345678",
      "payment_reference": "INV-2026-42"
    }
  ]
}
```

## CSV fájlnév-séma
`statement_<balanceId>_<currency>_<from>_<to>.csv`  
pl. `statement_25546267_HUF_2026-05-19_2026-06-02.csv`  
A fájlokat a Wise webfelületről kézzel kell letölteni és a `balance-statements/` mappába helyezni.

## Interface
- **CLI** (script neve: `wise-szamla`):
  - `wise-szamla status` — Wise API kapcsolat + profilok ellenőrzése
  - `wise-szamla balances` — elérhető egyenlegek listázása
  - `wise-szamla sync [--start DATE] [--end DATE] [--currency TEXT] [--json]` — élő API lekérés
  - `wise-szamla statements [--from DATE] [--to DATE] [--currency TEXT]` — CSV fájlok listázása
  - `wise-szamla import <filename> [--json]` — egy CSV beolvasása
- **REST API** (port 8003):
  - `GET /health` — állapotellenőrzés
  - `GET /settings` — aktív konfiguráció
  - `GET /profiles` — Wise profilok (API teszt)
  - `GET /balances` — elérhető egyenlegek
  - `POST /sync` — élő Wise API lekérés (egyelőre nem működik)
  - `GET /transactions/{wise_transaction_id}` — egy tranzakció részletei
  - `GET /balance-statements` — CSV fájlok listázása vagy legfrissebb beolvasása ← **szamla-db ezt hívja**
  - `GET /balance-statements/{filename}` — egy CSV beolvasása (JSON vagy raw CSV)

## Auth
- Wise API Key (`WISE_API_KEY`)
- Wise Profile ID (`WISE_PROFILE_ID`)
- SCA privát kulcs (`WISE_SCA_PRIVATE_KEY_PATH`) — balance-statements API-hoz (jövőbeli)
- Konfigurálható endpoint (`WISE_SANDBOX=true/false`)

## Tech stack
- Python 3.11+
- FastAPI, Typer, Rich
- Pydantic v2 (tranzakció modellek)
- pydantic-settings (.env konfiguráció)
- httpx (Wise API kliens)

---

## Kapcsolódások

### Hívási sorrend
```
szamla-db (MASTER)
  ↓ GET /balance-statements?from=...&to=...        (CSV lista)
  ↓ GET /balance-statements/{filename}             (tranzakciók beolvasása)
wise (ÉN)  ←→  balance-statements/ CSV fájlok
  ↓ visszaad StatementImport (tranzakció lista) szamla-db-nek
szamla-db
  ↓ wise_transaction tábla mentés + összekapcsolás
```

> A `POST /sync` (élő Wise API) egyelőre nem működik — a CSV import az aktív integrációs út.

### Wiki linkek
- **Prompt**: [[wise-prompt.md|Wise Prompt]]
- **Meghívva**: [[szamla-db-spec.md|Szamla-DB (MASTER)]]
- **Meghívom**: (senki — DB-t nem kezel)
- **Wise API Docs**: https://docs.wise.com/api-reference
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]
