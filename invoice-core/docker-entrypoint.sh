#!/bin/sh
set -e

uv run alembic upgrade head
exec uv run uvicorn invoice_core.api.main:app --host 0.0.0.0 --port 8004
