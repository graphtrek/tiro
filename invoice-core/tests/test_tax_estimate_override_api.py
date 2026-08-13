"""Tests for GET/PUT /api/v1/reports/tax-estimate/overrides."""

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


def test_get_overrides_empty_for_year_with_none_saved(client):
    tc, _session = client

    resp = tc.get("/api/v1/reports/tax-estimate/overrides", params={"year": 2026})

    assert resp.status_code == 200
    assert resp.json() == {"year": 2026, "months": []}


def test_put_then_get_round_trips(client):
    tc, _session = client

    put_resp = tc.put(
        "/api/v1/reports/tax-estimate/overrides",
        json={"year": 2026, "months": [{"month": 8, "gross_revenue": 2500000.0}]},
    )
    assert put_resp.status_code == 200
    assert put_resp.json() == {
        "year": 2026,
        "months": [{"month": 8, "gross_revenue": 2500000.0}],
    }

    get_resp = tc.get("/api/v1/reports/tax-estimate/overrides", params={"year": 2026})
    assert get_resp.status_code == 200
    assert get_resp.json() == {
        "year": 2026,
        "months": [{"month": 8, "gross_revenue": 2500000.0}],
    }


def test_put_twice_same_month_updates_not_duplicates(client):
    tc, session = client

    tc.put(
        "/api/v1/reports/tax-estimate/overrides",
        json={"year": 2026, "months": [{"month": 8, "gross_revenue": 2500000.0}]},
    )
    resp = tc.put(
        "/api/v1/reports/tax-estimate/overrides",
        json={"year": 2026, "months": [{"month": 8, "gross_revenue": 2700000.0}]},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "year": 2026,
        "months": [{"month": 8, "gross_revenue": 2700000.0}],
    }

    from invoice_core.db import TaxEstimateOverride

    rows = session.query(TaxEstimateOverride).filter_by(year=2026, month=8).all()
    assert len(rows) == 1
    assert rows[0].gross_revenue == 2700000.0


def test_put_leaves_other_months_untouched(client):
    tc, _session = client

    tc.put(
        "/api/v1/reports/tax-estimate/overrides",
        json={
            "year": 2026,
            "months": [
                {"month": 8, "gross_revenue": 2500000.0},
                {"month": 9, "gross_revenue": 3000000.0},
            ],
        },
    )
    resp = tc.put(
        "/api/v1/reports/tax-estimate/overrides",
        json={"year": 2026, "months": [{"month": 8, "gross_revenue": 2700000.0}]},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "year": 2026,
        "months": [
            {"month": 8, "gross_revenue": 2700000.0},
            {"month": 9, "gross_revenue": 3000000.0},
        ],
    }


def test_put_empty_months_is_a_no_op(client):
    tc, _session = client

    tc.put(
        "/api/v1/reports/tax-estimate/overrides",
        json={"year": 2026, "months": [{"month": 8, "gross_revenue": 2500000.0}]},
    )
    resp = tc.put("/api/v1/reports/tax-estimate/overrides", json={"year": 2026, "months": []})

    assert resp.status_code == 200
    assert resp.json() == {
        "year": 2026,
        "months": [{"month": 8, "gross_revenue": 2500000.0}],
    }


def test_put_duplicate_month_in_payload_returns_400(client):
    tc, _session = client

    resp = tc.put(
        "/api/v1/reports/tax-estimate/overrides",
        json={
            "year": 2026,
            "months": [
                {"month": 8, "gross_revenue": 2500000.0},
                {"month": 8, "gross_revenue": 2700000.0},
            ],
        },
    )

    assert resp.status_code == 400
    assert "8" in resp.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"year": 2026, "months": [{"month": 0, "gross_revenue": 100.0}]},
        {"year": 2026, "months": [{"month": 13, "gross_revenue": 100.0}]},
        {"year": 2026, "months": [{"month": 5, "gross_revenue": -1.0}]},
        {"year": 1999, "months": []},
        {"year": 2101, "months": []},
    ],
)
def test_put_validation_rejections_return_422(client, payload):
    tc, _session = client

    resp = tc.put("/api/v1/reports/tax-estimate/overrides", json=payload)

    assert resp.status_code == 422


def test_get_defaults_to_current_year(client, monkeypatch):
    tc, _session = client
    from datetime import date

    import invoice_core.api.main as main_module

    monkeypatch.setattr(main_module, "today", lambda: date(2026, 8, 13))

    resp = tc.get("/api/v1/reports/tax-estimate/overrides")

    assert resp.status_code == 200
    assert resp.json()["year"] == 2026
