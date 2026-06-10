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
uv run uvicorn api.main:app --reload      # or: uv run python -m api.main

# CLI (installed as `pdf-szamla`)
uv run pdf-szamla process                                   # last 30 days, via graphtrek-email
uv run pdf-szamla process --start 2026-05-01 --end 2026-05-31
uv run pdf-szamla process --local --output-dir ./downloads  # process existing PDFs, no download
uv run pdf-szamla process --json                            # machine-readable output

# Tests
uv run pytest tests/ -v
```

## REST API

- `GET  /health` — health check
- `GET  /settings` — effective configuration
- `POST /api/v1/invoices/extract` — download (via graphtrek-email) + extract metadata
- `POST /api/v1/invoices/extract-batch` — batch extraction over one or more directories
- `GET  /api/v1/invoices` — in-memory processing history

`POST /api/v1/invoices/extract` body (`ExtractRequest`):

```json
{ "start_date": "2026-05-01", "end_date": "2026-05-31", "output_dir": "./downloads", "download": true }
```

Set `"download": false` to skip graphtrek-email and process PDFs already in `output_dir`.

## Configuration (`.env` from `.env.example`)

`GRAPHTREK_EMAIL_URL`, `OUTPUT_DIR`, `DOWNLOAD_TIMEOUT`, `POLL_INTERVAL`,
`API_HOST`, `API_PORT`, `LOG_LEVEL`.

## Pipeline

```
szamla-db (MASTER) → nav-szamla → pdf-szamla (this) → graphtrek-email
```
