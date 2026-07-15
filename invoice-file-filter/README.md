# invoice-file-filter

Moneypenny pipeline microservice #2 (port 8001). Calls **attachment-downloader** to download
invoice PDF attachments, selects invoices among the downloaded files by keyword matching,
and exposes the result through a **FastAPI** REST API and a **Typer** CLI.

## System dependencies

The OCR fallback (for scanned/image-only PDFs) requires **Poppler** and **Tesseract** to be
installed on the host. The Python packages (`pdf2image`, `pytesseract`, `Pillow`) are already
in `pyproject.toml` — only the system binaries need to be added.

### macOS

```bash
brew install poppler tesseract tesseract-lang
```

`tesseract-lang` adds the Hungarian language pack (`hun`) used by the default `hun+eng` OCR mode.

### Debian / Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-hun tesseract-ocr-eng
```

---

## Running

```bash
cd invoice-file-filter
uv sync

# REST API (port 8001)
python run_api.py
# or
uv run uvicorn invoice_file_filter.api.main:app --host 0.0.0.0 --port 8001 --reload

# CLI
uv run invoice-file-filter process                                  # last 30 days, download via attachment-downloader
uv run invoice-file-filter process --start 2026-05-01 --end 2026-05-31
uv run invoice-file-filter process --local --output-dir ./downloads # process existing PDFs, no download
uv run invoice-file-filter process --json                           # machine-readable output
uv run invoice-file-filter process --verbose                        # verbose logging

uv run invoice-file-filter words invoice.pdf                        # print words as CSV to stdout
uv run invoice-file-filter words invoice.pdf -o words.csv           # save CSV to file

uv run invoice-file-filter cache-info
uv run invoice-file-filter cache-info --json
uv run invoice-file-filter cache-clear

# Tests
uv run pytest tests/ -v
```

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/invoices/extract` | Download (via attachment-downloader) + filter invoices |
| `POST` | `/api/v1/pdf/words` | Extract all words from a PDF as CSV |
| `GET` | `/api/v1/pdf/words/cache` | Words cache stats |
| `DELETE` | `/api/v1/pdf/words/cache` | Evict all words cache entries |

### GET /health

```bash
curl http://localhost:8001/health
```

```json
{"status": "ok", "timestamp": "2026-06-12T16:00:00.000000"}
```

### POST /api/v1/invoices/extract

Download PDFs via attachment-downloader for the given date range, filter invoices, return metadata.

```bash
curl -X POST http://localhost:8001/api/v1/invoices/extract \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-05-01", "end_date": "2026-05-31", "download": true}'
```

Process PDFs already in `output_dir` without downloading:

```bash
curl -X POST http://localhost:8001/api/v1/invoices/extract \
  -H "Content-Type: application/json" \
  -d '{"output_dir": "./downloads", "download": false}'
```

Response:

```json
{
  "total_files": 5,
  "invoice_count": 3,
  "output_dir": "./downloads",
  "files": [
    {"filename": "invoice_2026_05.pdf", "path": "/abs/path/downloads/invoice_2026_05.pdf", "modified": "2026-05-15T10:30:00"},
    {"filename": "szamla_2026_05.pdf",  "path": "/abs/path/downloads/szamla_2026_05.pdf",  "modified": "2026-05-20T14:00:00"},
    {"filename": "bill_may.pdf",         "path": "/abs/path/downloads/bill_may.pdf",         "modified": "2026-05-28T09:15:00"}
  ]
}
```

**Request fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `start_date` | `string` | 30 days ago | Filter start date (`YYYY-MM-DD`) |
| `end_date` | `string` | today | Filter end date (`YYYY-MM-DD`) |
| `output_dir` | `string` | `OUTPUT_DIR` env | Directory for downloaded / existing PDFs |
| `download` | `bool` | `true` | `true` = call attachment-downloader; `false` = use existing files |

### POST /api/v1/pdf/words

Extract distinct, normalised words from a PDF and return them as a single-column CSV download.
Words are lower-cased, diacritics are stripped, tokens shorter than 3 characters are dropped,
duplicates are removed, and results are sorted alphabetically.

```bash
curl -X POST http://localhost:8001/api/v1/pdf/words \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/invoice.pdf"}' \
  -o invoice_words.csv
```

Response — `text/csv` attachment (`<basename>_words.csv`):

```
word
afa
graphtrek
szamla
```

### GET /api/v1/pdf/words/cache

Returns stats for the words cache only (see [Caching](#caching)).

```bash
curl http://localhost:8001/api/v1/pdf/words/cache
```

```json
{"entries": 2, "paths": ["/downloads/invoice_a.pdf", "/downloads/invoice_b.pdf"]}
```

### DELETE /api/v1/pdf/words/cache

Evicts all entries from the words cache only.

```bash
curl -X DELETE http://localhost:8001/api/v1/pdf/words/cache
```

```json
{"removed": 2}
```

## CLI

### process

```bash
uv run invoice-file-filter process [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--start DATE` | 30 days ago | Filter start date (`YYYY-MM-DD`) |
| `--end DATE` | today | Filter end date (`YYYY-MM-DD`) |
| `--output-dir PATH` | `OUTPUT_DIR` env | PDF directory |
| `--local` / `--download` | `--download` | Skip attachment-downloader; use existing files |
| `--json` | off | Output result as JSON |
| `--verbose` / `-v` | off | Enable DEBUG logging |

### words

```bash
uv run invoice-file-filter words PDF_PATH [--output FILE]
```

Outputs a single-column CSV (`word` header) with one distinct, normalised word per line.
Words are lower-cased and diacritics are stripped (`á`→`a`, `ő`→`o`, etc.); words shorter
than 3 characters are dropped; duplicates are removed and the list is sorted alphabetically.

For PDFs with an embedded text layer pdfplumber is used directly.
For scanned / image-only PDFs the command falls back to Tesseract OCR automatically
(requires Poppler and Tesseract — see [System dependencies](#system-dependencies)).

### cache-info / cache-clear

```bash
uv run invoice-file-filter cache-info [--json]
uv run invoice-file-filter cache-clear
```

Manages the **words cache** only (see [Caching](#caching)).

> The cache is process-local — clearing the CLI cache does not affect a running API server.

## Caching

All three extraction functions maintain an **in-memory, mtime-keyed cache** for the lifetime of the process. A cache entry is reused as long as the file's modification time has not changed; if the file is replaced or updated, the entry is invalidated automatically.

| Cache | Populated by | Covers |
|-------|-------------|--------|
| `_text_cache` | `extract_text()` | Full page text used for invoice keyword matching in the main pipeline |
| `_page_count_cache` | `get_page_count()` | Page count used to reject files outside the 1–2 page range |
| `_words_cache` | `extract_words_csv()` | Normalised word list returned by `POST /api/v1/pdf/words` |

The `GET/DELETE /api/v1/pdf/words/cache` endpoints and the `cache-info`/`cache-clear` CLI commands manage the words cache only. The text and page count caches are internal to the extraction pipeline and have no dedicated management interface.

## Logs

Written to stdout and `logs/invoice-file-filter.log`.

```
2026-06-12 16:00:00 INFO  invoice_file_filter.client:  POST http://localhost:8000/api/v1/jobs → 3 file(s) in 1243ms
2026-06-12 16:00:01 INFO  invoice_file_filter.service: Extraction complete: 3 invoice(s) from 5 file(s) in 1350ms
2026-06-12 16:00:01 INFO  invoice_file_filter.api.main: POST /api/v1/invoices/extract → 200 in 342ms
```

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ATTACHMENT_DOWNLOADER_URL` | `http://localhost:8000` | Base URL of the attachment-downloader service |
| `OUTPUT_DIR` | `../attachment-downloader/downloads` | Default PDF directory |
| `DOWNLOAD_TIMEOUT` | `120` | Max seconds to wait for attachment-downloader |
| `INVOICE_KEYWORDS` | `["invoice","bill","szamla","számla","számviteli bizonylat"]` | JSON array of detection keywords (case-insensitive, diacritics-folded) |
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8001` | FastAPI port |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `OCR_ENABLED` | `true` | Enable Tesseract OCR fallback for scanned PDFs |
| `OCR_LANGUAGE` | `hun+eng` | Tesseract language(s) — `+`-separated Tesseract lang codes |
| `OCR_MIN_CHARS` | `50` | pdfplumber char count below which OCR is attempted |
| `AUTH_ENABLED` | `true` *(currently `false` in `.env`)* | JWT validation on/off |
| `AUTH_SERVICE_URL` | `http://localhost:8007` | Central auth service base URL (JWKS) |

## Authentication (JWT)

With `AUTH_ENABLED=true`, every endpoint except `GET /health` requires a valid JWT issued by the central **auth** service (:8007) after a Google login. The token arrives as an `Authorization: Bearer <token>` header or an `mp_access_token` HttpOnly cookie (invoice-core forwards it automatically); validation is local against the JWKS public keys. Without a token the response is `401 Unauthorized`. The incoming token is passed through to attachment-downloader (`TokenPassthrough` in `src/invoice_file_filter/auth.py`). Spec: `../moneypenny/auth-service-spec.md`.

## Pipeline

```
invoice-core (MASTER) → nav-invoice → invoice-file-filter (this) → attachment-downloader
```
