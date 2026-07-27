"""Tests for report_service — Controlling / Reports."""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import ActivityType, Base, Customer, Project, User
from invoice_core.models import TimesheetEntryIn
from invoice_core.services import report_service, timesheet_service


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
def other_customer(db):
    record = Customer(name="Graphtrek")
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
def other_project(db, other_customer, owner):
    record = Project(
        customer_id=other_customer.id,
        sequence_no=1,
        short_name="MP",
        code="Graphtrek - 001 - MP",
        owner_id=owner.id,
        start_date=date(2026, 1, 1),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
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


@pytest.fixture
def other_activity_type(db):
    record = ActivityType(name="Ügyfél megbeszélés", is_active=True)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _entry(project_id, activity_type_id, user_id, entry_date, hours, participants=None):
    return TimesheetEntryIn(
        user_id=user_id,
        project_id=project_id,
        activity_type_id=activity_type_id,
        entry_date=entry_date,
        hours=hours,
        participants=participants,
    )


def test_get_project_report_groups_by_week_with_cumulative_and_pivot(
    db, project, owner, activity_type, other_activity_type
):
    # created_at anchor 2026-01-05 -> 2026-01-05 is W1, 2026-01-12 (day 7) is W2.
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, other_activity_type.id, owner.id, date(2026, 1, 6), 1.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 12), 3.0)
    )

    report = report_service.get_project_report(db, project.id)

    assert report.project_code == "IFUA - 001 - FVM"
    assert report.customer_name == "IFUA"
    assert report.activity_type_names == ["Szakértői munka", "Ügyfél megbeszélés"]
    assert [w.project_week for w in report.weeks] == [1, 2]

    week1, week2 = report.weeks
    assert week1.week_hours == 3.0
    assert week1.cumulative_hours == 3.0
    assert week1.by_activity_type == {"Szakértői munka": 2.0, "Ügyfél megbeszélés": 1.0}

    assert week2.week_hours == 3.0
    assert week2.cumulative_hours == 6.0
    assert week2.by_activity_type == {"Szakértői munka": 3.0}

    assert report.total_hours == 6.0


def test_get_project_report_filters_by_activity_type(
    db, project, owner, activity_type, other_activity_type
):
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, other_activity_type.id, owner.id, date(2026, 1, 5), 1.0)
    )

    report = report_service.get_project_report(db, project.id, activity_type_id=activity_type.id)

    assert report.activity_type_names == ["Szakértői munka"]
    assert report.total_hours == 2.0


def test_get_project_report_filters_by_date_range(db, project, owner, activity_type):
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 12), 3.0)
    )

    report = report_service.get_project_report(
        db, project.id, date_from=date(2026, 1, 10), date_to=date(2026, 1, 20)
    )

    assert [w.project_week for w in report.weeks] == [2]
    assert report.total_hours == 3.0


def test_get_project_report_filters_by_user(db, project, owner, other_user, activity_type):
    project.permitted_users = [other_user]
    db.commit()

    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, other_user.id, date(2026, 1, 5), 5.0)
    )

    report = report_service.get_project_report(db, project.id, user_id=owner.id)

    assert report.total_hours == 2.0


def test_get_project_report_empty_when_no_entries(db, project):
    report = report_service.get_project_report(db, project.id)

    assert report.weeks == []
    assert report.total_hours == 0.0
    assert report.activity_type_names == []


def test_get_group_report_person_totals_and_pivot(
    db, project, owner, other_user, activity_type, other_activity_type
):
    project.permitted_users = [other_user]
    db.commit()

    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, other_activity_type.id, owner.id, date(2026, 1, 6), 1.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, other_user.id, date(2026, 1, 5), 4.0)
    )

    report = report_service.get_group_report(db, "person")

    assert report.group_by == "person"
    assert report.activity_type_names == ["Szakértői munka", "Ügyfél megbeszélés"]
    assert report.total_hours == 7.0

    by_label = {row.key_label: row for row in report.rows}
    assert by_label["Kozma Zoltán"].total_hours == 3.0
    assert by_label["Kozma Zoltán"].entry_count == 2
    assert by_label["Kozma Zoltán"].by_activity_type == {
        "Szakértői munka": 2.0,
        "Ügyfél megbeszélés": 1.0,
    }
    assert by_label["Tatai Imre"].total_hours == 4.0
    assert by_label["Tatai Imre"].entry_count == 1

    # Sorted alphabetically by label.
    assert [row.key_label for row in report.rows] == ["Kozma Zoltán", "Tatai Imre"]


def test_get_group_report_customer_totals(db, project, other_project, owner, activity_type):
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(other_project.id, activity_type.id, owner.id, date(2026, 1, 5), 5.0)
    )

    report = report_service.get_group_report(db, "customer")

    by_label = {row.key_label: row for row in report.rows}
    assert by_label["IFUA"].total_hours == 2.0
    assert by_label["Graphtrek"].total_hours == 5.0
    assert report.total_hours == 7.0


def test_get_group_report_activity_type_has_no_pivot(
    db, project, owner, activity_type, other_activity_type
):
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, other_activity_type.id, owner.id, date(2026, 1, 5), 1.0)
    )

    report = report_service.get_group_report(db, "activity_type")

    assert report.activity_type_names == []
    for row in report.rows:
        assert row.by_activity_type == {}
    assert {row.key_label for row in report.rows} == {"Szakértői munka", "Ügyfél megbeszélés"}


def test_get_group_report_filters_by_customer(
    db, project, other_project, owner, customer, activity_type
):
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(other_project.id, activity_type.id, owner.id, date(2026, 1, 5), 5.0)
    )

    report = report_service.get_group_report(db, "person", customer_id=customer.id)

    assert report.total_hours == 2.0


def test_get_group_report_empty_when_no_entries(db):
    report = report_service.get_group_report(db, "person")

    assert report.rows == []
    assert report.entries == []
    assert report.total_hours == 0.0


def test_get_group_report_entries_list_detail_rows(
    db, project, owner, other_user, activity_type, other_activity_type
):
    project.permitted_users = [other_user]
    db.commit()

    timesheet_service.create_timesheet_entry(
        db,
        _entry(
            project.id,
            activity_type.id,
            owner.id,
            date(2026, 1, 5),
            2.0,
            participants="Kovács Béla",
        ),
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, other_activity_type.id, other_user.id, date(2026, 1, 6), 1.5)
    )

    report = report_service.get_group_report(db, "person")

    assert len(report.entries) == 2
    row = next(r for r in report.entries if r.user_name == "Kozma Zoltán")
    assert row.entry_date == "2026-01-05"
    assert row.weekday == "hétfő"
    assert row.project_week == 1
    assert row.project_code == "IFUA - 001 - FVM"
    assert row.customer_name == "IFUA"
    assert row.activity_type_name == "Szakértői munka"
    assert row.participants == "Kovács Béla"
    assert row.hours == 2.0

    other_row = next(r for r in report.entries if r.user_name == "Tatai Imre")
    assert other_row.entry_date == "2026-01-06"
    assert other_row.weekday == "kedd"
    assert other_row.participants == ""


def test_get_group_report_entries_respect_filters(
    db, project, other_project, owner, customer, activity_type
):
    timesheet_service.create_timesheet_entry(
        db, _entry(project.id, activity_type.id, owner.id, date(2026, 1, 5), 2.0)
    )
    timesheet_service.create_timesheet_entry(
        db, _entry(other_project.id, activity_type.id, owner.id, date(2026, 1, 5), 5.0)
    )

    report = report_service.get_group_report(db, "person", customer_id=customer.id)

    assert len(report.entries) == 1
    assert report.entries[0].customer_name == "IFUA"
