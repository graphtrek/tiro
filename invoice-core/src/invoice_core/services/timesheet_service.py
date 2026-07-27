from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from invoice_core.db import ActivityType, Project, TimesheetEntry, User, _ProjectStatus
from invoice_core.models import TimesheetEntryIn, TimesheetEntryUpdate


def _validate_hours(hours: float) -> None:
    if hours <= 0 or round(hours * 2) != hours * 2:
        raise ValueError("Az óraszám csak pozitív, 0,5 órás lépésekben adható meg")


def _assert_project_permitted(project: Project, user_id: int) -> None:
    if project.status != _ProjectStatus.OPEN:
        raise ValueError("A projekt nincs nyitva, nem rögzíthető rá idő")
    if project.owner_id != user_id and user_id not in project.permitted_user_ids:
        raise ValueError("Nincs jogosultsága ehhez a projekthez időt rögzíteni")


def with_joins(db: Session):
    return db.query(TimesheetEntry).options(
        joinedload(TimesheetEntry.user),
        joinedload(TimesheetEntry.project).joinedload(Project.customer),
        joinedload(TimesheetEntry.activity_type),
    )


def list_timesheet_entries(db: Session, user_id: int) -> list[TimesheetEntry]:
    return (
        with_joins(db)
        .filter(TimesheetEntry.user_id == user_id)
        .order_by(TimesheetEntry.entry_date, TimesheetEntry.id)
        .all()
    )


def create_timesheet_entry(db: Session, payload: TimesheetEntryIn) -> TimesheetEntry:
    project = db.query(Project).filter(Project.id == payload.project_id).one_or_none()
    if project is None:
        raise ValueError("Projekt nem található")
    user = db.query(User).filter(User.id == payload.user_id).one_or_none()
    if user is None:
        raise ValueError("Felhasználó nem található")
    activity_type = (
        db.query(ActivityType).filter(ActivityType.id == payload.activity_type_id).one_or_none()
    )
    if activity_type is None or not activity_type.is_active:
        raise ValueError("Tevékenység típus nem található vagy nem aktív")

    _assert_project_permitted(project, payload.user_id)
    _validate_hours(payload.hours)

    record = TimesheetEntry(
        user_id=payload.user_id,
        project_id=payload.project_id,
        activity_type_id=payload.activity_type_id,
        entry_date=payload.entry_date,
        hours=payload.hours,
        participants=payload.participants,
        description=payload.description,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_timesheet_entry(
    db: Session, entry_id: int, user_id: int, payload: TimesheetEntryUpdate
) -> TimesheetEntry | None:
    record = (
        db.query(TimesheetEntry)
        .filter(TimesheetEntry.id == entry_id, TimesheetEntry.user_id == user_id)
        .one_or_none()
    )
    if record is None:
        return None

    project = db.query(Project).filter(Project.id == payload.project_id).one_or_none()
    if project is None:
        raise ValueError("Projekt nem található")
    activity_type = (
        db.query(ActivityType).filter(ActivityType.id == payload.activity_type_id).one_or_none()
    )
    if activity_type is None or not activity_type.is_active:
        raise ValueError("Tevékenység típus nem található vagy nem aktív")

    _assert_project_permitted(project, user_id)
    _validate_hours(payload.hours)

    record.project_id = payload.project_id
    record.activity_type_id = payload.activity_type_id
    record.entry_date = payload.entry_date
    record.hours = payload.hours
    record.participants = payload.participants
    record.description = payload.description

    db.commit()
    db.refresh(record)
    return record


def delete_timesheet_entry(db: Session, entry_id: int, user_id: int) -> bool:
    record = (
        db.query(TimesheetEntry)
        .filter(TimesheetEntry.id == entry_id, TimesheetEntry.user_id == user_id)
        .one_or_none()
    )
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True
