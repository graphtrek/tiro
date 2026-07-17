"""Tests for project_service — Controlling / Projektek CRUD."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base, Customer, User
from invoice_core.models import ProjectIn, ProjectUpdate
from invoice_core.services import project_service


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
    record = User(provider="google", sub="owner-sub", email="owner@example.com", name="Kozma Zoltán")
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


def test_create_project(db, customer, owner):
    record = project_service.create_project(
        db, ProjectIn(customer_id=customer.id, short_name="FVM", owner_id=owner.id, permitted_user_ids=[])
    )

    assert record.id is not None
    assert record.sequence_no == 1
    assert record.code == "IFUA - 001 - FVM"
    assert record.is_active is True


def test_create_project_increments_sequence_per_customer(db, customer, other_customer, owner):
    first = project_service.create_project(
        db, ProjectIn(customer_id=customer.id, short_name="FVM", owner_id=owner.id, permitted_user_ids=[])
    )
    second = project_service.create_project(
        db, ProjectIn(customer_id=customer.id, short_name="MUIR", owner_id=owner.id, permitted_user_ids=[])
    )
    other = project_service.create_project(
        db,
        ProjectIn(
            customer_id=other_customer.id, short_name="Money Penny", owner_id=owner.id, permitted_user_ids=[]
        ),
    )

    assert first.sequence_no == 1
    assert second.sequence_no == 2
    assert second.code == "IFUA - 002 - MUIR"
    assert other.sequence_no == 1
    assert other.code == "Graphtrek - 001 - Money Penny"


def test_create_project_sets_permitted_users(db, customer, owner, other_user):
    record = project_service.create_project(
        db,
        ProjectIn(
            customer_id=customer.id,
            short_name="FVM",
            owner_id=owner.id,
            permitted_user_ids=[owner.id, other_user.id],
        ),
    )

    assert sorted(record.permitted_user_ids) == sorted([owner.id, other_user.id])


def test_create_project_rejects_unknown_customer(db, owner):
    with pytest.raises(ValueError):
        project_service.create_project(
            db, ProjectIn(customer_id=999, short_name="FVM", owner_id=owner.id, permitted_user_ids=[])
        )


def test_create_project_rejects_unknown_owner(db, customer):
    with pytest.raises(ValueError):
        project_service.create_project(
            db, ProjectIn(customer_id=customer.id, short_name="FVM", owner_id=999, permitted_user_ids=[])
        )


def test_list_projects_orders_by_code(db, customer, other_customer, owner):
    project_service.create_project(
        db, ProjectIn(customer_id=customer.id, short_name="MUIR", owner_id=owner.id, permitted_user_ids=[])
    )
    project_service.create_project(
        db,
        ProjectIn(
            customer_id=other_customer.id, short_name="Money Penny", owner_id=owner.id, permitted_user_ids=[]
        ),
    )

    rows = project_service.list_projects(db)
    assert [r.code for r in rows] == ["Graphtrek - 001 - Money Penny", "IFUA - 001 - MUIR"]


def test_update_project_renames_and_keeps_sequence(db, customer, owner):
    created = project_service.create_project(
        db, ProjectIn(customer_id=customer.id, short_name="FVM", owner_id=owner.id, permitted_user_ids=[])
    )

    updated = project_service.update_project(
        db,
        created.id,
        ProjectUpdate(
            customer_id=customer.id,
            short_name="FVM2",
            owner_id=owner.id,
            is_active=True,
            permitted_user_ids=[],
        ),
    )

    assert updated.sequence_no == 1
    assert updated.code == "IFUA - 001 - FVM2"


def test_update_project_changing_customer_reassigns_sequence(db, customer, other_customer, owner):
    project_service.create_project(
        db, ProjectIn(customer_id=other_customer.id, short_name="Money Penny", owner_id=owner.id, permitted_user_ids=[])
    )
    created = project_service.create_project(
        db, ProjectIn(customer_id=customer.id, short_name="FVM", owner_id=owner.id, permitted_user_ids=[])
    )

    updated = project_service.update_project(
        db,
        created.id,
        ProjectUpdate(
            customer_id=other_customer.id,
            short_name="FVM",
            owner_id=owner.id,
            is_active=True,
            permitted_user_ids=[],
        ),
    )

    assert updated.sequence_no == 2
    assert updated.code == "Graphtrek - 002 - FVM"


def test_update_project_replaces_permitted_users(db, customer, owner, other_user):
    created = project_service.create_project(
        db,
        ProjectIn(
            customer_id=customer.id, short_name="FVM", owner_id=owner.id, permitted_user_ids=[owner.id]
        ),
    )

    updated = project_service.update_project(
        db,
        created.id,
        ProjectUpdate(
            customer_id=customer.id,
            short_name="FVM",
            owner_id=owner.id,
            is_active=True,
            permitted_user_ids=[other_user.id],
        ),
    )

    assert updated.permitted_user_ids == [other_user.id]


def test_update_project_rejects_code_collision(db, owner):
    # Two differently-IDed customers sharing a display name can land on the same
    # composed code — each gets its own independent per-customer sequence, so
    # nothing prevents both producing e.g. "Same Co - 001 - FVM".
    customer_a = Customer(name="Same Co")
    customer_b = Customer(name="Same Co")
    db.add_all([customer_a, customer_b])
    db.commit()

    project_service.create_project(
        db, ProjectIn(customer_id=customer_a.id, short_name="FVM", owner_id=owner.id, permitted_user_ids=[])
    )
    second = project_service.create_project(
        db, ProjectIn(customer_id=customer_b.id, short_name="MUIR", owner_id=owner.id, permitted_user_ids=[])
    )

    with pytest.raises(ValueError):
        project_service.update_project(
            db,
            second.id,
            ProjectUpdate(
                customer_id=customer_b.id,
                short_name="FVM",
                owner_id=owner.id,
                is_active=True,
                permitted_user_ids=[],
            ),
        )


def test_update_project_returns_none_when_not_found(db, customer, owner):
    result = project_service.update_project(
        db,
        999,
        ProjectUpdate(
            customer_id=customer.id, short_name="X", owner_id=owner.id, is_active=True, permitted_user_ids=[]
        ),
    )
    assert result is None


def test_delete_project_removes_row(db, customer, owner):
    created = project_service.create_project(
        db, ProjectIn(customer_id=customer.id, short_name="FVM", owner_id=owner.id, permitted_user_ids=[])
    )

    assert project_service.delete_project(db, created.id) is True
    assert project_service.list_projects(db) == []


def test_delete_project_returns_false_when_not_found(db):
    assert project_service.delete_project(db, 999) is False
