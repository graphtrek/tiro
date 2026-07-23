"""Tests for audit_service — the /ui/admin/audit trail backing store."""

from datetime import date, datetime
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import (
    ActivityType, BankTransaction, Base, Invoice, Project, Supplier, TimesheetEntry,
    _InvoiceDirection, _PaymentStatus,
)
from invoice_core.services import audit_service


@pytest.fixture
def db():
    """Fully isolated in-memory DB (finalize_record() commits, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def _request(method: str, path: str, email: str | None = "user@example.com", label: str | None = None):
    state = SimpleNamespace(user={"email": email} if email else None)
    url = SimpleNamespace(path=path)
    headers = {audit_service.LABEL_HEADER: quote(label)} if label else {}
    return SimpleNamespace(method=method, url=url, state=state, headers=headers)


def _response(status_code: int = 200):
    return SimpleNamespace(status_code=status_code)


def _run(db, method: str, path: str, status_code: int = 200, **request_kwargs):
    """Mirror the middleware: resolve the record before the mutation, act, then finalize."""
    request = _request(method, path, **request_kwargs)
    prepared = audit_service.prepare_record(db, request)
    audit_service.finalize_record(db, request, _response(status_code), prepared)


def test_record_logs_recognized_mutation(db):
    _run(db, "PATCH", "/api/v1/invoices/12")

    rows = audit_service.list_audit_log(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_email == "user@example.com"
    assert row.page == "Számlák"
    assert row.action == "update"
    assert row.status_code == 200
    assert row.label is None


def test_record_decodes_percent_encoded_label(db):
    """Hungarian ő/ű aren't valid Latin-1, so vision percent-encodes the header."""
    _run(db, "PUT", "/api/v1/invoices/12/customer", label="Vevő kapcsolása")

    rows = audit_service.list_audit_log(db)
    assert rows[0].label == "Vevő kapcsolása"


def test_record_skips_get_requests(db):
    _run(db, "GET", "/api/v1/invoices")
    assert audit_service.list_audit_log(db) == []


def test_record_skips_failed_requests(db):
    _run(db, "POST", "/api/v1/activity-types", status_code=400)
    assert audit_service.list_audit_log(db) == []


def test_record_skips_unmapped_paths(db):
    _run(db, "POST", "/api/v1/sync")
    _run(db, "POST", "/api/v1/users")
    assert audit_service.list_audit_log(db) == []


def test_record_without_authenticated_user_leaves_email_blank(db):
    sup = Supplier(name="ACME Kft")
    db.add(sup)
    db.commit()

    _run(db, "DELETE", f"/api/v1/partners/suppliers/{sup.id}", status_code=204, email=None)

    rows = audit_service.list_audit_log(db)
    assert len(rows) == 1
    assert rows[0].user_email is None
    assert rows[0].page == "Szállítók"
    assert rows[0].action == "delete"


def test_list_audit_log_filters_by_user_and_page(db):
    _run(db, "POST", "/api/v1/projects", email="a@example.com")
    _run(db, "POST", "/api/v1/activity-types", email="b@example.com")

    rows = audit_service.list_audit_log(db, user_email="a@example.com")
    assert [r.page for r in rows] == ["Projektek"]

    rows = audit_service.list_audit_log(db, page="Tevékenység típusok")
    assert [r.user_email for r in rows] == ["b@example.com"]


def test_record_resolves_invoice_number(db):
    inv = Invoice(
        invoice_number="INV-2026-001",
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.OUTBOUND,
    )
    db.add(inv)
    db.commit()

    _run(db, "PATCH", f"/api/v1/invoices/{inv.id}")

    assert audit_service.list_audit_log(db)[0].record == "INV-2026-001"


def test_record_resolves_bank_transaction_id(db):
    txn = BankTransaction(
        bank="erste", transaction_id="ERSTE-REF-77", amount=100.0, currency="HUF",
        direction="CREDIT", transaction_date=datetime(2026, 5, 1),
    )
    db.add(txn)
    db.commit()

    _run(db, "PUT", f"/api/v1/transactions/{txn.id}/supplier")

    assert audit_service.list_audit_log(db)[0].record == "ERSTE-REF-77"


def test_record_resolves_invoice_transaction_link_pair(db):
    inv = Invoice(
        invoice_number="INV-2026-002",
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.OUTBOUND,
    )
    txn = BankTransaction(
        bank="erste", transaction_id="ERSTE-REF-88", amount=100.0, currency="HUF",
        direction="CREDIT", transaction_date=datetime(2026, 5, 1),
    )
    db.add_all([inv, txn])
    db.commit()

    _run(db, "PUT", f"/api/v1/invoices/{inv.id}/transactions/{txn.id}")

    assert audit_service.list_audit_log(db)[0].record == "INV-2026-002 ↔ ERSTE-REF-88"


def test_record_survives_hard_delete(db):
    """The record's name must be captured before delete_supplier's db.delete() removes it."""
    sup = Supplier(name="ACME Kft")
    db.add(sup)
    db.commit()
    supplier_id = sup.id

    request = _request("DELETE", f"/api/v1/partners/suppliers/{supplier_id}")
    prepared = audit_service.prepare_record(db, request)

    db.delete(sup)
    db.commit()

    audit_service.finalize_record(db, request, _response(200), prepared)

    assert audit_service.list_audit_log(db)[0].record == "ACME Kft"


def test_record_resolves_activity_type_name(db):
    at = ActivityType(name="Oktatás", is_active=True)
    db.add(at)
    db.commit()

    _run(db, "PUT", f"/api/v1/activity-types/{at.id}")
    assert audit_service.list_audit_log(db)[-1].record == "Oktatás"


def test_record_resolves_project_code(db):
    from invoice_core.db import Customer, User

    cust = Customer(name="ACME Kft")
    owner = User(provider="google", sub="u1", email="owner@example.com")
    db.add_all([cust, owner])
    db.commit()
    proj = Project(customer_id=cust.id, sequence_no=1, short_name="Demo", code="DEMO-01", owner_id=owner.id)
    db.add(proj)
    db.commit()

    _run(db, "PUT", f"/api/v1/projects/{proj.id}")
    assert audit_service.list_audit_log(db)[-1].record == "DEMO-01"


def test_record_resolves_timesheet_entry_as_project_and_date(db):
    from invoice_core.db import Customer, User

    cust = Customer(name="ACME Kft")
    owner = User(provider="google", sub="u2", email="owner2@example.com")
    at = ActivityType(name="Fejlesztés", is_active=True)
    db.add_all([cust, owner, at])
    db.commit()
    proj = Project(customer_id=cust.id, sequence_no=1, short_name="Demo", code="DEMO-02", owner_id=owner.id)
    db.add(proj)
    db.commit()
    entry = TimesheetEntry(
        user_id=owner.id, project_id=proj.id, activity_type_id=at.id,
        entry_date=date(2026, 5, 12), hours=2.0,
    )
    db.add(entry)
    db.commit()

    _run(db, "DELETE", f"/api/v1/timesheet-entries/{entry.id}", status_code=204)
    assert audit_service.list_audit_log(db)[-1].record == "DEMO-02 2026-05-12"
