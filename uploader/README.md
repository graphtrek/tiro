# uploader — Bankkivonat Feltöltő Mikroszerviz

Moneypenny pipeline mikroszerviz (port 8006). Webes felületen keresztül lehetővé teszi az Erste és Wise CSV bankkivonatok feltöltését a `bank` szerviz `balance-statements/` tároló mappájába.

**Levél szolgáltatás** — csak fájlrendszert kezel, DB-t nem kezel.

A feltöltési UI a `vision` szervizben van (`/ui/upload`); a vision közvetlenül ezt az API-t hívja.

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
| `DELETE` | `/api/v1/files/{bank}/{filename}`    | Fájl törlése                                   |

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
| `ERSTE_SUBDIR`       | `erste`                               | Erste almappa neve                                 |
| `WISE_SUBDIR`        | `wise`                                | Wise almappa neve                                  |
| `MAX_FILE_SIZE_MB`   | `50`                                  | Maximális feltölthető fájlméret MB-ban             |
| `API_HOST`           | `0.0.0.0`                             | FastAPI bind cím                                   |
| `API_PORT`           | `8006`                                | FastAPI port                                       |
| `LOG_LEVEL`          | `INFO`                                | Napló szint (`DEBUG`, `INFO`, `WARNING`, `ERROR`)  |
| `AUTH_ENABLED`       | `true` *(a `.env`-ben jelenleg `false`)* | JWT ellenőrzés be/ki                            |
| `AUTH_SERVICE_URL`   | `http://localhost:8007`               | Központi auth szerviz base URL (JWKS)              |

> `STORAGE_DIR` ugyanaz a könyvtár, mint a `bank` szerviz `BALANCE_STATEMENTS_DIR`-je. Dev környezetben relatív elérési úttal konfigurálható; prodban abszolút út ajánlott.

## Authentikáció (JWT)

`AUTH_ENABLED=true` esetén a `GET /health` kivételével minden végpont érvényes
JWT-t igényel, amelyet a központi **auth** szerviz (:8007) állít ki Google
belépés után. A token `Authorization: Bearer <token>` fejlécben vagy
`mp_access_token` HttpOnly cookie-ban érkezhet (a vision automatikusan
továbbadja); az ellenőrzés lokális a JWKS publikus kulcsokkal. Token nélkül a
válasz `401 Unauthorized`.

Implementáció: `src/uploader/auth.py` · specifikáció: `../moneypenny/auth-service-spec.md`.

## Vision UI

A feltöltési felület a `vision` szervizben érhető el a `/ui/upload` útvonalon.

**Funkciók:**
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
    └── balance-statements/          # feltöltött CSV-k (.gitignore)
        ├── erste/                   #   <számlaszám>_<from>_<to>.csv
        └── wise/                    #   statement_<balanceId>_<currency>_<from>_<to>.csv

uploader/
├── pyproject.toml
├── run_api.py                       # VS Code debug belépési pont (port 8006)
├── .env
└── src/uploader/
    ├── config.py                    # pydantic-settings, configure_logging()
    ├── models.py                    # UploadResult, StorageFile, StorageStatus
    ├── detector.py                  # bankdetektálás fájlnévből (regex)
    ├── storage.py                   # fájl mentés / lista / törlés
    ├── api/main.py                  # FastAPI végpontok
    └── cli/main.py                  # Typer CLI (uploader script)
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
