"""Tests for activity_type_service — admin master data CRUD."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base
from invoice_core.models import ActivityTypeIn, ActivityTypeUpdate
from invoice_core.services import activity_type_service


@pytest.fixture
def db():
    """Fully isolated in-memory DB (create/update commit, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def test_create_activity_type(db):
    record = activity_type_service.create_activity_type(db, ActivityTypeIn(name="Ügyfél megbeszélés"))

    assert record.id is not None
    assert record.name == "Ügyfél megbeszélés"
    assert record.is_active is True


def test_create_rejects_duplicate_name_case_insensitive(db):
    activity_type_service.create_activity_type(db, ActivityTypeIn(name="Utazás"))

    with pytest.raises(ValueError):
        activity_type_service.create_activity_type(db, ActivityTypeIn(name="utazás"))


def test_list_activity_types_orders_by_name(db):
    activity_type_service.create_activity_type(db, ActivityTypeIn(name="Szakértői munka"))
    activity_type_service.create_activity_type(db, ActivityTypeIn(name="Belsős megbeszélés"))

    rows = activity_type_service.list_activity_types(db)
    assert [r.name for r in rows] == ["Belsős megbeszélés", "Szakértői munka"]


def test_update_activity_type_renames_and_toggles_status(db):
    created = activity_type_service.create_activity_type(db, ActivityTypeIn(name="Oktatás"))

    updated = activity_type_service.update_activity_type(
        db, created.id, ActivityTypeUpdate(name="Oktatás (átnevezve)", is_active=False)
    )

    assert updated.id == created.id
    assert updated.name == "Oktatás (átnevezve)"
    assert updated.is_active is False


def test_update_rejects_duplicate_name(db):
    first = activity_type_service.create_activity_type(db, ActivityTypeIn(name="Első"))
    second = activity_type_service.create_activity_type(db, ActivityTypeIn(name="Második"))

    with pytest.raises(ValueError):
        activity_type_service.update_activity_type(
            db, second.id, ActivityTypeUpdate(name="Első", is_active=True)
        )


def test_update_returns_none_when_not_found(db):
    result = activity_type_service.update_activity_type(
        db, 999, ActivityTypeUpdate(name="Nincs ilyen", is_active=True)
    )
    assert result is None


def test_delete_activity_type_removes_row(db):
    created = activity_type_service.create_activity_type(db, ActivityTypeIn(name="Törlendő"))

    assert activity_type_service.delete_activity_type(db, created.id) is True
    assert activity_type_service.list_activity_types(db) == []


def test_delete_returns_false_when_not_found(db):
    assert activity_type_service.delete_activity_type(db, 999) is False
