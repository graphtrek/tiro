---
title: "Specifikáció: NAV Online Számla Mikorszerviz"
description: "NAV Online Számla API integrációs mikroszerviz"
language: "HU"
last_updated: "2026-09-03"
related: [INDEX.md, invoice-core-spec.md, invoice-file-filter-spec.md]
---

# NAV Online Számla Mikorszerviz - Specifikáció

> 🔗 **Hívási Lánc**: [[invoice-core-spec.md|← MASTER (invoice-core)]] **→** [[invoice-file-filter-spec.md|PDF Feldolgozó →]]

---

## Szerepkör és kontextus
Te egy Backend API Integrációs Mérnök vagy. A feladatod a NAV Online Számla API hídjét fejleszteni a `invoice-core` orchestrator és a magyar fiskális hatóság között. Ez a szolgáltatás biztosítja, hogy a vállalati számlák naprakészen legyenek a NAV rendszerben regisztrálva, és az adatok konzisztenciája az egész Tiro rendszeren keresztül fenntartott legyen.

## Funkció
- NAV Online Számla API-tól számlák lekérdezése (query): számlalista (`queryInvoiceDigest`), egyedi számla (`queryInvoiceData`), adószám-ellenőrzés (`queryTaxpayer`)
- Adatszolgáltatás (`manageInvoice`) — számla beküldése a NAV felé, automatikus `tokenExchange`-szel
- **Levél szolgáltatás** — más mikroszervízt nem hív meg; eredményt ad vissza a `invoice-core`-nek

## API Integrációs pontok
- Számlák lekérdezése (számlaszám alapján) — `queryInvoiceData`
- Számlalista lekérdezése (dátumtartomány, irány, lapszám) — `queryInvoiceDigest`
- Adószám ellenőrzése — `queryTaxpayer`
- Számla beküldése (adatszolgáltatás) — `manageInvoice` + `queryTransactionStatus`

## Request paraméterek (számlalista lekérdezés)
- `from_date` (YYYY-MM-DD, optional) - kiállítás dátuma (tól), default: ma − 30 nap
- `to_date` (YYYY-MM-DD, optional) - kiállítás dátuma (ig), default: ma; max 35 napos tartomány
- `direction` (OUTBOUND|INBOUND, optional, default: OUTBOUND) - kiállított / befogadott
- `page` (egész, optional, default: 1) - lapszám (NAV oldalankénti limit)

Egyedi számlalekérdezés:
- `szamlaszam` (path param) - számlaszám
- `direction` (query, optional, default: OUTBOUND)

## Response (GET /invoices)
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

## Interface
- **CLI** (script neve: `nav`, port 8002):
  - `nav login` — tokenExchange tesztelése
  - `nav list [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--direction INBOUND|OUTBOUND] [--page N] [--json]`
  - `nav show <számlaszám> [--direction INBOUND|OUTBOUND]` — egyedi számla XML
  - `nav report --json '{...}'` — manageInvoice (adatszolgáltatás); `--json` nélkül csak placeholder üzenet
  - `nav cache-clear` — memória-cache törlése
  - `nav --verbose list ...` (alias: `-v`) — DEBUG szintű napló
- **REST API** (port 8002):
  - `GET /health` — állapotellenőrző (JWT nélkül is elérhető)
  - `POST /auth/login` — tokenExchange (hitelesítés teszt)
  - `GET /invoices` — számlalista (queryInvoiceDigest)
  - `GET /invoices/{szamlaszam}` — egyedi számla: dekódolt XML + feldolgozott részletmezők (queryInvoiceData + `InvoiceDetailData`)
  - `POST /report` — számla beküldése (manageInvoice)
  - `POST /cache/clear` — memória-cache törlése
  - `GET /settings` — aktív konfiguráció
- **JWT védelem**: minden végpont (kivéve `/health`) érvényes access tokent követel (lásd Auth szekció lentebb)

## Tech stack
- Python 3.14+ (`pyproject.toml`: `requires-python >=3.14`; Docker kép: `python3.14-bookworm-slim`)
- FastAPI, Click
- NAV Online Számla API 3.0 REST/XML (`/invoiceService/v3`)
- pydantic-settings (konfiguráció a monorepo gyökeri közös `.env`-ből)
- requests (HTTP kliens), lxml (XML feldolgozás)
- cryptography (AES-128 token visszafejtés)
- pyjwt[crypto] + certifi (JWT validálás a központi auth szerviz JWKS kulcsaival)

## Auth
- **Technikai felhasználó** hitelesítés: SHA-512 jelszó hash, SHA3-512 kérés-aláírás, AES-128 token visszafejtés
- Konfigurálható endpoint (`test` / `production`)
- **JWT védelem (06c9d10)**: a REST API minden végpontja (kivéve `/health`) RS256-os access tokent követel — Bearer fejlécben vagy `mp_access_token` cookie-ban. A tokent a központi auth szerviz (:8007) bocsátja ki (`aud=tiro`, `iss=auth-service`); a JWKS publikus kulcsokat a szerviz lokálisan cache-eli (1 óra TTL, ismeretlen `kid` esetén újratöltés), így nincs kérésenkénti hálózati hívás. `AUTH_ENABLED=false` esetén a védelem kikapcsolható (teszt).
- **`read_only` szerep (c6c9bd3)**: ha a JWT `role` claim-je `read_only`, a `require_auth` a nem-GET/HEAD/OPTIONS metódusú kéréseket `403`-mal elutasítja (`"Csak olvasási jogosultság — írási művelet nem engedélyezett"`) — ez a szerviz esetében a `POST /report` és `POST /cache/clear` végpontokat érinti.
- Memória-cache (TTL konfigurálható, `CACHE_TTL_SECONDS`, default 3600 mp)

---

## Online Számla Csatlakozási Lépések

### 1. Technikai felhasználó létrehozása (NAV portal)

1. Lépj be a NAV Online Számla tesztkörnyezetébe: `https://onlineszamla-test.nav.gov.hu/`
2. **Felhasználók** menüpontban hozz létre új **Technikai felhasználót**.
3. Mentés után generáld le és jegyezd fel a 4 hitelesítő adatot:

| Adat | .env kulcs | NAV spec neve | Megjegyzés |
|---|---|---|---|
| Felhasználónév | `USERNAME` | `login` | technikai felhasználó neve |
| Jelszó | `PASSWORD` | `passwordHash` inputja | SHA-512 hash-elve kerül a kérésbe |
| Aláírókulcs | `LICENSE_KEY` | `signKey` | requestSignature számításához |
| Cserekulcs | `CSERE_KEY` | `exchangeKey` | AES-128 token visszafejtéshez, pontosan 16 karakter |

Éles (`production`) környezetben: `https://onlineszamla.nav.gov.hu/`

---

### 2. Konfigurációs fájl beállítása (közös gyökeri `.env`)

A konfiguráció a **monorepo gyökerében** lévő közös `.env` fájlból töltődik (340075c refactor — nincs külön `nav-invoice/.env.example`).

```dotenv
# Technikai felhasználó (NAV portálról)
USERNAME=technikai_felhasznalonev
PASSWORD=jelszó_plaintext
LICENSE_KEY=alairokuls_string
CSERE_KEY=16karaktercsere!!   # pontosan 16 karakter

# Adóalany adószámának törzsszáma (8 számjegy)
TAX_NUMBER=12345678

# Környezet: "test" vagy "production"
ENVIRONMENT=test
# ENDPOINT_URL=...  # opcionális teljes base URL felülírás (pl. proxy/teszt szerver)

# Szoftver regisztrációs blokk (minden kérésben szerepel)
SOFTWARE_ID=HU00000000NAVSZAML0
SOFTWARE_NAME=nav-invoice-python
SOFTWARE_OPERATION=LOCAL_SOFTWARE
SOFTWARE_MAIN_VERSION=0.1.0
SOFTWARE_DEV_NAME=nav-invoice
SOFTWARE_DEV_CONTACT=dev@example.com
SOFTWARE_DEV_COUNTRY_CODE=HU
# SOFTWARE_DEV_TAX_NUMBER=  # opcionális; hiányában a TAX_NUMBER kerül bele

# FastAPI szerver
API_HOST=0.0.0.0
NAV_INVOICE_API_PORT=8002   # alias: API_PORT
LOG_LEVEL=INFO
CACHE_TTL_SECONDS=3600      # query cache TTL

# JWT védelem (központi auth szerviz, :8007)
AUTH_ENABLED=true           # false = teszt, védelem kikapcsolva
AUTH_SERVICE_URL=http://localhost:8007
JWT_AUDIENCE=tiro
JWT_ISSUER=auth-service
```

> **Megjegyzés**: a régi `certificate_path` / `private_key_path` kulcsok továbbra is léteznek a `Settings`-ben, de a v3 REST API **nem használja** őket (kompatibilitás miatt maradtak); a privát kulcsok nincsenek verziózva (d8a4898).

---

### 3. XML kérés-boríték felépítése

Minden NAV API kérés azonos boríték-struktúrát követ (`client.py:build_request`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<{OperationRequest} xmlns="http://schemas.nav.gov.hu/OSA/3.0/api"
                    xmlns:common="http://schemas.nav.gov.hu/NTCA/1.0/common">
  <common:header>
    <common:requestId>{30 karakteres egyedi ID, [A-Z0-9]}</common:requestId>
    <common:timestamp>{YYYY-MM-DDTHH:MM:SS.mmmZ UTC}</common:timestamp>
    <common:requestVersion>3.0</common:requestVersion>
    <common:headerVersion>1.0</common:headerVersion>
  </common:header>
  <common:user>
    <common:login>{USERNAME}</common:login>
    <common:passwordHash cryptoType="SHA-512">{SHA-512(PASSWORD).upper()}</common:passwordHash>
    <common:taxNumber>{TAX_NUMBER}</common:taxNumber>
    <common:requestSignature cryptoType="SHA3-512">{lásd lent}</common:requestSignature>
  </common:user>
  <software>
    <softwareId>...</softwareId>
    <!-- ... software regisztrációs mezők ... -->
  </software>
  {operáció-specifikus XML body}
</{OperationRequest}>
```

---

### 4. Kriptográfiai lépések (`crypto.py`)

#### 4a. `passwordHash` — SHA-512
```python
import hashlib
pwd_hash = hashlib.sha512(password.encode("utf-8")).hexdigest().upper()
# → kérés: <passwordHash cryptoType="SHA-512">{pwd_hash}</passwordHash>
```

#### 4b. `requestSignature` — SHA3-512
Az aláírás alapstringjét az alábbiak konkatenációjából kell képezni:
```
base = requestId + YYYYMMDDHHMMSS(UTC) + signKey
```
Manage kéréseknél (manageInvoice) minden számlához hozzáfűz egy részletet:
```
base += SHA3-512(operation + base64_invoiceData)   # minden számlára
```
Végül:
```python
signature = hashlib.sha3_512(base.encode("utf-8")).hexdigest().upper()
```

#### 4c. `encodedExchangeToken` visszafejtése — AES-128-ECB
```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import base64

ciphertext = base64.b64decode(encoded_token)
decryptor = Cipher(algorithms.AES(exchange_key_bytes), modes.ECB()).decryptor()
decrypted = decryptor.update(ciphertext) + decryptor.finalize()
# PKCS7 padding eltávolítása: pad_len = decrypted[-1]; decrypted = decrypted[:-pad_len]
token = decrypted.decode("utf-8")
```

---

### 5. `tokenExchange` — hitelesítés ellenőrzése (`auth.py`)

A NAV API-nak nincs munkamenet-kezelése. A `tokenExchange` egyszerre:
- hitelesítési teszt (helyes-e a technikai felhasználó?)
- `manageInvoice` kérésekhez szükséges exchange token forrása

**Folyamat:**
1. Boríték felépítése `TokenExchangeRequest` root elemmel, body nélkül.
2. `POST /tokenExchange` → XML válasz `encodedExchangeToken` mezővel.
3. AES-128-ECB visszafejtés a cserekulccsal → plaintext token.
4. A token érvényessége: `tokenValidityFrom` / `tokenValidityTo`.

**Végpontok:**
```
Teszt:  https://api-test.onlineszamla.nav.gov.hu/invoiceService/v3/tokenExchange
Éles:   https://api.onlineszamla.nav.gov.hu/invoiceService/v3/tokenExchange
```

CLI teszt: `uv run nav login`

---

### 6. `queryInvoiceDigest` — számlalista (`query.py`)

**Kérés body:**
```xml
<page>1</page>
<invoiceDirection>INBOUND</invoiceDirection>   <!-- vagy OUTBOUND -->
<invoiceQueryParams>
  <mandatoryQueryParams>
    <invoiceIssueDate>
      <dateFrom>2026-05-01</dateFrom>
      <dateTo>2026-05-31</dateTo>          <!-- max 35 napos tartomány -->
    </invoiceIssueDate>
  </mandatoryQueryParams>
</invoiceQueryParams>
```

**Válasz feldolgozása:** `<invoiceDigest>` elemek iterálása → `InvoiceDigest` modellek.
Mezők: `invoiceNumber`, `invoiceOperation`, `invoiceCategory`, `invoiceIssueDate`,
`supplierTaxNumber`, `supplierName`, `customerTaxNumber`, `customerName`,
`invoiceNetAmountHUF`, `invoiceVatAmountHUF`, `currency`, `insDate`.

**Cache:** `digest:{from}:{to}:{direction}:{page}` kulcson, TTL: `CACHE_TTL_SECONDS` (default 3600 mp).

---

### 7. `queryInvoiceData` — egyedi számla XML (`query.py`)

**Kérés body:**
```xml
<invoiceNumberQuery>
  <invoiceNumber>SZAMLA-2026-001</invoiceNumber>
  <invoiceDirection>OUTBOUND</invoiceDirection>
  <!-- INBOUND esetén opcionális: <supplierTaxNumber>12345678</supplierTaxNumber> -->
</invoiceNumberQuery>
```

**Válasz feldolgozása:**
1. `<invoiceData>` mező: base64-kódolt tartalom.
2. `<compressedContentIndicator>` = `"true"` → gzip decompress szükséges.
3. Dekódolt string: a számla teljes business XML-je.

```python
raw = base64.b64decode(encoded)
if compressed:
    raw = gzip.decompress(raw)
invoice_xml = raw.decode("utf-8")
```

**Cache:** `data:{számlaszám}:{direction}` kulcson, TTL: `CACHE_TTL_SECONDS`.

**Részletmezők (3f60db6 / 830ccfc):** a dekódolt business XML-t a `invoice_data.py:parse_invoice_data` feldolgozza, és a `GET /invoices/{szamlaszam}` válasz a `szamlaszam` és `invoice_xml` mellett az alábbi `InvoiceDetailData` mezőket is adja (amik a digestből nem érhetők el):

| Mező | Forrás XML elem | Típus |
|---|---|---|
| `supplier_address` / `customer_address` | `supplierAddress` / `customerAddress` (detailedAddress összefűzve) | str |
| `supplier_bank_account` / `customer_bank_account` | `supplierBankAccountNumber` / `customerBankAccountNumber` | str |
| `payment_method` | `paymentMethod` | str |
| `payment_due_date` | `paymentDate` | str |
| `invoice_category` | `invoiceDetail/invoiceCategory` | str |
| `delivery_date` | `invoiceDeliveryDate` | str |
| `currency_code` | `currencyCode` | str |
| `exchange_rate` | `exchangeRate` | float \| None |
| `invoice_appearance` | `invoiceAppearance` | str |
| `invoice_net_amount` / `invoice_vat_amount` / `invoice_gross_amount` | `invoiceSummary` | float \| None |
| `lines` | `invoiceLines/line` → `InvoiceLineData` (lineNumber, lineDescription, quantity, unitOfMeasure, unitPrice, lineNetAmount, lineVatRate, lineVatAmount, lineGrossAmount) | lista |
| `vat_summary` | `summaryNormal/summaryByVatRate` → `InvoiceVatSummaryData` (vatRate, vatRateNetAmount, vatRateVatAmount) | lista |

**Modell-struktúra (c6167eb):** a `keltes_datuma` mező kikerült az `InvoiceDetail`-ből — a dátum továbbra is az `InvoiceHeader`-ben él, az `InvoiceDetail` = `header` + `line_items` + `status`.

---

### 7b. `queryTaxpayer` — adószám-ellenőrzés (`query.py`)

Magyar adószám érvényességének ellenőrzése a NAV nyilvántartásában (API-n és CLI-n keresztül jelenleg nem érhető el, csak Python API-ból).

**Kérés body:** `<taxNumber>{adószám}</taxNumber>`

**Cache:** `taxpayer:{adószám}` kulcson, TTL: `CACHE_TTL_SECONDS`.

**Válasz:** `{"valid": bool, "name": str, "short_name": str}` (`taxpayerValidity`, `taxpayerName`, `taxpayerShortName`).

---

### 8. Hibakezelés (`client.py`)

A NAV válasz gyökérelemének neve alapján:

| Root elem | Jelentés | Kezelés |
|---|---|---|
| `GeneralExceptionResponse` | Általános hiba | `NavApiError` kivétel |
| `TechnicalFault` | Technikai hiba | `NavApiError` kivétel |
| `GeneralErrorResponse` | Validációs hiba | `NavApiError` kivétel |
| `funcCode != "OK"` | Műveleti hiba | `NavApiError` kivétel |

A `NavApiError` tárolja: `message`, `func_code`, `error_code`.

HTTP Content-Type: `application/xml;charset=UTF-8` (kérés és válasz is).
Timeout: 70 mp (NAV API lassú lehet).

---

### 9. `manageInvoice` — adatszolgáltatás (`reporting.py`)

A számla beküldése a `reporting.py` modulban történik, automatikus `tokenExchange`-szel:

1. `request_token()` — exchange token kérése és AES-128 visszafejtése (a 4c pont szerint).
2. A szakmai XML base64-kódolása; a kérés-aláírás az operációnkénti `SHA3-512(operation + base64_invoiceData)` hash-ekkel bővül.
3. `POST /manageInvoice` → válaszban `transactionId`; `compressedContent` = `false`.

```xml
<exchangeToken>...</exchangeToken>
<invoiceOperations>
  <compressedContent>false</compressedContent>
  <invoiceOperation>
    <index>1</index>
    <invoiceOperation>CREATE</invoiceOperation>   <!-- CREATE | MODIFY | STORNO -->
    <invoiceData>{base64 szakmai XML}</invoiceData>
  </invoiceOperation>
</invoiceOperations>
```

**`queryTransactionStatus`** (`transactionId` + `returnOriginalRequest=false`) — a beküldött tranzakció feldolgozási státuszának lekérdezése (`processingResult` → `invoiceStatus`).

A `POST /report` végpont és a `nav report --json` parancs a régi `SubmitInvoiceRequest` modellből (fejléc + tételek) épít fel egy **egykulcsos, minimális** `InvoiceData` XML-t, majd azt küldi be `CREATE` művelettel; bonyolultabb számlákhoz dedikált számlagenerátor + `manage_invoice()` javasolt.

---

## Kapcsolódások

### Hívási sorrend

```mermaid
flowchart TD
    SD[invoice-core] -->|query| NAV[nav-invoice]
    NAV -->|request| NAVAPI[NAV API]
    NAVAPI -->|response| NAV
    NAV -->|digest| SD
```

### Wiki linkek
- **Prompt**: [[nav-invoice-prompt.md|NAV Invoice Prompt]]
- **Meghívva**: [[invoice-core-spec.md|Invoice-Core (MASTER)]]
- **Meghívom**: (senki — csak a NAV API-t hívja)
- **Projekt Index**: [[INDEX.md|Tiro - Mikorszervízek Indexe]]
