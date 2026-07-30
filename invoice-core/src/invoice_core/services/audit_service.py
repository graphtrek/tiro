from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date, datetime
from enum import Enum as PyEnum
from urllib.parse import unquote

from fastapi import Request, Response
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from starlette.concurrency import iterate_in_threadpool

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


# Anchored to the full path — checked before _OBJECT_RULES below, which would
# otherwise match its "/api/v1/invoices/(\d+)" prefix too. Not resolved via
# _OBJECT_RULES because it identifies a many-to-many link row (invoice ↔
# transaction), not a single entity, so there's nothing to field-diff.
_INVOICE_TRANSACTION_RE = re.compile(r"^/api/v1/invoices/(\d+)/transactions/(\d+)$")

# Ordered (regex, resolver) pairs — first match wins. Each resolver looks the
# row up in the DB *before* the mutation runs (see prepare_record), so a
# DELETE can still show what was deleted instead of a stale/missing lookup.
# Resolving to the actual ORM object (rather than straight to a display
# string) lets the same lookup feed both the "record" label (_record_label)
# and the before/after field snapshot for update actions (_snapshot).
_OBJECT_RULES: list[tuple[re.Pattern, Callable[[Session, re.Match], object | None]]] = [
    (
        re.compile(r"^/api/v1/invoices/(\d+)"),
        lambda db, m: db.query(Invoice).filter(Invoice.id == int(m.group(1))).one_or_none(),
    ),
    (
        re.compile(r"^/api/v1/invoice-files/(\d+)"),
        lambda db, m: db.query(InvoiceFile).filter(InvoiceFile.id == int(m.group(1))).one_or_none(),
    ),
    (
        re.compile(r"^/api/v1/transactions/(\d+)"),
        lambda db, m: db.query(BankTransaction)
        .filter(BankTransaction.id == int(m.group(1)))
        .one_or_none(),
    ),
    (
        re.compile(r"^/api/v1/partners/suppliers/(\d+)"),
        lambda db, m: db.query(Supplier).filter(Supplier.id == int(m.group(1))).one_or_none(),
    ),
    (
        re.compile(r"^/api/v1/partners/customers/(\d+)"),
        lambda db, m: db.query(Customer).filter(Customer.id == int(m.group(1))).one_or_none(),
    ),
    (
        re.compile(r"^/api/v1/activity-types/(\d+)"),
        lambda db, m: db.query(ActivityType).filter(ActivityType.id == int(m.group(1))).one_or_none(),
    ),
    (
        re.compile(r"^/api/v1/projects/(\d+)"),
        lambda db, m: db.query(Project).filter(Project.id == int(m.group(1))).one_or_none(),
    ),
    (
        re.compile(r"^/api/v1/timesheet-entries/(\d+)"),
        lambda db, m: db.query(TimesheetEntry)
        .filter(TimesheetEntry.id == int(m.group(1)))
        .one_or_none(),
    ),
]


def _resolve_object(db: Session, path: str) -> object | None:
    for pattern, resolver in _OBJECT_RULES:
        m = pattern.match(path)
        if m:
            return resolver(db, m)
    return None


def _record_label(obj: object | None) -> str | None:
    if obj is None:
        return None
    if isinstance(obj, Invoice):
        return obj.invoice_number
    if isinstance(obj, InvoiceFile):
        return obj.filename
    if isinstance(obj, BankTransaction):
        return obj.transaction_id
    if isinstance(obj, (Supplier, Customer, ActivityType)):
        return obj.name
    if isinstance(obj, Project):
        return obj.code
    if isinstance(obj, TimesheetEntry):
        project_code = obj.project.code if obj.project else "?"
        return f"{project_code} {obj.entry_date}"
    return None


def _resolve_record(db: Session, path: str) -> str | None:
    m = _INVOICE_TRANSACTION_RE.match(path)
    if m:
        return _invoice_transaction_link(db, m)
    return _record_label(_resolve_object(db, path))


def _jsonable(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, PyEnum):
        return value.value
    return value


# Never useful in a field-change diff: id never changes, and the timestamps
# just reflect the mutation itself.
_SNAPSHOT_EXCLUDED_FIELDS = {"id", "created_at", "updated_at"}


def _snapshot(obj: object) -> dict[str, object]:
    """Plain-column field values, JSON-safe, for before/after diffing."""
    mapper = sa_inspect(obj).mapper
    return {
        col.key: _jsonable(getattr(obj, col.key))
        for col in mapper.column_attrs
        if col.key not in _SNAPSHOT_EXCLUDED_FIELDS
    }


def prepare_record(db: Session, request: Request) -> dict | None:
    """Resolve page + record identifier (+ pre-mutation field snapshot for
    updates) *before* the mutation runs.

    Must run pre-mutation: a DELETE removes the row, so looking the record up
    afterwards (e.g. for its name/number) would find nothing, and an UPDATE's
    old field values are gone the instant the mutation commits. Returns None
    for requests that won't be audited (GET, unmapped path) so the caller can
    skip the second DB round-trip entirely.
    """
    action = _ACTIONS.get(request.method)
    if action is None:
        return None
    page = _match_page(request.url.path)
    if page is None:
        return None

    path = request.url.path
    m = _INVOICE_TRANSACTION_RE.match(path)
    if m:
        record, before = _invoice_transaction_link(db, m), None
    else:
        obj = _resolve_object(db, path)
        record = _record_label(obj)
        before = _snapshot(obj) if obj is not None and action == "update" else None

    return {"action": action, "page": page, "record": record, "before": before}


async def extract_created_id(response: Response) -> int | None:
    """Best-effort: pull the new row's id out of a create endpoint's JSON body.

    Only called for POSTs whose path had no id to resolve a record from (see
    finalize_record). BaseHTTPMiddleware wraps the downstream response as a
    one-shot async stream, so the body is buffered and replayed onto the
    response for the actual client to still receive it.
    """
    if not hasattr(response, "body_iterator"):
        return None
    chunks = [section async for section in response.body_iterator]
    response.body_iterator = iterate_in_threadpool(iter(chunks))
    try:
        data = json.loads(b"".join(chunks))
    except (ValueError, UnicodeDecodeError):
        return None
    return data.get("id") if isinstance(data, dict) else None


def finalize_record(
    db: Session,
    request: Request,
    response: Response,
    prepared: dict | None,
    created_id: int | None = None,
) -> None:
    if prepared is None or not (200 <= response.status_code < 300):
        return
    record = prepared["record"]
    if record is None and created_id is not None:
        # A create endpoint's path has no id (e.g. POST /api/v1/projects) so
        # prepare_record couldn't resolve it before the mutation ran; now that
        # the row exists, reuse the normal id-based rules via a synthetic path.
        record = _resolve_record(db, f"{request.url.path.rstrip('/')}/{created_id}")

    changes = None
    before = prepared.get("before")
    if before is not None:
        # Re-resolve post-mutation (fresh query — the endpoint's own db
        # session already committed by the time this middleware step runs)
        # and diff against the pre-mutation snapshot prepare_record took.
        obj = _resolve_object(db, request.url.path)
        after = _snapshot(obj) if obj is not None else None
        if after is not None:
            changes = [
                {"field": key, "old": before.get(key), "new": after[key]}
                for key in after
                if after[key] != before.get(key)
            ] or None

    claims = getattr(request.state, "user", None)
    raw_label = request.headers.get(LABEL_HEADER)
    db.add(
        AuditLog(
            user_email=claims.get("email") if claims else None,
            impersonator_email=claims.get("impersonator_email") if claims else None,
            method=request.method,
            path=request.url.path,
            page=prepared["page"],
            record=record,
            label=unquote(raw_label) if raw_label else None,
            action=prepared["action"],
            changes=changes,
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
    return query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
