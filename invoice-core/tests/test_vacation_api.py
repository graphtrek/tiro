"""Tests for POST/GET/PUT/DELETE /api/v1/vacation-requests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from invoice_core.api.main import app
from invoice_core.auth import require_auth
from invoice_core.db import Base, User, get_db


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


@pytest.fixture
def owner(client):
    _tc, session = client
    record = User(provider="google", sub="owner-sub", email="owner@example.com", name="Kozma")
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def test_create_then_list_round_trips(client, owner):
    tc, _session = client

    resp = tc.post(
        "/api/v1/vacation-requests",
        json={
            "user_id": owner.id,
            "kind": "vacation",
            "start_date": "2026-08-17",
            "end_date": "2026-08-21",
            "note": "Nyaralás",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == owner.id
    assert body["user_name"] == "Kozma"
    assert body["kind"] == "vacation"
    assert body["note"] == "Nyaralás"

    list_resp = tc.get("/api/v1/vacation-requests")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    scoped_resp = tc.get("/api/v1/vacation-requests", params={"user_id": owner.id})
    assert scoped_resp.status_code == 200
    assert len(scoped_resp.json()) == 1


def test_create_unknown_user_returns_409(client):
    tc, _session = client

    resp = tc.post(
        "/api/v1/vacation-requests",
        json={
            "user_id": 999,
            "kind": "vacation",
            "start_date": "2026-08-17",
            "end_date": "2026-08-21",
        },
    )
    assert resp.status_code == 409


def test_create_invalid_date_range_returns_409(client, owner):
    tc, _session = client

    resp = tc.post(
        "/api/v1/vacation-requests",
        json={
            "user_id": owner.id,
            "kind": "vacation",
            "start_date": "2026-08-21",
            "end_date": "2026-08-17",
        },
    )
    assert resp.status_code == 409


def test_update_round_trips(client, owner):
    tc, _session = client

    created = tc.post(
        "/api/v1/vacation-requests",
        json={
            "user_id": owner.id,
            "kind": "vacation",
            "start_date": "2026-08-17",
            "end_date": "2026-08-21",
        },
    ).json()

    resp = tc.put(
        f"/api/v1/vacation-requests/{created['id']}",
        params={"user_id": owner.id},
        json={
            "kind": "out_of_office",
            "start_date": "2026-08-18",
            "end_date": "2026-08-19",
            "note": "OOO",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "out_of_office"
    assert body["note"] == "OOO"


def test_update_wrong_owner_returns_404(client, owner):
    tc, _session = client

    created = tc.post(
        "/api/v1/vacation-requests",
        json={
            "user_id": owner.id,
            "kind": "vacation",
            "start_date": "2026-08-17",
            "end_date": "2026-08-21",
        },
    ).json()

    resp = tc.put(
        f"/api/v1/vacation-requests/{created['id']}",
        params={"user_id": 999},
        json={
            "kind": "vacation",
            "start_date": "2026-08-17",
            "end_date": "2026-08-21",
        },
    )
    assert resp.status_code == 404


def test_delete_round_trips_and_missing_returns_404(client, owner):
    tc, _session = client

    created = tc.post(
        "/api/v1/vacation-requests",
        json={
            "user_id": owner.id,
            "kind": "note",
            "start_date": "2026-08-17",
            "end_date": "2026-08-21",
        },
    ).json()

    resp = tc.delete(f"/api/v1/vacation-requests/{created['id']}", params={"user_id": owner.id})
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}

    missing_resp = tc.delete(
        f"/api/v1/vacation-requests/{created['id']}", params={"user_id": owner.id}
    )
    assert missing_resp.status_code == 404
