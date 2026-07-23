"""Tests for audit_service — the /ui/admin/audit trail backing store."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base
from invoice_core.services import audit_service


@pytest.fixture
def db():
    """Fully isolated in-memory DB (record() commits, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def _request(method: str, path: str, email: str | None = "user@example.com"):
    state = SimpleNamespace(user={"email": email} if email else None)
    url = SimpleNamespace(path=path)
    return SimpleNamespace(method=method, url=url, state=state)


def _response(status_code: int = 200):
    return SimpleNamespace(status_code=status_code)


def test_record_logs_recognized_mutation(db):
    audit_service.record(db, _request("PATCH", "/api/v1/invoices/12"), _response(200))

    rows = audit_service.list_audit_log(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_email == "user@example.com"
    assert row.page == "Számlák"
    assert row.action == "update"
    assert row.status_code == 200


def test_record_skips_get_requests(db):
    audit_service.record(db, _request("GET", "/api/v1/invoices"), _response(200))
    assert audit_service.list_audit_log(db) == []


def test_record_skips_failed_requests(db):
    audit_service.record(db, _request("POST", "/api/v1/activity-types"), _response(400))
    assert audit_service.list_audit_log(db) == []


def test_record_skips_unmapped_paths(db):
    audit_service.record(db, _request("POST", "/api/v1/sync"), _response(200))
    audit_service.record(db, _request("POST", "/api/v1/users"), _response(200))
    assert audit_service.list_audit_log(db) == []


def test_record_without_authenticated_user_leaves_email_blank(db):
    audit_service.record(db, _request("DELETE", "/api/v1/partners/suppliers/5", email=None), _response(204))

    rows = audit_service.list_audit_log(db)
    assert len(rows) == 1
    assert rows[0].user_email is None
    assert rows[0].page == "Szállítók"
    assert rows[0].action == "delete"


def test_list_audit_log_filters_by_user_and_page(db):
    audit_service.record(db, _request("POST", "/api/v1/projects", email="a@example.com"), _response(200))
    audit_service.record(db, _request("POST", "/api/v1/activity-types", email="b@example.com"), _response(200))

    rows = audit_service.list_audit_log(db, user_email="a@example.com")
    assert [r.page for r in rows] == ["Projektek"]

    rows = audit_service.list_audit_log(db, page="Tevékenység típusok")
    assert [r.user_email for r in rows] == ["b@example.com"]
