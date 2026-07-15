# attachment-downloader

Moneypenny pipeline microservice #1 (`attachment-downloader`, port 8000). Downloads
PDF attachments from an email provider for a given date range.
Exposes a CLI and a REST API consumed by `invoice-file-filter`.

Supported providers: **Gmail** (Google OAuth2, `gmail.readonly`). The architecture
is designed for additional providers (e.g. Outlook/Microsoft Graph) — see [Adding a provider](#adding-a-provider).

## Prerequisites

- Python 3.9+

**Gmail provider:**
- Google Cloud Project with Gmail API enabled
- OAuth2 Desktop client credentials JSON

## Setup

### Gmail

1. Download OAuth2 Desktop credentials from Google Cloud Console and place the
   JSON file in the project root (or set `GOOGLE_CREDENTIALS_FILE` in `.env`).
2. Copy `.env.example` to `.env` and adjust paths if needed.
3. `token.json` is generated automatically on first authentication (browser flow on port 8888).

```bash
cd attachment-downloader
uv sync --extra gmail
```

## Running

```bash
# REST API — listens on 0.0.0.0:8000
python run_api.py
# or: uv run uvicorn attachment_downloader.api.main:app --host 0.0.0.0 --port 8000 --reload

# CLI (defaults to --provider gmail)
uv run attachment-downloader --start 2026-05-01 --end 2026-05-31
uv run attachment-downloader --start 2026-05-01 --end 2026-05-31 --output invoices
uv run attachment-downloader --start 2026-05-01 --end 2026-05-31 --provider gmail

# Tests
uv run pytest tests/ -v
```

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET`    | `/health`       | Health check |
| `POST`   | `/api/v1/jobs`  | Download PDF attachments for a date range; blocks until done |
| `GET`    | `/api/v1/cache` | Return cache stats (entries, hits, misses) |
| `DELETE` | `/api/v1/cache` | Evict all cached results |

### GET /health

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "timestamp": "2026-06-17T12:00:00.000000"}
```

### POST /api/v1/jobs

Runs synchronously — blocks until all matching attachments are fetched and saved,
then returns the result.

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-05-01", "end_date": "2026-05-31"}'

# Explicit provider
curl -X POST "http://localhost:8000/api/v1/jobs?provider=gmail" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-05-01", "end_date": "2026-05-31"}'
```

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start_date` | string | yes | Start of date range (`YYYY-MM-DD`) |
| `end_date` | string | yes | End of date range (`YYYY-MM-DD`, inclusive) |
| `output_dir` | string | no | Subdirectory under `DOWNLOAD_ROOT_DIR` (omit to save directly in the root) |

**Query parameter:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `provider` | `gmail` | Email provider to use |

**Response:**

```json
{
  "total_emails": 3,
  "total_files": 5,
  "skipped_files": 1,
  "output_dir": "/path/to/attachment-downloader/downloads",
  "files": [
    {
      "filename": "2026-05-15_0001_invoice_may.pdf",
      "original_filename": "invoice may.pdf",
      "message_id": "18f3a2b1c4d5e6f7",
      "email_date": "2026-05-15",
      "size_bytes": 204800,
      "saved_path": "/path/to/attachment-downloader/downloads/2026-05-15_0001_invoice_may.pdf"
    }
  ]
}
```

Files are named `YYYY-MM-DD_NNNN_<sanitized_original>.pdf`. `NNNN` is a
per-year counter that resumes across runs from the highest number already in
`output_dir`. Attachments already present (matched by original filename + size,
counter ignored) are skipped without re-downloading.

`output_dir` (and `--output` on the CLI) is a subdirectory name relative to
`DOWNLOAD_ROOT_DIR` (project root `downloads/` by default). Omit it to save
directly into the root.

Results are cached in memory by `(start_date, end_date, output_dir)` for
`CACHE_TTL_SECONDS` (default 1 hour). A cache hit returns immediately without
querying the provider. Use `DELETE /api/v1/cache` to force a fresh fetch.

### GET /api/v1/cache

```bash
curl http://localhost:8000/api/v1/cache
```

```json
{"entries": 1, "hits": 3, "misses": 1}
```

### DELETE /api/v1/cache

```bash
curl -X DELETE http://localhost:8000/api/v1/cache
```

Returns `204 No Content`.

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DOWNLOAD_ROOT_DIR` | `downloads` | Root download folder, relative to the project root |
| `CACHE_TTL_SECONDS` | `3600` | How long (seconds) to keep a cached `DownloadResult` |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `API_HOST` | `0.0.0.0` | Bind address for the FastAPI server |
| `API_PORT` | `8000` | Port for the FastAPI server |
| `GOOGLE_CREDENTIALS_FILE` | `credentials.json` | Path to OAuth2 Desktop credentials JSON |
| `GOOGLE_TOKEN_FILE` | `token.json` | Path to generated token (auto-created on first auth) |
| `AUTH_ENABLED` | `true` *(currently `false` in `.env`)* | JWT validation on/off |
| `AUTH_SERVICE_URL` | `http://localhost:8007` | Central auth service base URL (JWKS) |

Logs are written to stdout and `logs/attachment-downloader.log`.

## Authentication (JWT)

With `AUTH_ENABLED=true`, every endpoint except `GET /health` requires a valid JWT issued by the central **auth** service (:8007) after a Google login (this is separate from the Gmail OAuth credentials above, which are for reading the mailbox). The token arrives as an `Authorization: Bearer <token>` header or an `mp_access_token` HttpOnly cookie (invoice-file-filter forwards it automatically); validation is local against the JWKS public keys. Without a token the response is `401 Unauthorized`. Implementation: `src/attachment_downloader/auth.py` · spec: `../moneypenny/auth-service-spec.md`.

## Architecture

```
src/attachment_downloader/
├── base.py              # EmailClient Protocol — the provider interface
├── config.py            # Pydantic Settings (all env vars) + configure_logging()
├── models.py            # Pydantic models (DownloadRequest, DownloadResult, …)
├── cache.py             # Thread-safe TTL cache
├── utils.py             # Helpers: filename sanitization, output directory scanning
├── providers/
│   ├── __init__.py      # get_client(provider, settings) factory
│   └── gmail/
│       └── client.py    # GmailClient — Google OAuth2 + Gmail API v1
├── cli/main.py          # Typer CLI
└── api/main.py          # FastAPI app
```

## Adding a provider

1. Create `src/attachment_downloader/providers/<name>/client.py` with a class that
   implements `download_pdf_attachments(start_date, end_date, output_dir, log) -> DownloadResult`.
2. Add an `elif provider == "<name>":` branch in `providers/__init__.py`.
3. Add provider-specific dependencies as a new optional extra in `pyproject.toml`.

The `EmailClient` Protocol in `base.py` defines the required interface.

## Pipeline

```
invoice-core (MASTER) → nav-invoice → invoice-file-filter → attachment-downloader (this)
```
