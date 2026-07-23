from __future__ import annotations

from datetime import date, datetime

from fastapi import Request, Response
from sqlalchemy.orm import Session

from invoice_core.db import AuditLog

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


def _match_page(path: str) -> str | None:
    for prefix, page in _PAGE_RULES:
        if path.startswith(prefix):
            return page
    return None


def record(db: Session, request: Request, response: Response) -> None:
    action = _ACTIONS.get(request.method)
    if action is None or not (200 <= response.status_code < 300):
        return
    page = _match_page(request.url.path)
    if page is None:
        return
    claims = getattr(request.state, "user", None)
    db.add(
        AuditLog(
            user_email=claims.get("email") if claims else None,
            method=request.method,
            path=request.url.path,
            page=page,
            action=action,
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
