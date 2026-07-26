"""API-level regression tests for DEF-012: POST /api/v1/sync (and its stage
variants) must reject a second concurrent sync with a clean HTTP 409 and a
Hungarian message, never hang/queue/contend, per the API-layer contract on
top of the service-level guard already covered by tests/test_sync_lock.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from invoice_core.api.main import app
from invoice_core.auth import require_auth
from invoice_core.db import Base, SyncLock, get_db
from invoice_core.service import SYNC_LOCK_ID
from invoice_core.timeutil import utcnow


@pytest.fixture
def client():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    session = Session()

    def _get_db():
        yield session

    async def _no_auth():
        yield None

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[require_auth] = _no_auth
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()
        session.close()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/sync",
        "/api/v1/sync/nav",
        "/api/v1/sync/pdf",
        "/api/v1/sync/bank",
        "/api/v1/sync/match",
    ],
)
def test_sync_endpoint_returns_409_when_a_sync_is_already_in_progress(client, path):
    tc, session = client
    # Simulate an in-progress sync by holding the lock directly, the same way
    # a concurrent request's sync_all would.
    session.add(SyncLock(id=SYNC_LOCK_ID, locked_at=utcnow(), locked_by="host:1"))
    session.commit()

    resp = tc.post(path, json={"start_date": "2026-01-01", "end_date": "2026-01-31"})

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "folyamatban" in detail.lower()
