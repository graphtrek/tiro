"""Template rendering utilities for vision UI."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi.responses import RedirectResponse

if TYPE_CHECKING:
    from fastapi import Request

    from vision.clients.invoice_core import InvoiceCoreClient

_ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
# invoice-core stores/serializes timestamps as naive UTC (datetime.utcnow()) — convert
# to local wall-clock time here so templates never have to think about it.
_LOCAL_TZ = ZoneInfo("Europe/Budapest")


def local_today() -> date:
    """Return the current Budapest business date used by UI filter defaults."""
    return datetime.now(_LOCAL_TZ).date()


def current_user(client: InvoiceCoreClient, request: Request) -> dict | None:
    """Resolve the invoice-core User row for the logged-in vision session.

    Vision only holds JWT claims (email/name/sub); invoice-core's `user` table
    is the source of truth for `User.id`, upserted by the auth service on
    every login.
    """
    claims = getattr(request.state, "user", None)
    if claims is None:
        return None
    email = claims.get("email")
    return next((u for u in client.get_users() if u["email"] == email), None)


def redirect_if_readonly(request: Request) -> RedirectResponse | None:
    """Admin section (users, activity types, audit, sync, upload) is fully
    off-limits to read-only users — redirect straight to the dashboard on any
    direct navigation instead of only hiding the sidebar links."""
    claims = getattr(request.state, "user", None) or {}
    if claims.get("role") == "read_only":
        return RedirectResponse("/ui/", status_code=302)
    return None


def is_anonymized(request: Request) -> bool:
    """True for the untrusted read-only tier (any verified account not covered
    by READONLY_EMAILS/READONLY_DOMAINS) — mirrors invoice-core's
    `should_anonymize()`. `role == 'read_only'` alone does not imply this: the
    trusted READONLY_EMAILS/READONLY_DOMAINS tier is also read_only but keeps
    real data."""
    claims = getattr(request.state, "user", None) or {}
    return claims.get("anonymized") is True


def _parse_leaf(v):
    if isinstance(v, str) and _ISO_DT.match(v):
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            return v
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(_LOCAL_TZ)
    return v


def dict_to_ns(obj):
    """Recursively convert dicts → SimpleNamespace so templates can use dot-notation.
    ISO datetime strings are parsed back to datetime objects."""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: dict_to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [dict_to_ns(i) for i in obj]
    return _parse_leaf(obj)
