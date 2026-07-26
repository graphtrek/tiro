"""Shared fixtures for the Moneypenny e2e suite.

Drives the real running services over HTTP (no mocks). Services are expected to already be
running (see ../README.md).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent

BASE_URLS = {
    "attachment_downloader": "http://localhost:8000",
    "invoice_file_filter": "http://localhost:8001",
    "nav_invoice": "http://localhost:8002",
    "invoice_core": "http://localhost:8004",
    "bank": "http://localhost:8005",
    "uploader": "http://localhost:8006",
    "auth": "http://localhost:8007",
    "vision": "http://localhost:8009",
}


@pytest.fixture(scope="session")
def base_urls() -> dict[str, str]:
    return BASE_URLS


@pytest.fixture(scope="session")
def auth_token() -> str:
    """Mint a short-lived RS256 access token via auth's own JWTService.

    This calls the exact same signing code the real Google-login flow uses, for a test
    identity covered by the shared .env's ALLOWED_DOMAINS/ALLOWED_EMAILS — but it never talks
    to Google and never involves a browser consent screen. It requires `auth/keys/` to already
    hold a keypair (`cd auth && uv run auth keygen`).

    The shared root .env sets JWT_PRIVATE_KEY_PATH/JWT_PUBLIC_KEY_PATH as `./keys/...`, resolved
    relative to auth/'s own cwd when the real service runs there — since this suite's cwd is
    e2e/, the two env vars are pointed at absolute paths here (process-local override only, the
    shared .env file itself is never touched).
    """
    os.environ.setdefault(
        "JWT_PRIVATE_KEY_PATH", str(_WORKSPACE_ROOT / "auth" / "keys" / "jwt_private.pem")
    )
    os.environ.setdefault(
        "JWT_PUBLIC_KEY_PATH", str(_WORKSPACE_ROOT / "auth" / "keys" / "jwt_public.pem")
    )

    from auth_service.config import Settings
    from auth_service.jwt_service import JWTService
    from auth_service.models import UserInfo

    settings = Settings()
    svc = JWTService(settings)
    user = UserInfo(
        sub="qa-e2e-tester",
        email="imre.tatai@graphtrek.co",
        name="QA E2E",
        provider="google",
    )
    return svc.issue_access_token(user)


@pytest.fixture()
def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture()
def api_session(auth_token: str) -> requests.Session:
    """A requests.Session pre-configured with a valid bearer token."""
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {auth_token}"})
    return session
