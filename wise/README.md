# wise-szamla — Wise Banki Mikroszerviz

Moneypenny pipeline önálló mikroszerviz #5 (`wise`, port 8004). Letölti a Wise bankkivonatot
([Wise API](https://docs.wise.com/api-reference)), Pydantic modellbe parsolja a tranzakciókat,
majd idempotensen szinkronizálja a `szamla-db` PostgreSQL adatbázisba. Önálló belépési pont —
`szamla-db` nem hívja, hanem közvetlenül írja be a tranzakciókat.

## Indítás

```bash
cd wise
uv sync

# REST API (port 8004)
python run_api.py

# Vagy uvicorn-nal közvetlenül
uv run uvicorn wise_szamla.api.main:app --host 0.0.0.0 --port 8004 --reload

# CLI (telepítve: `wise-szamla` script)
uv run wise-szamla sync                                          # utolsó 30 nap, WISE_ACCOUNT_CURRENCY
uv run wise-szamla sync --start 2026-05-01 --end 2026-05-31
uv run wise-szamla sync --start 2026-05-01 --currency GBP
uv run wise-szamla sync --json                                   # géppel olvasható JSON kimenet
uv run wise-szamla sync --verbose                                # részletes napló

uv run wise-szamla status                                        # Wise API kapcsolat + profilok ellenőrzése
uv run wise-szamla list-transactions                             # előzmény elérési útvonalak (API)

# Tesztek
uv run pytest tests/ -v
```

## REST API

| Metódus  | Útvonal                                   | Leírás                                      |
|----------|-------------------------------------------|---------------------------------------------|
| `GET`    | `/health`                                 | Állapotellenőrző végpont                    |
| `GET`    | `/settings`                               | Aktív konfiguráció (API kulcs nélkül)       |
| `POST`   | `/api/v1/sync`                            | Wise tranzakciók szinkronizálása            |
| `GET`    | `/api/v1/sync/history`                    | Szinkronizálási előzmények (in-memory)      |
| `GET`    | `/api/v1/transactions/{reference_number}` | Egy tranzakció részletei referenciaszám alapján |
| `GET`    | `/api/v1/profiles`                        | Wise profilok (API kapcsolat teszt)         |

### GET /health

```bash
curl http://localhost:8004/health
```

```json
{"status": "ok", "timestamp": "2026-06-14T10:00:00.000000"}
```

### GET /settings

```bash
curl http://localhost:8004/settings
```

```json
{
  "wise_profile_id": 12345678,
  "wise_account_currency": "EUR",
  "wise_sandbox": false,
  "szamla_db_url": "http://localhost:8003",
  "api_port": 8004,
  "max_retries": 3
}
```

### POST /api/v1/sync

Wise bankkivonat letöltése és szinkronizálása a megadott dátumintervallumra.

```bash
curl -X POST http://localhost:8004/api/v1/sync \
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
  "synced": 1,
  "skipped": 1,
  "errors": 0,
  "transactions": [
    {
      "reference_number": "TRANSFER-11111111",
      "type": "CREDIT",
      "date": "2026-05-15T10:30:00Z",
      "amount": "1500.00",
      "currency": "EUR",
      "description": "Átutalás: INV-2026-42",
      "partner_name": "ACME Corp",
      "payment_reference": "INV-2026-42",
      "synced_to_db": true
    },
    {
      "reference_number": "CARD-22222222",
      "type": "DEBIT",
      "date": "2026-05-20T08:00:00Z",
      "amount": "49.99",
      "currency": "EUR",
      "description": "Scaleway SAS",
      "partner_name": "Scaleway SAS",
      "payment_reference": null,
      "synced_to_db": false
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

| Mező           | Leírás                                                   |
|----------------|----------------------------------------------------------|
| `fetched`      | A Wise API-tól lekért tranzakciók száma                  |
| `synced`       | Sikeresen szamla-db-be írt tranzakciók                   |
| `skipped`      | Már meglévő tranzakciók (idempotens, HTTP 409)           |
| `errors`       | Sikertelen push-ok (szamla-db hálózati / szerver hiba)   |
| `synced_to_db` | `true` = sikeresen bekerült a szamla-db-be              |

### GET /api/v1/sync/history

Visszaadja a szerviz indulásakor indított szinkronizálási futások összefoglalóját.

```bash
curl http://localhost:8004/api/v1/sync/history
```

```json
[
  {
    "start_date": "2026-05-01",
    "end_date": "2026-05-31",
    "currency": "EUR",
    "fetched": 2,
    "synced": 1,
    "skipped": 1,
    "errors": 0
  }
]
```

### GET /api/v1/transactions/{reference_number}

Egy korábban szinkronizált tranzakció részletei referenciaszám alapján (in-memory keresés).

```bash
curl http://localhost:8004/api/v1/transactions/TRANSFER-11111111
```

### GET /api/v1/profiles

Wise profilok lekérdezése — API kapcsolat és hitelesítés tesztelésére.

```bash
curl http://localhost:8004/api/v1/profiles
```

## CLI

### sync

Wise tranzakciók letöltése és szinkronizálása.

```bash
uv run wise-szamla sync [OPTIONS]
```

| Opció               | Default                 | Leírás                          |
|---------------------|-------------------------|---------------------------------|
| `--start DATE`      | 30 napja                | Szűrés kezdete (`YYYY-MM-DD`)   |
| `--end DATE`        | ma                      | Szűrés vége (`YYYY-MM-DD`)      |
| `--currency TEXT`   | `WISE_ACCOUNT_CURRENCY` | Pénznem (pl. `EUR`, `GBP`)      |
| `--json`            | ki                      | JSON kimenet                    |
| `--verbose` / `-v`  | ki                      | INFO szintű napló               |

Példa kimenet:

```
✓ 2 tranzakció (2026-05-01..2026-05-31, EUR) — 1 szinkronizálva, 1 kihagyva, 0 hiba

 Referencia          Típus   Dátum        Összeg       Partner       DB
 TRANSFER-11111111   CREDIT  2026-05-15   1,500.00 EUR  ACME Corp    ✓
 CARD-22222222       DEBIT   2026-05-20      49.99 EUR  Scaleway SAS  –
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

### list-transactions

Tájékoztató parancs — az in-memory előzmény az API szerveren keresztül érhető el.

```bash
uv run wise-szamla list-transactions
```

## Naplózás

Naplók stdout-ra és `logs/wise.log` fájlba is kerülnek.

```
2026-06-14 10:00:00 INFO     wise_szamla.sync: Wise sync indítás: 2026-05-01..2026-05-31 (EUR)
2026-06-14 10:00:01 INFO     wise_szamla.client: Wise statement 2026-05-01..2026-05-31 (EUR): 2 tranzakció 843ms alatt
2026-06-14 10:00:01 INFO     wise_szamla.sync: Wise sync kész: 2 lekért, 1 szinkronizált, 1 kihagyott, 0 hiba — 920ms
2026-06-14 10:00:01 INFO     wise_szamla.api.main: POST /api/v1/sync → 200 in 925ms
```

## Konfiguráció (`.env` — `.env.example` alapján)

| Változó                | Default                                      | Leírás                                          |
|------------------------|----------------------------------------------|-------------------------------------------------|
| `WISE_API_KEY`         | —                                            | Wise Bearer token (kötelező)                    |
| `WISE_PROFILE_ID`      | —                                            | Numerikus Wise profil ID (kötelező)             |
| `WISE_ACCOUNT_CURRENCY`| `EUR`                                        | Alapértelmezett pénznem                         |
| `WISE_SANDBOX`         | `false`                                      | `true` = sandbox, `false` = éles               |
| `SZAMLA_DB_URL`        | `http://localhost:8003`                      | szamla-db orchestrátor URL                      |
| `API_HOST`             | `0.0.0.0`                                    | FastAPI bind cím                                |
| `API_PORT`             | `8004`                                       | FastAPI port                                    |
| `LOG_LEVEL`            | `INFO`                                       | Napló szint (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `REQUEST_TIMEOUT`      | `30`                                         | Wise API kérés timeout (másodperc)              |
| `MAX_RETRIES`          | `3`                                          | Automatikus újrapróbálások száma (429/5xx)      |
| `RETRY_DELAY`          | `1.0`                                        | Újrapróbálás backoff alap (másodperc)           |

## szamla-db integráció

A szerviz minden Wise tranzakciót `POST /api/v1/wise/transactions`-on keresztül küld a
`szamla-db`-nek. Az idempotencia garantált: HTTP 409 válasz esetén (tranzakció már létezik)
a tétel kihagyásra kerül (`skipped++`), nem duplikálódik.

Ha a `szamla-db` nem elérhető, a szinkronizálás lefut, a tranzakciók `synced_to_db=false`
értékkel kerülnek vissza, a push hibák naplózódnak (`WARNING` szinten).

**szamla-db push payload:**

```json
{
  "source": "wise",
  "external_id": "TRANSFER-11111111",
  "transaction_date": "2026-05-15T10:30:00+00:00",
  "amount_total": 1500.0,
  "currency": "EUR",
  "description": "Átutalás: INV-2026-42",
  "partner_name": "ACME Corp",
  "payment_reference": "INV-2026-42",
  "direction": "INBOUND"
}
```

## Architektúra

```
wise/
├── pyproject.toml
├── run_api.py                      # VS Code debug belépési pont
├── .env.example
└── src/wise_szamla/
    ├── config.py                   # pydantic-settings, logging
    ├── models.py                   # WiseStatement, SyncRequest/Response, TransactionSummary
    ├── client.py                   # WiseClient (Bearer auth, retry, live/sandbox URL)
    ├── sync.py                     # run_sync() + SzamlaDbClient (idempotens push)
    ├── api/main.py                 # FastAPI végpontok
    └── cli/main.py                 # Typer CLI
```

## Pipeline helye

```
wise (ez) → közvetlen írás → szamla-db PostgreSQL
```

A többi Moneypenny szolgáltatástól független, önálló belépési pont:

```
szamla-db (MASTER)
  ├─ nav-szamla ←→ NAV Online Számla 3.0 API
  └─ pdf-szamla → graphtrek-email ←→ Gmail API

wise (önálló) ←→ Wise API → szamla-db PostgreSQL
```
