# invoice-file-filter

Moneypenny pipeline microservice #2 (port 8001). Calls **attachment-downloader** to download
invoice PDF attachments, selects invoices among the downloaded files by keyword matching,
and exposes the result through a **FastAPI** REST API and a **Typer** CLI.

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
    {"filename": "invoice_2026_05.pdf", "modified": "2026-05-15T10:30:00"},
    {"filename": "szamla_2026_05.pdf",  "modified": "2026-05-20T14:00:00"},
    {"filename": "bill_may.pdf",         "modified": "2026-05-28T09:15:00"}
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

Extract every word from a PDF file and return them as a CSV download with positional metadata.

```bash
curl -X POST http://localhost:8001/api/v1/pdf/words \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "/path/to/invoice.pdf"}' \
  -o invoice_words.csv
```

Response — `text/csv` attachment (`<basename>_words.csv`):

```
page,word,x0,top,x1,bottom
1,Invoice,72.0,48.2,108.5,60.1
1,Number:,110.0,48.2,148.3,60.1
```

### GET /api/v1/pdf/words/cache

```bash
curl http://localhost:8001/api/v1/pdf/words/cache
```

```json
{"entries": 2, "paths": ["/downloads/invoice_a.pdf", "/downloads/invoice_b.pdf"]}
```

### DELETE /api/v1/pdf/words/cache

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

Columns: `page`, `word`, `x0`, `top`, `x1`, `bottom`.

### cache-info / cache-clear

```bash
uv run invoice-file-filter cache-info [--json]
uv run invoice-file-filter cache-clear
```

> The cache is process-local — clearing the CLI cache does not affect a running API server.

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
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8001` | FastAPI port |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## Pipeline

```
invoice-core (MASTER) → nav-invoice → invoice-file-filter (this) → attachment-downloader
```
