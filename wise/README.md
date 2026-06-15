# wise-szamla — Wise Banki Mikroszerviz

Moneypenny pipeline mikroszerviz #5 (`wise`, port 8003). Letölti a Wise bankkivonatot
([Wise API](https://docs.wise.com/api-reference)), Pydantic modellbe parsolja a tranzakciókat,
és strukturált JSON-ként adja vissza a `szamla-db` orchestratornak.

**Levél szolgáltatás** — csak a Wise API-t hívja, DB-t nem kezel.

## Indítás

```bash
cd wise
uv sync

# REST API (port 8003)
python run_api.py

# Vagy uvicorn-nal közvetlenül
uv run uvicorn wise_szamla.api.main:app --host 0.0.0.0 --port 8003 --reload

# CLI (telepítve: `wise-szamla` script)
uv run wise-szamla status                                        # Wise API kapcsolat + profilok ellenőrzése
uv run wise-szamla balances                                      # elérhető pénznemek és balance ID-k
uv run wise-szamla sync                                          # utolsó 30 nap, WISE_ACCOUNT_CURRENCY
uv run wise-szamla sync --start 2026-05-01 --end 2026-05-31
uv run wise-szamla sync --start 2026-05-01 --currency HUF
uv run wise-szamla sync --json                                   # géppel olvasható JSON kimenet
uv run wise-szamla --verbose sync --start 2026-05-01            # DEBUG szintű napló
uv run wise-szamla statements                                    # letöltött kivonat CSV-k listázása
uv run wise-szamla statements --currency HUF --from 2026-05-01
uv run wise-szamla import statement_25546267_HUF_2026-05-19_2026-06-02.csv
uv run wise-szamla import statement_25546267_HUF_2026-05-19_2026-06-02.csv --json

# Tesztek
uv run pytest tests/ -v
```

## REST API

| Metódus  | Útvonal                               | Leírás                                          |
|----------|---------------------------------------|-------------------------------------------------|
| `GET`    | `/health`                             | Állapotellenőrző végpont                        |
| `GET`    | `/settings`                           | Aktív konfiguráció (API kulcs nélkül)           |
| `GET`    | `/profiles`                           | Wise profilok (API kapcsolat teszt)             |
| `GET`    | `/balances`                           | Elérhető egyenlegek pénzneménként               |
| `POST`   | `/sync`                               | Wise tranzakciók lekérése                       |
| `GET`    | `/transactions/{wise_transaction_id}` | Egy tranzakció részletei azonosító alapján      |
| `GET`    | `/balance-statements`                 | CSV-k listázása vagy a legfrissebb beolvasása   |
| `GET`    | `/balance-statements/{filename}`      | Egy CSV fájl beolvasása (JSON vagy raw CSV)     |

### GET /health

```bash
curl http://localhost:8003/health
```

```json
{"status": "ok", "timestamp": "2026-06-14T10:00:00.000000"}
```

### GET /settings

```bash
curl http://localhost:8003/settings
```

```json
{
  "wise_profile_id": 12345678,
  "wise_account_currency": "EUR",
  "wise_sandbox": false,
  "api_port": 8003,
  "max_retries": 3
}
```

### GET /profiles

Wise profilok lekérdezése — API kapcsolat és hitelesítés tesztelésére.

```bash
curl http://localhost:8003/profiles
```

### GET /balances

Elérhető STANDARD egyenlegek listája (pénznem és balance ID).

```bash
curl http://localhost:8003/balances
```

```json
[
  {"id": 11111111, "currency": "EUR", "amount": {"value": 1234.56, "currency": "EUR"}},
  {"id": 22222222, "currency": "HUF", "amount": {"value": 500000.00, "currency": "HUF"}}
]
```

### POST /sync

Wise bankkivonat lekérése a megadott dátumintervallumra. A helyes flow a Wise API-n belül:
1. `GET /v1/borderless-accounts?profileId={profileId}` — megkeresi a borderless számla ID-t és az elérhető pénznemeket
2. `GET /v1/borderless-accounts/{accountId}/statement.json?currency={currency}&intervalStart=...&intervalEnd=...` — lekéri a kivonatot

```bash
curl -X POST http://localhost:8003/sync \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-05-01",
    "end_date": "2026-05-31",
    "currency": "EUR"
  }'
```

Hiányzó paraméterek esetén: `start_date` = 30 napja, `end_date` = ma, `currency` = `WISE_ACCOUNT_CURRENCY`.

Válasz:

```json
{
  "start_date": "2026-05-01",
  "end_date": "2026-05-31",
  "currency": "EUR",
  "fetched": 2,
  "transactions": [
    {
      "wise_transaction_id": "TRANSFER-11111111",
      "type": "CREDIT",
      "transaction_date": "2026-05-15T10:30:00Z",
      "amount": "1500.00",
      "currency": "EUR",
      "description": "Átutalás: INV-2026-42",
      "counterparty_name": "ACME Corp",
      "counterparty_account": "GB29NWBK60161331926819",
      "payment_reference": "INV-2026-42"
    },
    {
      "wise_transaction_id": "CARD-22222222",
      "type": "DEBIT",
      "transaction_date": "2026-05-20T08:00:00Z",
      "amount": "49.99",
      "currency": "EUR",
      "description": "Scaleway SAS",
      "counterparty_name": "Scaleway SAS",
      "counterparty_account": null,
      "payment_reference": null
    }
  ]
}
```

**Kérés mezők (`SyncRequest`):**

| Mező         | Típus    | Default                  | Leírás                              |
|--------------|----------|--------------------------|-------------------------------------|
| `start_date` | `string` | 30 napja                 | Szűrés kezdete (`YYYY-MM-DD`)       |
| `end_date`   | `string` | ma                       | Szűrés vége (`YYYY-MM-DD`)          |
| `currency`   | `string` | `WISE_ACCOUNT_CURRENCY`  | Pénznem (pl. `EUR`, `GBP`, `HUF`)  |

**Válasz mezők (`SyncResponse`):**

| Mező                    | Leírás                                              |
|-------------------------|-----------------------------------------------------|
| `fetched`               | A Wise API-tól lekért tranzakciók száma             |
| `transactions`          | Tranzakció lista (`TransactionSummary[]`)           |
| `wise_transaction_id`   | Wise referenciaszám (idempotencia kulcs)            |
| `transaction_date`      | Tranzakció dátuma (ISO 8601)                        |
| `counterparty_name`     | Partner neve (küldő / fogadó / merchant)            |
| `counterparty_account`  | Partner bankszámlaszáma (ha elérhető)               |

### GET /transactions/{wise_transaction_id}

Egy korábban lekért tranzakció részletei azonosító alapján (in-memory keresés a futó session-ben).

```bash
curl http://localhost:8003/transactions/TRANSFER-11111111
```

### GET /balance-statements

A `balance-statements/` mappában lévő kivonat CSV-k kezelése.

- **Szűrő nélkül**: a legfrissebb CSV fájlt olvassa be és adja vissza `StatementImport` JSON-ként.
- **Szűrőkkel** (`from`, `to`, `currency`): a megfelelő fájlok metaadatait listázza.

```bash
# A legfrissebb kivonat tranzakciói
curl http://localhost:8003/balance-statements

# Fájllista szűréssel
curl "http://localhost:8003/balance-statements?currency=HUF&from=2026-05-01"
```

### GET /balance-statements/{filename}

Egy konkrét kivonat CSV beolvasása és visszaadása JSON-ként. A `?csv=true` paraméterrel az eredeti CSV fájl tölthető le.

```bash
# JSON (alapértelmezett)
curl http://localhost:8003/balance-statements/statement_25546267_HUF_2026-05-19_2026-06-02.csv

# Eredeti CSV letöltése
curl "http://localhost:8003/balance-statements/statement_25546267_HUF_2026-05-19_2026-06-02.csv?csv=true" -o kivonat.csv
```

Válasz (`StatementImport`):

```json
{
  "filename": "statement_25546267_HUF_2026-05-19_2026-06-02.csv",
  "balance_id": 25546267,
  "currency": "HUF",
  "from_date": "2026-05-19",
  "to_date": "2026-06-02",
  "fetched": 3,
  "transactions": [...]
}
```

## CLI

A `--verbose` / `-v` globális opció — a parancs neve **elé** kell írni:

```bash
uv run wise-szamla --verbose sync --start 2026-05-01
```

### status

Wise API kapcsolat és profilok ellenőrzése.

```bash
uv run wise-szamla status
```

```
✓ Wise API OK (live) — 1 profil
  ID: 12345678  Típus: BUSINESS  Név: Graphtrek Kft.
```

### balances

Elérhető pénznemek és balance ID-k listázása. Hasznos a `WISE_ACCOUNT_CURRENCY` beállításához
és a `sync` parancs `--currency` opciójához.

```bash
uv run wise-szamla balances
```

```
 Balance ID  Pénznem  Egyenleg
 11111111    EUR      1,234.56 EUR
 22222222    HUF    500,000.00 HUF
```

### sync

Wise tranzakciók lekérése és kilistázása.

```bash
uv run wise-szamla sync [OPTIONS]
```

| Opció             | Default                 | Leírás                          |
|-------------------|-------------------------|---------------------------------|
| `--start DATE`    | 30 napja                | Szűrés kezdete (`YYYY-MM-DD`)   |
| `--end DATE`      | ma                      | Szűrés vége (`YYYY-MM-DD`)      |
| `--currency TEXT` | `WISE_ACCOUNT_CURRENCY` | Pénznem (pl. `EUR`, `GBP`)      |
| `--json`          | ki                      | JSON kimenet                    |

Példa kimenet:

```
✓ 2 tranzakció (2026-05-01..2026-05-31, EUR)

 Azonosító           Típus   Dátum        Összeg        Partner
 TRANSFER-11111111   CREDIT  2026-05-15   1,500.00 EUR  ACME Corp
 CARD-22222222       DEBIT   2026-05-20      49.99 EUR  Scaleway SAS
```

### statements

A `balance-statements/` mappában lévő, kézzel letöltött kivonat CSV-k listázása.

```bash
uv run wise-szamla statements [OPTIONS]
```

| Opció             | Default  | Leírás                                     |
|-------------------|----------|--------------------------------------------|
| `--from DATE`     | —        | Csak ettől a dátumtól adatot tartalmazók   |
| `--to DATE`       | —        | Csak eddig a dátumig adatot tartalmazók    |
| `--currency TEXT` | —        | Pénznem szűrő (pl. HUF)                    |

Példa kimenet:

```
 Fájl                                              Balance ID  Pénznem  Időszak                     Méret
 statement_25546267_HUF_2026-05-19_2026-06-02.csv  25546267    HUF      2026-05-19 .. 2026-06-02   12,345 B
```

### import

Egy letöltött kivonat CSV beolvasása és tranzakcióinak megjelenítése.

```bash
uv run wise-szamla import <FILENAME> [--json]
```

A `FILENAME` a `balance-statements/` mappán belüli fájlnév (útvonal-komponens nem megengedett).

```bash
uv run wise-szamla import statement_25546267_HUF_2026-05-19_2026-06-02.csv
uv run wise-szamla import statement_25546267_HUF_2026-05-19_2026-06-02.csv --json
```

Példa kimenet:

```
✓ 3 tranzakció (2026-05-19..2026-06-02, HUF)

 Azonosító       Típus   Dátum        Összeg          Partner
 TRANSFER-AAA    CREDIT  2026-05-20   150,000.00 HUF  ACME Kft.
 CARD-BBB        DEBIT   2026-05-25     4,990.00 HUF  Netflix
```

## Naplózás

Naplók stdout-ra és `logs/wise.log` fájlba is kerülnek. Alapértelmezett szint: `LOG_LEVEL` (`.env`).

```
2026-06-14 10:00:00 INFO     wise_szamla.sync: Wise lekérés: 2026-05-01..2026-05-31 (EUR)
2026-06-14 10:00:01 INFO     wise_szamla.client: Wise statement 2026-05-01..2026-05-31 (EUR, balance_id=11111111): 2 tranzakció 843ms alatt
2026-06-14 10:00:01 INFO     wise_szamla.sync: Wise lekérés kész: 2 tranzakció
```

## SCA (Strong Customer Authentication) beállítása

A Wise **bankszámlakivonat letöltés** (`/balance-statements`) SCA hitelesítést igényel.
Egyszer kell beállítani:

```bash
# 1. RSA kulcspár generálása (a wise/ könyvtárban)
openssl genrsa -out wise_sca_private.pem 2048
openssl rsa -in wise_sca_private.pem -pubout -out wise_sca_public.pem

# 2. A nyilvános kulcs tartalma (ezt kell Wise-ba másolni)
cat wise_sca_public.pem
```

3. Wise weboldalon: **Settings → API tokens → [token neve] → Manage → Add SCA public key**  
   Másold be a `wise_sca_public.pem` teljes tartalmát (BEGIN/END sorral együtt).

4. `.env` beállítás (már megvan):
   ```
   WISE_SCA_PRIVATE_KEY_PATH=./wise_sca_private.pem
   ```

A privát kulcs fájlt ne commitold — már szerepel a `.gitignore`-ban.

## Kivonat CSV-k (kézi letöltés)

Ha a Wise API SCA-val védett balance-statements végpontja nem érhető el (pl. EU/UK személyes token, PSD2 korlátok), a kivonatokat kézzel is le lehet tölteni a Wise webfelületről, majd a `balance-statements/` mappába másolni.

**Fájlnév-séma** (a Wise által generált fájlnév megtartandó):
```
statement_<balanceId>_<currency>_<from>_<to>.csv
pl. statement_25546267_HUF_2026-05-19_2026-06-02.csv
```

A `csv_import` modul a fájlnévből parsolja ki a balance ID-t, pénznemet és időszakot. A `balance-statements/` mappa `.gitignore`-ban van.

---

## Konfiguráció (`.env` — `.env.example` alapján)

| Változó                 | Default   | Leírás                                              |
|-------------------------|-----------|-----------------------------------------------------|
| `WISE_API_KEY`          | —         | Wise Bearer token (kötelező)                        |
| `WISE_PROFILE_ID`       | —         | Numerikus Wise profil ID (kötelező)                 |
| `WISE_ACCOUNT_CURRENCY` | `EUR`     | Alapértelmezett pénznem a `sync` parancshoz         |
| `WISE_SANDBOX`          | `false`   | `true` = sandbox, `false` = éles                   |
| `WISE_SCA_PRIVATE_KEY_PATH` | —    | RSA privát kulcs elérési útja (SCA, lásd fent)     |
| `BALANCE_STATEMENTS_DIR` | `./balance-statements` | Kézzel letöltött kivonat CSV-k mappája    |
| `API_HOST`              | `0.0.0.0` | FastAPI bind cím                                    |
| `API_PORT`              | `8003`    | FastAPI port                                        |
| `LOG_LEVEL`             | `INFO`    | Napló szint (`DEBUG`, `INFO`, `WARNING`, `ERROR`)   |
| `REQUEST_TIMEOUT`       | `30`      | Wise API kérés timeout (másodperc)                  |
| `MAX_RETRIES`           | `3`       | Automatikus újrapróbálások száma (429/5xx)          |
| `RETRY_DELAY`           | `1.0`     | Újrapróbálás backoff alap (másodperc)               |

## Architektúra

```
wise/
├── pyproject.toml
├── run_api.py                      # VS Code debug belépési pont (port 8003)
├── .env.example
├── balance-statements/             # Wise webfelületről kézzel letöltött CSV-k (.gitignore)
│                                   #   Fájlnév-séma: statement_<balanceId>_<currency>_<from>_<to>.csv
└── src/wise_szamla/
    ├── config.py                   # pydantic-settings, configure_logging()
    ├── models.py                   # WiseStatement, SyncRequest/Response, TransactionSummary,
    │                               #   StatementFile, StatementImport
    ├── client.py                   # WiseClient — Bearer auth, retry, live/sandbox URL
    │                               #   get_profiles() · get_balances() · get_statement()
    │                               #   uses v1 borderless-accounts (wider account support)
    ├── sync.py                     # run_sync() — Wise API lekérés, modell konverzió
    ├── csv_import.py               # list_statement_files() · parse_statement_csv()
    │                               #   kézzel letöltött CSV-k feldolgozása (SCA nélkül)
    ├── api/main.py                 # FastAPI végpontok
    └── cli/main.py                 # Typer CLI
```

## Pipeline helye

```
szamla-db (MASTER)
  ├─ nav-szamla    ←→ NAV Online Számla 3.0 API
  ├─ invoice-file-filter → attachment-downloader ←→ Gmail API
  └─ wise (ez)  ←→ Wise API
```

A `szamla-db` hívja `POST /sync`-en keresztül, megkapja a tranzakciókat, majd maga kezeli
a `wise_transaction` tábla mentését és az összekapcsolást a többi táblával.
