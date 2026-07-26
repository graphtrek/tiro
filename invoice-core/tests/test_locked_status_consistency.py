"""Regression tests for DEF-007: the invoice-detail view's displayed
`payment_status` must never disagree with the list view for the same
invoice at the same moment.

Root cause was `invoice_service._derive_payment_status` (used by
`get_invoice`) recomputing status from linked bank transactions
unconditionally, ignoring `payment_status_locked` -- unlike
`list_invoices`, which already guarded on the lock and was upgrade-only
(UNPAID -> PAID). Both paths now share `_effective_payment_status`.
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
from invoice_core.services import invoice_service


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def _make_invoice_with_txn(
    db,
    *,
    invoice_number: str,
    amount_total: float,
    txn_amount: float,
    stored_status: _PaymentStatus,
    locked: bool,
) -> Invoice:
    sup = Supplier(name=f"Sup-{invoice_number}", tax_id=invoice_number)
    cust = Customer(name=f"Cust-{invoice_number}", tax_id=invoice_number)
    db.add_all([sup, cust])
    db.flush()

    inv = Invoice(
        invoice_number=invoice_number,
        invoice_date=date(2026, 6, 1),
        supplier_id=sup.id,
        customer_id=cust.id,
        amount_total=amount_total,
        payment_status=stored_status,
        payment_status_locked=locked,
        direction=_InvoiceDirection.INBOUND,
        currency="HUF",
    )
    db.add(inv)
    db.flush()

    txn = BankTransaction(
        transaction_id=f"B-{invoice_number}",
        bank="erste",
        direction="CREDIT",
        amount=txn_amount,
        currency="HUF",
        transaction_date=datetime(2026, 6, 3),
    )
    db.add(txn)
    db.flush()
    inv.bank_transactions.append(txn)
    db.commit()
    return inv


def test_locked_paid_invoice_with_partial_linked_txn_reports_paid_in_detail(db):
    """DEF-007 exact reproduction: invoice id 1 (GRPHT-2026-12) style case --
    manually marked PAID + locked, then a partial-amount transaction is
    manually linked. Detail must keep reporting PAID, matching the list.
    """
    inv = _make_invoice_with_txn(
        db,
        invoice_number="GRPHT-2026-12",
        amount_total=2_533_650.0,
        txn_amount=5_408.61,
        stored_status=_PaymentStatus.PAID,
        locked=True,
    )

    detail = invoice_service.get_invoice(db, inv.id)
    assert detail.payment_status == "PAID"

    rows = {r.invoice_number: r for r in invoice_service.list_invoices(db)}
    assert rows["GRPHT-2026-12"].payment_status == "PAID"


@pytest.mark.parametrize(
    "stored_status,locked,txn_amount,amount_total,expected",
    [
        # locked + partial payment -> stays at stored (PAID), matches list.
        (_PaymentStatus.PAID, True, 100.0, 1000.0, "PAID"),
        # locked + full payment -> stays at stored (PAID) either way.
        (_PaymentStatus.PAID, True, 1000.0, 1000.0, "PAID"),
        # unlocked, stored UNPAID, full payment -> legitimate upgrade to PAID.
        (_PaymentStatus.UNPAID, False, 1000.0, 1000.0, "PAID"),
        # unlocked, stored UNPAID, partial payment -> legitimate auto-derivation
        # to PARTIAL (unchanged pre-fix behaviour for the unlocked case).
        (_PaymentStatus.UNPAID, False, 400.0, 1000.0, "PARTIAL"),
    ],
)
def test_detail_and_list_report_same_status(
    db, stored_status, locked, txn_amount, amount_total, expected
):
    """The regression test that matters most: detail and list must never
    disagree about the same invoice, across locked/unlocked x
    partial/full-payment combinations.
    """
    inv = _make_invoice_with_txn(
        db,
        invoice_number="INV-MATRIX",
        amount_total=amount_total,
        txn_amount=txn_amount,
        stored_status=stored_status,
        locked=locked,
    )

    detail = invoice_service.get_invoice(db, inv.id)
    rows = {r.invoice_number: r for r in invoice_service.list_invoices(db)}

    assert detail.payment_status == expected
    assert rows["INV-MATRIX"].payment_status == expected
    assert detail.payment_status == rows["INV-MATRIX"].payment_status


def test_unlocked_invoice_still_auto_derives_partial(db):
    """Don't over-correct: an UNLOCKED invoice must still recompute its
    displayed status from linked transaction amounts, as before the fix.
    """
    inv = _make_invoice_with_txn(
        db,
        invoice_number="INV-UNLOCKED-PARTIAL",
        amount_total=1000.0,
        txn_amount=250.0,
        stored_status=_PaymentStatus.UNPAID,
        locked=False,
    )

    detail = invoice_service.get_invoice(db, inv.id)
    assert detail.payment_status == "PARTIAL"
