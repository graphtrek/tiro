"""An invoice with a linked bank transaction counts as PAID.

Covers the derivation in the read services (so existing links show as paid
without a re-sync) and the bulk backfill written by sync_bank.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import (
    Base,
    BankTransaction,
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
        invoice_number="INV-1", invoice_date=date(2026, 6, 1),
        supplier_id=sup.id, customer_id=cust.id, amount_total=1000.0,
        payment_status=_PaymentStatus.UNPAID, direction=_InvoiceDirection.INBOUND,
    )
    unpaid_inv = Invoice(
        invoice_number="INV-2", invoice_date=date(2026, 6, 2),
        supplier_id=sup.id, customer_id=cust.id, amount_total=500.0,
        payment_status=_PaymentStatus.UNPAID, direction=_InvoiceDirection.INBOUND,
    )
    db.add_all([paid_inv, unpaid_inv])
    db.flush()

    db.add(BankTransaction(
        transaction_id="B-1", bank="wise", direction="CREDIT",
        amount=1000.0, currency="HUF",
        transaction_date=datetime(2026, 6, 3), invoice_id=paid_inv.id,
    ))
    db.commit()
    return paid_inv, unpaid_inv


def test_list_invoices_marks_bank_linked_as_paid(wdb):
    paid_inv, unpaid_inv = _seed(wdb)
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
