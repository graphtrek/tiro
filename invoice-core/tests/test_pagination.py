"""Pagination (limit/offset) for the two read-path list endpoints that
currently return the entire table with no bound: invoice_service.list_invoices
and invoice_file_service.list_invoice_files.

See plans/005-invoice-core-read-path-performance.md, Part A.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base, Invoice, InvoiceFile, _InvoiceDirection
from invoice_core.services import invoice_file_service, invoice_service


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def _seed_invoices(db, count: int) -> list[Invoice]:
    """Create `count` invoices with strictly increasing invoice_date, so
    the default ordering (invoice_date desc, id desc) is unambiguous.
    """
    base = date(2026, 1, 1)
    invoices = []
    for i in range(count):
        inv = Invoice(
            invoice_number=f"INV-{i:03d}",
            invoice_date=base + timedelta(days=i),
            direction=_InvoiceDirection.OUTBOUND,
        )
        db.add(inv)
        invoices.append(inv)
    db.commit()
    return invoices


def _seed_invoice_files(db, count: int) -> list[InvoiceFile]:
    base = datetime(2026, 1, 1)
    files = []
    for i in range(count):
        f = InvoiceFile(
            filename=f"file-{i:03d}.pdf",
            created_at=base + timedelta(days=i),
        )
        db.add(f)
        files.append(f)
    db.commit()
    return files


# ── invoice_service.list_invoices ────────────────────────────────────────────


def test_list_invoices_default_limit_returns_everything_under_1000(db):
    _seed_invoices(db, 5)
    rows = invoice_service.list_invoices(db)
    assert len(rows) == 5


def test_list_invoices_limit_returns_exactly_that_many(db):
    _seed_invoices(db, 5)
    rows = invoice_service.list_invoices(db, limit=2)
    assert len(rows) == 2
    # Default order is invoice_date desc, so the first page is the two
    # most recently dated invoices.
    assert [r.invoice_number for r in rows] == ["INV-004", "INV-003"]


def test_list_invoices_offset_returns_next_page_without_overlap(db):
    _seed_invoices(db, 5)
    page1 = invoice_service.list_invoices(db, limit=2, offset=0)
    page2 = invoice_service.list_invoices(db, limit=2, offset=2)

    assert [r.invoice_number for r in page1] == ["INV-004", "INV-003"]
    assert [r.invoice_number for r in page2] == ["INV-002", "INV-001"]
    assert {r.id for r in page1}.isdisjoint({r.id for r in page2})


def test_list_invoices_offset_past_end_returns_empty(db):
    _seed_invoices(db, 3)
    rows = invoice_service.list_invoices(db, limit=2, offset=10)
    assert rows == []


# ── invoice_file_service.list_invoice_files ──────────────────────────────────
# No prior test coverage existed for this function at all.


def test_list_invoice_files_default_limit_returns_everything_under_1000(db):
    _seed_invoice_files(db, 5)
    rows = invoice_file_service.list_invoice_files(db)
    assert len(rows) == 5


def test_list_invoice_files_limit_returns_exactly_that_many(db):
    _seed_invoice_files(db, 5)
    rows = invoice_file_service.list_invoice_files(db, limit=2)
    assert len(rows) == 2
    # Default order is created_at desc, so the first page is the two
    # most recently created files.
    assert [r.filename for r in rows] == ["file-004.pdf", "file-003.pdf"]


def test_list_invoice_files_offset_returns_next_page_without_overlap(db):
    _seed_invoice_files(db, 5)
    page1 = invoice_file_service.list_invoice_files(db, limit=2, offset=0)
    page2 = invoice_file_service.list_invoice_files(db, limit=2, offset=2)

    assert [r.filename for r in page1] == ["file-004.pdf", "file-003.pdf"]
    assert [r.filename for r in page2] == ["file-002.pdf", "file-001.pdf"]
    assert {r.id for r in page1}.isdisjoint({r.id for r in page2})


def test_list_invoice_files_offset_past_end_returns_empty(db):
    _seed_invoice_files(db, 3)
    rows = invoice_file_service.list_invoice_files(db, limit=2, offset=10)
    assert rows == []


# ── Tie-breaking regression tests (DEF-011) ──────────────────────────────────
# `sync_pdf`/bulk NAV inserts commit a whole batch of rows in a single
# transaction, and PostgreSQL's now() is transaction-scoped, so every row in
# that batch gets an IDENTICAL created_at/invoice_date. The previous
# `_seed_invoice_files`/`_seed_invoices` fixtures above always assign
# strictly-increasing timestamps, so they never exercise this tie condition,
# which is exactly why the ORDER BY created_at DESC (no tiebreaker) regression
# in invoice_file_service.list_invoice_files slipped through: on ties,
# PostgreSQL is free to return rows in a different order per query, so
# LIMIT/OFFSET paging can repeat some rows and silently drop others. These
# tests seed rows with an IDENTICAL created_at/invoice_date (matching real
# bulk-sync data) and page through the full result set, asserting every row
# appears exactly once.


def _seed_invoice_files_same_timestamp(db, count: int) -> list[InvoiceFile]:
    """Create `count` invoice files that all share one identical created_at,
    reproducing what a single sync_pdf transaction actually produces on
    PostgreSQL (server_default=func.now(), transaction-scoped).
    """
    same_time = datetime(2026, 1, 1, 12, 0, 0)
    files = []
    for i in range(count):
        f = InvoiceFile(filename=f"tied-{i:03d}.pdf", created_at=same_time)
        db.add(f)
        files.append(f)
    db.commit()
    return files


def _seed_invoices_same_date(db, count: int) -> list[Invoice]:
    """Create `count` invoices that all share one identical invoice_date."""
    same_date = date(2026, 1, 1)
    invoices = []
    for i in range(count):
        inv = Invoice(
            invoice_number=f"TIED-{i:03d}",
            invoice_date=same_date,
            direction=_InvoiceDirection.OUTBOUND,
        )
        db.add(inv)
        invoices.append(inv)
    db.commit()
    return invoices


def test_list_invoice_files_pages_through_tied_created_at_without_dupes_or_gaps(db):
    seeded = _seed_invoice_files_same_timestamp(db, 9)
    expected_ids = {f.id for f in seeded}

    seen: list[int] = []
    limit = 3
    for offset in range(0, 9, limit):
        page = invoice_file_service.list_invoice_files(db, limit=limit, offset=offset)
        assert len(page) == limit
        seen.extend(r.id for r in page)

    assert len(seen) == len(set(seen)), f"duplicate ids across pages: {seen}"
    assert set(seen) == expected_ids, (
        f"missing ids: {expected_ids - set(seen)}, unexpected ids: {set(seen) - expected_ids}"
    )


def test_list_invoices_pages_through_tied_invoice_date_without_dupes_or_gaps(db):
    seeded = _seed_invoices_same_date(db, 9)
    expected_ids = {inv.id for inv in seeded}

    seen: list[int] = []
    limit = 3
    for offset in range(0, 9, limit):
        page = invoice_service.list_invoices(db, limit=limit, offset=offset)
        assert len(page) == limit
        seen.extend(r.id for r in page)

    assert len(seen) == len(set(seen)), f"duplicate ids across pages: {seen}"
    assert set(seen) == expected_ids, (
        f"missing ids: {expected_ids - set(seen)}, unexpected ids: {set(seen) - expected_ids}"
    )


def _captured_order_by_sql(db, fn, *args, **kwargs) -> list[str]:
    """Run `fn` and capture the ORDER BY clause of every SELECT it issues.

    Behavior-based tie tests above are backend-dependent: SQLite tends to
    return tied rows in a stable, insertion-order-like sequence regardless of
    whether the ORDER BY has a tiebreaker, which is exactly why the original
    bug (missing tiebreaker on invoice_file_service.list_invoice_files)
    shipped with a green test suite -- the seed data in this file's own
    fixtures never created ties, and even when it does (see the tests above),
    SQLite's behavior doesn't reliably expose the ambiguity the way
    PostgreSQL's MVCC heap storage does. Asserting on the actual ORDER BY
    clause text is backend-agnostic and fails immediately, on any backend,
    the moment a unique tiebreaker column is removed from a paginated query.
    """
    captured: list[str] = []

    def listener(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith("SELECT") and " ORDER BY " in statement.upper():
            captured.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", listener)
    try:
        fn(*args, **kwargs)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    return captured


def _order_by_clause(statement: str) -> str:
    idx = statement.upper().rindex(" ORDER BY ")
    clause = statement[idx + len(" ORDER BY ") :]
    for stop in (" LIMIT ", " OFFSET "):
        stop_idx = clause.upper().find(stop)
        if stop_idx != -1:
            clause = clause[:stop_idx]
    return clause


def test_list_invoice_files_order_by_has_unique_id_tiebreaker(db):
    """Regression guard for DEF-011: the query must sort by more than just
    created_at (which is not unique -- a whole sync_pdf batch shares one
    transaction-scoped timestamp on PostgreSQL) so LIMIT/OFFSET paging is
    stable. Fails immediately if the id tiebreaker is ever removed, on any
    database backend -- unlike the tie-seeding tests above, which SQLite can
    pass even when the tiebreaker is missing.
    """
    _seed_invoice_files(db, 3)
    statements = _captured_order_by_sql(
        db, invoice_file_service.list_invoice_files, db, limit=2, offset=0
    )
    main_select = next(s for s in statements if "invoice_file" in s.lower() and "JOIN" in s.upper())
    order_by = _order_by_clause(main_select)
    assert "created_at" in order_by.lower()
    assert "invoice_file.id" in order_by.lower() or "invoice_file\".\"id" in order_by.lower(), (
        f"expected a unique id tiebreaker in ORDER BY, got: {order_by!r}"
    )


def test_list_invoices_order_by_has_unique_id_tiebreaker(db):
    """Regression guard mirroring the invoice_file_service one above --
    invoice_service.list_invoices already has the correct id tiebreaker
    (Invoice.id.desc()); this pins it so it can never silently regress back
    to the same bug DEF-011 found in the sibling invoice-files endpoint.
    """
    _seed_invoices(db, 3)
    statements = _captured_order_by_sql(db, invoice_service.list_invoices, db, limit=2, offset=0)
    main_select = next(s for s in statements if "invoice.invoice_number" in s.lower())
    order_by = _order_by_clause(main_select)
    assert "invoice_date" in order_by.lower()
    assert "invoice.id" in order_by.lower(), (
        f"expected a unique id tiebreaker in ORDER BY, got: {order_by!r}"
    )
