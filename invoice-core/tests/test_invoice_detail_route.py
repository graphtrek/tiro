"""Regression test for DEF-001: GET /api/v1/invoices/{invoice_number} must
return 200 (not a ResponseValidationError 500) when the invoice has no
linked supplier/customer -- the common case since sync_nav no longer
force-links every invoice to a pre-existing partner.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from invoice_core.api.main import app
from invoice_core.auth import require_auth
from invoice_core.db import Base, Invoice, _InvoiceDirection, get_db


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


def test_invoice_detail_by_number_returns_200_with_null_partner_ids(client):
    tc, session = client
    session.add(
        Invoice(
            invoice_number="AHUW261564234",
            supplier_id=None,
            customer_id=None,
            direction=_InvoiceDirection.INBOUND,
        )
    )
    session.commit()

    resp = tc.get("/api/v1/invoices/AHUW261564234")

    assert resp.status_code == 200
    body = resp.json()
    assert body["invoice_number"] == "AHUW261564234"
    assert body["supplier_id"] is None
    assert body["customer_id"] is None


def test_invoice_detail_by_number_returns_404_when_missing(client):
    tc, _session = client

    resp = tc.get("/api/v1/invoices/DOES-NOT-EXIST")

    assert resp.status_code == 404
