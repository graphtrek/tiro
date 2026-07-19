#!/bin/sh
set -e

if [ ! -f keys/jwt_private.pem ]; then
    uv run auth keygen
fi
exec uv run uvicorn auth_service.api.main:app --host 0.0.0.0 --port 8007
