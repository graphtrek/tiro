"""Tests for the NAV/bank field-enrichment sync logic.

Covers: classify_bank_account(), sync_nav() persisting address/iban/bban/
payment fields (only fetching detail when needed), and sync_bank() persisting
+ re-syncing the new BankTransaction fields.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.bank_client import BankClient
from invoice_core.config import Settings
from invoice_core.db import Base, BankTransaction, Customer, Invoice, Supplier
from invoice_core.nav_client import NavClient
from invoice_core.service import classify_bank_account, sync_bank, sync_nav


@pytest.fixture
def sdb():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


@pytest.fixture
def settings():
    return Settings(_env_file=None)


class TestClassifyBankAccount:
    def test_iban(self):
        assert classify_bank_account("HU42117730161111101800000000") == (
            "HU42117730161111101800000000", None
        )

    def test_bban(self):
        assert classify_bank_account("11773016-11111018-00000000") == (
            None, "11773016-11111018-00000000",
        )

    def test_empty(self):
        assert classify_bank_account("") == (None, None)
        assert classify_bank_account(None) == (None, None)


def test_sync_nav_persists_enriched_fields(sdb, settings, monkeypatch):
    digest = {
        "invoice_number": "INV-100",
        "invoice_issue_date": "2026-05-12",
        "supplier_tax_number": "11111111-1-11",
        "supplier_name": "Supplier Kft.",
        "customer_tax_number": "22222222-2-22",
        "customer_name": "Customer Kft.",
        "invoice_net_amount": 1000.0,
        "invoice_vat_amount": 270.0,
        "currency": "HUF",
        "invoice_operation": "CREATE",
        "invoice_category": "NORMAL",
        "ins_date": "2026-05-12T10:00:00",
        "direction": "OUTBOUND",
    }
    detail = {
        "invoice_number": "INV-100",
        "supplier_address": "1011 Budapest, Fő utca 1",
        "supplier_bank_account": "HU42117730161111101800000000",
        "customer_address": "1052 Budapest, Váci utca 10",
        "customer_bank_account": "11773016-11111018-00000000",
        "payment_method": "TRANSFER",
        "payment_due_date": "2026-05-26",
    }

    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [digest])
    monkeypatch.setattr(
        NavClient, "get_invoice_detail",
        lambda self, invoice_number, direction, supplier_tax_number="": detail,
    )

    count = sync_nav("2026-05-01", "2026-05-31", sdb, settings)
    assert count == 1

    inv = sdb.query(Invoice).filter_by(invoice_number="INV-100").first()
    assert inv is not None
    assert inv.payment_method == "TRANSFER"
    assert inv.payment_due_date == date(2026, 5, 26)

    supplier = sdb.query(Supplier).filter_by(tax_id="11111111-1-11").first()
    assert supplier.address == "1011 Budapest, Fő utca 1"
    assert supplier.iban == "HU42117730161111101800000000"
    assert supplier.bban is None

    customer = sdb.query(Customer).filter_by(tax_id="22222222-2-22").first()
    assert customer.address == "1052 Budapest, Váci utca 10"
    assert customer.bban == "11773016-11111018-00000000"
    assert customer.iban is None


def test_sync_nav_skips_detail_fetch_when_already_enriched(sdb, settings, monkeypatch):
    """Re-syncing an invoice that already has payment_method must not call get_invoice_detail again."""
    sup = Supplier(name="Supplier Kft.", tax_id="11111111-1-11")
    cust = Customer(name="Customer Kft.", tax_id="22222222-2-22")
    sdb.add_all([sup, cust])
    sdb.flush()
    sdb.add(Invoice(
        invoice_number="INV-100", supplier_id=sup.id, customer_id=cust.id,
        payment_method="TRANSFER", direction="OUTBOUND",
    ))
    sdb.commit()

    digest = {
        "invoice_number": "INV-100",
        "invoice_issue_date": "2026-05-12",
        "supplier_tax_number": "11111111-1-11",
        "supplier_name": "Supplier Kft.",
        "customer_tax_number": "22222222-2-22",
        "customer_name": "Customer Kft.",
        "direction": "OUTBOUND",
    }
    calls = []
    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [digest])
    monkeypatch.setattr(
        NavClient, "get_invoice_detail",
        lambda self, *a, **kw: calls.append(1) or None,
    )

    sync_nav("2026-05-01", "2026-05-31", sdb, settings)
    assert calls == []


def test_sync_bank_persists_new_fields_and_updates_existing(sdb, settings, monkeypatch):
    txn_dict = {
        "transaction_id": "TX-1",
        "bank": "erste",
        "amount": 1000.0,
        "currency": "HUF",
        "direction": "CREDIT",
        "date": "2026-05-12",
        "counterparty_name": "ACME Kft",
        "counterparty_address": None,
        "sender_address": None,
        "counterparty_bank_code": None,
        "exchange_rate": None,
        "exchange_to_currency": None,
        "card_last_four": None,
        "note": None,
    }
    monkeypatch.setattr(BankClient, "get_transactions", lambda self: [dict(txn_dict)])

    count = sync_bank("2026-05-01", "2026-05-31", sdb, settings)
    assert count == 1
    btxn = sdb.query(BankTransaction).filter_by(transaction_id="TX-1").first()
    assert btxn.counterparty_address is None

    # Re-sync: the bank service now returns richer data for the same transaction_id
    enriched = dict(txn_dict)
    enriched.update({
        "counterparty_address": "Budapest Fő utca 1",
        "counterparty_bank_code": "117",
        "note": "late reconciliation",
    })
    monkeypatch.setattr(BankClient, "get_transactions", lambda self: [enriched])

    count2 = sync_bank("2026-05-01", "2026-05-31", sdb, settings)
    assert count2 == 0  # no *new* transaction, just an update
    sdb.refresh(btxn)
    assert btxn.counterparty_address == "Budapest Fő utca 1"
    assert btxn.counterparty_bank_code == "117"
    assert btxn.note == "late reconciliation"
