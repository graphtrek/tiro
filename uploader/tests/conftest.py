"""Közös fixtures az uploader tesztekhez."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from uploader.auth import require_auth
from uploader.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings, amely a storage könyvtárat egy izolált tmp_path-ra tereli."""
    return Settings(storage_dir=str(tmp_path))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """TestClient izolált storage könyvtárral, auth-ellenőrzés nélkül."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    from uploader.api import main as api_main

    api_main.app.dependency_overrides[require_auth] = lambda: None
    with TestClient(api_main.app) as test_client:
        yield test_client
    api_main.app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """TestClient valódi (felül nem írt) require_auth dependency-vel."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    from uploader.api import main as api_main

    with TestClient(api_main.app) as test_client:
        yield test_client
