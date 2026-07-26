# Moneypenny e2e tests

End-to-end tests that drive the *real running services* (not mocks) over HTTP, plus a real
browser (via Playwright) for the `vision` UI. Owned by QA (see `AGENTS.md` / `CLAUDE.md`).

## Prerequisites

- All services running (`./start-all.sh` from repo root, or each service's `python run_api.py`).
- PostgreSQL reachable and `invoice-core` migrated (`cd invoice-core && uv run alembic upgrade head`).
- `auth/keys/` populated (`cd auth && uv run auth keygen`) — needed so this suite can mint a
  short-lived RS256 access token locally via `auth_service.jwt_service.JWTService` (the exact same
  code path the real Google login issues a token with). This is **not** a way around Google OAuth
  for real users — it only lets automated tests attach a valid `Authorization: Bearer` /
  `mp_access_token` cookie without a browser consent step, for an email covered by
  `ALLOWED_DOMAINS`/`ALLOWED_EMAILS` in the shared `.env`.
- Playwright browsers installed once: `uv run playwright install chromium`.

## Running

```bash
cd e2e
uv sync
uv run pytest -v
```

Some tests are slow/live by nature (`test_sync_pipeline.py::test_full_sync_end_to_end` drives the
real Gmail → invoice-file-filter (OCR) → NAV → bank pipeline and can take minutes; it also
requires real external credentials in the shared `.env` — attachment-downloader's Gmail
`token.json`/`credentials.json`, NAV production/test credentials, and bank CSVs under
`storage/bank/balance-statements/`). Mark-select them out with `-m "not slow"` if you only want
the fast read-API/health checks.

## Layout

- `conftest.py` — base URLs for every service, the `auth_token` fixture (mints a JWT), an
  `api_get`/`api_post` helper that attaches the bearer token, and a Playwright `browser_context`
  fixture that seeds the `mp_access_token` cookie so authenticated `vision` pages can be screenshotted
  without a Google login.
- `test_health.py` — REQUIREMENTS acceptance criterion: every service answers `GET /health`
  without authentication.
- `test_auth_gating.py` — AUTH_ENABLED=true acceptance criterion: unauthenticated API calls to
  protected backend routes get 401; an unauthenticated browser hitting a protected `vision` page
  is redirected to `/login`.
- `test_sync_pipeline.py` — `POST /api/v1/sync` (and each CLI stage) degrades cleanly with a
  sync_log row when a downstream call fails, and completes end-to-end against real data when it
  succeeds.
- `test_read_api.py` — smoke tests + timing for the invoice-core read API (dashboard, invoices +
  filters, invoice-files, partners, transactions + balances, sync/logs, reports).
- `test_manual_overrides.py` — the manual-override acceptance criterion: a note, paid flag, PDF
  link and bank-transaction link all survive a subsequent sync unchanged.
- `test_ui_screenshots.py` — screenshots every `vision` page into `../screenshots/` for visual
  review against REQUIREMENTS "Look and feel".
