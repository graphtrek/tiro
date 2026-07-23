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
from invoice_core.db import Base, BankTransaction, Customer, Invoice, InvoiceDetail, InvoiceLine, InvoiceVatSummary, Supplier
from invoice_core.nav_client import NavClient
from invoice_core.service import classify_bank_account, get_pending_sync_counts, sync_bank, sync_nav


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
    # Sync no longer auto-creates partners (see test_sync_nav.py), so the
    # supplier/customer must already exist — as if created manually — for
    # sync_nav to attach the NAV-enriched fields to them.
    sdb.add_all([
        Supplier(name="Supplier Kft.", tax_id="11111111-1-11"),
        Customer(name="Customer Kft.", tax_id="22222222-2-22"),
    ])
    sdb.commit()

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
        "invoice_xml": "<InvoiceData>...</InvoiceData>",
        "invoice_category": "NORMAL",
        "delivery_date": "2026-05-12",
        "currency_code": "HUF",
        "exchange_rate": 1.0,
        "invoice_appearance": "ELECTRONIC",
        "invoice_net_amount": 1000.0,
        "invoice_vat_amount": 270.0,
        "invoice_gross_amount": 1270.0,
        "lines": [
            {
                "line_number": "1",
                "line_description": "Consulting",
                "quantity": 2.0,
                "unit_of_measure": "",
                "unit_price": 500.0,
                "line_net_amount": 1000.0,
                "line_vat_rate": 0.27,
                "line_vat_amount": 270.0,
                "line_gross_amount": 1270.0,
            },
        ],
        "vat_summary": [
            {"vat_rate": 0.27, "vat_rate_net_amount": 1000.0, "vat_rate_vat_amount": 270.0},
        ],
    }

    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [digest])
    monkeypatch.setattr(
        NavClient, "get_invoice_detail",
        lambda self, invoice_number, direction, supplier_tax_number="": detail,
    )

    count, warnings = sync_nav("2026-05-01", "2026-05-31", sdb, settings)
    assert count == 1
    assert warnings == []

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

    detail_row = sdb.query(InvoiceDetail).filter_by(invoice_id=inv.id).first()
    assert detail_row is not None
    assert detail_row.supplier_name == "Supplier Kft."
    assert detail_row.supplier_tax_number == "11111111-1-11"
    assert detail_row.supplier_address == "1011 Budapest, Fő utca 1"
    assert detail_row.supplier_bank_account == "HU42117730161111101800000000"
    assert detail_row.customer_name == "Customer Kft."
    assert detail_row.customer_tax_number == "22222222-2-22"
    assert detail_row.customer_address == "1052 Budapest, Váci utca 10"
    assert detail_row.customer_bank_account == "11773016-11111018-00000000"
    assert detail_row.raw_xml == "<InvoiceData>...</InvoiceData>"
    assert detail_row.invoice_category == "NORMAL"
    assert detail_row.delivery_date == date(2026, 5, 12)
    assert detail_row.currency_code == "HUF"
    assert detail_row.exchange_rate == 1.0
    assert detail_row.invoice_appearance == "ELECTRONIC"
    assert detail_row.invoice_net_amount == 1000.0
    assert detail_row.invoice_vat_amount == 270.0
    assert detail_row.invoice_gross_amount == 1270.0

    line_rows = sdb.query(InvoiceLine).filter_by(invoice_id=inv.id).all()
    assert len(line_rows) == 1
    assert line_rows[0].line_description == "Consulting"
    assert line_rows[0].quantity == 2.0
    assert line_rows[0].line_net_amount == 1000.0

    vat_rows = sdb.query(InvoiceVatSummary).filter_by(invoice_id=inv.id).all()
    assert len(vat_rows) == 1
    assert vat_rows[0].vat_rate == 0.27
    assert vat_rows[0].vat_rate_net_amount == 1000.0
    assert vat_rows[0].vat_rate_vat_amount == 270.0


def test_sync_nav_skips_detail_fetch_when_already_enriched(sdb, settings, monkeypatch):
    """Re-syncing an invoice with payment_method AND a fully-populated detail row
    (raw_xml set — the marker _persist_invoice_detail always writes alongside the
    rest of the detail-only fields) must not call get_invoice_detail again."""
    sup = Supplier(name="Supplier Kft.", tax_id="11111111-1-11")
    cust = Customer(name="Customer Kft.", tax_id="22222222-2-22")
    sdb.add_all([sup, cust])
    sdb.flush()
    inv = Invoice(
        invoice_number="INV-100", supplier_id=sup.id, customer_id=cust.id,
        payment_method="TRANSFER", direction="OUTBOUND",
    )
    sdb.add(inv)
    sdb.flush()
    sdb.add(InvoiceDetail(invoice_id=inv.id, invoice_category="NORMAL", raw_xml="<xml/>"))
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


def test_sync_nav_backfills_detail_for_previously_enriched_invoice_missing_detail_row(sdb, settings, monkeypatch):
    """An invoice synced before this feature existed (payment_method set, no
    InvoiceDetail row) must still trigger a detail fetch so it gets backfilled."""
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
    detail = {"invoice_number": "INV-100", "invoice_category": "NORMAL"}
    calls = []
    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [digest])
    monkeypatch.setattr(
        NavClient, "get_invoice_detail",
        lambda self, *a, **kw: calls.append(1) or detail,
    )

    sync_nav("2026-05-01", "2026-05-31", sdb, settings)
    assert calls == [1]

    inv = sdb.query(Invoice).filter_by(invoice_number="INV-100").first()
    detail_row = sdb.query(InvoiceDetail).filter_by(invoice_id=inv.id).first()
    assert detail_row is not None
    assert detail_row.invoice_category == "NORMAL"


def test_sync_nav_backfills_detail_for_row_with_failed_enrichment(sdb, settings, monkeypatch):
    """An InvoiceDetail row can exist with only the partner-snapshot fields set
    (raw_xml still NULL) when a previous sync's enrichment call failed or
    returned empty — see _persist_invoice_detail's docstring. That must not be
    mistaken for "already enriched"; it must retry on the next sync."""
    sup = Supplier(name="Supplier Kft.", tax_id="11111111-1-11")
    cust = Customer(name="Customer Kft.", tax_id="22222222-2-22")
    sdb.add_all([sup, cust])
    sdb.flush()
    inv = Invoice(
        invoice_number="INV-100", supplier_id=sup.id, customer_id=cust.id,
        payment_method="TRANSFER", direction="OUTBOUND",
    )
    sdb.add(inv)
    sdb.flush()
    sdb.add(InvoiceDetail(
        invoice_id=inv.id, supplier_name="Supplier Kft.", supplier_tax_number="11111111-1-11",
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
    detail = {"invoice_number": "INV-100", "invoice_xml": "<xml/>", "supplier_address": "1011, Budapest"}
    calls = []
    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [digest])
    monkeypatch.setattr(
        NavClient, "get_invoice_detail",
        lambda self, *a, **kw: calls.append(1) or detail,
    )

    sync_nav("2026-05-01", "2026-05-31", sdb, settings)
    assert calls == [1]

    detail_row = sdb.query(InvoiceDetail).filter_by(invoice_id=inv.id).first()
    assert detail_row.raw_xml == "<xml/>"
    assert detail_row.supplier_address == "1011, Budapest"


def test_sync_nav_replaces_lines_and_vat_summary_on_resync(sdb, settings, monkeypatch):
    """InvoiceLine/InvoiceVatSummary rows are replaced (delete-then-reinsert),
    not accumulated, across successive enrichment fetches for the same invoice."""
    sup = Supplier(name="Supplier Kft.", tax_id="11111111-1-11")
    cust = Customer(name="Customer Kft.", tax_id="22222222-2-22")
    sdb.add_all([sup, cust])
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
    detail_v1 = {
        "invoice_number": "INV-100",
        "lines": [{"line_number": "1", "line_description": "Old line"}],
        "vat_summary": [{"vat_rate": 0.27, "vat_rate_net_amount": 100.0, "vat_rate_vat_amount": 27.0}],
    }
    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [digest])
    monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: detail_v1)
    sync_nav("2026-05-01", "2026-05-31", sdb, settings)

    inv = sdb.query(Invoice).filter_by(invoice_number="INV-100").first()
    assert [ln.line_description for ln in sdb.query(InvoiceLine).filter_by(invoice_id=inv.id).all()] == ["Old line"]

    # Invoice still lacks a payment_method, so the next sync fetches detail again.
    detail_v2 = {
        "invoice_number": "INV-100",
        "lines": [
            {"line_number": "1", "line_description": "New line A"},
            {"line_number": "2", "line_description": "New line B"},
        ],
        "vat_summary": [{"vat_rate": 0.05, "vat_rate_net_amount": 200.0, "vat_rate_vat_amount": 10.0}],
    }
    monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: detail_v2)
    sync_nav("2026-05-01", "2026-05-31", sdb, settings)

    lines = sdb.query(InvoiceLine).filter_by(invoice_id=inv.id).order_by(InvoiceLine.id).all()
    assert [ln.line_description for ln in lines] == ["New line A", "New line B"]

    vat_rows = sdb.query(InvoiceVatSummary).filter_by(invoice_id=inv.id).all()
    assert len(vat_rows) == 1
    assert vat_rows[0].vat_rate == 0.05


def test_sync_nav_stores_partner_snapshot_even_when_unmatched(sdb, settings, monkeypatch):
    """An invoice whose supplier/customer can't be matched locally must still
    get an invoice_detail row carrying the NAV-reported name/tax number, so
    the user knows exactly who to create — even if the full detail call
    (address/bank account) also fails."""
    monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [_unknown_partner_digest()])
    monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: {})

    sync_nav("2026-05-01", "2026-05-31", sdb, settings)

    inv = sdb.query(Invoice).filter_by(invoice_number="INV-200").first()
    assert inv.supplier_id is None
    assert inv.customer_id is None

    detail_row = sdb.query(InvoiceDetail).filter_by(invoice_id=inv.id).first()
    assert detail_row is not None
    assert detail_row.supplier_name == "Unknown Supplier Kft."
    assert detail_row.supplier_tax_number == "33333333-1-11"
    assert detail_row.customer_name == "Unknown Customer Kft."
    assert detail_row.customer_tax_number == "44444444-2-22"
    # No successful detail-call this run, so address/bank account stay unset.
    assert detail_row.supplier_address is None
    assert detail_row.supplier_bank_account is None


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

    count, warnings = sync_bank("2026-05-01", "2026-05-31", sdb, settings)
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

    count2, warnings2 = sync_bank("2026-05-01", "2026-05-31", sdb, settings)
    assert count2 == 0  # no *new* transaction, just an update
    sdb.refresh(btxn)
    assert btxn.counterparty_address == "Budapest Fő utca 1"
    assert btxn.counterparty_bank_code == "117"
    assert btxn.note == "late reconciliation"


def test_sync_bank_locked_supplier_not_overwritten_by_counterparty_fallback(sdb, settings, monkeypatch):
    """A manually cleared (locked) supplier link on an existing transaction must
    stay cleared even though the counterparty-name fallback would otherwise match."""
    sdb.add(Supplier(name="ACME Kft", tax_id="55555555-1-11"))
    sdb.commit()

    txn_dict = {
        "transaction_id": "TX-LOCKED-1",
        "bank": "erste",
        "amount": 1000.0,
        "currency": "HUF",
        "direction": "CREDIT",
        "date": "2026-05-12",
        "counterparty_name": "ACME Kft",
    }
    monkeypatch.setattr(BankClient, "get_transactions", lambda self: [dict(txn_dict)])

    sync_bank("2026-05-01", "2026-05-31", sdb, settings)
    btxn = sdb.query(BankTransaction).filter_by(transaction_id="TX-LOCKED-1").first()
    assert btxn.supplier_id is not None  # auto-matched on first sync

    # User decides this match is wrong and manually clears it — locking the field.
    btxn.supplier_id = None
    btxn.supplier_locked = True
    sdb.commit()

    sync_bank("2026-05-01", "2026-05-31", sdb, settings)
    sdb.refresh(btxn)
    assert btxn.supplier_id is None  # stays cleared despite the matching counterparty name


def _unknown_partner_digest(**overrides):
    digest = {
        "invoice_number": "INV-200",
        "invoice_issue_date": "2026-05-12",
        "supplier_tax_number": "33333333-1-11",
        "supplier_name": "Unknown Supplier Kft.",
        "customer_tax_number": "44444444-2-22",
        "customer_name": "Unknown Customer Kft.",
        "direction": "OUTBOUND",
    }
    digest.update(overrides)
    return digest


class TestSyncNavDoesNotAutoCreatePartners:
    """sync_nav must only ever link to an existing Supplier/Customer, never
    create one — manual creation (partner_service) is now the sole path.
    An invoice whose supplier/customer isn't found yet is still imported,
    just left unlinked, with a warning surfaced to the caller."""

    def test_unknown_partners_leave_invoice_unlinked_with_warning(self, sdb, settings, monkeypatch):
        monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [_unknown_partner_digest()])
        monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: {})

        count, warnings = sync_nav("2026-05-01", "2026-05-31", sdb, settings)

        assert count == 1
        assert sdb.query(Supplier).count() == 0
        assert sdb.query(Customer).count() == 0
        inv = sdb.query(Invoice).filter_by(invoice_number="INV-200").first()
        assert inv is not None
        assert inv.supplier_id is None
        assert inv.customer_id is None
        assert any("Unknown Supplier Kft." in w for w in warnings)
        assert any("Unknown Customer Kft." in w for w in warnings)

    def test_manual_placeholder_gets_tax_id_backfilled_not_duplicated(self, sdb, settings, monkeypatch):
        # Simulate a supplier created by hand before its tax number was known.
        sdb.add(Supplier(name="Unknown Supplier Kft."))
        sdb.commit()

        monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [_unknown_partner_digest()])
        monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: {})

        count, warnings = sync_nav("2026-05-01", "2026-05-31", sdb, settings)

        assert sdb.query(Supplier).count() == 1  # no duplicate created
        supplier = sdb.query(Supplier).filter_by(name="Unknown Supplier Kft.").one()
        assert supplier.tax_id == "33333333-1-11"  # backfilled
        assert not any("Unknown Supplier Kft." in w for w in warnings)  # supplier side resolved

    def test_resync_self_heals_previously_pending_invoice(self, sdb, settings, monkeypatch):
        monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [_unknown_partner_digest()])
        monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: {})

        # First run: nothing exists yet, invoice lands pending.
        sync_nav("2026-05-01", "2026-05-31", sdb, settings)
        inv = sdb.query(Invoice).filter_by(invoice_number="INV-200").first()
        assert inv.supplier_id is None
        assert inv.customer_id is None

        # User manually creates the missing partners in the meantime.
        sdb.add_all([
            Supplier(name="Unknown Supplier Kft.", tax_id="33333333-1-11"),
            Customer(name="Unknown Customer Kft.", tax_id="44444444-2-22"),
        ])
        sdb.commit()

        # Second run over the same date range: self-heals the existing invoice.
        count, warnings = sync_nav("2026-05-01", "2026-05-31", sdb, settings)

        assert count == 0  # no *new* invoice, just backfilled
        assert warnings == []
        sdb.refresh(inv)
        assert inv.supplier_id is not None
        assert inv.customer_id is not None
        assert sdb.query(Supplier).count() == 1
        assert sdb.query(Customer).count() == 1

    def test_locked_invoice_not_self_healed_even_when_partners_appear(self, sdb, settings, monkeypatch):
        monkeypatch.setattr(NavClient, "get_invoices", lambda self, start, end: [_unknown_partner_digest()])
        monkeypatch.setattr(NavClient, "get_invoice_detail", lambda self, *a, **kw: {})

        # First run: nothing exists yet, invoice lands pending.
        sync_nav("2026-05-01", "2026-05-31", sdb, settings)
        inv = sdb.query(Invoice).filter_by(invoice_number="INV-200").first()
        # User explicitly decides "no supplier/customer here" — manual clear locks it.
        inv.supplier_locked = True
        inv.customer_locked = True
        sdb.commit()

        # The missing partners show up later (e.g. created for an unrelated invoice).
        sdb.add_all([
            Supplier(name="Unknown Supplier Kft.", tax_id="33333333-1-11"),
            Customer(name="Unknown Customer Kft.", tax_id="44444444-2-22"),
        ])
        sdb.commit()

        sync_nav("2026-05-01", "2026-05-31", sdb, settings)

        sdb.refresh(inv)
        assert inv.supplier_id is None
        assert inv.customer_id is None


def test_sync_bank_unmatched_counterparty_warns_without_creating_partner(sdb, settings, monkeypatch):
    txn_dict = {
        "transaction_id": "TX-2",
        "bank": "erste",
        "amount": 500.0,
        "currency": "HUF",
        "direction": "CREDIT",
        "date": "2026-05-12",
        "counterparty_name": "Nobody Kft",
    }
    monkeypatch.setattr(BankClient, "get_transactions", lambda self: [dict(txn_dict)])

    count, warnings = sync_bank("2026-05-01", "2026-05-31", sdb, settings)

    assert count == 1
    btxn = sdb.query(BankTransaction).filter_by(transaction_id="TX-2").first()
    assert btxn.supplier_id is None
    assert btxn.customer_id is None
    # sync_bank does pre-seed one Supplier row per configured bank (for
    # fee/interest transactions) — but never one for the counterparty itself.
    assert sdb.query(Supplier).filter_by(name="Nobody Kft").first() is None
    assert sdb.query(Customer).count() == 0
    assert any("Nobody Kft" in w for w in warnings)


def test_get_pending_sync_counts(sdb, settings):
    sup = Supplier(name="ACME Kft")
    sdb.add(sup)
    sdb.flush()
    sdb.add_all([
        Invoice(invoice_number="INV-1", supplier_id=None, customer_id=None, direction="OUTBOUND"),
        Invoice(invoice_number="INV-2", supplier_id=sup.id, customer_id=None, direction="OUTBOUND"),
        Invoice(invoice_number="INV-3", supplier_id=sup.id, customer_id=sup.id, direction="OUTBOUND"),
        BankTransaction(
            bank="erste", transaction_id="TX-1", amount=100, currency="HUF", direction="CREDIT",
            transaction_date=datetime(2026, 5, 1),
        ),
        BankTransaction(
            bank="erste", transaction_id="TX-2", amount=100, currency="HUF", direction="CREDIT",
            transaction_date=datetime(2026, 5, 1), supplier_id=sup.id,
        ),
    ])
    sdb.commit()

    unmatched_invoices, unmatched_transactions = get_pending_sync_counts(sdb, settings)

    assert unmatched_invoices == 2  # INV-1 (neither) + INV-2 (missing customer)
    assert unmatched_transactions == 1  # TX-1 only; TX-2 has a supplier


def test_get_pending_sync_counts_excludes_tax_account_transactions(sdb):
    tax_account = "10032000-00290080-00000000"
    settings = Settings(_env_file=None, tax_accounts={tax_account: "NAV ÁFA"})
    sdb.add(BankTransaction(
        bank="erste", transaction_id="TX-TAX", amount=100, currency="HUF", direction="CREDIT",
        transaction_date=datetime(2026, 5, 1), counterparty_account=tax_account,
    ))
    sdb.commit()

    _, unmatched_transactions = get_pending_sync_counts(sdb, settings)

    assert unmatched_transactions == 0
