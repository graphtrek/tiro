---
title: "Specifikáció: Uploader – Bankkivonat Feltöltő Szolgáltatás"
description: "Erste és Wise CSV bankkivonatok feltöltése a bank szerviz storage mappájába, plusz Erste/Wise PDF bankkivonatok feltöltése/kezelése; UI a vision-ben, backend neve uploader"
type: "service-spec"
status: "implementált"
port: 8006
language: "HU"
last_updated: "2026-09-03"
depends_on: [bank-spec.md, vision-spec.md, auth-service-spec.md]
related: [INDEX.md, bank-spec.md, bank-prompt.md, vision-spec.md, vision-prompt.md, uploader-promp.md, auth-service-spec.md]
tags: [uploader, bank, erste, wise, csv, storage, fastapi, vision, upload, jwt, docker]
---

# Uploader – Bankkivonat Feltöltő Szolgáltatás — Specifikáció

> 🔗 **Kapcsolat**: feltöltött fájlokat [[bank-spec.md|Bank szerviz]] (port 8005) olvassa; UI [[vision-spec.md|Vision]] (port 8009) kiszolgálja

---

## Szerepkör és kontextus

Az Uploader egy önálló leaf mikroszerviz, amely webes felületen keresztül lehetővé teszi az Erste és Wise **CSV** bankkivonatok feltöltését a bank szerviz `balance-statements/` tároló mappájába, **plusz** az Erste és Wise **PDF** bankkivonatok (a bank saját formátumú kivonat-PDF-jei) feltöltését és kezelését egy külön `statements-pdf/` mappában. Nincs adatbázisa — csak fájlrendszert kezel.

**Probléma**: A `bank` szerviz azt feltételezi, hogy a CSV kivonatok a `balance-statements/erste/` ill. `balance-statements/wise/` alkönyvtárba kerülnek. Az Uploader webes feltöltési UI-t biztosít ehhez — így nem kell kézzel másolni a fájlokat a storage mappába. A PDF kivonatok (emberi olvasásra szánt, letölthető/megőrzendő dokumentumok) egy párhuzamos, a `bank` szerviz feldolgozási láncától független tárolóba kerülnek — a `bank` szerviz és a sync pipeline **nem** olvassa őket, kizárólag archívum/letöltés célra szolgálnak.

**UI elhelyezése**: A CSV feltöltési felület a `vision` szervizben van (`/ui/upload`), a PDF kivonatok kezelése egy külön oldalon (`/ui/bank-statements`). A vision mindkét esetben közvetlenül az uploader REST API-ját hívja multipart file upload-hoz.

**Hívási lánc**:
```
Böngésző → Vision (/ui/upload) → Uploader (POST /api/v1/upload) → balance-statements/{bank}/*.csv
                                                                         ↓
                                                               Bank szerviz olvassa

Böngésző → Vision (/ui/bank-statements) → Uploader (POST /api/v1/pdf/upload) → statements-pdf/{bank}/*.pdf
                                                                                     (archívum — senki más nem olvassa)
```

---

## Fájl-felderítés és bankdetektálás

A banktípust a fájlnévből kell meghatározni — pontosan ugyanolyan séma szerint, ahogy a `bank` szerviz feldolgozza:

| Bank | Fájlnév-séma | Példa |
|---|---|---|
| Erste | `<számlaszám>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv` | `11600006-00000001-97860425_2026-01-01_2026-06-19.csv` |
| Wise | `statement_<balanceId>_<currency>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv` | `statement_25546267_HUF_2026-01-01_2026-06-17.csv` |

Detektálási logika (prioritás sorrendben; a mintaillesztés kis- és nagybetűtől független):
1. Ha a fájlnév `statement_`-tal kezdődik → **Wise**
2. Ha a fájlnév dátum-mintájú végű (`_YYYY-MM-DD_YYYY-MM-DD.csv`, regex: `.+_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv$`) és nem `statement_`-tal kezdődik → **Erste**
3. Egyéb → `None`, a feltöltés `400` hibával elutasítva

### PDF kivonatok

A PDF kivonatok neve nem egyezik a CSV sémával — a `parse_pdf_statement()` egyszerre azonosítja a bankot **és** a kivonat időszakát (`from_date`/`to_date`) a fájlnévből:

| Bank | Fájlnév-séma | Példa | Dátumformátum |
|---|---|---|---|
| Wise | `statement_<balanceId>_<currency>_<YYYY-MM-DD>_<YYYY-MM-DD>.pdf` | `statement_25546267_HUF_2026-01-01_2026-06-17.pdf` | kötőjeles ISO dátum |
| Erste | `<számlaszám/IBAN>_<YYYYMMDD>_<YYYYMMDD>.pdf` | `11600006-00000001-97860425_20260101_20260619.pdf` | kötőjel nélküli dátum |

Detektálás: előbb a Wise minta (`statement_` prefix), utána az Erste minta (`..._<8 számjegy>_<8 számjegy>.pdf`) próbálkozik; ha egyik sem illik, a feltöltés `400`-zal elutasítva. A CSV-detektálástól eltérően itt a `bank` mező explicit megadása **nem** kerüli meg a fájlnév-parszolást — `from_date`/`to_date` mindig a fájlnévből származik.

---

## Adatmodellek

### `UploadResult`

```python
class UploadResult(BaseModel):
    filename: str           # mentett fájlnév
    bank: str               # "erste" | "wise"
    saved_path: str         # teljes elérési út a storage-ban
    size_bytes: int
    overwritten: bool       # igaz, ha azonos nevű fájl már létezett
```

### `StorageFile`

```python
class StorageFile(BaseModel):
    bank: str               # "erste" | "wise"
    filename: str
    size_bytes: int
    modified_at: datetime
    path: str
```

### `StorageStatus`

```python
class StorageStatus(BaseModel):
    storage_dir: str
    banks: dict[str, list[StorageFile]]   # {"erste": [...], "wise": [...]}
    total_files: int
```

### `PdfUploadResult`

```python
class PdfUploadResult(BaseModel):
    filename: str
    bank: str               # "erste" | "wise"
    from_date: date         # a fájlnévből kiolvasott kivonat-időszak eleje
    to_date: date           # a fájlnévből kiolvasott kivonat-időszak vége
    saved_path: str
    size_bytes: int
    overwritten: bool
```

### `PdfStatementFile`

```python
class PdfStatementFile(BaseModel):
    bank: str               # "erste" | "wise"
    filename: str
    from_date: date
    to_date: date
    size_bytes: int
    modified_at: datetime
    path: str
```

---

## REST API (port 8006)

> **Hitelesítés**: minden végpont JWT-t igényel (lásd a [[auth-service-spec.md|JWT hitelesítés]] szakaszt lentebb) — kivéve a `GET /health`-et, ami publikus.

| Method | Endpoint | Leírás |
|---|---|---|
| `GET` | `/health` | állapotellenőrzés (publikus, JWT nélkül) |
| `GET` | `/settings` | aktív konfiguráció (storage, limitek, port, log szint) |
| `GET` | `/api/v1/files` | tárolt fájlok listája (minden bank) |
| `GET` | `/api/v1/files/{bank}` | adott bank fájljai (`erste` / `wise`); `400` ismeretlen bank esetén |
| `POST` | `/api/v1/upload` | CSV feltöltése (multipart/form-data) |
| `GET` | `/api/v1/files/{bank}/{filename}/download` | fájl letöltése (`text/csv`); `404` ha nem létezik |
| `DELETE` | `/api/v1/files/{bank}/{filename}` | fájl törlése → `204`; `404` ha nem létezik |
| `GET` | `/api/v1/pdf/files` | tárolt PDF bankkivonatok listája (minden bank) |
| `POST` | `/api/v1/pdf/upload` | PDF bankkivonat feltöltése (multipart/form-data) |
| `GET` | `/api/v1/pdf/files/{bank}/{filename}/download` | PDF letöltése (`application/pdf`); `404` ha nem létezik |
| `DELETE` | `/api/v1/pdf/files/{bank}/{filename}` | PDF törlése → `204`; `404` ha nem létezik |

### `POST /api/v1/upload`

**Request**: `multipart/form-data`

| Mező | Típus | Kötelező | Leírás |
|---|---|---|---|
| `file` | `UploadFile` | igen | CSV fájl (a fájlnév `.csv` végződésű legyen) |
| `bank` | `str` | nem | `erste` \| `wise` — ha megadva, felülírja az automatikus detektálást |
| `overwrite` | `bool` | nem (default: `false`) | létező fájl felülírása |

**Validáció (sorrendben)**:
1. Hiányzó fájlnév → `400`
2. Fájlnév nem `.csv` végződésű (kis/nagybetűtől függetlenül) → `400`
3. Méret > `MAX_FILE_SIZE_MB` → `400`
4. Bankdetektálás: a `bank` mező, ha megadva, felülírja a `detect_bank()`-ot; ha az eredmény nem `erste`/`wise` → `400` (formátum-hint az üzenetben)
5. `overwrite=false` és azonos nevű fájl már létezik → `400` (`FileExistsError`)

**Response** `200 OK`: `UploadResult`

**Hibák**:
- `400` — hiányzó fájlnév, nem CSV, méretlimit túllépés, nem felismerhető formátum, `overwrite=false` és fájl már létezik
- `401` — hiányzó/érvénytelen access token (ha az auth be van kapcsolva)
- `503` — az auth szerviz (JWKS) nem érhető el
- `422` — hiányzó `file` mező (FastAPI validáció)

**Példa response**:

```json
{
  "filename": "11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
  "bank": "erste",
  "saved_path": "/tiro/storage/bank/balance-statements/erste/11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
  "size_bytes": 48320,
  "overwritten": false
}
```

### `GET /api/v1/files`

**Response** `200 OK`: `StorageStatus`

```json
{
  "storage_dir": "/tiro/storage/bank/balance-statements",
  "banks": {
    "erste": [
      {
        "bank": "erste",
        "filename": "11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
        "size_bytes": 48320,
        "modified_at": "2026-06-24T10:30:00",
        "path": "/tiro/storage/bank/balance-statements/erste/11600006-00000001-97860425_2026-01-01_2026-06-19.csv"
      }
    ],
    "wise": []
  },
  "total_files": 1
}
```

### `POST /api/v1/pdf/upload`

**Request**: `multipart/form-data`

| Mező | Típus | Kötelező | Leírás |
|---|---|---|---|
| `file` | `UploadFile` | igen | PDF fájl (a fájlnév `.pdf` végződésű legyen) |
| `bank` | `str` | nem | `erste` \| `wise` — ha megadva, felülírja az automatikus bank-detektálást (a `from_date`/`to_date` ekkor is a fájlnévből származik) |
| `overwrite` | `bool` | nem (default: `false`) | létező fájl felülírása |

**Validáció (sorrendben)**: hiányzó fájlnév → `400`; nem `.pdf` végződés → `400`; méret > `MAX_FILE_SIZE_MB` → `400`; `parse_pdf_statement()` nem ismeri fel a fájlnevet (sem Erste, sem Wise minta) → `400`; `overwrite=false` és azonos nevű fájl már létezik → `400`.

**Response** `200 OK`: `PdfUploadResult`

```json
{
  "filename": "statement_25546267_HUF_2026-01-01_2026-06-17.pdf",
  "bank": "wise",
  "from_date": "2026-01-01",
  "to_date": "2026-06-17",
  "saved_path": "/tiro/storage/bank/statements-pdf/wise/statement_25546267_HUF_2026-01-01_2026-06-17.pdf",
  "size_bytes": 184320,
  "overwritten": false
}
```

`GET /api/v1/pdf/files` ugyanígy `PdfStatementFile` listát ad vissza — egy sík lista, szemben a CSV `GET /api/v1/files` bank-kulcsos `StorageStatus` struktúrájával.

---

## JWT hitelesítés

Az uploader a [[auth-service-spec.md|központi auth szerviz]] (`:8007`) JWKS kulcsaival validálja a tokeneket — a `require_auth` app-szintű dependency minden végponton fut, kivéve a `PUBLIC_PATHS = {"/health"}`-et.

- **Token forrása**: `Authorization: Bearer <access-token>` fejléc **vagy** `mp_access_token` cookie
- **Algoritmus**: RS256; ellenőrzött claim-ek: `exp`, `aud` (`tiro`), `iss` (`auth-service`), `typ` (`access`)
- **JWKS**: `{auth_service_url}/.well-known/jwks.json` — a `PyJWKClient` cache-eli (1 óra TTL, ismeretlen `kid` esetén újratöltés), így nincs kérésenkénti hálózati hívás az auth szerviz felé
- **Hibák**: `401` hiányzó/érvénytelen token; `503` ha az auth szerviz/JWKS nem érhető el (hálózat/TLS hiba)
- **Kikapcsolás**: `AUTH_ENABLED=false` (tesztekhez) — ilyenkor minden végpont token nélkül hívható

A Vision kliens a bejelentkezett felhasználó access tokenjét továbbítja a hívásaiban; a CLI közvetlenül a storage-t éri el, JWT nélkül.

---

## CLI (script neve: `uploader`)

```bash
uploader status                            # storage mappa + fájlok összesítése
uploader list [--bank erste|wise|all]      # elérhető fájlok listázása
uploader upload <fájl> [--bank erste|wise] [--overwrite]  # fájl feltöltése
uploader delete <bank> <fájlnév>           # fájl törlése
```

A CLI közvetlenül a storage mappát kezeli — **nem igényel JWT-t**; a `-v`/`--verbose` globális kapcsoló DEBUG naplózást kapcsol be.

> A PDF-kivonat funkcióhoz (lásd lentebb) **nincs CLI parancs** — csak a REST API-n és a Vision UI-n keresztül kezelhető.

---

## Vision UI (megvalósult)

A feltöltési felület a vision szervizben fut (`ui/uploader_router.py`, `prefix="/ui"`), és közvetlenül az uploader REST API-ját hívja a `clients/uploader.py`-ból (`UploaderClient`).

### Route-ok

| Method | Endpoint | Leírás |
|---|---|---|
| `GET` | `/ui/upload` | feltöltési oldal (`upload.html`) — a tárolt fájlok listájával |
| `POST` | `/ui/upload/do` | HTMX: feltöltés végrehajtása, eredmény alert partial |
| `GET` | `/ui/upload/files` | HTMX partial: tárolt fájlok táblázata (`partials/upload_files.html`) |
| `GET` | `/ui/upload/files/{bank}/{filename}/download` | átirányítás az uploader letöltési végpontjára |
| `DELETE` | `/ui/upload/files/{bank}/{filename}` | HTMX: fájl törlése |

**Tartalom**:
- Drag & drop vagy fájlböngésző (`<input type="file" accept=".csv">`)
- `Overwrite` checkbox
- Feltöltés → uploader `POST /api/v1/upload` (multipart, az auth token továbbításával)
- Eredmény: sikeres/hibás feltöltés jelzése (Bootstrap alert)
- Jelenlegi fájlok listája (`GET /api/v1/files`) — táblázatban, törölhető sorokkal (HTMX DELETE)

### Navbar

A `_sidebar.html` tartalmazza:

```
📤 Feltöltés  →  /ui/upload
```

### Vision kliens

`clients/uploader.py` — `UploaderClient`:

```python
class UploaderClient:
    def upload_file(self, file_bytes: bytes, filename: str, bank: str | None = None, overwrite: bool = False) -> dict | None: ...
    def list_files(self) -> dict | None: ...
    def delete_file(self, bank: str, filename: str) -> bool: ...
```

A kliens HTTP hibánál `{"error": ...}` dictet, hálózati hibánál `None`-t ad vissza.

### PDF bankkivonatok oldala (`/ui/bank-statements`)

Külön route-modul (`ui/bank_statements_router.py`, `prefix="/ui"`) — az `/ui/upload` CSV-feltöltő oldaltól függetlenül kezeli a PDF-eket, de ugyanazt az uploader REST API-t hívja (`UploaderClient` PDF metódusai: `upload_pdf_statement`, `list_pdf_statements`, `delete_pdf_statement`).

| Method | Endpoint | Leírás |
|---|---|---|
| `GET` | `/ui/bank-statements` | PDF bankkivonatok oldala (`bank_statements.html`) |
| `POST` | `/ui/bank-statements/upload` | HTMX: feltöltés végrehajtása, eredmény alert partial |
| `GET` | `/ui/bank-statements/table` | HTMX partial: tárolt PDF-ek táblázata (`partials/bank_statement_table.html`) |
| `GET` | `/ui/bank-statements/{bank}/{filename}/download` | streamelt letöltés az uploader-től (`403` anonimizált nézetben) |
| `DELETE` | `/ui/bank-statements/{bank}/{filename}` | HTMX: törlés, majd a táblázat rerenderelése |

**Anonimizált (`anonymized: true`) nézet**: a fájlnevek (amik számlaszámot/IBAN-t tartalmaznak) determinisztikus álnévre cserélődnek (`_fake_statement_filename()` — SHA-256 alapú, invoice-core `fake_identifier()` mintájára), és a letöltés `403`-mal el van tiltva — a valódi bankszámla-adat így az anonimizált tier alól sem szivárog ki.

A `_sidebar.html` a `/ui/upload` mellett külön menüpontot tartalmaz a `/ui/bank-statements`-hez.

---

## Projektstruktúra

```
uploader/
├── src/uploader/
│   ├── __init__.py
│   ├── auth.py            # JWT validálás az auth szerviz JWKS kulcsaival
│   ├── config.py          # pydantic-settings, közös gyökér .env
│   ├── models.py          # UploadResult, StorageFile, StorageStatus, PdfUploadResult, PdfStatementFile
│   ├── detector.py        # bankdetektálás fájlnévből (CSV) + parse_pdf_statement() (PDF: bank + időszak)
│   ├── storage.py         # fájl mentés / lista / törlés / letöltés (CSV: balance-statements/, PDF: statements-pdf/)
│   ├── api/
│   │   └── main.py        # FastAPI app
│   └── cli/
│       └── main.py        # Typer CLI
├── tests/                 # pytest: conftest, test_api, test_auth_jwks, test_detector, test_storage
├── Dockerfile             # uv-alapú, python3.14-bookworm-slim, EXPOSE 8006
├── pyproject.toml
└── run_api.py             # debug entry (uvicorn, reload)
```

---

## Tech stack

- Python 3.14 (`requires-python >=3.14`)
- FastAPI + Uvicorn (`python-multipart` a file upload-hoz)
- PyJWT (`pyjwt[crypto]`) + certifi — JWT validálás, TLS trust store a JWKS lekéréshez
- Typer, Rich
- Pydantic v2
- pydantic-settings (`.env` konfiguráció)
- pytest + httpx (tesztek), ruff (lint)
- Docker: `ghcr.io/astral-sh/uv:python3.14-bookworm-slim`, `EXPOSE 8006`

---

## Environment (`.env`)

A konfiguráció a **közös gyökér `.env`-ből** töltődik (`<workspace>/.env`, 340075c óta) — nincs lokális `uploader/.env`. Minden beállításnak kódbeli defaultja is van, így `.env` nélkül is működik a szerviz.

```env
# Megegyezik a bank szerviz BALANCE_STATEMENTS_DIR-jével
STORAGE_DIR=../storage/bank/balance-statements   # az uploader és bank közös könyvtár (default), CSV
PDF_STORAGE_DIR=../storage/bank/statements-pdf   # PDF kivonatok archívuma (default) — csak az uploader olvassa/írja
ERSTE_SUBDIR=erste
WISE_SUBDIR=wise
MAX_FILE_SIZE_MB=50
API_HOST=0.0.0.0
UPLOADER_API_PORT=8006     # API_PORT is elfogadott alias
LOG_LEVEL=INFO
# JWT / auth (lásd auth.py — az auth szerviz JWKS-ét használja)
AUTH_ENABLED=true
AUTH_SERVICE_URL=http://localhost:8007
JWT_AUDIENCE=tiro
JWT_ISSUER=auth-service
```

> **Fontos**: `STORAGE_DIR` ugyanaz a könyvtár, mint a `bank` szerviz `BALANCE_STATEMENTS_DIR`-je (`<workspace>/storage/bank/balance-statements`). Dev környezetben relatív elérési úttal konfigurálható; prodban abszolút út ajánlott. `PDF_STORAGE_DIR` ezzel szemben egy elkülönített archívum-mappa (`<workspace>/storage/bank/statements-pdf`) — ezt a `bank` szerviz **nem** olvassa.

A naplózás (`LOG_LEVEL`) stream + fájl (`uploader/logs/uploader.log`) formában történik.

---

## Megvalósítási állapot

Minden tétel elkészült (e2e520a → 1606239 közötti commitok):

1. ✅ `config.py` + `models.py` — pydantic-settings + modellek
2. ✅ `detector.py` — Erste/Wise fájlnév detektálás (regex)
3. ✅ `storage.py` — fájl mentés, lista, törlés a konfigurált mappában
4. ✅ `api/main.py` — FastAPI: `/health`, `/settings`, `/api/v1/files`, `/api/v1/upload`, `/api/v1/files/{bank}/{filename}/download`, DELETE
5. ✅ JWT védelem (06c9d10) — `auth.py`, app-szintű `require_auth` dependency
6. ✅ `cli/main.py` — Typer CLI: `status`, `list`, `upload`, `delete`
7. ✅ Vision UI (`ui/uploader_router.py`): `/ui/upload`, HTMX upload/delete/list, `clients/uploader.py`
8. ✅ Docker (21d44bf) + tesztek (1606239: conftest, api, auth_jwks, detector, storage)
9. ✅ Közös gyökér `.env` (340075c)
10. ✅ PDF bankkivonat feltöltés/kezelés (cf550b9): `api/main.py` `/api/v1/pdf/*` végpontok, `models.PdfUploadResult`/`PdfStatementFile`, `detector.parse_pdf_statement()`, `storage.py` `statements-pdf/` ág, Vision `ui/bank_statements_router.py` (`/ui/bank-statements`) + anonimizált fájlnév-maszkolás

---

## Kapcsolódások

```mermaid
flowchart TD
    B[Böngésző] -->|GET /ui/upload| V[vision :8009]
    V -->|POST /api/v1/upload| U[uploader :8006]
    V -->|GET /api/v1/files| U
    V -->|DELETE /api/v1/files/...| U
    U -->|write CSV| S[(storage/bank/balance-statements/erste/ vagy wise/)]
    BK[bank :8005] -->|read CSV| S
    IC[invoice-core :8004] -->|GET /balance-statement/all| BK
    A[auth :8007] -->|JWKS / JWT validálás| U

    B -->|GET /ui/bank-statements| V
    V -->|POST /api/v1/pdf/upload| U
    V -->|GET /api/v1/pdf/files| U
    U -->|write PDF| P[(storage/bank/statements-pdf/erste/ vagy wise/ — archívum, senki más nem olvassa)]
```

---

## Wiki Linkek

- **Prompt**: [[uploader-promp.md|Uploader Prompt]]
- **Tárolt fájlokat olvassa**: [[bank-spec.md|Bank Spec]] (port 8005)
- **UI helye**: [[vision-spec.md|Vision Spec]] (port 8009, `/ui/upload` oldal)
- **Projekt Index**: [[INDEX.md|Tiro Index]]
