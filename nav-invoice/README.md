# NAV Online Számla

Python kliens könyvtár és REST API a NAV (Nemzeti Adó- és Vámhivatal) Online Számla rendszeréhez.

A NAV **Online Számla 3.0** REST/XML interfészére épülő kliens
(`/invoiceService/v3`), `technikai felhasználó` hitelesítéssel.

## Funkciók

- **Bejelentkezés** – `tokenExchange` (SHA-512 jelszó hash, SHA3-512 aláírás, AES-128 token)
- **Lekérdezés** – `queryInvoiceDigest` (lista) és `queryInvoiceData` (egyedi számla XML)
- **Adószám ellenőrzés** – `queryTaxpayer`
- **Adatszolgáltatás** – `manageInvoice` + `queryTransactionStatus`
- **REST API** – FastAPI alapú webes felület (port **8002**)
- **CLI eszköz** – parancssoros hozzáférés
- **Naplózás** – INFO szintű fájl- és konzolnapló a `logs/nav-invoice.log` fájlban

## Telepítés

```bash
cd nav-invoice
uv sync
```

## Konfiguráció

Másold a `.env.example` fájlt `.env`-be, és töltsd ki a saját adataiddal:

```bash
cp .env.example .env
```

### Konfigurációs paraméterek

| Változó | Leírás | Példa |
|---------|--------|-------|
| `USERNAME` | Technikai felhasználó login (15 karakter) | `abcdef123456789` |
| `PASSWORD` | Technikai felhasználó jelszó | `titkos_jelszo` |
| `LICENSE_KEY` | XML aláírókulcs (signKey) | `1-2-abc...` |
| `CSERE_KEY` | XML cserekulcs (exchangeKey, 16 karakter) | `1234ABCD5678EFGH` |
| `TAX_NUMBER` | Adószám törzsszám (8 számjegy) | `12345678` |
| `SOFTWARE_*` | Számlázó szoftver regisztrációs adatai | — |
| `ENVIRONMENT` | Környezet: `test` vagy `production` | `test` |
| `ENDPOINT_URL` | Teljes base URL felülírás (`/invoiceService/v3`), opcionális | — |
| `API_HOST` | FastAPI szerver host | `0.0.0.0` |
| `API_PORT` | FastAPI szerver port (`.env` alapján; `run_api.py` 8002-t hardkódol) | `8000` |
| `LOG_LEVEL` | Naplózási szint | `INFO` |
| `CACHE_TTL_SECONDS` | Memória-cache TTL másodpercben | `3600` |
| `AUTH_ENABLED` | JWT ellenőrzés be/ki (a `.env`-ben jelenleg `false`) | `true` |
| `AUTH_SERVICE_URL` | Központi auth szerviz base URL (JWKS) | `http://localhost:8007` |

## Authentikáció (JWT)

`AUTH_ENABLED=true` esetén a `GET /health` kivételével minden végpont érvényes
JWT-t igényel, amelyet a központi **auth** szerviz (:8007) állít ki Google
belépés után. A token `Authorization: Bearer <token>` fejlécben vagy
`mp_access_token` HttpOnly cookie-ban érkezhet (az invoice-core automatikusan
továbbadja); az ellenőrzés lokális a JWKS publikus kulcsokkal. Token nélkül a
válasz `401 Unauthorized`.

> Implementáció: `src/nav_invoice/jwt_auth.py` — itt szándékosan **nem**
> `auth.py` a neve, mert az a NAV `tokenExchange` (belépés) modulja.
> Specifikáció: `../moneypenny/auth-service-spec.md`.

## Használat

### REST API indítása

```bash
# Fejlesztői szerver (automatikus újratöltéssel)
cd nav-invoice
python run_api.py

# Vagy közvetlenül uvicorn-nal
uv run uvicorn nav_invoice.api.main:app --host 0.0.0.0 --port 8002 --reload
```

Az API elérhető a `http://localhost:8002` címen.
Swagger UI dokumentáció: `http://localhost:8002/docs`

### CLI

A telepített parancssori eszköz neve `nav` (a `uv sync` után elérhető).

```bash
# Bejelentkezés tesztelése (tokenExchange)
uv run nav login

# Számlák listázása (utolsó 30 nap, kiállított)
uv run nav list

# Dátumtartomány szűréssel (max 35 nap)
uv run nav list --from 2026-05-01 --to 2026-05-31

# Befogadott (vevő oldali) számlák
uv run nav list --direction INBOUND

# Lapozás
uv run nav list --from 2026-05-01 --to 2026-05-31 --page 2

# Egyedi számla XML megjelenítése
uv run nav show SZAMLA-2026-001

# Befogadott egyedi számla
uv run nav show SZAMLA-2026-001 --direction INBOUND

# JSON kimenet
uv run nav list --json

# Részletes naplózás
uv run nav --verbose list --from 2026-05-01 --to 2026-05-31

# Számla beküldése (Adatszolgáltatás) — JSON-ként kell megadni
uv run nav report --json '{"invoice": {...}}'

# Cache törlése
uv run nav cache-clear

# Hibás parancs esetén a kilépési kód 1 (hasznos shell scriptekben / CI-ban)
uv run nav list --from 2026-06-01 --to 2026-05-01 || echo "Hiba: $?"
```

---

## API végpontok és curl példák

Az alapértelmezett alap URL: `http://localhost:8002`

### GET /health — Állapot ellenőrzés

```bash
curl http://localhost:8002/health
```

Válasz:
```json
{"status": "ok", "timestamp": "2026-06-12T17:45:00.123456"}
```

---

### POST /auth/login — Bejelentkezés (tokenExchange)

Ellenőrzi, hogy a `.env`-ben lévő technikai felhasználó hitelesítési adatok érvényesek-e.

```bash
curl -X POST http://localhost:8002/auth/login
```

Sikeres válasz:
```json
{
  "success": true,
  "session_id": "aBcDeFgHiJkLmNoP...",
  "valid_from": "2026-06-12T17:45:00Z",
  "valid_to": "2026-06-12T17:50:00Z",
  "message": "Bejelentkezés sikeres"
}
```

Hibás hitelesítés esetén `401` státuszkód.

---

### GET /invoices — Számlák listázása (queryInvoiceDigest)

| Query paraméter | Típus | Leírás | Alapértelmezett |
|-----------------|-------|--------|-----------------|
| `from_date` | `YYYY-MM-DD` | Kiállítás dátuma (tól) | mai nap − 30 nap |
| `to_date` | `YYYY-MM-DD` | Kiállítás dátuma (ig) | mai nap |
| `direction` | `OUTBOUND` \| `INBOUND` | Kiállított / befogadott | `OUTBOUND` |
| `page` | egész szám ≥ 1 | Lapszám | `1` |

> **Validáció (422):** `from_date` nem lehet nagyobb `to_date`-nél, és a tartomány nem haladhatja meg a 35 napot (NAV limit). Érvénytelen paraméterek esetén az API `422 Unprocessable Entity` hibát ad vissza, nem továbbítja a kérést a NAV felé.

```bash
# Utolsó 30 nap, kiállított számlák (alapértelmezett)
curl "http://localhost:8002/invoices"

# Adott hónap, kiállított számlák
curl "http://localhost:8002/invoices?from_date=2026-05-01&to_date=2026-05-31"

# Befogadott számlák, adott időszak
curl "http://localhost:8002/invoices?from_date=2026-05-01&to_date=2026-05-31&direction=INBOUND"

# Lapozás — 2. oldal
curl "http://localhost:8002/invoices?from_date=2026-05-01&to_date=2026-05-31&page=2"

# Formázott JSON kimenet (jq szükséges)
curl -s "http://localhost:8002/invoices?from_date=2026-05-01&to_date=2026-05-31" | jq .
```

Válasz (lista):
```json
[
  {
    "invoice_number": "SZAMLA-2026-001",
    "invoice_operation": "CREATE",
    "invoice_category": "NORMAL",
    "invoice_issue_date": "2026-05-15",
    "supplier_tax_number": "12345678",
    "supplier_name": "Példa Kft.",
    "customer_tax_number": "87654321",
    "customer_name": "Vevő Zrt.",
    "invoice_net_amount": 100000.0,
    "invoice_vat_amount": 27000.0,
    "currency": "HUF",
    "ins_date": "2026-05-15T10:30:00Z"
  }
]
```

---

### GET /invoices/{szamlaszam} — Egyedi számla XML (queryInvoiceData)

| Query paraméter | Típus | Leírás | Alapértelmezett |
|-----------------|-------|--------|-----------------|
| `direction` | `OUTBOUND` \| `INBOUND` | Kiállított / befogadott | `OUTBOUND` |

```bash
# Kiállított számla XML lekérése
curl "http://localhost:8002/invoices/SZAMLA-2026-001"

# Befogadott számla XML lekérése
curl "http://localhost:8002/invoices/SZAMLA-2026-001?direction=INBOUND"

# Csak az XML tartalom kinyerése jq-val
curl -s "http://localhost:8002/invoices/SZAMLA-2026-001" | jq -r .invoice_xml
```

Sikeres válasz:
```json
{
  "szamlaszam": "SZAMLA-2026-001",
  "invoice_xml": "<?xml version=\"1.0\" encoding=\"UTF-8\"?>..."
}
```

Nem található számla esetén `404` státuszkód.

---

### POST /report — Számla beküldése (manageInvoice)

Számlaadatot küld be a NAV-nak (`tokenExchange` + `manageInvoice`).

```bash
curl -X POST http://localhost:8002/report \
  -H "Content-Type: application/json" \
  -d '{
    "invoice": {
      "header": {
        "szamlaszam": "SZAMLA-2026-042",
        "szamlatipus": "SML",
        "keltes_datuma": "2026-06-12",
        "szamlazas_vegezo": "Példa Kft.",
        "vevo_adoszama": "87654321",
        "vevo_neve": "Vevő Zrt.",
        "vevo_cime": "1234 Budapest, Fő u. 1.",
        "bruttototal": 127000.0,
        "netto_total": 100000.0,
        "ado_total": 27000.0
      },
      "line_items": [
        {
          "tétel_leiras": "Szoftverfejlesztési szolgáltatás",
          "mennyiseg": 1.0,
          "egysagar": 100000.0,
          "adomertek": 27000.0,
          "ado_kulcs": 27
        }
      ],
      "keltes_datuma": "2026-06-12"
    }
  }'
```

Sikeres válasz:
```json
{
  "success": true,
  "message": "Adatszolgáltatás beküldve",
  "submission_id": "transaction-id-xyz"
}
```

Hiba esetén `502` státuszkód. Hibás vagy hiányos JSON esetén `422 Unprocessable Entity`.

---

### POST /cache/clear — Cache törlése

Törli az összes memóriában tárolt lekérdezési eredményt (`queryInvoiceDigest`, `queryInvoiceData`, `queryTaxpayer`).

```bash
curl -X POST http://localhost:8002/cache/clear
```

Válasz:
```json
{"cleared": 3, "message": "3 bejegyzés törölve a cache-ből"}
```

---

### GET /settings — Aktuális konfiguráció

```bash
curl http://localhost:8002/settings
```

Válasz:
```json
{
  "username": "abcdef123456789",
  "environment": "test",
  "endpoint": "https://api-test.onlineszamla.nav.gov.hu/invoiceService/v3",
  "is_production": false
}
```

---

## Projekt struktúra

```
nav-invoice/
├── pyproject.toml          # Projekt konfiguráció (uv)
├── .env.example            # Konfigurációs sablon
├── run_api.py              # VS Code / debug belépési pont (port 8002)
├── README.md               # Ez a fájl
│
├── certs/                  # TLS tanúsítványok (nem verziókezelt)
│   ├── cert.pem
│   └── key.pem
│
├── src/nav_invoice/         # Fő csomag
│   ├── config.py           # Beállítások (Pydantic) + configure_logging()
│   ├── models.py           # Adatmodellek
│   ├── crypto.py           # SHA-512 / SHA3-512 hash, aláírás, AES token
│   ├── client.py           # REST kliens + boriték (envelope) építés
│   ├── auth.py             # tokenExchange (bejelentkezés)
│   ├── query.py            # queryInvoiceDigest / queryInvoiceData / queryTaxpayer
│   ├── reporting.py        # manageInvoice / queryTransactionStatus
│   ├── api/main.py         # FastAPI alkalmazás
│   └── cli/main.py         # Click CLI eszköz
│
├── logs/                   # Napló fájlok (automatikusan létrejön)
│   └── nav-invoice.log
│
└── tests/                  # Egységtesztek
    ├── conftest.py
    └── test_models.py
```

## Függőségek

- **fastapi** + **uvicorn** – REST API szerver
- **pydantic-settings** – .env konfiguráció
- **requests** – HTTP kliens a REST hívásokhoz
- **lxml** – XML feldolgozás
- **cryptography** – AES-128 token visszafejtés
- **click** – CLI keretrendszer

## Fejlesztés

```bash
# Tesztek futtatása
uv run pytest tests/ -v

# Linter és formázás
uv run ruff check src/
uv run ruff format src/
```

## Licenc

MIT
