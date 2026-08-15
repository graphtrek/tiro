"""Tests for user_service.upsert_user — login records saved on behalf of the auth service."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base
from invoice_core.models import UserIn
from invoice_core.services import user_service


@pytest.fixture
def db():
    """Fully isolated in-memory DB (upsert_user commits, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def test_upsert_user_creates_new_row(db):
    payload = UserIn(
        provider="google",
        sub="google-user-1",
        email="imre.tatai@graphtrek.co",
        name="Imre Tatai",
        picture="https://example.com/avatar.png",
    )
    record = user_service.upsert_user(db, payload)

    assert record.id is not None
    assert record.provider == "google"
    assert record.sub == "google-user-1"
    assert record.email == "imre.tatai@graphtrek.co"
    assert record.name == "Imre Tatai"
    assert record.last_login_at is not None


def test_upsert_user_persists_role_on_insert(db):
    payload = UserIn(
        provider="google",
        sub="google-user-1",
        email="kulso@gmail.com",
        role="read_only",
    )
    record = user_service.upsert_user(db, payload)

    assert record.role == "read_only"


def test_upsert_user_defaults_role_to_read_write(db):
    payload = UserIn(provider="google", sub="google-user-1", email="imre.tatai@graphtrek.co")
    record = user_service.upsert_user(db, payload)

    assert record.role == "read_write"


def test_upsert_user_updates_role_on_conflict(db):
    first = user_service.upsert_user(
        db,
        UserIn(
            provider="google",
            sub="google-user-1",
            email="imre.tatai@graphtrek.co",
            role="read_only",
        ),
    )
    assert first.role == "read_only"

    second = user_service.upsert_user(
        db,
        UserIn(
            provider="google",
            sub="google-user-1",
            email="imre.tatai@graphtrek.co",
            role="read_write",
        ),
    )

    assert second.id == first.id
    assert second.role == "read_write"


def test_upsert_user_updates_existing_row_by_provider_and_sub(db):
    first = user_service.upsert_user(
        db, UserIn(provider="google", sub="google-user-1", email="old@example.com", name="Old Name")
    )
    first_login = first.last_login_at

    second = user_service.upsert_user(
        db, UserIn(provider="google", sub="google-user-1", email="new@example.com", name="New Name")
    )

    assert second.id == first.id
    assert user_service.list_users(db) == [second]
    assert second.email == "new@example.com"
    assert second.name == "New Name"
    assert second.last_login_at >= first_login


def test_list_users_orders_by_last_login_desc(db):
    user_service.upsert_user(db, UserIn(provider="google", sub="u1", email="a@example.com"))
    user_service.upsert_user(db, UserIn(provider="google", sub="u2", email="b@example.com"))

    users = user_service.list_users(db)
    assert [u.sub for u in users] == ["u2", "u1"]


def test_touch_last_login_bumps_existing_user(db):
    created = user_service.upsert_user(
        db, UserIn(provider="google", sub="google-user-1", email="imre.tatai@graphtrek.co")
    )
    first_login = created.last_login_at

    user_service.touch_last_login(db, "google", "google-user-1")

    refreshed = user_service.list_users(db)[0]
    assert refreshed.id == created.id
    assert refreshed.last_login_at >= first_login


def test_touch_last_login_noop_for_unknown_user(db):
    # Should not raise or create a row for a (provider, sub) with no existing record.
    user_service.touch_last_login(db, "google", "no-such-user")
    assert user_service.list_users(db) == []
