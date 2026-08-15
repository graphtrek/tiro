"""Tests for vacation_service — Vacation Planner CRUD."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base, User
from invoice_core.models import VacationRequestIn, VacationRequestUpdate
from invoice_core.services import vacation_service


@pytest.fixture
def db():
    """Fully isolated in-memory DB (create/update commit, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


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


def _payload(user_id=None, kind="vacation", start_date=date(2026, 8, 17), end_date=date(2026, 8, 21), note=None):
    kwargs = {
        "kind": kind,
        "start_date": start_date,
        "end_date": end_date,
        "note": note,
    }
    if user_id is not None:
        return VacationRequestIn(user_id=user_id, **kwargs)
    return VacationRequestUpdate(**kwargs)


def test_create_vacation_request_success(db, owner):
    record = vacation_service.create_vacation_request(db, _payload(user_id=owner.id))

    assert record.id is not None
    assert record.user_id == owner.id
    assert record.user_name == "Kozma Zoltán"
    assert record.kind == "vacation"
    assert record.start_date == date(2026, 8, 17)
    assert record.end_date == date(2026, 8, 21)


def test_create_vacation_request_rejects_unknown_user(db):
    with pytest.raises(ValueError):
        vacation_service.create_vacation_request(db, _payload(user_id=999))


def test_create_vacation_request_rejects_end_before_start(db, owner):
    with pytest.raises(ValueError):
        vacation_service.create_vacation_request(
            db,
            _payload(
                user_id=owner.id,
                start_date=date(2026, 8, 21),
                end_date=date(2026, 8, 17),
            ),
        )


def test_create_vacation_request_allows_single_day(db, owner):
    record = vacation_service.create_vacation_request(
        db,
        _payload(user_id=owner.id, start_date=date(2026, 8, 17), end_date=date(2026, 8, 17)),
    )
    assert record.start_date == record.end_date


def test_list_vacation_requests_scoped_to_user(db, owner, other_user):
    vacation_service.create_vacation_request(db, _payload(user_id=owner.id))
    vacation_service.create_vacation_request(db, _payload(user_id=other_user.id))

    rows = vacation_service.list_vacation_requests(db, owner.id)
    assert len(rows) == 1
    assert rows[0].user_id == owner.id


def test_list_vacation_requests_without_user_id_returns_all_users(db, owner, other_user):
    vacation_service.create_vacation_request(db, _payload(user_id=owner.id))
    vacation_service.create_vacation_request(db, _payload(user_id=other_user.id))

    rows = vacation_service.list_vacation_requests(db)
    assert {row.user_id for row in rows} == {owner.id, other_user.id}


def test_update_vacation_request_changes_fields(db, owner):
    created = vacation_service.create_vacation_request(db, _payload(user_id=owner.id))

    updated = vacation_service.update_vacation_request(
        db,
        created.id,
        owner.id,
        _payload(kind="out_of_office", start_date=date(2026, 8, 18), end_date=date(2026, 8, 19), note="OOO"),
    )

    assert updated.kind == "out_of_office"
    assert updated.start_date == date(2026, 8, 18)
    assert updated.end_date == date(2026, 8, 19)
    assert updated.note == "OOO"


def test_update_vacation_request_returns_none_for_other_users_record(db, owner, other_user):
    created = vacation_service.create_vacation_request(db, _payload(user_id=owner.id))

    result = vacation_service.update_vacation_request(
        db, created.id, other_user.id, _payload()
    )

    assert result is None


def test_update_vacation_request_returns_none_when_not_found(db, owner):
    result = vacation_service.update_vacation_request(db, 999, owner.id, _payload())
    assert result is None


def test_update_vacation_request_rejects_end_before_start(db, owner):
    created = vacation_service.create_vacation_request(db, _payload(user_id=owner.id))

    with pytest.raises(ValueError):
        vacation_service.update_vacation_request(
            db,
            created.id,
            owner.id,
            _payload(start_date=date(2026, 8, 21), end_date=date(2026, 8, 17)),
        )


def test_delete_vacation_request_removes_row(db, owner):
    created = vacation_service.create_vacation_request(db, _payload(user_id=owner.id))

    assert vacation_service.delete_vacation_request(db, created.id, owner.id) is True
    assert vacation_service.list_vacation_requests(db, owner.id) == []


def test_delete_vacation_request_returns_false_when_not_owned(db, owner, other_user):
    created = vacation_service.create_vacation_request(db, _payload(user_id=owner.id))

    assert vacation_service.delete_vacation_request(db, created.id, other_user.id) is False


def test_delete_vacation_request_returns_false_when_not_found(db, owner):
    assert vacation_service.delete_vacation_request(db, 999, owner.id) is False
