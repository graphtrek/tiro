"""Tests for partner_service — manual create/edit/delete of suppliers & customers."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base, Customer, Invoice, Supplier
from invoice_core.models import CustomerIn, CustomerUpdate, SupplierIn, SupplierUpdate
from invoice_core.services import partner_service


@pytest.fixture
def db():
    """Fully isolated in-memory DB (create/update commit, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


# ── Suppliers ────────────────────────────────────────────────────────────────


def test_create_supplier(db):
    record = partner_service.create_supplier(db, SupplierIn(name="ACME Kft", tax_id="12345678-1-42"))

    assert record.id is not None
    assert record.name == "ACME Kft"
    assert record.tax_id == "12345678-1-42"


def test_create_supplier_allows_blank_tax_id(db):
    record = partner_service.create_supplier(db, SupplierIn(name="ACME Kft"))

    assert record.tax_id is None


def test_create_supplier_rejects_duplicate_name_case_insensitive(db):
    partner_service.create_supplier(db, SupplierIn(name="ACME Kft"))

    with pytest.raises(ValueError):
        partner_service.create_supplier(db, SupplierIn(name="acme kft"))


def test_create_supplier_rejects_duplicate_tax_id(db):
    partner_service.create_supplier(db, SupplierIn(name="ACME Kft", tax_id="12345678-1-42"))

    with pytest.raises(ValueError):
        partner_service.create_supplier(db, SupplierIn(name="Other Kft", tax_id="12345678-1-42"))


def test_create_supplier_allows_multiple_blank_tax_ids(db):
    partner_service.create_supplier(db, SupplierIn(name="Első"))
    second = partner_service.create_supplier(db, SupplierIn(name="Második"))

    assert second.id is not None


def test_update_supplier_edits_fields(db):
    created = partner_service.create_supplier(db, SupplierIn(name="ACME Kft"))

    updated = partner_service.update_supplier(
        db, created.id, SupplierUpdate(name="ACME Kft", address="Fő utca 1", iban="HU00")
    )

    assert updated.address == "Fő utca 1"
    assert updated.iban == "HU00"


def test_update_supplier_rejects_duplicate_name(db):
    partner_service.create_supplier(db, SupplierIn(name="Első"))
    second = partner_service.create_supplier(db, SupplierIn(name="Második"))

    with pytest.raises(ValueError):
        partner_service.update_supplier(db, second.id, SupplierUpdate(name="Első"))


def test_update_supplier_returns_none_when_not_found(db):
    result = partner_service.update_supplier(db, 999, SupplierUpdate(name="Nincs ilyen"))
    assert result is None


def test_delete_supplier_removes_row(db):
    created = partner_service.create_supplier(db, SupplierIn(name="Törlendő"))

    assert partner_service.delete_supplier(db, created.id) is True
    assert partner_service.list_suppliers(db) == []


def test_delete_supplier_returns_false_when_not_found(db):
    assert partner_service.delete_supplier(db, 999) is False


def test_delete_supplier_blocked_when_linked_to_invoice(db):
    supplier = partner_service.create_supplier(db, SupplierIn(name="ACME Kft"))
    customer = partner_service.create_customer(db, CustomerIn(name="Vevő Kft"))
    db.add(Invoice(invoice_number="INV-1", supplier_id=supplier.id, customer_id=customer.id))
    db.commit()

    with pytest.raises(ValueError):
        partner_service.delete_supplier(db, supplier.id)


# ── Customers ────────────────────────────────────────────────────────────────


def test_create_customer(db):
    record = partner_service.create_customer(db, CustomerIn(name="Vevő Kft", payment_terms=30))

    assert record.id is not None
    assert record.payment_terms == 30


def test_create_customer_rejects_duplicate_name_case_insensitive(db):
    partner_service.create_customer(db, CustomerIn(name="Vevő Kft"))

    with pytest.raises(ValueError):
        partner_service.create_customer(db, CustomerIn(name="vevő kft"))


def test_create_customer_rejects_duplicate_tax_id(db):
    partner_service.create_customer(db, CustomerIn(name="Vevő Kft", tax_id="87654321-1-42"))

    with pytest.raises(ValueError):
        partner_service.create_customer(db, CustomerIn(name="Más Kft", tax_id="87654321-1-42"))


def test_update_customer_edits_fields(db):
    created = partner_service.create_customer(db, CustomerIn(name="Vevő Kft"))

    updated = partner_service.update_customer(
        db, created.id, CustomerUpdate(name="Vevő Kft", payment_terms=14)
    )

    assert updated.payment_terms == 14


def test_update_customer_returns_none_when_not_found(db):
    result = partner_service.update_customer(db, 999, CustomerUpdate(name="Nincs ilyen"))
    assert result is None


def test_delete_customer_removes_row(db):
    created = partner_service.create_customer(db, CustomerIn(name="Törlendő"))

    assert partner_service.delete_customer(db, created.id) is True
    assert partner_service.list_customers(db) == []


def test_delete_customer_returns_false_when_not_found(db):
    assert partner_service.delete_customer(db, 999) is False


def test_delete_customer_blocked_when_linked_to_invoice(db):
    supplier = partner_service.create_supplier(db, SupplierIn(name="ACME Kft"))
    customer = partner_service.create_customer(db, CustomerIn(name="Vevő Kft"))
    db.add(Invoice(invoice_number="INV-1", supplier_id=supplier.id, customer_id=customer.id))
    db.commit()

    with pytest.raises(ValueError):
        partner_service.delete_customer(db, customer.id)
