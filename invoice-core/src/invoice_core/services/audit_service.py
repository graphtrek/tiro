from __future__ import annotations

import re
from datetime import date, datetime
from typing import Callable
from urllib.parse import unquote

from fastapi import Request, Response
from sqlalchemy.orm import Session

from invoice_core.db import (
    ActivityType,
    AuditLog,
    BankTransaction,
    Customer,
    Invoice,
    InvoiceFile,
    Project,
    Supplier,
    TimesheetEntry,
)

# Ordered path prefix → Hungarian page label, matched against request.url.path.
# GET requests, /api/v1/sync* (tracked separately via SyncLog) and /api/v1/users
# (system-generated login upsert) never match and are not logged.
_PAGE_RULES: list[tuple[str, str]] = [
    ("/api/v1/invoices/", "Számlák"),
    ("/api/v1/invoice-files/", "Szla Fájlok"),
    ("/api/v1/transactions/", "Bank"),
    ("/api/v1/partners/suppliers", "Szállítók"),
    ("/api/v1/partners/customers", "Vevők"),
    ("/api/v1/activity-types", "Tevékenység típusok"),
    ("/api/v1/projects", "Projektek"),
    ("/api/v1/timesheet-entries", "Timesheet"),
]

_ACTIONS: dict[str, str] = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}

# Header vision sends with the human-readable button/action the user clicked
# (e.g. "Szállító zárolása"), percent-encoded — Hungarian double-acute letters
# (ő/ű) aren't valid Latin-1, which is all raw HTTP header values may contain.
# Optional — falls back to a generic create/update/delete badge in the UI when
# a caller (or an older client) doesn't send it.
LABEL_HEADER = "X-Audit-Label"


def _match_page(path: str) -> str | None:
    for prefix, page in _PAGE_RULES:
        if path.startswith(prefix):
            return page
    return None


def _invoice_transaction_link(db: Session, m: re.Match) -> str | None:
    inv = db.query(Invoice).filter(Invoice.id == int(m.group(1))).one_or_none()
    txn = db.query(BankTransaction).filter(BankTransaction.id == int(m.group(2))).one_or_none()
    if inv is None and txn is None:
        return None
    return f"{inv.invoice_number if inv else '?'} ↔ {txn.transaction_id if txn else '?'}"


def _timesheet_entry_record(db: Session, m: re.Match) -> str | None:
    entry = db.query(TimesheetEntry).filter(TimesheetEntry.id == int(m.group(1))).one_or_none()
    if entry is None:
        return None
    project_code = entry.project.code if entry.project else "?"
    return f"{project_code} {entry.entry_date}"


# Ordered (regex, resolver) pairs — first match wins. Each resolver looks the
# record up in the DB *before* the mutation runs (see prepare_record), so a
# DELETE can still show what was deleted instead of a stale/missing lookup.
_RECORD_RULES: list[tuple[re.Pattern, Callable[[Session, re.Match], str | None]]] = [
    (
        re.compile(r"^/api/v1/invoices/(\d+)/transactions/(\d+)$"),
        _invoice_transaction_link,
    ),
    (
        re.compile(r"^/api/v1/invoices/(\d+)"),
        lambda db, m: (lambda r: r.invoice_number if r else None)(
            db.query(Invoice).filter(Invoice.id == int(m.group(1))).one_or_none()
        ),
    ),
    (
        re.compile(r"^/api/v1/invoice-files/(\d+)"),
        lambda db, m: (lambda r: r.filename if r else None)(
            db.query(InvoiceFile).filter(InvoiceFile.id == int(m.group(1))).one_or_none()
        ),
    ),
    (
        re.compile(r"^/api/v1/transactions/(\d+)"),
        lambda db, m: (lambda r: r.transaction_id if r else None)(
            db.query(BankTransaction).filter(BankTransaction.id == int(m.group(1))).one_or_none()
        ),
    ),
    (
        re.compile(r"^/api/v1/partners/suppliers/(\d+)"),
        lambda db, m: (lambda r: r.name if r else None)(
            db.query(Supplier).filter(Supplier.id == int(m.group(1))).one_or_none()
        ),
    ),
    (
        re.compile(r"^/api/v1/partners/customers/(\d+)"),
        lambda db, m: (lambda r: r.name if r else None)(
            db.query(Customer).filter(Customer.id == int(m.group(1))).one_or_none()
        ),
    ),
    (
        re.compile(r"^/api/v1/activity-types/(\d+)"),
        lambda db, m: (lambda r: r.name if r else None)(
            db.query(ActivityType).filter(ActivityType.id == int(m.group(1))).one_or_none()
        ),
    ),
    (
        re.compile(r"^/api/v1/projects/(\d+)"),
        lambda db, m: (lambda r: r.code if r else None)(
            db.query(Project).filter(Project.id == int(m.group(1))).one_or_none()
        ),
    ),
    (
        re.compile(r"^/api/v1/timesheet-entries/(\d+)"),
        _timesheet_entry_record,
    ),
]


def _resolve_record(db: Session, path: str) -> str | None:
    for pattern, resolver in _RECORD_RULES:
        m = pattern.match(path)
        if m:
            return resolver(db, m)
    return None


def prepare_record(db: Session, request: Request) -> dict | None:
    """Resolve page + record identifier *before* the mutation runs.

    Must run pre-mutation: a DELETE removes the row, so looking the record up
    afterwards (e.g. for its name/number) would find nothing. Returns None for
    requests that won't be audited (GET, unmapped path) so the caller can skip
    the second DB round-trip entirely.
    """
    action = _ACTIONS.get(request.method)
    if action is None:
        return None
    page = _match_page(request.url.path)
    if page is None:
        return None
    return {"action": action, "page": page, "record": _resolve_record(db, request.url.path)}


def finalize_record(db: Session, request: Request, response: Response, prepared: dict | None) -> None:
    if prepared is None or not (200 <= response.status_code < 300):
        return
    claims = getattr(request.state, "user", None)
    raw_label = request.headers.get(LABEL_HEADER)
    db.add(
        AuditLog(
            user_email=claims.get("email") if claims else None,
            method=request.method,
            path=request.url.path,
            page=prepared["page"],
            record=prepared["record"],
            label=unquote(raw_label) if raw_label else None,
            action=prepared["action"],
            status_code=response.status_code,
        )
    )
    db.commit()


def list_audit_log(
    db: Session,
    user_email: str | None = None,
    page: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 200,
) -> list[AuditLog]:
    query = db.query(AuditLog)
    if user_email:
        query = query.filter(AuditLog.user_email == user_email)
    if page:
        query = query.filter(AuditLog.page == page)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= datetime.combine(date_to, datetime.max.time()))
    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()
