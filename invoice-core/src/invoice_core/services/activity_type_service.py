from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from invoice_core.db import ActivityType
from invoice_core.models import ActivityTypeIn, ActivityTypeUpdate


def _name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    query = db.query(ActivityType).filter(func.lower(ActivityType.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(ActivityType.id != exclude_id)
    return query.first() is not None


def list_activity_types(db: Session) -> list[ActivityType]:
    return db.query(ActivityType).order_by(ActivityType.name).all()


def create_activity_type(db: Session, payload: ActivityTypeIn) -> ActivityType:
    if _name_taken(db, payload.name):
        raise ValueError(f"Activity type '{payload.name}' already exists")
    record = ActivityType(name=payload.name, is_active=True)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_activity_type(
    db: Session, activity_type_id: int, payload: ActivityTypeUpdate
) -> ActivityType | None:
    record = db.query(ActivityType).filter(ActivityType.id == activity_type_id).one_or_none()
    if record is None:
        return None
    if _name_taken(db, payload.name, exclude_id=activity_type_id):
        raise ValueError(f"Activity type '{payload.name}' already exists")
    record.name = payload.name
    record.is_active = payload.is_active
    db.commit()
    db.refresh(record)
    return record


def delete_activity_type(db: Session, activity_type_id: int) -> bool:
    """Hard-delete — only ever called from the UI when the usage count is 0.

    There is no usage-tracking table yet (no Timesheet feature), so there is
    nothing to re-check server-side; the UI is the sole gatekeeper until that
    lands.
    """
    record = db.query(ActivityType).filter(ActivityType.id == activity_type_id).one_or_none()
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True
