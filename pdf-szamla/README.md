# pdf-szamla — PDF Invoice Metadata Extractor

Moneypenny pipeline microservice #2 (`pdf-szamla`, port 8001). Calls the
**attachment-downloader** service to download invoice PDF attachments (last 30 days by
default), selects the invoices (`invoice` / `számla`) among the downloaded files,
extracts structured metadata (invoice number, dates, supplier/customer, amounts,
VAT, currency, due date) with a confidence score, and exposes the result through
a **FastAPI** REST API and a **Typer** CLI.

## Running

```bash
cd pdf-szamla
uv sync

# REST API (port 8001)
python run_api.py

# Or directly with uvicorn
uv run uvicorn pdf_szamla.api.main:app --host 0.0.0.0 --port 8001 --reload

# CLI (installed as `pdf-szamla`)
uv run pdf-szamla process                                     # last 30 days, download via attachment-downloader
uv run pdf-szamla process --start 2026-05-01 --end 2026-05-31
uv run pdf-szamla process --start 2026-05-01 --end 2026-05-31 --json  # machine-readable output
uv run pdf-szamla process --local --output-dir ./downloads    # process existing PDFs, no download
uv run pdf-szamla process --download                          # explicit download (default)
uv run pdf-szamla process --verbose                           # verbose logging

uv run pdf-szamla words invoice.pdf                           # print words as CSV to stdout
uv run pdf-szamla words invoice.pdf -o words.csv              # save CSV to file

uv run pdf-szamla cache-info                                  # show words cache stats
uv run pdf-szamla cache-info --json
uv run pdf-szamla cache-clear                                 # evict all cached word extractions

# Tests
uv run pytest tests/ -v
```

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check |
| `GET`  | `/settings` | Effective configuration |
| `POST` | `/api/v1/invoices/extract` | Download (via attachment-downloader) + extract metadata |
| `POST` | `/api/v1/invoices/extract-batch` | Batch extraction over one or more local directories |
| `GET`  | `/api/v1/invoices` | In-memory processing history |
| `POST` | `/api/v1/pdf/words` | Extract all words from a PDF as CSV |
| `GET`  | `/api/v1/pdf/words/cache` | Words cache stats (entry count + cached paths) |
| `DELETE` | `/api/v1/pdf/words/cache` | Evict all entries from the words cache |

### GET /health

```bash
curl http://localhost:8001/health
```

```json
{"status": "ok", "timestamp": "2026-06-12T16:00:00.000000"}
```

### GET /settings

```bash
curl http://localhost:8001/settings
```

```json
{
  "attachment_downloader_url": "http://localhost:8000",
  "output_dir": "../attachment-downloader/downloads",
  "invoice_keywords": ["invoice", "bill", "szamla", "számla"],
  "download_timeout": 120,
  "poll_interval": 2.0
}
```

### POST /api/v1/invoices/extract

Download PDFs via attachment-downloader for the given date range, then extract metadata.

```bash
curl -X POST http://localhost:8001/api/v1/invoices/extract \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-05-01",
    "end_date": "2026-05-31",
    "download": true
  }'
```

Process PDFs already in `output_dir` without downloading:

```bash
curl -X POST http://localhost:8001/api/v1/invoices/extract \
  -H "Content-Type: application/json" \
  -d '{
    "output_dir": "./downloads",
    "download": false
  }'
```

Response:

```json
{
  "total_files": 5,
  "invoice_count": 3,
  "output_dir": "./downloads",
  "files": [
    {"filename": "downloads/invoice_2026_05.pdf", "modified": "2026-05-15T10:30:00"},
    {"filename": "downloads/szamla_2026_05.pdf",  "modified": "2026-05-20T14:00:00"},
    {"filename": "downloads/bill_may.pdf",         "modified": "2026-05-28T09:15:00"}
  ]
}
```

**Request fields (`ExtractRequest`):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `start_date` | `string` | 30 days ago | Filter start date (`YYYY-MM-DD`) |
| `end_date` | `string` | today | Filter end date (`YYYY-MM-DD`) |
| `output_dir` | `string` | env `OUTPUT_DIR` | Directory for downloaded / existing PDFs |
| `download` | `bool` | `true` | `true` = call attachment-downloader; `false` = use existing files |

### POST /api/v1/invoices/extract-batch

Process multiple local directories in one call (no download).

```bash
curl -X POST http://localhost:8001/api/v1/invoices/extract-batch \
  -H "Content-Type: application/json" \
  -d '{
    "output_dirs": [
      "./downloads/2026-04",
      "./downloads/2026-05"
    ]
  }'
```

Response — array of `ExtractResponse`, one entry per directory:

```json
[
  {
    "total_files": 2,
    "invoice_count": 2,
    "output_dir": "./downloads/2026-04",
    "files": [{"filename": "downloads/2026-04/april_invoice.pdf", "modified": "2026-04-10T08:00:00"}]
  },
  {
    "total_files": 5,
    "invoice_count": 3,
    "output_dir": "./downloads/2026-05",
    "files": [{"filename": "downloads/2026-05/invoice_2026_05.pdf", "modified": "2026-05-15T10:30:00"}]
  }
]
```

### GET /api/v1/invoices

Return the in-memory history of all extraction runs since the service started.

```bash
curl http://localhost:8001/api/v1/invoices
```

Response — array of `ExtractResponse` objects (same shape as `/extract`).

### POST /api/v1/pdf/words

Extract every word from a PDF file and return them as a CSV download with positional
metadata sourced from pdfplumber's word-extraction engine.

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
1,2026-0042,150.0,48.2,210.7,60.1
...
```

**CSV columns:**

| Column | Description |
|--------|-------------|
| `page` | 1-based page number |
| `word` | Extracted word text |
| `x0` | Left edge of the word bounding box (points from left) |
| `top` | Top edge of the word bounding box (points from top of page) |
| `x1` | Right edge of the word bounding box |
| `bottom` | Bottom edge of the word bounding box |

**Request fields (`WordsRequest`):**

| Field | Type | Description |
|-------|------|-------------|
| `pdf_path` | `string` | Absolute or relative path to the PDF file |

### GET /api/v1/pdf/words/cache

Return stats about the in-process words cache.

```bash
curl http://localhost:8001/api/v1/pdf/words/cache
```

```json
{"entries": 2, "paths": ["/downloads/invoice_a.pdf", "/downloads/invoice_b.pdf"]}
```

### DELETE /api/v1/pdf/words/cache

Evict all entries from the in-process words cache.

```bash
curl -X DELETE http://localhost:8001/api/v1/pdf/words/cache
```

```json
{"removed": 2}
```

> **Note:** the cache is process-local. The CLI and the API server each maintain their
> own cache; clearing one does not affect the other.

## CLI

### process

Download invoice PDFs via attachment-downloader (or process local files) and print a summary table.

```bash
uv run pdf-szamla process [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--start DATE` | 30 days ago | Filter start date (`YYYY-MM-DD`) |
| `--end DATE` | today | Filter end date (`YYYY-MM-DD`) |
| `--output-dir PATH` | env `OUTPUT_DIR` | PDF directory |
| `--local` / `--download` | `--download` | Skip attachment-downloader; use existing files |
| `--json` | off | Output result as JSON |
| `--verbose` / `-v` | off | Enable INFO logging |

### words

Extract every word from a PDF and emit CSV with positional metadata.

```bash
uv run pdf-szamla words PDF_PATH [--output FILE]
```

| Argument / Option | Description |
|-------------------|-------------|
| `PDF_PATH` | Path to the PDF file (required) |
| `--output FILE` / `-o FILE` | Write CSV to this file; omit to print to stdout |

Output columns: `page`, `word`, `x0`, `top`, `x1`, `bottom`.

### cache-info

Show stats about the in-process words cache (entry count and cached file paths).

```bash
uv run pdf-szamla cache-info
uv run pdf-szamla cache-info --json
```

### cache-clear

Evict all entries from the in-process words cache.

```bash
uv run pdf-szamla cache-clear
```

> **Note:** the cache is process-local. Each CLI invocation has its own cache; this
> command does not affect a running API server instance.

## Logs

Logs are written to both stdout and `logs/pdf-szamla.log`.

Every HTTP request is logged at `INFO` level with method, path, status code, and elapsed time:

```
2026-06-12 16:00:01 INFO     pdf_szamla.api.main: POST /api/v1/invoices/extract → 200 in 342ms
```

Service calls to attachment-downloader are also logged with elapsed time:

```
2026-06-12 16:00:00 INFO     pdf_szamla.client: POST http://localhost:8000/api/v1/jobs → job_id=abc123 in 85ms
2026-06-12 16:00:01 INFO     pdf_szamla.client: Download job abc123 completed: 5 file(s) in 1243ms
2026-06-12 16:00:01 INFO     pdf_szamla.service: Extraction complete: 3 invoice(s) from 5 file(s) in 1350ms
```

## Configuration (`.env` from `.env.example`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ATTACHMENT_DOWNLOADER_URL` | `http://localhost:8000` | Base URL of the attachment-downloader service |
| `OUTPUT_DIR` | `./downloads` | Default PDF download directory |
| `DOWNLOAD_TIMEOUT` | `120` | Max seconds to wait for a attachment-downloader job |
| `POLL_INTERVAL` | `2.0` | Polling interval in seconds |
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8001` | FastAPI port |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Pipeline

```
szamla-db (MASTER) → nav-szamla → pdf-szamla (this) → attachment-downloader
```
