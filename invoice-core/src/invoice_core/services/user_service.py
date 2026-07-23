from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from invoice_core.db import User
from invoice_core.models import UserIn


def upsert_user(db: Session, payload: UserIn) -> User:
    """Create or refresh the user row keyed by (provider, sub) — called on every login."""
    record = (
        db.query(User)
        .filter(User.provider == payload.provider, User.sub == payload.sub)
        .one_or_none()
    )
    if record is None:
        record = User(provider=payload.provider, sub=payload.sub, email=payload.email)
        db.add(record)
    record.email = payload.email
    record.name = payload.name
    record.picture = payload.picture
    record.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(record)
    return record


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.last_login_at.desc()).all()


def touch_last_login(db: Session, provider: str, sub: str) -> None:
    """Bump `last_login_at` for an existing user on any authenticated request —
    so "Utolsó belépés" reflects last activity, not just the OAuth login moment."""
    db.query(User).filter(User.provider == provider, User.sub == sub).update(
        {"last_login_at": datetime.utcnow()}
    )
    db.commit()
