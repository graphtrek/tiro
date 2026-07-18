"""An invoice with no matched supplier/customer must still show up in
list_invoices()/get_invoice() (outer join, not inner join) — sync no longer
auto-creates a partner for an unmatched NAV digest, so `supplier_id`/
`customer_id` can legitimately be NULL and the invoice must not be silently
dropped from these views.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base, Customer, Invoice, Supplier, _InvoiceDirection
from invoice_core.services import invoice_service


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def test_list_invoices_includes_invoice_with_no_partner(db):
    db.add(Invoice(
        invoice_number="INV-PENDING", supplier_id=None, customer_id=None,
        direction=_InvoiceDirection.OUTBOUND,
    ))
    db.commit()

    rows = invoice_service.list_invoices(db)

    assert len(rows) == 1
    assert rows[0].supplier_id is None
    assert rows[0].supplier_name is None
    assert rows[0].customer_id is None
    assert rows[0].customer_name is None


def test_list_invoices_includes_invoice_with_only_supplier_matched(db):
    sup = Supplier(name="ACME Kft")
    db.add(sup)
    db.flush()
    db.add(Invoice(
        invoice_number="INV-PARTIAL", supplier_id=sup.id, customer_id=None,
        direction=_InvoiceDirection.OUTBOUND,
    ))
    db.commit()

    rows = invoice_service.list_invoices(db)

    assert len(rows) == 1
    assert rows[0].supplier_name == "ACME Kft"
    assert rows[0].customer_id is None
    assert rows[0].customer_name is None


def test_get_invoice_returns_detail_with_no_partner(db):
    inv = Invoice(
        invoice_number="INV-PENDING", supplier_id=None, customer_id=None,
        direction=_InvoiceDirection.OUTBOUND,
    )
    db.add(inv)
    db.commit()

    detail = invoice_service.get_invoice(db, inv.id)

    assert detail is not None
    assert detail.supplier_id is None
    assert detail.supplier_name is None
    assert detail.supplier_tax_id is None
    assert detail.customer_id is None
    assert detail.customer_name is None
    assert detail.customer_tax_id is None
