"""Regression test for DEF-008 (backend half): the dashboard API's
`recent_invoices[]` rows must carry `supplier_id` alongside `supplier_name`
so vision can link a dashboard row to the supplier's detail page the same
way `/ui/invoices` already does.

Root cause was `dashboard_service.RecentInvoiceRow` carrying only
`supplier_name`, no `supplier_id` -- the frontend's `{% if row.supplier_id %}`
guard always saw a missing field and fell back to the placeholder even for
invoices with a real, linked supplier. This test hits the real
`GET /api/v1/dashboard` endpoint (not a hand-mocked payload) so it actually
proves the contract the frontend depends on.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from invoice_core.api.main import app
from invoice_core.auth import require_auth
from invoice_core.db import Base, Invoice, Supplier, _InvoiceDirection, get_db


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


def test_dashboard_recent_invoices_include_supplier_id(client):
    tc, session = client
    supplier = Supplier(name="GRAPHTREK Kft.", tax_id="12345678")
    session.add(supplier)
    session.flush()

    session.add_all(
        [
            Invoice(
                invoice_number="INV-WITH-SUPPLIER",
                invoice_date=date(2026, 6, 1),
                supplier_id=supplier.id,
                direction=_InvoiceDirection.INBOUND,
            ),
            Invoice(
                invoice_number="INV-NO-SUPPLIER",
                invoice_date=date(2026, 6, 2),
                supplier_id=None,
                direction=_InvoiceDirection.INBOUND,
            ),
        ]
    )
    session.commit()

    resp = tc.get("/api/v1/dashboard")
    assert resp.status_code == 200
    body = resp.json()

    rows = {r["invoice_number"]: r for r in body["recent_invoices"]}

    assert "supplier_id" in rows["INV-WITH-SUPPLIER"]
    assert rows["INV-WITH-SUPPLIER"]["supplier_id"] == supplier.id
    assert rows["INV-WITH-SUPPLIER"]["supplier_name"] == "GRAPHTREK Kft."

    assert "supplier_id" in rows["INV-NO-SUPPLIER"]
    assert rows["INV-NO-SUPPLIER"]["supplier_id"] is None
    assert rows["INV-NO-SUPPLIER"]["supplier_name"] is None
