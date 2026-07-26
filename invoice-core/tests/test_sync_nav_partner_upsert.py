"""Regression tests for DEF-004: sync_nav must upsert suppliers/customers
(create when NAV gives usable identifying data and no matching row exists
yet) rather than only ever linking to pre-existing rows.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.config import Settings
from invoice_core.db import Base, Customer, Invoice, Supplier
from invoice_core.nav_client import NavClient
from invoice_core.service import sync_nav


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


@pytest.fixture
def settings():
    return Settings(_env_file=None)


def _digest(**overrides):
    base = {
        "invoice_number": "INV-1",
        "invoice_issue_date": "2026-06-12",
        "supplier_tax_number": "",
        "supplier_name": "",
        "customer_tax_number": "",
        "customer_name": "",
        "direction": "OUTBOUND",
    }
    base.update(overrides)
    return base


def _sync(monkeypatch, db, settings, digests):
    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: digests)
    monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: {})
    return sync_nav("2026-06-01", "2026-06-30", db, settings)


def test_unknown_supplier_creates_exactly_one_supplier_and_links_it(db, settings, monkeypatch):
    digest = _digest(
        supplier_tax_number="12345678-1-11",
        supplier_name="Brand New Supplier Kft.",
        customer_tax_number="87654321-1-11",
        customer_name="Brand New Customer Kft.",
    )

    count, warnings = _sync(monkeypatch, db, settings, [digest])

    assert count == 1
    assert warnings == []  # both sides present, both get created -> no warning
    suppliers = db.query(Supplier).all()
    assert len(suppliers) == 1
    assert suppliers[0].name == "Brand New Supplier Kft."
    assert suppliers[0].tax_id == "12345678-1-11"
    inv = db.query(Invoice).filter_by(invoice_number="INV-1").first()
    assert inv.supplier_id == suppliers[0].id


def test_resync_does_not_create_a_duplicate_supplier(db, settings, monkeypatch):
    digest = _digest(
        supplier_tax_number="12345678-1-11",
        supplier_name="Brand New Supplier Kft.",
    )

    _sync(monkeypatch, db, settings, [digest])
    _sync(monkeypatch, db, settings, [digest])

    assert db.query(Supplier).count() == 1


def test_resync_matches_supplier_by_normalized_8_digit_tax_core(db, settings, monkeypatch):
    """Same taxpayer, different VAT-code/county suffix on the tax number must
    still match the previously-created row rather than creating a second."""
    first = _digest(
        supplier_tax_number="12345678-1-11",
        supplier_name="Brand New Supplier Kft.",
    )
    second = _digest(
        invoice_number="INV-2",
        supplier_tax_number="12345678-2-44",
        supplier_name="Brand New Supplier Kft.",
    )

    _sync(monkeypatch, db, settings, [first])
    _sync(monkeypatch, db, settings, [second])

    assert db.query(Supplier).count() == 1


def test_user_edited_field_survives_resync(db, settings, monkeypatch):
    sup = Supplier(
        name="Brand New Supplier Kft.",
        tax_id="12345678-1-11",
        address="User-entered address 1.",
    )
    db.add(sup)
    db.commit()

    digest = _digest(
        supplier_tax_number="12345678-1-11",
        supplier_name="Brand New Supplier Kft.",
    )
    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [digest])
    monkeypatch.setattr(
        NavClient,
        "get_invoice_detail",
        lambda self, *a, **kw: {"supplier_address": "NAV-reported address 2."},
    )
    sync_nav("2026-06-01", "2026-06-30", db, settings)

    db.refresh(sup)
    assert sup.address == "User-entered address 1."


def test_no_tax_number_and_no_name_creates_nothing_and_warns(db, settings, monkeypatch):
    digest = _digest()  # empty supplier_tax_number and supplier_name

    count, warnings = _sync(monkeypatch, db, settings, [digest])

    assert count == 1
    assert db.query(Supplier).count() == 0
    assert any("szállító" in w for w in warnings)
    inv = db.query(Invoice).filter_by(invoice_number="INV-1").first()
    assert inv.supplier_id is None


def test_unknown_customer_creates_exactly_one_customer_and_links_it(db, settings, monkeypatch):
    digest = _digest(
        customer_tax_number="87654321-1-11",
        customer_name="Brand New Customer Kft.",
    )

    count, _warnings = _sync(monkeypatch, db, settings, [digest])

    assert count == 1
    customers = db.query(Customer).all()
    assert len(customers) == 1
    assert customers[0].tax_id == "87654321-1-11"
    inv = db.query(Invoice).filter_by(invoice_number="INV-1").first()
    assert inv.customer_id == customers[0].id
