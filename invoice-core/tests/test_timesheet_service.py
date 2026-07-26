"""Tests for timesheet_service — Controlling / Timesheet CRUD."""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import ActivityType, Base, Customer, Project, User
from invoice_core.models import TimesheetEntryIn, TimesheetEntryUpdate
from invoice_core.services import timesheet_service


@pytest.fixture
def db():
    """Fully isolated in-memory DB (create/update commit, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


@pytest.fixture
def customer(db):
    record = Customer(name="IFUA")
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@pytest.fixture
def owner(db):
    record = User(
        provider="google", sub="owner-sub", email="owner@example.com", name="Kozma Zoltán"
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@pytest.fixture
def other_user(db):
    record = User(provider="google", sub="other-sub", email="other@example.com", name="Tatai Imre")
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@pytest.fixture
def project(db, customer, owner):
    record = Project(
        customer_id=customer.id,
        sequence_no=1,
        short_name="FVM",
        code="IFUA - 001 - FVM",
        owner_id=owner.id,
        is_active=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    # Fixed anchor so project_week is deterministic in tests.
    record.created_at = datetime(2026, 1, 5)
    db.commit()
    db.refresh(record)
    return record


@pytest.fixture
def activity_type(db):
    record = ActivityType(name="Szakértői munka", is_active=True)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _payload(project_id, activity_type_id, user_id=None, entry_date=date(2026, 1, 12), hours=2.0):
    kwargs = {
        "project_id": project_id,
        "activity_type_id": activity_type_id,
        "entry_date": entry_date,
        "hours": hours,
        "participants": "Kozma Zoltán",
        "description": "Specifikáció írása",
    }
    if user_id is not None:
        return TimesheetEntryIn(user_id=user_id, **kwargs)
    return TimesheetEntryUpdate(**kwargs)


def test_create_timesheet_entry_success(db, project, owner, activity_type):
    record = timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=owner.id)
    )

    assert record.id is not None
    assert record.user_name == "Kozma Zoltán"
    assert record.project_code == "IFUA - 001 - FVM"
    assert record.customer_name == "IFUA"
    assert record.activity_type_name == "Szakértői munka"


def test_create_timesheet_entry_computes_project_week(db, project, owner, activity_type):
    # 2026-01-05 (created_at) -> 2026-01-12 is exactly 7 days later -> W2.
    record = timesheet_service.create_timesheet_entry(
        db,
        _payload(project.id, activity_type.id, user_id=owner.id, entry_date=date(2026, 1, 12)),
    )

    assert record.project_week == 2


def test_create_timesheet_entry_rejects_unknown_project(db, owner, activity_type):
    with pytest.raises(ValueError):
        timesheet_service.create_timesheet_entry(
            db, _payload(999, activity_type.id, user_id=owner.id)
        )


def test_create_timesheet_entry_rejects_unknown_user(db, project, activity_type):
    with pytest.raises(ValueError):
        timesheet_service.create_timesheet_entry(
            db, _payload(project.id, activity_type.id, user_id=999)
        )


def test_create_timesheet_entry_rejects_inactive_project(db, project, owner, activity_type):
    project.is_active = False
    db.commit()

    with pytest.raises(ValueError):
        timesheet_service.create_timesheet_entry(
            db, _payload(project.id, activity_type.id, user_id=owner.id)
        )


def test_create_timesheet_entry_rejects_unpermitted_user(db, project, other_user, activity_type):
    with pytest.raises(ValueError):
        timesheet_service.create_timesheet_entry(
            db, _payload(project.id, activity_type.id, user_id=other_user.id)
        )


def test_create_timesheet_entry_allows_permitted_non_owner_user(
    db, project, other_user, activity_type
):
    project.permitted_users = [other_user]
    db.commit()

    record = timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=other_user.id)
    )

    assert record.user_id == other_user.id


def test_create_timesheet_entry_rejects_unknown_activity_type(db, project, owner):
    with pytest.raises(ValueError):
        timesheet_service.create_timesheet_entry(db, _payload(project.id, 999, user_id=owner.id))


def test_create_timesheet_entry_rejects_inactive_activity_type(db, project, owner, activity_type):
    activity_type.is_active = False
    db.commit()

    with pytest.raises(ValueError):
        timesheet_service.create_timesheet_entry(
            db, _payload(project.id, activity_type.id, user_id=owner.id)
        )


def test_create_timesheet_entry_rejects_non_half_hour_step(db, project, owner, activity_type):
    with pytest.raises(ValueError):
        timesheet_service.create_timesheet_entry(
            db, _payload(project.id, activity_type.id, user_id=owner.id, hours=1.3)
        )


def test_create_timesheet_entry_rejects_zero_or_negative_hours(db, project, owner, activity_type):
    with pytest.raises(ValueError):
        timesheet_service.create_timesheet_entry(
            db, _payload(project.id, activity_type.id, user_id=owner.id, hours=0)
        )


def test_list_timesheet_entries_scoped_to_user(db, project, owner, other_user, activity_type):
    project.permitted_users = [other_user]
    db.commit()

    timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=owner.id)
    )
    timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=other_user.id)
    )

    rows = timesheet_service.list_timesheet_entries(db, owner.id)
    assert len(rows) == 1
    assert rows[0].user_id == owner.id


def test_update_timesheet_entry_changes_fields(db, project, owner, activity_type):
    created = timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=owner.id, hours=2.0)
    )

    updated = timesheet_service.update_timesheet_entry(
        db,
        created.id,
        owner.id,
        _payload(project.id, activity_type.id, hours=3.5, entry_date=date(2026, 1, 13)),
    )

    assert updated.hours == 3.5
    assert updated.entry_date == date(2026, 1, 13)


def test_update_timesheet_entry_returns_none_for_other_users_record(
    db, project, owner, other_user, activity_type
):
    project.permitted_users = [other_user]
    db.commit()

    created = timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=owner.id)
    )

    result = timesheet_service.update_timesheet_entry(
        db, created.id, other_user.id, _payload(project.id, activity_type.id)
    )

    assert result is None


def test_update_timesheet_entry_returns_none_when_not_found(db, project, owner, activity_type):
    result = timesheet_service.update_timesheet_entry(
        db, 999, owner.id, _payload(project.id, activity_type.id)
    )
    assert result is None


def test_update_timesheet_entry_rejects_hours_step_violation(db, project, owner, activity_type):
    created = timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=owner.id)
    )

    with pytest.raises(ValueError):
        timesheet_service.update_timesheet_entry(
            db, created.id, owner.id, _payload(project.id, activity_type.id, hours=1.1)
        )


def test_delete_timesheet_entry_removes_row(db, project, owner, activity_type):
    created = timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=owner.id)
    )

    assert timesheet_service.delete_timesheet_entry(db, created.id, owner.id) is True
    assert timesheet_service.list_timesheet_entries(db, owner.id) == []


def test_delete_timesheet_entry_returns_false_when_not_owned(
    db, project, owner, other_user, activity_type
):
    created = timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=owner.id)
    )

    assert timesheet_service.delete_timesheet_entry(db, created.id, other_user.id) is False


def test_delete_timesheet_entry_returns_false_when_not_found(db, owner):
    assert timesheet_service.delete_timesheet_entry(db, 999, owner.id) is False
