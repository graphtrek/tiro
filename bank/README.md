# bank — Bank Konszolidált Kivonat Mikroszerviz

Tiro pipeline mikroszerviz (port 8005). Erste és Wise kézzel letöltött CSV bankkivonatokat olvas be és egységes formátumban adja vissza strukturált JSON-ként az `invoice-core` orchestratornak.

**Levél szolgáltatás** — CSV fájlokat olvas, DB-t nem kezel.

## Indítás

```bash
cd bank
uv sync

# REST API (port 8005)
python run_api.py

# Vagy uvicorn-nal közvetlenül
uv run uvicorn bank.api.main:app --host 0.0.0.0 --port 8005 --reload

# CLI (telepítve: `bank` script)
uv run bank status                                             # CSV mappák + fájlok összesítése
uv run bank list                                               # minden elérhető fájl listázása
uv run bank list --bank erste                                  # csak Erste fájlok
uv run bank list --bank wise                                   # csak Wise fájlok
uv run bank import 11600006-00000001-97860425_2026-01-01_2026-06-19.csv  # Erste CSV beolvasása
uv run bank import statement_25546267_HUF_2026-01-01_2026-06-17.csv      # Wise CSV beolvasása
uv run bank import <filename> --json                           # JSON kimenet
uv run bank statements                                         # konszolidált (Erste + Wise) legfrissebb kivonat
uv run bank statements --bank erste                            # csak Erste
uv run bank statements --bank wise                             # csak Wise
uv run bank statements --from 2026-05-01 --to 2026-05-31      # dátum szűrés
uv run bank statements --currency HUF --json                   # JSON kimenet
uv run bank --verbose statements                               # DEBUG napló
```

## REST API

| Metódus | Útvonal                              | Leírás                                      |
|---------|--------------------------------------|---------------------------------------------|
| `GET`   | `/health`                            | Állapotellenőrző végpont                    |
| `GET`   | `/settings`                          | Aktív konfiguráció                          |
| `GET`   | `/balance-statements`                | Elérhető CSV fájlok listája (minden bank)   |
| `GET`   | `/balance-statements/{bank}`         | Adott bank elérhető fájljai                 |
| `GET`   | `/balance-statement/all`             | Konszolidált kivonat (Erste + Wise együtt)  |
| `GET`   | `/balance-statement/{bank}`          | Adott bank legfrissebb kivonatának tranzakciói |
| `GET`   | `/balance-statement/{bank}/{filename}` | Konkrét CSV fájl beolvasása               |

`{bank}` értékek: `erste` / `wise`

### GET /health

```bash
curl http://localhost:8005/health
```

```json
{"status": "ok", "timestamp": "2026-06-19T10:00:00.000000"}
```

### GET /balance-statements

```bash
curl http://localhost:8005/balance-statements
```

```json
[
  {
    "bank": "erste",
    "filename": "11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
    "account_id": "11600006-00000001-97860425",
    "currency": null,
    "from_date": "2026-01-01",
    "to_date": "2026-06-19",
    "path": "/path/to/balance-statements/erste/..."
  },
  {
    "bank": "wise",
    "filename": "statement_25546267_HUF_2026-01-01_2026-06-17.csv",
    "account_id": "25546267",
    "currency": "HUF",
    "from_date": "2026-01-01",
    "to_date": "2026-06-17",
    "path": "/path/to/balance-statements/wise/..."
  }
]
```

### GET /balance-statement/{bank}

Adott bank legfrissebb (to_date szerint) kivonatának tranzakciói. Opcionális dátumszűrés query paraméterekkel.

```bash
# Legfrissebb Erste kivonat
curl http://localhost:8005/balance-statement/erste

# Szűrés dátumra
curl "http://localhost:8005/balance-statement/wise?from=2026-05-01&to=2026-05-31"

# Pénznem szűrő
curl "http://localhost:8005/balance-statement/wise?currency=HUF"
```

| Paraméter  | Típus        | Leírás                                  |
|------------|--------------|-----------------------------------------|
| `from`     | `YYYY-MM-DD` | Csak ettől a dátumtól kezdődő tranzakciók |
| `to`       | `YYYY-MM-DD` | Csak eddig a dátumig tartó tranzakciók  |
| `currency` | string       | Pénznem szűrő (pl. `HUF`)              |

Válasz (`BankStatement`):

```json
{
  "bank": "erste",
  "filename": "11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
  "account_id": "11600006-00000001-97860425",
  "currency": null,
  "from_date": "2026-01-01",
  "to_date": "2026-06-19",
  "fetched": 50,
  "transactions": [
    {
      "bank": "erste",
      "transaction_id": "F0HO030620260399820",
      "date": "2026-06-03",
      "datetime": "2026-06-03T00:00:00",
      "amount": "2133600.00",
      "currency": "HUF",
      "direction": "CREDIT",
      "description": "Trn: F0HO030620260399820 Oth.bank: 11699006 ...",
      "payment_reference": "GRPHT-2026-10",
      "counterparty_name": "Erste Bank Hungary Zrt. Budapest",
      "counterparty_account": "11699006-37912000-00000008",
      "counterparty_iban": "HU41116990063791200000000008",
      "transaction_type": "Átutalás",
      "category": "Egyéb bevétel",
      "balance": "4276057.00",
      "fees": null
    }
  ]
}
```

### GET /balance-statement/all

Konszolidált kivonat: Erste + Wise tranzakciók dátum szerint csökkenő sorrendben.

```bash
curl http://localhost:8005/balance-statement/all

# Szűréssel
curl "http://localhost:8005/balance-statement/all?from=2026-05-01&to=2026-05-31"
```

Válasz (`ConsolidatedStatement`):

```json
{
  "from_date": "2026-01-01",
  "to_date": "2026-06-17",
  "banks": ["erste", "wise"],
  "total": 112,
  "transactions": [...]
}
```

### GET /balance-statement/{bank}/{filename}

```bash
curl http://localhost:8005/balance-statement/erste/11600006-00000001-97860425_2026-01-01_2026-06-19.csv
curl http://localhost:8005/balance-statement/wise/statement_25546267_HUF_2026-01-01_2026-06-17.csv
```

## CLI

A `--verbose` / `-v` globális opció — a parancs neve **elé** kell írni:

```bash
uv run bank --verbose statements --bank erste
```

### status

CSV mappák és fájlok összesítése.

```bash
uv run bank status
```

```
Balance statements könyvtár: ./balance-statements

ERSTE — 1 fájl
  11600006-00000001-97860425_2026-01-01_2026-06-19.csv  (2026-01-01 .. 2026-06-19)

WISE — 1 fájl
  statement_25546267_HUF_2026-01-01_2026-06-17.csv  (2026-01-01 .. 2026-06-17)
```

### list

Elérhető CSV fájlok listázása.

```bash
uv run bank list [--bank erste|wise|all]
```

```
 Bank   Fájl                                          Számlaszám / ID                    Pénznem  Időszak
 erste  11600006-00000001-97860425_2026-01-01_...csv  11600006-00000001-97860425         –        2026-01-01 .. 2026-06-19
 wise   statement_25546267_HUF_2026-01-01_...csv      25546267                           HUF      2026-01-01 .. 2026-06-17
```

### import

Egy CSV fájl beolvasása. Az Erste fájlokat (`<számlaszám>_...`) és a Wise fájlokat (`statement_...`) a fájlnévből ismeri fel.

```bash
uv run bank import <filename> [--json]
```

```bash
uv run bank import 11600006-00000001-97860425_2026-01-01_2026-06-19.csv
uv run bank import statement_25546267_HUF_2026-01-01_2026-06-17.csv --json
```

Példa kimenet:

```
✓ 50 tranzakció (2026-01-01 .. 2026-06-19) — 11600006-00000001-97860425_2026-01-01_2026-06-19.csv

 Bank   Azonosító            Dir    Dátum         Összeg            Partner             Közlemény
 erste  F0HO030620260399820  CREDIT 2026-06-03    2,133,600.00 HUF  Erste Bank Hungary  GRPHT-2026-10
 erste  F0HO020620260488496  DEBIT  2026-06-02    3,825,000.00 HUF  TATAI IMRE CIB      Osztalék
```

### statements

Bankkivonatok lekérdezése a legfrissebb fájlból, opcionális szűréssel.

```bash
uv run bank statements [--bank erste|wise|all] [--from DATE] [--to DATE] [--currency TEXT] [--json]
```

| Opció             | Default | Leírás                              |
|-------------------|---------|-------------------------------------|
| `--bank`          | `all`   | `erste`, `wise`, vagy `all`         |
| `--from DATE`     | —       | Szűrés kezdete (`YYYY-MM-DD`)       |
| `--to DATE`       | —       | Szűrés vége (`YYYY-MM-DD`)          |
| `--currency TEXT` | —       | Pénznem szűrő (pl. `HUF`)           |
| `--json`          | ki      | JSON kimenet                        |

## Adatmodell (`BankTransaction`)

| Mező                  | Leírás                                                       |
|-----------------------|--------------------------------------------------------------|
| `bank`                | `"erste"` vagy `"wise"`                                      |
| `transaction_id`      | Erste: `Tranzakcióazonosító`; Wise: `TransferWise ID`        |
| `date`                | Könyvelési dátum (`YYYY-MM-DD`)                              |
| `datetime`            | Tranzakció időpontja (ha elérhető)                           |
| `amount`              | Összeg (abszolút érték)                                      |
| `currency`            | ISO 4217 (pl. `HUF`)                                         |
| `direction`           | `"CREDIT"` (jóváírás) vagy `"DEBIT"` (terhelés)             |
| `description`         | Erste: `Könyvelési információk`; Wise: `Description`         |
| `payment_reference`   | Erste: `Közlemény`; Wise: `Payment Reference`                |
| `counterparty_name`   | Erste: `Partner név`; Wise: `Payer Name` / `Payee Name`      |
| `counterparty_account`| Erste: `Partner számlaszáma`; Wise: `Payee Account Number`   |
| `counterparty_iban`   | Erste: `Partner IBAN száma`; Wise: `null`                    |
| `transaction_type`    | Erste: `Tranzakció típusa`; Wise: `Transaction Details Type` |
| `category`            | Erste: `Kategória`; Wise: `null`                             |
| `balance`             | Egyenleg a tranzakció után                                   |
| `fees`                | Wise: `Total fees`; Erste: `null`                            |

## Kivonat CSV-k

A CSV fájlokat kézzel kell letölteni a bankfelületekről, majd a `storage/bank/balance-statements/` megfelelő almappájába másolni (a workspace gyökerében).

### Erste

**Mappa:** `storage/bank/balance-statements/erste/`  
**Fájlnév-séma:** `<számlaszám>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv`  
**Példa:** `11600006-00000001-97860425_2026-01-01_2026-06-19.csv`

Technikai jellemzők:
- Kódolás: UTF-16 (BOM)
- Elválasztó: `,` (vesszős, idézőjeles mezők)
- Összeg ezres elválasztója: `\xa0` (non-breaking space) — pl. `"-13 470"` = -13 470 HUF
- Egyenleg formátum: `"3 343 587 HUF"` (pénznem kód a végén)
- Dátumformátum: `YYYY.MM.DD` és `YYYY.MM.DD HH:MM:SS`

### Wise

**Mappa:** `storage/bank/balance-statements/wise/`  
**Fájlnév-séma:** `statement_<balanceId>_<currency>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv`  
**Példa:** `statement_25546267_HUF_2026-01-01_2026-06-17.csv`

Technikai jellemzők:
- Kódolás: UTF-8
- Elválasztó: `,`
- Dátumformátum: `DD-MM-YYYY` és `DD-MM-YYYY HH:MM:SS.mmm`

A `storage/` mappa `.gitignore`-ban van.

## Konfiguráció (`.env`)

| Változó                  | Default                | Leírás                                             |
|--------------------------|------------------------|----------------------------------------------------|
| `BALANCE_STATEMENTS_DIR` | `../storage/bank/balance-statements` | CSV fájlok gyökérmappája (workspace-relatív)  |
| `ERSTE_SUBDIR`           | `erste`                | Erste almappa neve (relatív az alap könyvtárhoz)   |
| `WISE_SUBDIR`            | `wise`                 | Wise almappa neve                                  |
| `API_HOST`               | `0.0.0.0`              | FastAPI bind cím                                   |
| `API_PORT`               | `8005`                 | FastAPI port                                       |
| `LOG_LEVEL`              | `INFO`                 | Napló szint (`DEBUG`, `INFO`, `WARNING`, `ERROR`)  |
| `AUTH_ENABLED`           | `true` *(a `.env`-ben jelenleg `false`)* | JWT ellenőrzés be/ki                |
| `AUTH_SERVICE_URL`       | `http://localhost:8007` | Központi auth szerviz base URL (JWKS)             |

## Authentikáció (JWT)

`AUTH_ENABLED=true` esetén a `GET /health` kivételével minden végpont érvényes
JWT-t igényel, amelyet a központi **auth** szerviz (:8007) állít ki Google
belépés után. A token `Authorization: Bearer <token>` fejlécben vagy
`mp_access_token` HttpOnly cookie-ban érkezhet; az ellenőrzés lokális (RS256
aláírás a `/.well-known/jwks.json` publikus kulcsaival + `exp`/`aud`/`iss`) —
kérésenként nincs hálózati hívás az auth szerviz felé. Token nélkül a válasz
`401 Unauthorized`.

Implementáció: `src/bank/auth.py` (projektenként bemásolt modul) · specifikáció:
`../doc/auth-service-spec.md`.

## Naplózás

Naplók stdout-ra és `logs/bank.log` fájlba is kerülnek.

```
2026-06-19 10:00:00 INFO     bank.parsers.erste: Erste CSV: 11600006-00000001-97860425_2026-01-01_2026-06-19.csv — 50 tranzakció
2026-06-19 10:00:00 INFO     bank.parsers.wise: Wise CSV: statement_25546267_HUF_2026-01-01_2026-06-17.csv — 62 tranzakció
2026-06-19 10:00:00 INFO     bank.api.main: GET /balance-statement/all → 200 in 5ms
```

## Architektúra

```
# Workspace gyökér
storage/
└── bank/
    └── balance-statements/          # kézzel letöltött CSV-k (.gitignore)
        ├── erste/                   #   <számlaszám>_<from>_<to>.csv
        └── wise/                    #   statement_<balanceId>_<currency>_<from>_<to>.csv

bank/
├── pyproject.toml
├── run_api.py                       # VS Code debug belépési pont (port 8005)
├── .env
└── src/bank/
    ├── config.py                    # pydantic-settings, configure_logging()
    ├── models.py                    # BankTransaction, StatementFile, BankStatement,
    │                                #   ConsolidatedStatement
    ├── parsers/
    │   ├── erste.py                 # UTF-16 CSV → BankTransaction[]
    │   └── wise.py                  # UTF-8 CSV → BankTransaction[]
    ├── service.py                   # fájlfelfedezés, szűrés, konszolidáció
    ├── api/main.py                  # FastAPI végpontok
    └── cli/main.py                  # Typer CLI (bank script)
```

## Pipeline helye

```
invoice-core (MASTER)
  ├─ nav-invoice          ←→ NAV Online Számla 3.0 API
  ├─ invoice-file-filter → attachment-downloader ←→ Gmail API
  └─ bank (ez)            ← balance-statements/erste/*.csv
                          ← balance-statements/wise/*.csv
```

Az `invoice-core` a `GET /balance-statement/all` végponton keresztül hívja (konszolidált Erste + Wise tranzakciók). A `wise` mikroszerviz (port 8003, közvetlen Wise API hozzáférés) jelenleg **szünetel** — Wise partner program hiányában az online kivonat letöltés nem elérhető.
