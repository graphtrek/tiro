"""Tests for GET/PUT /api/v1/fizetes-kalkulator."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from invoice_core.api.main import app
from invoice_core.auth import require_auth
from invoice_core.db import Base, get_db


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


def test_get_returns_defaults_when_never_saved(client):
    tc, _session = client

    resp = tc.get("/api/v1/fizetes-kalkulator")

    assert resp.status_code == 200
    assert resp.json() == {"net_wage": 1_000_000.0, "revenue": 0.0, "revenue_touched": False}


def test_put_then_get_round_trips(client):
    tc, _session = client

    put_resp = tc.put(
        "/api/v1/fizetes-kalkulator",
        json={"net_wage": 1_200_000.0, "revenue": 8_000_000.0, "revenue_touched": True},
    )
    assert put_resp.status_code == 200
    assert put_resp.json() == {
        "net_wage": 1_200_000.0,
        "revenue": 8_000_000.0,
        "revenue_touched": True,
    }

    get_resp = tc.get("/api/v1/fizetes-kalkulator")
    assert get_resp.status_code == 200
    assert get_resp.json() == {
        "net_wage": 1_200_000.0,
        "revenue": 8_000_000.0,
        "revenue_touched": True,
    }


def test_put_twice_updates_the_same_row_not_a_new_one(client):
    tc, session = client

    tc.put(
        "/api/v1/fizetes-kalkulator",
        json={"net_wage": 1_000_000.0, "revenue": 0.0, "revenue_touched": False},
    )
    resp = tc.put(
        "/api/v1/fizetes-kalkulator",
        json={"net_wage": 1_500_000.0, "revenue": 9_000_000.0, "revenue_touched": True},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "net_wage": 1_500_000.0,
        "revenue": 9_000_000.0,
        "revenue_touched": True,
    }

    from invoice_core.db import FizetesKalkulatorState

    rows = session.query(FizetesKalkulatorState).all()
    assert len(rows) == 1
    assert rows[0].net_wage == 1_500_000.0


@pytest.mark.parametrize(
    "payload",
    [
        {"net_wage": -1.0, "revenue": 0.0},
        {"net_wage": 0.0, "revenue": -1.0},
        {"net_wage": 0.0},
    ],
)
def test_put_validation_rejections_return_422(client, payload):
    tc, _session = client

    resp = tc.put("/api/v1/fizetes-kalkulator", json=payload)

    assert resp.status_code == 422
