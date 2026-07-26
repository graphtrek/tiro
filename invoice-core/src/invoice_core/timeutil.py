"""Time helpers for invoice-core.

All SQLAlchemy ``DateTime`` columns in this service are naive (no
``timezone=True``) and persisted as UTC. To keep persisted values naive-UTC
and comparisons working — while still avoiding the deprecated
``datetime.utcnow()`` (DTZ003) — call ``utcnow()`` from here instead.

``today()`` returns the current UTC date for the same reason: date columns
are tz-agnostic, but the *value* should still reflect "now in UTC" so a
tax-year boundary computed in CET vs UTC doesn't shift by a day.
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def utcnow() -> datetime:
    """Return the current UTC time as a *naive* datetime.

    Equivalent to the legacy ``datetime.utcnow()``: same wall-clock value,
    same naive-UTC semantics the existing columns already store. Use this
    everywhere a row's ``created_at``/``updated_at``/``transaction_date``
    is set by hand so persisted values stay naive and remain directly
    comparable to the ``server_default=func.now()`` defaults.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def today() -> date:
    """Return the current UTC date (naive date, no tzinfo)."""
    return utcnow().date()
