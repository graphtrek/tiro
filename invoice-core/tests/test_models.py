"""Tests for Pydantic models, JDBC URL derivation, and ORM round-trips."""

from datetime import datetime

import pytest

from invoice_core.config import Settings
from invoice_core.db import Customer, Invoice, Supplier, _InvoiceDirection, _PaymentStatus
from invoice_core.models import InvoiceDirection, SyncMode, SyncRequest, SyncResponse


class TestSyncRequest:
    def test_defaults(self):
        req = SyncRequest()
        assert req.start_date is None
        assert req.end_date is None
        assert req.sync_mode is None

    def test_mode_coercion(self):
        req = SyncRequest(sync_mode="nav_only")
        assert req.sync_mode == SyncMode.nav_only

    def test_all_modes(self):
        for mode in SyncMode:
            req = SyncRequest(sync_mode=mode)
            assert req.sync_mode == mode


class TestSyncResponse:
    def test_defaults(self):
        resp = SyncResponse(start_date="2026-05-01", end_date="2026-05-31")
        assert resp.nav_invoices_synced == 0
        assert resp.pdf_files_synced == 0
        assert resp.bank_transactions_synced == 0
        assert resp.errors == []


class TestDatabaseUrl:
    def test_jdbc_strip_and_credential_injection(self):
        s = Settings(
            db_url="jdbc:postgresql://192.168.50.162:54320/invoice",
            db_user="invoice",
            db_pwd="invoice",
        )
        url = s.database_url
        assert url == "postgresql+psycopg2://invoice:invoice@192.168.50.162:54320/invoice"
        assert "jdbc:" not in url

    def test_driver_prefix_present(self):
        s = Settings(db_url="jdbc:postgresql://localhost:5432/test", db_user="u", db_pwd="p")
        assert s.database_url.startswith("postgresql+psycopg2://")

    def test_credentials_injected(self):
        s = Settings(db_url="jdbc:postgresql://host:5432/db", db_user="myuser", db_pwd="mypass")
        assert "myuser:mypass@" in s.database_url


class TestOrmModels:
    def test_supplier_insert(self, db):
        s = Supplier(name="ACME Kft.", tax_id="12345678-1-01")
        db.add(s)
        db.flush()
        assert s.id is not None
        result = db.query(Supplier).filter_by(tax_id="12345678-1-01").first()
        assert result.name == "ACME Kft."

    def test_customer_insert(self, db):
        c = Customer(name="Vevő Bt.", tax_id="87654321-2-02", payment_terms=30)
        db.add(c)
        db.flush()
        assert c.id is not None
        result = db.query(Customer).filter_by(tax_id="87654321-2-02").first()
        assert result.payment_terms == 30

    def test_invoice_insert_with_fks(self, db):
        supplier = Supplier(name="Szállító Kft.", tax_id="11111111-1-11")
        customer = Customer(name="Vevő Kft.", tax_id="22222222-2-22")
        db.add_all([supplier, customer])
        db.flush()

        inv = Invoice(
            invoice_number="INV-2026-001",
            supplier_id=supplier.id,
            customer_id=customer.id,
            payment_status=_PaymentStatus.UNPAID,
            direction=_InvoiceDirection.OUTBOUND,
        )
        db.add(inv)
        db.flush()

        result = db.query(Invoice).filter_by(invoice_number="INV-2026-001").first()
        assert result is not None
        assert result.payment_status == _PaymentStatus.UNPAID
        assert result.direction == _InvoiceDirection.OUTBOUND

    def test_invoice_inbound_direction(self, db):
        supplier = Supplier(name="Inbound Szállító", tax_id="33333333-3-33")
        customer = Customer(name="Inbound Vevő", tax_id="44444444-4-44")
        db.add_all([supplier, customer])
        db.flush()

        inv = Invoice(
            invoice_number="INV-2026-002",
            supplier_id=supplier.id,
            customer_id=customer.id,
            payment_status=_PaymentStatus.UNPAID,
            direction=_InvoiceDirection.INBOUND,
        )
        db.add(inv)
        db.flush()

        result = db.query(Invoice).filter_by(invoice_number="INV-2026-002").first()
        assert result.direction == _InvoiceDirection.INBOUND


class TestInvoiceDirection:
    def test_enum_values(self):
        assert InvoiceDirection.INBOUND == "INBOUND"
        assert InvoiceDirection.OUTBOUND == "OUTBOUND"
