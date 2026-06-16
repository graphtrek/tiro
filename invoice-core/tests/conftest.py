"""Shared fixtures for invoice-core tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base


@pytest.fixture(scope="session")
def engine():
    """In-memory SQLite engine for tests — no PostgreSQL required."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    """Fresh session per test, rolled back after."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
