# AGENTS.md

## Core Workspace Principles
- **Multi-project scope**: `uv`-based Python monorepo. Each sub-project has its own `pyproject.toml` and isolated `.venv`.
- **Isolated environments**: **NO shared venv**. Each project lives at `<project>/.venv`. Always `cd <project>` then `uv sync` and `uv run <cmd>` — never cross-use environments.
- **Shared config**: Single root `.env` (from `.env.example`) via `pydantic-settings`. Most keys use plain names; per-service exceptions (`API_PORT`, `AUTH_ENABLED`, `LOG_LEVEL`, `REQUEST_TIMEOUT`) use `<SERVICE>_<KEY>` overrides.
- **Root files**: `python-for-ai.code-workspace` (VS Code), `.env.example`, `AGENTS.md`, `CLAUDE.md` (authoritative), `REQUIREMENTS.md` (QA requirements).
- **Architecture**: attachment-downloader (:8000) → invoice-file-filter (:8001) → nav-invoice (:8002) → invoice-core (:8004) → vision (:8009). bank (:8005) and uploader (:8006) feed invoice-core; auth (:8007) is the centralized login gateway.

## Microservices (FastAPI + CLI, each with `uv run`)
| Project         | Port  | Purpose                                      |
|-----------------|-------|----------------------------------------------|
| `auth`          | 8007  | Google OAuth 2.0/OIDC, RS256 JWT issuance    |
| `attachment-downloader` | 8000 | Gmail PDF attachment download               |
| `invoice-file-filter`    | 8001 | PDF extraction, OCR, invoice keyword match |
| `nav-invoice`    | 8002  | NAV Online Számla 3.0 REST/XML client        |
| `invoice-core`   | 8004  | Master orchestrator — PostgreSQL persistence |
| `bank`           | 8005  | Consolidated bank statements (Erste + Wise)  |
| `uploader`       | 8006  | CSV upload endpoint for bank service         |
| `vision`         | 8009  | Web frontend — consumes invoice-core REST API|
| `e2e`            | —     | End-to-end QA tests (pytest + Playwright)    |
|| `vault-agent`    | 8010    | Chat with Obsidian vaults (Pydantic AI)      |
| `banking`        | —     | Internal banking logic utility library       |

## nav-invoice — NAV Online Számla 3.0 client
- **Layout**: `src/nav_invoice/` (config, models, crypto, client, auth, query), `api/main.py` (FastAPI), `cli/main.py` (Click), `tests/`. `requires-python >=3.11`.
- **Run**: `cd nav-invoice && uv run uvicorn nav_invoice.api.main:app --port 8002 --reload`. CLI: `uv run nav list [--from --to] [--direction]`.
- **Env** (root `.env`): `USERNAME`, `PASSWORD`, `LICENSE_KEY`, `CSERE_KEY`, `TAX_NUMBER`, `SOFTWARE_*`, `ENVIRONMENT` (`test`/`production`).

## attachment-downloader — Gmail PDF attachment downloader
- **Layout**: `src/attachment_downloader/` (api/main.py, cli/main.py, providers/gmail/client.py, base.py, cache.py, config.py, models.py), `tests/`. `requires-python >=3.9`.
- **Run**: `cd attachment-downloader && uv run uvicorn attachment_downloader.api.main:app --port 8000 --reload`. CLI: `uv run attachment-downloader --start --end`.
- **Auth**: Place OAuth2 `credentials.json` in project root; `token.json` generated on first auth. Override via `GOOGLE_CREDENTIALS_FILE`/`GOOGLE_TOKEN_FILE`.
- **Files**: `YYYY-MM-DD_NNNN_<sanitized>.pdf`; counter resumes from highest existing file.

## invoice-file-filter — PDF extraction + invoice filtering
- **Layout**: `src/invoice_file_filter/` (api/main.py, cli/main.py, service.py, client.py, config.py, models.py), `tests/`. `requires-python >=3.11`.
- **Run**: `cd invoice-file-filter && uv run uvicorn invoice_file_filter.api.main:app --port 8001 --reload`. CLI: `uv run invoice-file-filter process [--start --end] [--local]`.
- **System deps**: `brew install poppler tesseract tesseract-lang` (macOS).
- **Env**: `ATTACHMENT_DOWNLOADER_URL`, `OUTPUT_DIR`, `INVOICE_KEYWORDS` (JSON array), `OCR_ENABLED`, `OCR_LANGUAGE` (`hun+eng`), `EXTRACT_WORKERS` (default 4).

## invoice-core — master orchestrator (PostgreSQL)
- **Layout**: `src/invoice_core/` (api/main.py, services/, service.py, db.py, models.py, config.py, nav_client.py, pdf_client.py, bank_client.py), `tests/`. `requires-python >=3.11`.
- **Run**: `cd invoice-core && uv run alembic upgrade head`. API: `python run_api.py` (:8004). CLI: `uv run invoice-core sync-nav | sync-pdf | sync-bank | sync-match`.
- **REST API**: `/api/v1/dashboard`, `/api/v1/invoices` (filters: date, status, direction, has_pdf, supplier_name), `/api/v1/invoice-files` (+ PDF serve), partners, transactions (+ balances), sync/logs, reports (tax + dividend), `/api/v1/users`.
- **Env**: `DB_URL` (JDBC), `DB_USER`/`DB_PWD`, `NAV_INVOICE_URL` (`:8002`), `INVOICE_FILE_FILTER_URL` (`:8001`), `BANK_URL` (`:8005`), `SYNC_TIMEOUT`, `TAX_ACCOUNTS` (NAV/HIPA/Iparkamara).

## auth — central authentication (Google OAuth 2.0)
- **Layout**: `src/auth_service/` (config.py, models.py, jwt_service.py, providers/, service.py, api/main.py, cli/main.py), `tests/`. `requires-python >=3.11`.
- **Run**: `cd auth && uv run uvicorn auth_service.api.main:app --port 8007 --reload`. CLI: `uv run auth keygen` (once), `uv run auth status | verify <token>`.
- **JWT**: RS256 pair (access 15min, refresh 30days) via `JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`. Services validate locally via `JwtAuth` (no per-request network).
- **Env**: `GOOGLE_CLIENT_ID`/`SECRET`, `OAUTH_REDIRECT_URL`, `JWT_*_PATH`, `ACCESS_TOKEN_TTL`/`REFRESH_TOKEN_TTL`, `ALLOWED_EMAILS`/`DOMAINS`, `COOKIE_SECURE`, `VISION_URL`, `API_HOST`/`AUTH_API_PORT` (8007).

## bank — consolidated bank statements (Erste + Wise)
- **Purpose**: Aggregates Erste CSV and Wise balance-statements into a REST API consumed by `invoice-core`. Leaf service — no DB.
- **Layout**: `src/bank/` (api/main.py, csv_processor.py, models.py, config.py), `tests/`. `requires-python >=3.11`.
- **Run**: `cd bank && uv run uvicorn bank.api.main:app --port 8005 --reload`.
- **Env**: `BANK_API_PORT` (8005), `BALANCE_STATEMENTS_DIR` (`../storage/bank/balance-statements`), `ERSTE_SUBDIR`, `WISE_SUBDIR`.

## uploader — CSV upload endpoint
- **Purpose**: REST endpoint that receives bank CSV files and stores them under `STORAGE_DIR`. Consumed by `bank` service.
- **Layout**: `src/uploader/` (api/main.py, storage.py, models.py, config.py), `tests/`, `Dockerfile`. `requires-python >=3.11`.
- **Run**: `cd uploader && uv run uvicorn uploader.api.main:app --port 8006 --reload`.
- **Env**: `UPLOADER_API_PORT` (8006), `STORAGE_DIR` (`../storage/bank/balance-statements`).

## wise — Wise bank-statement service (deprecated)
- **Status**: On hold. Use `bank/` instead.
- **Layout**: `src/wise_invoice/` (api/main.py, cli/main.py, client.py, sync.py, csv_import.py), `tests/`.
- **SCA**: RSA keypair required for balance-statement downloads (`WISE_SCA_PRIVATE_KEY_PATH`).

## vision — frontend
- **Layout**: `src/vision/` (api/main.py, ui/router.py + invoice_router.py, utils.py (dict_to_ns()), clients/invoice_core.py + srcprofit.py, templates/ + static/), `tests/`. `requires-python >=3.11`.
- **Run**: `cd vision && uv run uvicorn vision.api.main:app --port 8009 --reload`. Open `http://localhost:8009/ui/`.
- **Pages**: `/` (pitch), `/pitch` (redirects to `/`), `/ui/*` (Dashboard, Számlák, Szla Fájlok, Szállítók, Vevők, Bank, Osztalék, Adók, Sync).
- **Env**: `INVOICE_CORE_URL` (`:8004`), `SRCPROFIT_URL`, `SRCPROFIT_USER`/`PASSWORD`, `REQUEST_TIMEOUT`, `API_HOST`/`VISION_API_PORT` (8009).

## e2e — QA tests
- **Purpose**: End-to-end tests against real services (pytest + Playwright). Owned by QA (see `REQUIREMENTS.md`).
- **Run**: `cd e2e && uv run pytest -v`. Slow tests: `uv run pytest -v -m "not slow"`.
- **Prerequisites**: All services running, `invoice-core` migrated (`alembic upgrade head`), `auth/keys/` populated, Playwright installed (`uv run playwright install chromium`), Gmail OAuth/NAV credentials in `.env`.
- **Layout**: `conftest.py` (base URLs, auth_token fixture, Playwright browser_context), `test_health.py`, `test_auth_gating.py`, `test_sync_pipeline.py`, `test_read_api.py`, `test_manual_overrides.py`, `test_ui_screenshots.py`.

## vault-agent — Obsidian vault chat CLI
- **Purpose**: Chat with any Obsidian vault using Pydantic AI. Uses wikilinks for cross-referencing; long notes returned section-by-section.
- **Run**: `cd vault-agent && uv run python cli.py <path>`. Web: `uv run python web.py` (serves http://127.0.0.1:8010).
- **Layout**: `cli.py`, `main.py`, `web.py`, `system_prompt.md`, `tests/`. Uses `VAULT_PATH`/`VAULT_NAME` (from `.env`).
- **Models**: Defaults to local (LM Studio). Cloud: `MODEL=openrouter:anthropic/claude-sonnet-4.6` or `deepseek:deepseek-reasoner`.

## banking — banking utility library
- **Purpose**: Internal Python library for banking logic (auth validation, transaction categorization). Not a standalone service.
- **Layout**: `src/banking/`, `tests/`. `requires-python >=3.11`.

## Conventions
- **Naming**: Python modules use snake_case. CLI scripts installed as console_scripts in `pyproject.toml`.
- **Config**: `pydantic-settings` reading root `.env` (or service-specific override). All services use the same `Settings` class structure.
- **Testing**: `pytest` under `tests/`. Use `uv run pytest -v`. Coverage and linting via `ruff`.
- **DB migrations**: `alembic revision -m "desc"` then `alembic upgrade head` (invoice-core only).
- **OCR deps**: System-level — install once per machine (not in `pyproject.toml`).
- **Authentication**: JWT-protected services set `AUTH_ENABLED=true` in root `.env`. `auth` posts login records to invoice-core's `/api/v1/users` (best-effort).

## Pitfalls
- **PORT conflict**: Each service binds to its own port (8000–8009). Check `docker-compose.yml` for service names vs ports.
- **auth/keys/ missing**: `uv run auth keygen` required once before e2e tests.
- **Auth toggle**: `AUTH_ENABLED=true` by default for all services except `attachment-downloader` (leaf service). Disable if Google OAuth isn't configured.
- **Vision redirect**: `/ui/*` routes require auth (redirect to `/login`). Use `uv run auth keygen` first.
- **CSV storage**: `bank/` and `uploader/` write to `../storage/bank/balance-statements/` relative to project root.
