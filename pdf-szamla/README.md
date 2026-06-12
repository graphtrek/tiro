# pdf-szamla — PDF Invoice Metadata Extractor

Moneypenny pipeline microservice #2 (`pdf-szamla`, port 8001). Calls the
**graphtrek-email** service to download invoice PDF attachments (last 30 days by
default), selects the invoices (`invoice` / `számla`) among the downloaded files,
extracts structured metadata (invoice number, dates, supplier/customer, amounts,
VAT, currency, due date) with a confidence score, and exposes the result through
a **FastAPI** REST API and a **Typer** CLI.

## Running

```bash
cd pdf-szamla
uv sync

# REST API (default port 8001)
uv run uvicorn pdf_szamla.api.main:app --reload

# CLI (installed as `pdf-szamla`)
uv run pdf-szamla process                                   # last 30 days, via graphtrek-email
uv run pdf-szamla process --start 2026-05-01 --end 2026-05-31
uv run pdf-szamla process --local --output-dir ./downloads  # process existing PDFs, no download
uv run pdf-szamla process --json                            # machine-readable output

# Tests
uv run pytest tests/ -v
```

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check |
| `GET`  | `/settings` | Effective configuration |
| `POST` | `/api/v1/invoices/extract` | Download (via graphtrek-email) + extract metadata |
| `POST` | `/api/v1/invoices/extract-batch` | Batch extraction over one or more local directories |
| `GET`  | `/api/v1/invoices` | In-memory processing history |

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
  "graphtrek_email_url": "http://localhost:8000",
  "output_dir": "../graphtrek-gmail/downloads",
  "invoice_keywords": ["invoice", "bill", "szamla", "számla"],
  "download_timeout": 120,
  "poll_interval": 2.0
}
```

### POST /api/v1/invoices/extract

Download PDFs via graphtrek-email for the given date range, then extract metadata.

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
    {"filename": "invoice_2026_05.pdf", "modified": "2026-05-15T10:30:00"},
    {"filename": "szamla_2026_05.pdf",  "modified": "2026-05-20T14:00:00"},
    {"filename": "bill_may.pdf",         "modified": "2026-05-28T09:15:00"}
  ]
}
```

**Request fields (`ExtractRequest`):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `start_date` | `string` | 30 days ago | Filter start date (`YYYY-MM-DD`) |
| `end_date` | `string` | today | Filter end date (`YYYY-MM-DD`) |
| `output_dir` | `string` | env `OUTPUT_DIR` | Directory for downloaded / existing PDFs |
| `download` | `bool` | `true` | `true` = call graphtrek-email; `false` = use existing files |

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
    "files": [{"filename": "april_invoice.pdf", "modified": "2026-04-10T08:00:00"}]
  },
  {
    "total_files": 5,
    "invoice_count": 3,
    "output_dir": "./downloads/2026-05",
    "files": [{"filename": "invoice_2026_05.pdf", "modified": "2026-05-15T10:30:00"}]
  }
]
```

### GET /api/v1/invoices

Return the in-memory history of all extraction runs since the service started.

```bash
curl http://localhost:8001/api/v1/invoices
```

Response — array of `ExtractResponse` objects (same shape as `/extract`).

## Logs

Logs are written to both stdout and `logs/pdf-szamla.log`.

Every HTTP request is logged at `INFO` level with method, path, status code, and elapsed time:

```
2026-06-12 16:00:01 INFO     pdf_szamla.api.main: POST /api/v1/invoices/extract → 200 in 342ms
```

Service calls to graphtrek-email are also logged with elapsed time:

```
2026-06-12 16:00:00 INFO     pdf_szamla.client: POST http://localhost:8000/api/v1/jobs → job_id=abc123 in 85ms
2026-06-12 16:00:01 INFO     pdf_szamla.client: Download job abc123 completed: 5 file(s) in 1243ms
2026-06-12 16:00:01 INFO     pdf_szamla.service: Extraction complete: 3 invoice(s) from 5 file(s) in 1350ms
```

## Configuration (`.env` from `.env.example`)

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAPHTREK_EMAIL_URL` | `http://localhost:8000` | Base URL of the graphtrek-email service |
| `OUTPUT_DIR` | `./downloads` | Default PDF download directory |
| `DOWNLOAD_TIMEOUT` | `120` | Max seconds to wait for a graphtrek-email job |
| `POLL_INTERVAL` | `2.0` | Polling interval in seconds |
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8001` | FastAPI port |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Pipeline

```
szamla-db (MASTER) → nav-szamla → pdf-szamla (this) → graphtrek-email
```
