"""Közös fixtures az uploader tesztekhez."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from uploader.auth import require_auth
from uploader.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings, amely a storage könyvtárakat egy izolált tmp_path-ra tereli."""
    return Settings(storage_dir=str(tmp_path / "csv"), pdf_storage_dir=str(tmp_path / "pdf"))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """TestClient izolált storage könyvtárral, auth-ellenőrzés nélkül."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "csv"))
    monkeypatch.setenv("PDF_STORAGE_DIR", str(tmp_path / "pdf"))

    from uploader.api import main as api_main

    api_main.app.dependency_overrides[require_auth] = lambda: None
    with TestClient(api_main.app) as test_client:
        yield test_client
    api_main.app.dependency_overrides.clear()


@pytest.fixture
def readonly_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """TestClient read_only role claims-szel (require_auth felülírva)."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "csv"))
    monkeypatch.setenv("PDF_STORAGE_DIR", str(tmp_path / "pdf"))

    from uploader.api import main as api_main

    async def _readonly_require_auth(request: Request):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            raise HTTPException(
                status_code=403,
                detail="Csak olvasási jogosultság — írási művelet nem engedélyezett",
            )
        return {"role": "read_only"}

    api_main.app.dependency_overrides[require_auth] = _readonly_require_auth
    with TestClient(api_main.app) as test_client:
        yield test_client
    api_main.app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """TestClient valódi (felül nem írt) require_auth dependency-vel."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "csv"))
    monkeypatch.setenv("PDF_STORAGE_DIR", str(tmp_path / "pdf"))

    from uploader.api import main as api_main

    with TestClient(api_main.app) as test_client:
        yield test_client
