"""Tests for the manual link/unlink supplier/customer API endpoints.

Covers the core guarantee: PUT sets the FK and locks the field; DELETE clears
the FK but *also* locks it (diverging from the invoice-file link precedent,
which unlocks on unlink) — a manual "no partner" decision must survive the
next sync just as much as a manual "this partner" decision does.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.api.main import (
    link_invoice_to_customer,
    link_invoice_to_supplier,
    link_transaction_to_customer,
    link_transaction_to_supplier,
    unlink_invoice_from_customer,
    unlink_invoice_from_supplier,
    unlink_transaction_from_customer,
    unlink_transaction_from_supplier,
)
from invoice_core.db import (
    BankTransaction,
    Base,
    Customer,
    Invoice,
    Supplier,
    _InvoiceDirection,
    _PaymentStatus,
)
from invoice_core.models import LinkCustomerRequest, LinkSupplierRequest
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
    from invoice_core.config import Settings

    return Settings(_env_file=None)


def _invoice(db, **overrides):
    inv = Invoice(
        invoice_number=overrides.pop("invoice_number", "INV-1"),
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
        **overrides,
    )
    db.add(inv)
    db.commit()
    return inv


def _txn(db, **overrides):
    txn = BankTransaction(
        transaction_id=overrides.pop("transaction_id", "TX-1"),
        bank="erste",
        amount=1000.0,
        currency="HUF",
        direction="CREDIT",
        transaction_date=datetime(2026, 5, 12),
        **overrides,
    )
    db.add(txn)
    db.commit()
    return txn


def test_put_invoice_supplier_sets_fk_and_locks(db):
    sup = Supplier(name="ACME Kft", tax_id="11111111-1-11")
    db.add(sup)
    db.commit()
    inv = _invoice(db)

    link_invoice_to_supplier(inv.id, LinkSupplierRequest(supplier_id=sup.id), db=db)

    db.refresh(inv)
    assert inv.supplier_id == sup.id
    assert inv.supplier_locked is True


def test_delete_invoice_supplier_clears_fk_but_still_locks(db):
    sup = Supplier(name="ACME Kft", tax_id="11111111-1-11")
    db.add(sup)
    db.commit()
    inv = _invoice(db, supplier_id=sup.id)

    unlink_invoice_from_supplier(inv.id, db=db)

    db.refresh(inv)
    assert inv.supplier_id is None
    assert inv.supplier_locked is True  # diverges from invoice_file_locked's unlink behavior


def test_put_invoice_customer_sets_fk_and_locks(db):
    cust = Customer(name="ACME Kft", tax_id="22222222-2-22")
    db.add(cust)
    db.commit()
    inv = _invoice(db)

    link_invoice_to_customer(inv.id, LinkCustomerRequest(customer_id=cust.id), db=db)

    db.refresh(inv)
    assert inv.customer_id == cust.id
    assert inv.customer_locked is True


def test_delete_invoice_customer_clears_fk_but_still_locks(db):
    cust = Customer(name="ACME Kft", tax_id="22222222-2-22")
    db.add(cust)
    db.commit()
    inv = _invoice(db, customer_id=cust.id)

    unlink_invoice_from_customer(inv.id, db=db)

    db.refresh(inv)
    assert inv.customer_id is None
    assert inv.customer_locked is True


def test_put_transaction_supplier_sets_fk_and_locks(db):
    sup = Supplier(name="ACME Kft", tax_id="11111111-1-11")
    db.add(sup)
    db.commit()
    txn = _txn(db)

    link_transaction_to_supplier(txn.id, LinkSupplierRequest(supplier_id=sup.id), db=db)

    db.refresh(txn)
    assert txn.supplier_id == sup.id
    assert txn.supplier_locked is True


def test_put_transaction_supplier_records_counterparty_name(db):
    """Manually linking a transaction whose counterparty name differs from
    the supplier's own name records that name on the supplier's known_names,
    so a later sync_bank can recognize it without an exact name match."""
    sup = Supplier(name="ACME Kft", tax_id="11111111-1-11")
    db.add(sup)
    db.commit()
    txn = _txn(db, counterparty_name="ACME Kft Zrt")

    link_transaction_to_supplier(txn.id, LinkSupplierRequest(supplier_id=sup.id), db=db)

    db.refresh(sup)
    assert sup.known_names == "ACME Kft Zrt"


def test_put_transaction_supplier_no_counterparty_name_leaves_known_names_unset(db):
    sup = Supplier(name="ACME Kft", tax_id="11111111-1-11")
    db.add(sup)
    db.commit()
    txn = _txn(db)  # no counterparty_name

    link_transaction_to_supplier(txn.id, LinkSupplierRequest(supplier_id=sup.id), db=db)

    db.refresh(sup)
    assert sup.known_names is None


def test_delete_transaction_supplier_clears_fk_but_still_locks(db):
    sup = Supplier(name="ACME Kft", tax_id="11111111-1-11")
    db.add(sup)
    db.commit()
    txn = _txn(db, supplier_id=sup.id)

    unlink_transaction_from_supplier(txn.id, db=db)

    db.refresh(txn)
    assert txn.supplier_id is None
    assert txn.supplier_locked is True


def test_put_transaction_customer_sets_fk_and_locks(db):
    cust = Customer(name="ACME Kft", tax_id="22222222-2-22")
    db.add(cust)
    db.commit()
    txn = _txn(db)

    link_transaction_to_customer(txn.id, LinkCustomerRequest(customer_id=cust.id), db=db)

    db.refresh(txn)
    assert txn.customer_id == cust.id
    assert txn.customer_locked is True


def test_put_transaction_customer_records_counterparty_name(db):
    cust = Customer(name="ACME Kft", tax_id="22222222-2-22")
    db.add(cust)
    db.commit()
    txn = _txn(db, counterparty_name="ACME Kft Zrt")

    link_transaction_to_customer(txn.id, LinkCustomerRequest(customer_id=cust.id), db=db)

    db.refresh(cust)
    assert cust.known_names == "ACME Kft Zrt"


def test_delete_transaction_customer_clears_fk_but_still_locks(db):
    cust = Customer(name="ACME Kft", tax_id="22222222-2-22")
    db.add(cust)
    db.commit()
    txn = _txn(db, customer_id=cust.id)

    unlink_transaction_from_customer(txn.id, db=db)

    db.refresh(txn)
    assert txn.customer_id is None
    assert txn.customer_locked is True


def test_manual_clear_survives_resync_end_to_end(db, settings, monkeypatch):
    """The scenario from the plan's verification section: a manual DELETE
    followed by a resync must leave the field cleared, not silently re-filled."""
    sup = Supplier(name="Unknown Supplier Kft.", tax_id="33333333-1-11")
    cust = Customer(name="Unknown Customer Kft.", tax_id="44444444-2-22")
    db.add_all([sup, cust])
    db.commit()

    digest = {
        "invoice_number": "INV-300",
        "invoice_issue_date": "2026-05-12",
        "supplier_tax_number": "33333333-1-11",
        "supplier_name": "Unknown Supplier Kft.",
        "customer_tax_number": "44444444-2-22",
        "customer_name": "Unknown Customer Kft.",
        "direction": "OUTBOUND",
    }
    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [digest])
    monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: {})

    sync_nav("2026-05-01", "2026-05-31", db, settings)
    inv = db.query(Invoice).filter_by(invoice_number="INV-300").first()
    assert inv.supplier_id == sup.id  # auto-matched on first sync

    # User decides the auto-match is wrong and manually clears it.
    unlink_invoice_from_supplier(inv.id, db=db)
    db.refresh(inv)
    assert inv.supplier_id is None
    assert inv.supplier_locked is True

    # Resync over the same range must not silently re-fill the cleared field.
    sync_nav("2026-05-01", "2026-05-31", db, settings)
    db.refresh(inv)
    assert inv.supplier_id is None
