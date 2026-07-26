"""Regression test for the ordering bug found while revisiting plan 005 Part B.

The N+1 in get_supplier/get_customer was already fixed elsewhere (see
selectinload(Invoice.bank_transactions) in partner_service.get_supplier/
get_customer) before this plan was executed. What remained was a latent
ordering bug in _partner_invoice_rows: it picked `i.bank_transactions[0]`,
which reflects the many-to-many relationship's default order (ascending
primary key on bank_transaction, i.e. insertion/sync order), not
`transaction_date` order. An invoice whose earlier-dated transaction was
synced/inserted *before* a later-dated one would report the earlier (stale)
transaction as its "current" bank_txn_db_id/bank_txn_external_id, even though
the later-dated one represents the more recent payment.

Ruling: report the most recent payment (transaction_date desc), matching
invoice_service.list_invoices's ordering of the same concept.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from invoice_core.db import BankTransaction, Base, Invoice, Supplier, _InvoiceDirection
from invoice_core.services import partner_service


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def test_bank_txn_reported_is_latest_by_date_not_insertion_order(db):
    """An invoice with two linked transactions where insert order and date
    order disagree must report the one with the later transaction_date.
    """
    sup = Supplier(name="ACME Kft")
    db.add(sup)
    db.flush()

    inv = Invoice(
        invoice_number="INV-1",
        invoice_date=date(2026, 1, 1),
        supplier_id=sup.id,
        direction=_InvoiceDirection.OUTBOUND,
    )
    db.add(inv)
    db.flush()

    # Inserted first (lower PK) but dated EARLIER — this is the one the old,
    # buggy `i.bank_transactions[0]` code would wrongly report.
    inserted_first_dated_earlier = BankTransaction(
        transaction_id="B-EARLY-INSERT-EARLY-DATE",
        bank="wise",
        direction="CREDIT",
        amount=50.0,
        currency="HUF",
        transaction_date=datetime(2026, 1, 15),
    )
    # Inserted second (higher PK) but dated LATER — the correct answer.
    inserted_second_dated_later = BankTransaction(
        transaction_id="B-LATE-INSERT-LATE-DATE",
        bank="wise",
        direction="CREDIT",
        amount=100.0,
        currency="HUF",
        transaction_date=datetime(2026, 3, 1),
    )
    db.add_all([inserted_first_dated_earlier, inserted_second_dated_later])
    db.flush()
    inv.bank_transactions.extend([inserted_first_dated_earlier, inserted_second_dated_later])
    db.commit()

    detail = partner_service.get_supplier(db, sup.id)

    assert len(detail.invoices) == 1
    row = detail.invoices[0]
    # The later-dated transaction must win, regardless of insertion order.
    assert row.bank_txn_db_id == inserted_second_dated_later.id
    assert row.bank_txn_external_id == "B-LATE-INSERT-LATE-DATE"


def test_get_customer_also_reports_latest_by_date(db):
    """Same semantics apply to get_customer (mirrors get_supplier)."""
    from invoice_core.db import Customer

    cust = Customer(name="Vevő Kft")
    db.add(cust)
    db.flush()

    inv = Invoice(
        invoice_number="INV-2",
        invoice_date=date(2026, 1, 1),
        customer_id=cust.id,
        direction=_InvoiceDirection.INBOUND,
    )
    db.add(inv)
    db.flush()

    inserted_first_dated_earlier = BankTransaction(
        transaction_id="C-EARLY-INSERT-EARLY-DATE",
        bank="erste",
        direction="DEBIT",
        amount=75.0,
        currency="HUF",
        transaction_date=datetime(2026, 2, 1),
    )
    inserted_second_dated_later = BankTransaction(
        transaction_id="C-LATE-INSERT-LATE-DATE",
        bank="erste",
        direction="DEBIT",
        amount=200.0,
        currency="HUF",
        transaction_date=datetime(2026, 5, 1),
    )
    db.add_all([inserted_first_dated_earlier, inserted_second_dated_later])
    db.flush()
    inv.bank_transactions.extend([inserted_first_dated_earlier, inserted_second_dated_later])
    db.commit()

    detail = partner_service.get_customer(db, cust.id)

    assert len(detail.invoices) == 1
    row = detail.invoices[0]
    assert row.bank_txn_db_id == inserted_second_dated_later.id
    assert row.bank_txn_external_id == "C-LATE-INSERT-LATE-DATE"


def _count_statements(db, fn):
    """Count SQL statements issued by `fn()` against `db`'s underlying engine."""
    count = 0

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        nonlocal count
        count += 1

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)
    return count


def _seed_supplier_with_invoices(db, supplier_name: str, invoice_count: int, txns_per_invoice: int):
    sup = Supplier(name=supplier_name)
    db.add(sup)
    db.flush()
    for i in range(invoice_count):
        inv = Invoice(
            invoice_number=f"{supplier_name}-INV-{i}",
            invoice_date=date(2026, 1, 1 + i % 27),
            supplier_id=sup.id,
            direction=_InvoiceDirection.OUTBOUND,
        )
        db.add(inv)
        db.flush()
        for j in range(txns_per_invoice):
            txn = BankTransaction(
                transaction_id=f"{supplier_name}-INV-{i}-TXN-{j}",
                bank="wise",
                direction="CREDIT",
                amount=10.0,
                currency="HUF",
                transaction_date=datetime(2026, 1, 1 + (i + j) % 27),
            )
            db.add(txn)
            db.flush()
            inv.bank_transactions.append(txn)
    db.commit()
    return sup


def test_get_supplier_statement_count_stays_flat_as_invoice_count_grows(db):
    """The N+1 is gone (selectinload is in place) — confirm the statement
    count for get_supplier stays the same (5) whether the supplier has 8 or
    20 invoices, matching the investigation's measurement.
    """
    sup_small = _seed_supplier_with_invoices(db, "Small", invoice_count=8, txns_per_invoice=1)
    sup_large = _seed_supplier_with_invoices(db, "Large", invoice_count=20, txns_per_invoice=1)

    small_count = _count_statements(db, lambda: partner_service.get_supplier(db, sup_small.id))
    large_count = _count_statements(db, lambda: partner_service.get_supplier(db, sup_large.id))

    assert small_count == 5
    assert large_count == 5
