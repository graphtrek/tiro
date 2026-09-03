# uploader — Bankkivonat Feltöltő Mikroszerviz

Tiro pipeline mikroszerviz (port 8006). Webes felületen keresztül lehetővé teszi az Erste és Wise **CSV** bankkivonatok feltöltését a `bank` szerviz `balance-statements/` tároló mappájába, **plusz** az Erste és Wise **PDF** bankkivonatok feltöltését/kezelését egy külön `statements-pdf/` archívum mappában (a `bank` szerviz és a sync pipeline nem olvassa ezeket — csak archívum/letöltés célra szolgálnak).

**Levél szolgáltatás** — csak fájlrendszert kezel, DB-t nem kezel.

A feltöltési UI a `vision` szervizben van: CSV a `/ui/upload`, PDF a `/ui/bank-statements` oldalon; a vision mindkét esetben közvetlenül ezt az API-t hívja.

## Indítás

```bash
cd uploader
uv sync

# REST API (port 8006)
python run_api.py

# Vagy uvicorn-nal közvetlenül
uv run uvicorn uploader.api.main:app --host 0.0.0.0 --port 8006 --reload

# CLI (telepítve: `uploader` script)
uv run uploader status                                              # storage mappa + fájlok összesítése
uv run uploader list                                               # minden elérhető fájl listázása
uv run uploader list --bank erste                                  # csak Erste fájlok
uv run uploader list --bank wise                                   # csak Wise fájlok
uv run uploader upload 11600006-00000001-97860425_2026-01-01_2026-06-19.csv  # Erste feltöltése
uv run uploader upload statement_25546267_HUF_2026-01-01_2026-06-17.csv      # Wise feltöltése
uv run uploader upload <fájl> --bank erste                         # bank kézi megadása
uv run uploader upload <fájl> --overwrite                          # létező fájl felülírása
uv run uploader delete erste 11600006-00000001-97860425_2026-01-01_2026-06-19.csv
uv run uploader --verbose upload <fájl>                            # DEBUG napló
```

## REST API

| Metódus  | Útvonal                              | Leírás                                         |
|----------|--------------------------------------|------------------------------------------------|
| `GET`    | `/health`                            | Állapotellenőrző végpont                       |
| `GET`    | `/settings`                          | Aktív konfiguráció                             |
| `GET`    | `/api/v1/files`                      | Tárolt fájlok listája (minden bank)            |
| `GET`    | `/api/v1/files/{bank}`               | Adott bank fájljai (`erste` / `wise`)          |
| `POST`   | `/api/v1/upload`                     | CSV feltöltése (`multipart/form-data`)         |
| `GET`    | `/api/v1/files/{bank}/{filename}/download` | CSV fájl letöltése (`text/csv`)          |
| `DELETE` | `/api/v1/files/{bank}/{filename}`    | Fájl törlése                                   |
| `GET`    | `/api/v1/pdf/files`                  | Tárolt PDF bankkivonatok listája (minden bank) |
| `POST`   | `/api/v1/pdf/upload`                 | PDF feltöltése (`multipart/form-data`)         |
| `GET`    | `/api/v1/pdf/files/{bank}/{filename}/download` | PDF letöltése (`application/pdf`)  |
| `DELETE` | `/api/v1/pdf/files/{bank}/{filename}`| PDF törlése                                    |

> A PDF végpontoknak **nincs CLI parancsa** — csak a REST API-n és a Vision UI-n (`/ui/bank-statements`) keresztül kezelhetők.

### GET /health

```bash
curl http://localhost:8006/health
```

```json
{"status": "ok", "timestamp": "2026-06-24T10:00:00.000000"}
```

### GET /api/v1/files

Az összes tárolt CSV fájl összesítő listája.

```bash
curl http://localhost:8006/api/v1/files
```

```json
{
  "storage_dir": "/path/to/storage/bank/balance-statements",
  "banks": {
    "erste": [
      {
        "bank": "erste",
        "filename": "11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
        "size_bytes": 48320,
        "modified_at": "2026-06-24T10:30:00",
        "path": "/path/to/balance-statements/erste/11600006-00000001-97860425_2026-01-01_2026-06-19.csv"
      }
    ],
    "wise": []
  },
  "total_files": 1
}
```

### POST /api/v1/upload

CSV bankkivonat feltöltése `multipart/form-data` formátumban.

| Mező       | Típus        | Kötelező | Leírás                                                      |
|------------|--------------|----------|-------------------------------------------------------------|
| `file`     | `UploadFile` | igen     | CSV fájl                                                    |
| `bank`     | `string`     | nem      | `erste` \| `wise` — ha megadva, felülírja az auto-detektálást |
| `overwrite`| `bool`       | nem      | `false` — létező fájl felülírása                           |

```bash
# Erste feltöltése (auto-detektálás fájlnévből)
curl -X POST http://localhost:8006/api/v1/upload \
  -F "file=@11600006-00000001-97860425_2026-01-01_2026-06-19.csv"

# Wise feltöltése overwrite-tal
curl -X POST http://localhost:8006/api/v1/upload \
  -F "file=@statement_25546267_HUF_2026-01-01_2026-06-17.csv" \
  -F "overwrite=true"
```

Sikeres válasz (`200 OK`):

```json
{
  "filename": "11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
  "bank": "erste",
  "saved_path": "/path/to/balance-statements/erste/11600006-00000001-97860425_2026-01-01_2026-06-19.csv",
  "size_bytes": 48320,
  "overwritten": false
}
```

Hibakódok:

| Kód  | Ok                                                                 |
|------|--------------------------------------------------------------------|
| `400`| Nem CSV fájl; nem felismerhető fájlnév-séma; fájl már létezik és `overwrite=false`; méret > max |
| `422`| Hiányzó vagy érvénytelen form mező                                |

### DELETE /api/v1/files/{bank}/{filename}

```bash
curl -X DELETE http://localhost:8006/api/v1/files/erste/11600006-00000001-97860425_2026-01-01_2026-06-19.csv
```

Sikeres válasz: `204 No Content`. Ha a fájl nem található: `404`.

### POST /api/v1/pdf/upload

PDF bankkivonat feltöltése `multipart/form-data` formátumban — a bank neve **és** a kivonat időszaka (`from_date`/`to_date`) is a fájlnévből olvasódik ki (lásd [PDF fájlnév-felismerés](#pdf-fájlnév-felismerés)).

| Mező       | Típus        | Kötelező | Leírás                                                      |
|------------|--------------|----------|-------------------------------------------------------------|
| `file`     | `UploadFile` | igen     | PDF fájl                                                    |
| `bank`     | `string`     | nem      | `erste` \| `wise` — ha megadva, felülírja az auto-detektálást (a `from_date`/`to_date` ekkor is a fájlnévből származik) |
| `overwrite`| `bool`       | nem      | `false` — létező fájl felülírása                           |

```bash
curl -X POST http://localhost:8006/api/v1/pdf/upload \
  -F "file=@statement_25546267_HUF_2026-01-01_2026-06-17.pdf"
```

Sikeres válasz (`200 OK`):

```json
{
  "filename": "statement_25546267_HUF_2026-01-01_2026-06-17.pdf",
  "bank": "wise",
  "from_date": "2026-01-01",
  "to_date": "2026-06-17",
  "saved_path": "/path/to/statements-pdf/wise/statement_25546267_HUF_2026-01-01_2026-06-17.pdf",
  "size_bytes": 184320,
  "overwritten": false
}
```

### GET /api/v1/pdf/files

```bash
curl http://localhost:8006/api/v1/pdf/files
```

Egy sík `PdfStatementFile` lista — szemben a CSV `GET /api/v1/files` bank-kulcsos struktúrájával.

### DELETE /api/v1/pdf/files/{bank}/{filename}

```bash
curl -X DELETE http://localhost:8006/api/v1/pdf/files/wise/statement_25546267_HUF_2026-01-01_2026-06-17.pdf
```

Sikeres válasz: `204 No Content`. Ha a fájl nem található: `404`.

## Bankdetektálás

A bank típusát a fájlnévből határozza meg — ugyanolyan séma szerint, ahogy a `bank` szerviz feldolgozza:

| Bank  | Fájlnév-séma                                         | Példa                                                       |
|-------|------------------------------------------------------|-------------------------------------------------------------|
| Erste | `<számlaszám>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv`         | `11600006-00000001-97860425_2026-01-01_2026-06-19.csv`      |
| Wise  | `statement_<balanceId>_<currency>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv` | `statement_25546267_HUF_2026-01-01_2026-06-17.csv` |

Detektálási prioritás:
1. `statement_` kezdetű → **Wise**
2. dátum-mintájú vég (`_YYYY-MM-DD_YYYY-MM-DD.csv`) és nem `statement_` → **Erste**
3. egyéb → `400` validációs hiba

### PDF fájlnév-felismerés

A PDF kivonatok fájlnév-sémája eltér a CSV-től; a `parse_pdf_statement()` a bankot **és** az időszakot (`from_date`/`to_date`) is a fájlnévből olvassa ki:

| Bank  | Fájlnév-séma                                                     | Példa                                                  | Dátumformátum         |
|-------|-------------------------------------------------------------------|---------------------------------------------------------|------------------------|
| Wise  | `statement_<balanceId>_<currency>_<YYYY-MM-DD>_<YYYY-MM-DD>.pdf` | `statement_25546267_HUF_2026-01-01_2026-06-17.pdf`      | kötőjeles ISO dátum   |
| Erste | `<számlaszám/IBAN>_<YYYYMMDD>_<YYYYMMDD>.pdf`                    | `11600006-00000001-97860425_20260101_20260619.pdf`      | kötőjel nélküli dátum |

Detektálási prioritás: előbb a Wise minta (`statement_` prefix), utána az Erste minta; ha egyik sem illik → `400`.

## CLI

A `--verbose` / `-v` globális opció — a parancs neve **elé** kell írni:

```bash
uv run uploader --verbose upload <fájl>
```

### status

Storage mappa és fájlok összesítése.

```bash
uv run uploader status
```

```
Storage könyvtár: /path/to/storage/bank/balance-statements

ERSTE — 1 fájl
  11600006-00000001-97860425_2026-01-01_2026-06-19.csv  (48,320 bájt, 2026-06-24 10:30)

WISE — 0 fájl

Összesen: 1 fájl
```

### list

Elérhető fájlok listázása.

```bash
uv run uploader list [--bank erste|wise|all]
```

```
 Bank   Fájlnév                                                       Méret       Módosítva
 erste  11600006-00000001-97860425_2026-01-01_2026-06-19.csv          48,320 B    2026-06-24 10:30
 wise   statement_25546267_HUF_2026-01-01_2026-06-17.csv              31,744 B    2026-06-23 14:15
```

### upload

CSV fájl feltöltése a storage mappába.

```bash
uv run uploader upload <fájl> [--bank erste|wise] [--overwrite]
```

| Opció       | Default | Leírás                                                  |
|-------------|---------|----------------------------------------------------------|
| `--bank`    | —       | Bank kézi megadása (auto-detektálás ha nem adott meg)   |
| `--overwrite` | ki   | Létező fájl felülírása                                  |

```bash
# Auto-detektálással
uv run uploader upload 11600006-00000001-97860425_2026-01-01_2026-06-19.csv

# Bank kézi megadásával
uv run uploader upload kivonat.csv --bank erste

# Felülírás
uv run uploader upload statement_25546267_HUF_2026-01-01_2026-06-17.csv --overwrite
```

Példa kimenet:

```
Feltöltve: 11600006-00000001-97860425_2026-01-01_2026-06-19.csv → ERSTE (48,320 bájt)
  /path/to/balance-statements/erste/11600006-00000001-97860425_2026-01-01_2026-06-19.csv
```

### delete

Fájl törlése a storage mappából.

```bash
uv run uploader delete <bank> <fájlnév>
```

```bash
uv run uploader delete erste 11600006-00000001-97860425_2026-01-01_2026-06-19.csv
uv run uploader delete wise statement_25546267_HUF_2026-01-01_2026-06-17.csv
```

## Konfiguráció (`.env`)

| Változó              | Default                               | Leírás                                             |
|----------------------|---------------------------------------|----------------------------------------------------|
| `STORAGE_DIR`        | `../storage/bank/balance-statements`  | CSV fájlok gyökérmappája (bank szervizzel közös)   |
| `PDF_STORAGE_DIR`    | `../storage/bank/statements-pdf`      | PDF kivonatok archívuma — csak az uploader olvassa/írja |
| `ERSTE_SUBDIR`       | `erste`                               | Erste almappa neve                                 |
| `WISE_SUBDIR`        | `wise`                                | Wise almappa neve                                  |
| `MAX_FILE_SIZE_MB`   | `50`                                  | Maximális feltölthető fájlméret MB-ban             |
| `API_HOST`           | `0.0.0.0`                             | FastAPI bind cím                                   |
| `UPLOADER_API_PORT`  | `8006`                                | FastAPI port (`API_PORT` is elfogadott alias)      |
| `LOG_LEVEL`          | `INFO`                                | Napló szint (`DEBUG`, `INFO`, `WARNING`, `ERROR`)  |
| `AUTH_ENABLED`       | `true`                                | JWT ellenőrzés be/ki                                |
| `AUTH_SERVICE_URL`   | `http://localhost:8007`               | Központi auth szerviz base URL (JWKS)              |

> `STORAGE_DIR` ugyanaz a könyvtár, mint a `bank` szerviz `BALANCE_STATEMENTS_DIR`-je. Dev környezetben relatív elérési úttal konfigurálható; prodban abszolút út ajánlott. `PDF_STORAGE_DIR` egy elkülönített archívum-mappa, amit a `bank` szerviz nem olvas.

## Authentikáció (JWT)

`AUTH_ENABLED=true` esetén a `GET /health` kivételével minden végpont érvényes
JWT-t igényel, amelyet a központi **auth** szerviz (:8007) állít ki Google
belépés után. A token `Authorization: Bearer <token>` fejlécben vagy
`mp_access_token` HttpOnly cookie-ban érkezhet (a vision automatikusan
továbbadja); az ellenőrzés lokális a JWKS publikus kulcsokkal. Token nélkül a
válasz `401 Unauthorized`.

Implementáció: `src/uploader/auth.py` · specifikáció: `../doc/auth-service-spec.md`.

## Vision UI

A CSV feltöltési felület a `vision` szervizben érhető el a `/ui/upload` útvonalon, a PDF bankkivonatok kezelése egy külön oldalon, a `/ui/bank-statements` útvonalon.

**CSV feltöltés (`/ui/upload`) funkciói:**
- Drag & drop vagy fájlböngésző (`accept=".csv"`)
- Bankdetektálás preview: feltöltés előtt kliensoldalon fájlnévből (JavaScript)
- Bank kézi megadása legördülővel
- Overwrite checkbox
- Tárolt fájlok listája törölhető sorokkal (HTMX DELETE)
- Eredmény: sikeres / hibás feltöltés Bootstrap alertként

```
Böngésző → Vision (/ui/upload) → POST /api/v1/upload → balance-statements/{bank}/*.csv
                                                                ↓
                                                      Bank szerviz olvassa
```

**PDF bankkivonatok (`/ui/bank-statements`) funkciói:**
- Ugyanaz a feltöltési/listázási/törlési UX mint a CSV oldalon, de a `.pdf` fájlokra és a `/api/v1/pdf/*` végpontokra hívva
- Letöltés gomb minden sorban (streamelt letöltés az uploader-től)
- **Anonimizált (`anonymized: true`) nézetben** a fájlnevek (számlaszámot/IBAN-t tartalmaznak) determinisztikus álnévre cserélődnek, és a letöltés `403`-mal el van tiltva

```
Böngésző → Vision (/ui/bank-statements) → POST /api/v1/pdf/upload → statements-pdf/{bank}/*.pdf
                                                                          (archívum — senki más nem olvassa)
```

## Naplózás

Naplók stdout-ra és `logs/uploader.log` fájlba is kerülnek.

```
2026-06-24 10:30:00 INFO     uploader.storage: Mentve: .../erste/11600006-..._2026-01-01_2026-06-19.csv (48320 bájt, overwrite=False)
2026-06-24 10:30:01 INFO     uploader.api.main: POST /api/v1/upload → 200 in 12ms
2026-06-24 10:31:00 INFO     uploader.storage: Törölve: .../wise/statement_25546267_HUF_2026-01-01_2026-06-17.csv
```

## Architektúra

```
# Workspace gyökér
storage/
└── bank/
    ├── balance-statements/          # feltöltött CSV-k (.gitignore)
    │   ├── erste/                   #   <számlaszám>_<from>_<to>.csv
    │   └── wise/                    #   statement_<balanceId>_<currency>_<from>_<to>.csv
    └── statements-pdf/               # feltöltött PDF kivonatok, archívum (.gitignore)
        ├── erste/                   #   <számlaszám>_<YYYYMMDD>_<YYYYMMDD>.pdf
        └── wise/                    #   statement_<balanceId>_<currency>_<from>_<to>.pdf

uploader/
├── pyproject.toml
├── run_api.py                       # VS Code debug belépési pont (port 8006)
├── .env
└── src/uploader/
    ├── config.py                    # pydantic-settings, configure_logging()
    ├── models.py                    # UploadResult, StorageFile, StorageStatus, PdfUploadResult, PdfStatementFile
    ├── detector.py                  # bankdetektálás fájlnévből (regex) + parse_pdf_statement() (PDF: bank + időszak)
    ├── storage.py                   # fájl mentés / lista / törlés / letöltés (CSV: balance-statements/, PDF: statements-pdf/)
    ├── api/main.py                  # FastAPI végpontok
    └── cli/main.py                  # Typer CLI (uploader script) — csak a CSV ágra
```

## Pipeline helye

```
Böngésző
  └─ vision (/ui/upload)
       └─ uploader (ez)  →  storage/bank/balance-statements/erste/*.csv
                         →  storage/bank/balance-statements/wise/*.csv
                                          ↓
                              bank (8005) olvassa
                                          ↓
                              invoice-core (8004) hívja
```

Az uploader által feltöltött CSV-ket a `bank` szerviz olvassa be automatikusan a következő `sync_bank` híváskor — explicit triggerelés nem szükséges.

A PDF kivonatok ezzel szemben egy párhuzamos, önálló archívumba (`statements-pdf/`) kerülnek — sem a `bank` szerviz, sem a sync pipeline nem olvassa őket, kizárólag emberi letöltés/megőrzés céljából tárolódnak.
