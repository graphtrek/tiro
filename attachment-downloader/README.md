# attachment-downloader — Gmail CLI + FastAPI

Moneypenny pipeline microservice #1 (`graphtrek-email`, port 8000). Provides a
CLI and REST interface for Gmail (list / read / send / reply / trash / mark
read-unread / labels) via Google OAuth2, and an async PDF-attachment download
job API consumed by the `pdf-szamla` service.

## Prerequisites

- Python 3.9+
- A Google Cloud Project with Gmail API enabled
- OAuth2 Desktop client credentials JSON file

## Setup

1. Download your OAuth2 Desktop credentials from the Google Cloud Console.
2. Place the file in the project root. Override the path via `GOOGLE_CREDENTIALS_FILE` in `.env` if needed.
3. `token.json` is generated automatically on first successful authentication.

```bash
cd attachment-downloader
uv sync

# REST API (port 8000)
python run_api.py

# Or directly with uvicorn
uv run uvicorn attachment_downloader.api.main:app --host 0.0.0.0 --port 8000 --reload

# CLI (installed as `attachment-downloader`)
uv run attachment-downloader list
uv run attachment-downloader list --query "from:billing@supplier.com" --max-results 20
uv run attachment-downloader list --query "is:unread has:attachment filename:pdf"
uv run attachment-downloader read   <email_id>
uv run attachment-downloader send   <to> "<subject>" "<body>"
uv run attachment-downloader send   <to> "<subject>" "<body>" --cc <cc> --bcc <bcc>
uv run attachment-downloader reply  <email_id> "<body>"
uv run attachment-downloader trash  <email_id>
uv run attachment-downloader mark-read   <email_id>
uv run attachment-downloader mark-unread <email_id>
uv run attachment-downloader download --start 2026-05-01 --end 2026-05-31
uv run attachment-downloader download --start 2026-05-01 --end 2026-05-31 --output ./pdfs/

# Tests
uv run pytest tests/ -v
```

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/emails` | List emails (supports Gmail search query) |
| `GET`  | `/emails/{email_id}` | Get full email details |
| `POST` | `/emails/send` | Send a new email |
| `POST` | `/emails/{email_id}/reply` | Reply to an email |
| `POST` | `/emails/{email_id}/trash` | Move email to trash |
| `POST` | `/emails/{email_id}/read` | Mark email as read |
| `POST` | `/emails/{email_id}/unread` | Mark email as unread |
| `GET`  | `/labels` | List all Gmail labels |
| `POST` | `/api/v1/jobs` | Start an async PDF download job |
| `GET`  | `/api/v1/jobs/{job_id}` | Poll job status and result |
| `GET`  | `/api/v1/jobs/{job_id}/logs` | Stream job log entries |

Every HTTP request is logged at `INFO` level with method, path, status code, and elapsed time.

---

### GET /emails

List inbox emails. Supports a Gmail search query via `q` and a `max_results` cap (default 10, max 50).

```bash
# Default inbox, last 10 emails
curl "http://localhost:8000/emails"

# Custom query
curl "http://localhost:8000/emails?q=from:sender@example.com&max_results=20"

# Unread emails with PDF attachments
curl "http://localhost:8000/emails?q=is:unread+has:attachment+filename:pdf"
```

Response:

```json
[
  {
    "id": "18f3a2b1c4d5e6f7",
    "subject": "Invoice May 2026",
    "from": "billing@supplier.com",
    "date": "Thu, 15 May 2026 10:30:00 +0200",
    "snippet": "Please find attached your invoice..."
  }
]
```

---

### GET /emails/{email_id}

Fetch full content of a single email.

```bash
curl "http://localhost:8000/emails/18f3a2b1c4d5e6f7"
```

Response:

```json
{
  "id": "18f3a2b1c4d5e6f7",
  "subject": "Invoice May 2026",
  "from": "billing@supplier.com",
  "to": "imre.tatai@graphtrek.co",
  "date": "Thu, 15 May 2026 10:30:00 +0200",
  "body": "Please find attached your invoice for May 2026..."
}
```

---

### POST /emails/send

Send a new email. All fields are query parameters.

```bash
curl -X POST "http://localhost:8000/emails/send" \
  --data-urlencode "to=recipient@example.com" \
  --data-urlencode "subject=Hello from attachment-downloader" \
  --data-urlencode "body=This is the email body." \
  -G
```

With CC and BCC:

```bash
curl -X POST "http://localhost:8000/emails/send?to=recipient@example.com&subject=Hello&body=Body&cc=cc@example.com&bcc=bcc@example.com"
```

Response:

```json
{"status": "success", "id": "18f3a2b1c4d5e6f8"}
```

---

### POST /emails/{email_id}/reply

Reply to an existing email. Body is passed as a query parameter.

```bash
curl -X POST "http://localhost:8000/emails/18f3a2b1c4d5e6f7/reply?body=Thank+you+for+the+invoice."
```

Response:

```json
{"status": "success", "id": "18f3a2b1c4d5e6f9"}
```

---

### POST /emails/{email_id}/trash

Move an email to trash.

```bash
curl -X POST "http://localhost:8000/emails/18f3a2b1c4d5e6f7/trash"
```

Response:

```json
{"status": "success"}
```

---

### POST /emails/{email_id}/read

Mark an email as read.

```bash
curl -X POST "http://localhost:8000/emails/18f3a2b1c4d5e6f7/read"
```

### POST /emails/{email_id}/unread

Mark an email as unread.

```bash
curl -X POST "http://localhost:8000/emails/18f3a2b1c4d5e6f7/unread"
```

Both return:

```json
{"status": "success"}
```

---

### GET /labels

List all Gmail labels (inbox, sent, custom labels, etc.).

```bash
curl "http://localhost:8000/labels"
```

Response:

```json
[
  {"id": "INBOX",  "name": "INBOX",  "type": "system"},
  {"id": "SENT",   "name": "SENT",   "type": "system"},
  {"id": "Label_1","name": "Invoices","type": "user"}
]
```

---

## PDF Download Jobs (graphtrek-email service)

Asynchronous PDF-attachment download used by `pdf-szamla`. Jobs run in the
background; poll for status or fetch logs while waiting.

Saved files follow the naming scheme `YYYY-MM-DD_DDD_<original_name>.pdf`,
where `DDD` is a per-day sequence starting at `001`.

### POST /api/v1/jobs

Start a download job. Returns `202 Accepted` immediately with the job descriptor.

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-05-01",
    "end_date": "2026-05-31"
  }'
```

With a custom output directory:

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-05-01",
    "end_date": "2026-05-31",
    "output_dir": "./downloads/2026-05"
  }'
```

Response (`202`):

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "pending",
  "request": {
    "start_date": "2026-05-01",
    "end_date": "2026-05-31",
    "output_dir": null
  },
  "created_at": "2026-05-31T16:00:00.000000",
  "started_at": null,
  "finished_at": null,
  "result": null,
  "error": null
}
```

**Request fields (`DownloadRequest`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start_date` | `string` | yes | Filter start date (`YYYY-MM-DD`) |
| `end_date` | `string` | yes | Filter end date (`YYYY-MM-DD`) |
| `output_dir` | `string` | no | Target directory (default: `./downloads/`) |

---

### GET /api/v1/jobs/{job_id}

Poll job status. `status` transitions: `pending` → `running` → `completed` / `failed`.

```bash
curl "http://localhost:8000/api/v1/jobs/a1b2c3d4e5f6"
```

Response when completed:

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "completed",
  "request": {"start_date": "2026-05-01", "end_date": "2026-05-31", "output_dir": null},
  "created_at": "2026-05-31T16:00:00.000000",
  "started_at": "2026-05-31T16:00:00.100000",
  "finished_at": "2026-05-31T16:00:05.300000",
  "result": {
    "total_emails": 3,
    "total_files": 5,
    "skipped_files": 1,
    "output_dir": "./downloads",
    "files": [
      {
        "filename": "2026-05-15_001_invoice_may.pdf",
        "original_filename": "invoice_may.pdf",
        "message_id": "18f3a2b1c4d5e6f7",
        "email_date": "2026-05-15",
        "size_bytes": 204800,
        "saved_path": "./downloads/2026-05-15_001_invoice_may.pdf"
      }
    ]
  },
  "error": null
}
```

---

### GET /api/v1/jobs/{job_id}/logs

Fetch all log entries captured during the job run.

```bash
curl "http://localhost:8000/api/v1/jobs/a1b2c3d4e5f6/logs"
```

Response:

```json
{
  "job_id": "a1b2c3d4e5f6",
  "logs": [
    {"timestamp": "2026-05-31T16:00:00.100000", "level": "INFO",  "message": "Starting download 2026-05-01 .. 2026-05-31"},
    {"timestamp": "2026-05-31T16:00:03.200000", "level": "INFO",  "message": "Saved 2026-05-15_001_invoice_may.pdf (200 KB)"},
    {"timestamp": "2026-05-31T16:00:05.300000", "level": "INFO",  "message": "Completed: 5 PDF(s) saved to ./downloads"}
  ]
}
```

---

## Logs

Logs are written to both stdout and `logs/attachment-downloader.log`.

Every HTTP request is logged at `INFO` level with method, path, status code, and elapsed time:

```
2026-06-12 16:00:01 INFO     attachment_downloader.api.main: POST /api/v1/jobs → 202 in 48ms
2026-06-12 16:00:06 INFO     attachment_downloader.api.main: GET /api/v1/jobs/a1b2c3d4e5f6 → 200 in 3ms
```

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CREDENTIALS_FILE` | `credentials.json` | Path to OAuth2 Desktop credentials |
| `GOOGLE_TOKEN_FILE` | `token.json` | Path to the generated token (auto-created) |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Pipeline

```
szamla-db (MASTER) → nav-szamla → pdf-szamla → graphtrek-email (this)
```
