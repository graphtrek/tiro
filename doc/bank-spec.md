---
title: "Specifikáció: Bank Konszolidált Kivonat Mikroszerviz"
description: "Erste és Wise CSV bankkivonatok egységes feldolgozása és strukturált JSON visszaadása az invoice-core számára"
language: "HU"
last_updated: "2026-08-09"
related: [INDEX.md, wise-spec.md, invoice-core-spec.md, bank-prompt.md]
---

# Bank Konszolidált Kivonat Mikroszerviz - Specifikáció

> 🔗 **Hívási Lánc**: [[invoice-core-spec.md|← MASTER (invoice-core)]]

---

## Szerepkör és kontextus

Leaf mikroszerviz — adatbázist nem kezel, CSV fájlokat olvas be és strukturált JSON-t ad vissza. Az `invoice-core` orchestrator hívja. Két bank kézzel letöltött kivonat CSV-jét dolgozza fel egységes formátumba normalizálva:

| Bank | Könyvtár | Fájlnév-séma | Kódolás |
|---|---|---|---|
| Erste | `storage/bank/balance-statements/erste/` | `<számlaszám>_<from>_<to>.csv` | UTF-16 LE (BOM), `,` elválasztó |
| Wise | `storage/bank/balance-statements/wise/` | `statement_<balanceId>_<currency>_<from>_<to>.csv` | UTF-8, `,` elválasztó |

---

## Adatforrások részletezése

### Erste CSV mezők

Kódolás: UTF-16 LE BOM, vesszős elválasztó, idézőjeles értékek.  
Dátumformátum: `YYYY.MM.DD`  
Összeg: ezres elválasztó `\xa0` (non-breaking space), negatív = terhelés.

| CSV oszlop | Leírás |
|---|---|
| `Könyvelés dátuma` | könyvelési dátum (elsődleges dátum) |
| `Tranzakció dátuma és ideje` | tényleges tranzakció datetime |
| `Összeg` | összeg (negatív = DEBIT) |
| `Devizanem` | pénznem (pl. HUF) |
| `Tranzakcióazonosító` | egyedi azonosító (pl. `F0HO10062026036547`); üresen `ERSTE-<sha1>` fallback ID |
| `Közlemény` | közlemény / payment reference |
| `Partner név` | partner neve |
| `Partner IBAN száma` | partner IBAN |
| `Partner számlaszáma` | partner számlaszám |
| `Partner bankkódja` | partner bankkódja (→ `counterparty_bank_code`) |
| `Partner címe` | partner címe (→ `counterparty_address`) |
| `Küldő címe` | küldő címe (→ `sender_address`) |
| `Könyvelési információk` | részletes leírás |
| `Tranzakció típusa` | pl. `Átutalás`, `Bankkártya használat`, `Kamat`, `Díj` |
| `Kategória` | Erste kategória |
| `Számlaegyenleg` | egyenleg tranzakció után |

### Wise CSV mezők

Kódolás: UTF-8, vesszős elválasztó.  
Dátumformátum: `DD-MM-YYYY` (Date), `DD-MM-YYYY HH:MM:SS.mmm` (Date Time)

| CSV oszlop | Leírás |
|---|---|
| `TransferWise ID` | egyedi azonosító (pl. `CARD-3911917494`, `TRANSFER-2186101708`) |
| `Date` | dátum |
| `Date Time` | datetime |
| `Amount` | összeg (negatív = DEBIT) |
| `Currency` | pénznem |
| `Description` | leírás |
| `Payment Reference` | közlemény |
| `Running Balance` | egyenleg tranzakció után |
| `Payer Name` | küldő neve (CREDIT esetén) |
| `Payee Name` | fogadó neve (DEBIT esetén) |
| `Payee Account Number` | fogadó számlaszám |
| `Merchant` | kereskedő neve (counterparty név fallback) |
| `Transaction Type` | `CREDIT` / `DEBIT` — elsődleges irány-forrás |
| `Transaction Details Type` | `CARD` / `DEPOSIT` / `TRANSFER` |
| `Total fees` | díj összege (`0` → `null`) |
| `Exchange Rate` | devizaárfolyam (→ `exchange_rate`) |
| `Exchange To` | cél pénznem (→ `exchange_to_currency`) |
| `Card Last Four Digits` | kártya utolsó 4 számjegye (→ `card_last_four`) |
| `Note` | megjegyzés (→ `note`) |

---

## Egységes adatmodell

### `BankTransaction`

```python
class BankTransaction(BaseModel):
    bank: str                        # "erste" | "wise"
    transaction_id: str              # Erste: Tranzakcióazonosító; Wise: TransferWise ID
    date: date                       # ISO 8601 (YYYY-MM-DD)
    datetime: datetime | None        # ISO 8601 datetime, ha elérhető
    amount: Decimal                  # abszolút érték
    currency: str                    # ISO 4217 (pl. "HUF")
    direction: Literal["CREDIT", "DEBIT"]  # pozitív összeg→CREDIT, negatív→DEBIT
    description: str | None          # Erste: Könyvelési információk; Wise: Description
    payment_reference: str | None    # Erste: Közlemény; Wise: Payment Reference
    counterparty_name: str | None    # Erste: Partner név; Wise: Payer/Payee/Merchant
    counterparty_account: str | None # Erste: Partner számlaszáma; Wise: Payee Account Number
    counterparty_iban: str | None    # Erste: Partner IBAN száma; Wise: nincs (None)
    transaction_type: str | None     # Erste: Tranzakció típusa; Wise: Transaction Details Type
    category: str | None             # Erste: Kategória; Wise: nincs (None)
    balance: Decimal | None          # egyenleg a tranzakció után
    fees: Decimal | None             # Wise: Total fees; Erste: None
    counterparty_address: str | None = None    # Erste: Partner címe
    sender_address: str | None = None          # Erste: Küldő címe
    counterparty_bank_code: str | None = None  # Erste: Partner bankkódja
    exchange_rate: Decimal | None = None       # Wise: Exchange Rate
    exchange_to_currency: str | None = None    # Wise: Exchange To
    card_last_four: str | None = None          # Wise: Card Last Four Digits
    note: str | None = None                    # Wise: Note
```

### `StatementFile`

```python
class StatementFile(BaseModel):
    bank: str           # "erste" | "wise"
    filename: str
    account_id: str     # Erste: számlaszám; Wise: balanceId
    currency: str | None
    from_date: date
    to_date: date
    path: str
```

### `BankStatement`

```python
class BankStatement(BaseModel):
    bank: str
    filename: str
    account_id: str
    currency: str | None
    from_date: date
    to_date: date
    fetched: int
    transactions: list[BankTransaction]
```

### `ConsolidatedStatement`

```python
class ConsolidatedStatement(BaseModel):
    from_date: date | None
    to_date: date | None
    banks: list[str]
    total: int
    transactions: list[BankTransaction]  # dátum szerint csökkenő sorrendben
```

---

## Fájlnév-séma és felderítés

### Erste
`<számlaszám>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv`  
pl. `11600006-00000001-97860425_2026-01-01_2026-06-19.csv`

Parsing:
- `account_id` = az első `_` előtt lévő rész
- `from_date`, `to_date` = az utolsó két `_`-dal elválasztott dátum

### Wise
`statement_<balanceId>_<currency>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv`  
pl. `statement_25546267_HUF_2026-01-01_2026-06-17.csv`

Parsing: split `_` → `["statement", balanceId, currency, from, to]`

---

## REST API (port 8005)

| Method | Endpoint | Auth | Leírás |
|---|---|---|---|
| `GET` | `/health` | **publikus** | állapotellenőrzés |
| `GET` | `/settings` | JWT | aktív konfiguráció |
| `GET` | `/balance-statements` | JWT | elérhető CSV fájlok listája (minden bank) |
| `GET` | `/balance-statements/{bank}` | JWT | adott bank elérhető fájljai (`erste` / `wise`) |
| `GET` | `/balance-statement/{bank}` | JWT | adott bank tranzakciói (legfrissebb fájl, opcionális szűréssel) |
| `GET` | `/balance-statement/all` | JWT | **fő endpoint** — konszolidált lista (Erste + Wise együtt) ← invoice-core ezt hívja |
| `GET` | `/balance-statement/{bank}/{filename}` | JWT | konkrét fájl beolvasása |

### `GET /balance-statement/{bank}` query paraméterek

| Paraméter | Típus | Leírás |
|---|---|---|
| `from` | `YYYY-MM-DD` (optional) | ettől a dátumtól tartalmazzon adatot |
| `to` | `YYYY-MM-DD` (optional) | eddig a dátumig tartalmazzon adatot |
| `currency` | string (optional) | pénznem szűrő (pl. `HUF`) |

Szűrő nélkül: a legfrissebb CSV fájl adatait adja vissza.

### Response: `BankStatement` / `ConsolidatedStatement` (JSON)

```json
{
  "bank": "erste",
  "filename": "11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
  "account_id": "11600006-00000001-97860425",
  "currency": null,
  "from_date": "2026-01-01",
  "to_date": "2026-06-19",
  "fetched": 42,
  "transactions": [
    {
      "bank": "erste",
      "transaction_id": "F0HO10062026036547",
      "date": "2026-06-12",
      "datetime": "2026-06-10T12:46:53",
      "amount": "13470.00",
      "currency": "HUF",
      "direction": "DEBIT",
      "description": "416583xxxxxx4076 87204990 Google Pay Alza.hu Huszar 260610...",
      "payment_reference": null,
      "counterparty_name": "Alza.hu Huszar u. 3",
      "counterparty_account": null,
      "counterparty_iban": null,
      "transaction_type": "Bankkártya használat",
      "category": "Online vásárlás",
      "balance": "3343587.00",
      "fees": null,
      "counterparty_address": null,
      "sender_address": null,
      "counterparty_bank_code": null,
      "exchange_rate": null,
      "exchange_to_currency": null,
      "card_last_four": null,
      "note": null
    }
  ]
}
```

---

## CLI (script neve: `bank`)

```bash
bank status                                      # CSV mappák + fájlok összesítése
bank list [--bank erste|wise|all]                # elérhető fájlok listázása
bank import <filename> [--json]                  # egy CSV beolvasása (bank felismerés a fájlnévből)
bank statements [--bank erste|wise|all] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--currency HUF] [--json]
```

- A `--verbose` / `-v` globális opció DEBUG naplózást kapcsol — a parancs neve **elé** kell írni: `bank --verbose statements`
- `bank import` a fájlnév alapján dönt: `statement_` prefix → Wise, egyébként → Erste

---

## Authentikáció (JWT)

A bank szerviz a központi **auth** szerviz (:8007) által kiállított JWT-ket fogadja el
(`src/bank/auth.py` — projektenként bemásolt modul, a mintát az
[[auth-service-spec.md|Auth Service Spec]] írja le). Az `require_auth` dependency app
szinten van bekötve: **a `GET /health` kivételével minden végpont érvényes JWT-t igényel**.

| Tulajdonság | Érték |
|---|---|
| Token forrása | `Authorization: Bearer <token>` fejléc **vagy** `mp_access_token` HttpOnly cookie |
| Algoritmus | RS256 |
| Publikus kulcsok | `GET {AUTH_SERVICE_URL}/.well-known/jwks.json` — PyJWKClient, 1 óra cache TTL, ismeretlen `kid` esetén automatikus újratöltés |
| `audience` | `tiro` |
| `issuer` | `auth-service` |
| `typ` claim | `access` kell legyen (refresh token nem elfogadott) |
| Ellenőrzés | **lokális** — nincs kérésenkénti hálózati hívás az auth szerviz felé |

- Hiányzó / érvénytelen token → `401 Unauthorized`
- JWKS lekérési hiba (auth szerviz nem fut / TLS hiba) → `503` — a certifi-alapú SSLContext biztosítja a TLS trust store-ot
- `AUTH_ENABLED=false` esetén a JWT ellenőrzés kikapcsol (tesztekhez)

---

## Projektstruktúra (wise-projekt mintájára)

```
# Workspace gyökér
storage/
└── bank/
    └── balance-statements/          # kézzel letöltött CSV-k (.gitignore)
        ├── erste/                   #   <számlaszám>_<from>_<to>.csv
        └── wise/                    #   statement_<balanceId>_<currency>_<from>_<to>.csv

bank/
├── Dockerfile                       # uv-alapú konténerkép (EXPOSE 8005)
├── pyproject.toml                   # bank script: bank.cli.main:app
├── uv.lock
├── run_api.py                       # debug belépési pont (port 8005, reload_dirs=["src"])
├── logs/bank.log                    # naplófájl
├── src/bank/
│   ├── __init__.py
│   ├── config.py          # pydantic-settings, workspace root .env
│   ├── auth.py            # JWT validálás (központi auth :8007 JWKS)
│   ├── models.py          # BankTransaction, StatementFile, BankStatement, ConsolidatedStatement
│   ├── parsers/
│   │   ├── erste.py       # UTF-16, ',' → BankTransaction[]
│   │   └── wise.py        # UTF-8, ',' → BankTransaction[]
│   ├── service.py         # file discovery, szűrés, konszolidáció
│   ├── api/
│   │   └── main.py        # FastAPI app
│   └── cli/
│       └── main.py        # Typer CLI
└── tests/
    ├── test_parsers.py    # Erste/Wise CSV parser tesztek (fixtures/)
    └── test_auth_jwks.py  # JWKS/JWT validálás tesztek
```

---

## Tech stack

- Python ≥ 3.14 (`requires-python = ">=3.14"`)
- FastAPI, Typer, Rich
- Pydantic v2
- pydantic-settings (workspace root `.env` konfiguráció)
- PyJWT[crypto] + certifi (JWT validálás, JWKS TLS trust store)
- `csv` + `codecs` (UTF-16 BOM kezelés)
- Docker (uv-alapú kép, `ghcr.io/astral-sh/uv:python3.14-bookworm-slim`)

---

## Environment (`.env`)

A beállítások a **workspace gyökér** `.env` fájljából jönnek (nem `bank/.env`) — a
`340075c` refaktor óta közös root konfiguráció, lásd a monorepo `.env`-jét.

```env
BALANCE_STATEMENTS_DIR=../storage/bank/balance-statements  # CSV-k gyökérmappája (workspace-relatív, .gitignore)
ERSTE_SUBDIR=erste                            # relatív az alap könyvtárhoz
WISE_SUBDIR=wise
API_HOST=0.0.0.0
BANK_API_PORT=8005                            # alias: API_PORT is elfogadott
LOG_LEVEL=INFO
AUTH_ENABLED=true                             # false → JWT ellenőrzés kikapcsolva (tesztekhez)
AUTH_SERVICE_URL=http://localhost:8007        # központi auth szerviz (JWKS)
```

A `balance_statements_dir` default értéke (env nélkül): `<workspace>/storage/bank/balance-statements`.
A naplók stdout-ra és `bank/logs/bank.log` fájlba kerülnek.

---

## Erste CSV különlegességek

- **Kódolás**: UTF-16 Little Endian BOM (`\xff\xfe`) — `open(file, encoding="utf-16")` szükséges
- **Elválasztó**: `,` (vesszős, idézőjeles mezők)
- **Összeg formátum**: `"2\xa0133\xa0600"` — a `\xa0` (non-breaking space) ezres elválasztó, nem tizedes pont; a `-` negatív előjel külön karakter (`"-602\xa0000"`)
- **Egyenleg**: `"4\xa0276\xa0057 HUF"` — pénznem kód a végén, eltávolítandó
- **Dátumformátum**: `2026.06.12` → `datetime.strptime(v, "%Y.%m.%d")`
- **Datetime formátum**: `2026.06.10 12:46:53` → `datetime.strptime(v, "%Y.%m.%d %H:%M:%S")`
- **Irány**: `Összeg` előjele alapján — pozitív → CREDIT, negatív → DEBIT
- **Azonosító fallback**: ha a `Tranzakcióazonosító` üres (pl. kártyás tranzakció), determinisztikus `ERSTE-<sha1>` ID generálódik a `(dátum, összeg, leírás)` kulcsból és előfordulásszámból

---

## Wise CSV különlegességek

- **Kódolás**: UTF-8 (`utf-8-sig`, BOM tolerált), `,` elválasztó
- **Dátumformátum**: `DD-MM-YYYY` (+ `DD-MM-YYYY HH:MM:SS[.mmm]` datetime)
- **Irány**: elsődlegesen a `Transaction Type` oszlop (`CREDIT` / `DEBIT`); hiányzó/ismertetlen értéknél az `Amount` előjele dönt
- **Counterparty**: `Payer Name` → `Payee Name` → `Merchant` sorrendben (az első nem üres nyer)
- **Díjak**: `Total fees` értéke `0` → `null`
- **Devizacsere**: `Exchange Rate` → `exchange_rate`, `Exchange To` → `exchange_to_currency` (az `Exchange From` nincs leképezve)
- **Kártyás tranzakciók**: `Card Last Four Digits` → `card_last_four`, `Note` → `note`

---

## Kapcsolódások

```mermaid
flowchart TD
    IC[invoice-core] -->|GET /balance-statement/all (fő)| B[bank]
    IC -.->|GET /balance-statement/erste| B[bank]
    IC -.->|GET /balance-statement/wise| B[bank]
    B -->|read CSV| E[storage/bank/balance-statements/erste/*.csv]
    B -->|read CSV| W[storage/bank/balance-statements/wise/*.csv]
    B -->|ConsolidatedStatement JSON| IC
```

---

## Wiki linkek

- **Prompt**: [[bank-prompt.md|Bank Prompt]]
- **Meghívva**: [[invoice-core-spec.md|Invoice-Core (MASTER)]]
- **Meghívom**: (senki — CSV fájlokat olvas, DB-t nem kezel)
- **Minta projekt**: [[wise-spec.md|Wise Spec]] (projektstruktúra alapja)
- **Projekt Index**: [[INDEX.md|Tiro Index]]
