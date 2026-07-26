"""An invoice with a linked bank transaction counts as PAID.

Covers the derivation in the read services (so existing links show as paid
without a re-sync) and the bulk backfill written by sync_bank.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import (
    BankTransaction,
    Base,
    Customer,
    Invoice,
    Supplier,
    _InvoiceDirection,
    _PaymentStatus,
)
from invoice_core.services import dashboard_service, invoice_service


@pytest.fixture
def wdb():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def _seed(db) -> tuple[Invoice, Invoice]:
    sup = Supplier(name="Acme", tax_id="111")
    cust = Customer(name="Buyer", tax_id="222")
    db.add_all([sup, cust])
    db.flush()

    # paid_inv stays stored UNPAID but gets a bank transaction → derived PAID.
    paid_inv = Invoice(
        invoice_number="INV-1",
        invoice_date=date(2026, 6, 1),
        supplier_id=sup.id,
        customer_id=cust.id,
        amount_total=1000.0,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
    )
    unpaid_inv = Invoice(
        invoice_number="INV-2",
        invoice_date=date(2026, 6, 2),
        supplier_id=sup.id,
        customer_id=cust.id,
        amount_total=500.0,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
    )
    db.add_all([paid_inv, unpaid_inv])
    db.flush()

    btxn = BankTransaction(
        transaction_id="B-1",
        bank="wise",
        direction="CREDIT",
        amount=1000.0,
        currency="HUF",
        transaction_date=datetime(2026, 6, 3),
    )
    db.add(btxn)
    db.flush()
    paid_inv.bank_transactions.append(btxn)
    db.commit()
    return paid_inv, unpaid_inv


def test_list_invoices_marks_bank_linked_as_paid(wdb):
    _seed(wdb)
    rows = {r.invoice_number: r for r in invoice_service.list_invoices(wdb)}
    assert rows["INV-1"].payment_status == "PAID"
    assert rows["INV-1"].bank_count == 1
    assert rows["INV-2"].payment_status == "UNPAID"


def test_paid_filter_includes_bank_linked(wdb):
    _seed(wdb)
    paid = invoice_service.list_invoices(wdb, payment_status="PAID")
    assert {r.invoice_number for r in paid} == {"INV-1"}

    unpaid = invoice_service.list_invoices(wdb, payment_status="UNPAID")
    assert {r.invoice_number for r in unpaid} == {"INV-2"}


def test_get_invoice_marks_bank_linked_as_paid(wdb):
    paid_inv, unpaid_inv = _seed(wdb)
    assert invoice_service.get_invoice(wdb, paid_inv.id).payment_status == "PAID"
    assert invoice_service.get_invoice(wdb, unpaid_inv.id).payment_status == "UNPAID"


def test_kpis_exclude_bank_linked_from_unpaid(wdb):
    _seed(wdb)
    kpis = dashboard_service.get_kpis(wdb)
    # Only INV-2 (500) remains unpaid; INV-1 is settled via bank transaction.
    assert kpis.unpaid_invoices == 1
    assert kpis.unpaid_amount == 500.0


def test_recent_invoices_derive_paid(wdb):
    _seed(wdb)
    recent = {r.invoice_number: r for r in dashboard_service.get_recent_invoices(wdb)}
    assert recent["INV-1"].payment_status == "PAID"
    assert recent["INV-2"].payment_status == "UNPAID"


def test_partial_payment_status(wdb):
    """A transaction covering only part of the invoice total gives PARTIAL status."""
    sup = Supplier(name="Acme2", tax_id="333")
    cust = Customer(name="Buyer2", tax_id="444")
    wdb.add_all([sup, cust])
    wdb.flush()
    inv = Invoice(
        invoice_number="INV-P1",
        invoice_date=date(2026, 6, 1),
        supplier_id=sup.id,
        customer_id=cust.id,
        amount_total=1000.0,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
        currency="HUF",
    )
    wdb.add(inv)
    wdb.flush()
    btxn = BankTransaction(
        transaction_id="B-P1",
        bank="wise",
        direction="CREDIT",
        amount=400.0,
        currency="HUF",
        transaction_date=datetime(2026, 6, 3),
    )
    wdb.add(btxn)
    wdb.flush()
    inv.bank_transactions.append(btxn)

    from invoice_core.service import _recompute_payment_status

    _recompute_payment_status(wdb, inv)
    wdb.commit()

    detail = invoice_service.get_invoice(wdb, inv.id)
    assert detail.payment_status == "PARTIAL"

    rows = {r.invoice_number: r for r in invoice_service.list_invoices(wdb)}
    assert rows["INV-P1"].payment_status == "PARTIAL"


def test_split_payment_full_coverage(wdb):
    """Two partial transactions together fully paying an invoice give PAID status."""
    sup = Supplier(name="Acme3", tax_id="555")
    cust = Customer(name="Buyer3", tax_id="666")
    wdb.add_all([sup, cust])
    wdb.flush()
    inv = Invoice(
        invoice_number="INV-S1",
        invoice_date=date(2026, 6, 1),
        supplier_id=sup.id,
        customer_id=cust.id,
        amount_total=1000.0,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
        currency="HUF",
    )
    wdb.add(inv)
    wdb.flush()
    b1 = BankTransaction(
        transaction_id="B-S1",
        bank="wise",
        direction="CREDIT",
        amount=600.0,
        currency="HUF",
        transaction_date=datetime(2026, 6, 3),
    )
    b2 = BankTransaction(
        transaction_id="B-S2",
        bank="wise",
        direction="CREDIT",
        amount=400.0,
        currency="HUF",
        transaction_date=datetime(2026, 6, 4),
    )
    wdb.add_all([b1, b2])
    wdb.flush()
    inv.bank_transactions.extend([b1, b2])

    from invoice_core.service import _recompute_payment_status

    _recompute_payment_status(wdb, inv)
    wdb.commit()

    detail = invoice_service.get_invoice(wdb, inv.id)
    assert detail.payment_status == "PAID"
    assert len(detail.bank_transactions) == 2
