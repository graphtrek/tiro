"""Tests for timesheet_service — Controlling / Timesheet CRUD."""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import ActivityType, Base, Customer, Project, User, _ProjectStatus
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
        start_date=date(2026, 1, 1),
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
    # The project's created_at (2026-01-05) predates any real work — project_week
    # must anchor to the first *logged entry*, not the project row's creation time,
    # since entries can be (and typically are) backdated before the project record
    # itself exists in the system.
    first = timesheet_service.create_timesheet_entry(
        db,
        _payload(project.id, activity_type.id, user_id=owner.id, entry_date=date(2026, 1, 12)),
    )
    assert first.project_week == 1

    # 2026-01-12 (first entry) -> 2026-01-19 is exactly 7 days later -> W2.
    second = timesheet_service.create_timesheet_entry(
        db,
        _payload(project.id, activity_type.id, user_id=owner.id, entry_date=date(2026, 1, 19)),
    )
    assert second.project_week == 2


def test_project_week_uses_calendar_weeks_not_rolling_window(db, project, owner, activity_type):
    # First entry on a Friday (2026-01-16) -> anchors W1 to that calendar week
    # (Mon 2026-01-12 - Sun 2026-01-18).
    first = timesheet_service.create_timesheet_entry(
        db,
        _payload(project.id, activity_type.id, user_id=owner.id, entry_date=date(2026, 1, 16)),
    )
    assert first.project_week == 1

    # The very next Monday (2026-01-19) is only 3 days later, but it falls in the
    # next calendar week -> W2, not W1 (a rolling 7-day window would say W1).
    monday_after = timesheet_service.create_timesheet_entry(
        db,
        _payload(project.id, activity_type.id, user_id=owner.id, entry_date=date(2026, 1, 19)),
    )
    assert monday_after.project_week == 2

    # 2026-01-26 is a further calendar week later -> W3.
    week_three = timesheet_service.create_timesheet_entry(
        db,
        _payload(project.id, activity_type.id, user_id=owner.id, entry_date=date(2026, 1, 26)),
    )
    assert week_three.project_week == 3


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


def test_create_timesheet_entry_rejects_closed_project(db, project, owner, activity_type):
    project.status = _ProjectStatus.CLOSED
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


def test_list_timesheet_entries_without_user_id_returns_all_users(
    db, project, owner, other_user, activity_type
):
    project.permitted_users = [other_user]
    db.commit()

    timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=owner.id)
    )
    timesheet_service.create_timesheet_entry(
        db, _payload(project.id, activity_type.id, user_id=other_user.id)
    )

    rows = timesheet_service.list_timesheet_entries(db)
    assert {row.user_id for row in rows} == {owner.id, other_user.id}


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
