"""Regression tests for DEF-012: sync_all must be guarded against concurrent
runs by a DB-backed lock (see SyncLock in db.py and _acquire_sync_lock/
_release_sync_lock in service.py).

Uses SyncMode.match_only so sync_all exercises real end-to-end logic
(acquire lock -> sync_match -> release lock) without needing to mock the
NAV/PDF/bank HTTP clients -- sync_match is pure DB logic.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.config import Settings
from invoice_core.db import Base, SyncLock
from invoice_core.models import SyncMode, SyncRequest
from invoice_core.service import (
    SYNC_LOCK_ID,
    SyncInProgressError,
    sync_all,
)
from invoice_core.timeutil import utcnow


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def settings():
    return Settings(_env_file=None)


def _match_only_request() -> SyncRequest:
    return SyncRequest(
        start_date="2026-01-01", end_date="2026-01-31", sync_mode=SyncMode.match_only
    )


def test_second_concurrent_sync_is_rejected_fast_and_cleanly(session_factory, settings):
    """A sync in progress (lock row held, not stale) must cause a second
    concurrent sync attempt -- even from a different DB session, simulating a
    second request/process -- to fail immediately with a clear error, never
    queue or block.
    """
    db1 = session_factory()
    db2 = session_factory()
    try:
        # Simulate db1's sync being "in progress": manually hold the lock the
        # same way _acquire_sync_lock would, without running the full pipeline.
        db1.add(SyncLock(id=SYNC_LOCK_ID, locked_at=utcnow(), locked_by="host:123"))
        db1.commit()

        with pytest.raises(SyncInProgressError) as excinfo:
            sync_all(_match_only_request(), db2, settings)

        # Clear, Hungarian message -- per DEF-012's contract for the API/CLI layer.
        assert "folyamatban" in str(excinfo.value).lower()
    finally:
        db1.close()
        db2.close()


def test_lock_is_released_after_a_successful_sync(db, settings):
    result = sync_all(_match_only_request(), db, settings)

    assert result.bank_files_matched == 0  # empty DB, but ran successfully
    lock = db.get(SyncLock, SYNC_LOCK_ID)
    assert lock is not None
    assert lock.locked_at is None


def test_lock_is_released_after_a_sync_that_raises(db, settings, monkeypatch):
    """The lock must not be held forever if the pipeline raises an unexpected
    (uncaught) exception -- the finally around sync_all's body must still run.
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("invoice_core.service.sync_nav", _boom)

    with pytest.raises(RuntimeError):
        sync_all(
            SyncRequest(start_date="2026-01-01", end_date="2026-01-31", sync_mode=SyncMode.full),
            db,
            settings,
        )

    lock = db.get(SyncLock, SYNC_LOCK_ID)
    assert lock is not None
    assert lock.locked_at is None


def test_a_second_sync_succeeds_once_the_first_releases_the_lock(db, settings):
    sync_all(_match_only_request(), db, settings)
    # Lock released -- a subsequent sync must succeed, not be rejected.
    result = sync_all(_match_only_request(), db, settings)
    assert result.start_date == "2026-01-01"


def test_stale_lock_does_not_block_a_later_legitimate_sync(db, settings):
    """If a process dies mid-sync (killed, crashed) without reaching the
    `finally` that releases the lock, the lock row is left holding a stale
    locked_at. A later sync must self-heal by taking the lock over once it's
    older than SYNC_LOCK_STALE_SECONDS, without any manual DB intervention.
    """
    stale_time = utcnow() - timedelta(hours=2)
    db.add(SyncLock(id=SYNC_LOCK_ID, locked_at=stale_time, locked_by="dead-process:999"))
    db.commit()

    result = sync_all(_match_only_request(), db, settings)

    assert result.start_date == "2026-01-01"
    lock = db.get(SyncLock, SYNC_LOCK_ID)
    assert lock.locked_at is None  # released again after this (successful) run


def test_fresh_non_stale_lock_from_a_dead_process_still_blocks(session_factory, settings):
    """Sanity check for the stale-lock test above: a *recent* lock (not yet
    past the staleness timeout) must still block, even if we can't tell from
    the DB alone whether the process holding it is dead or genuinely still
    running -- that's the whole point of the timeout being a timeout, not an
    immediate liveness check.
    """
    db1 = session_factory()
    db2 = session_factory()
    try:
        db1.add(SyncLock(id=SYNC_LOCK_ID, locked_at=utcnow(), locked_by="host:1"))
        db1.commit()

        with pytest.raises(SyncInProgressError):
            sync_all(_match_only_request(), db2, settings)
    finally:
        db1.close()
        db2.close()
