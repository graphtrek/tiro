from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from invoice_core.db import Customer, Project, User
from invoice_core.models import ProjectIn, ProjectUpdate


def _compose_code(sequence_no: int, short_name: str) -> str:
    return f"{short_name}-{sequence_no:03d}"


def _next_sequence_no(db: Session, customer_id: int) -> int:
    """Max existing sequence_no for this customer + 1.

    Not race-safe: two concurrent creates for the same customer could compute the
    same number and collide on the `uq_project_customer_seq` unique constraint,
    surfacing as a 500. Acceptable given this is low-concurrency admin data.
    """
    current_max = (
        db.query(func.max(Project.sequence_no)).filter(Project.customer_id == customer_id).scalar()
    )
    return (current_max or 0) + 1


def _code_taken(db: Session, code: str, exclude_id: int | None = None) -> bool:
    query = db.query(Project).filter(func.lower(Project.code) == code.lower())
    if exclude_id is not None:
        query = query.filter(Project.id != exclude_id)
    return query.first() is not None


def _permitted_users(db: Session, user_ids: list[int]) -> list[User]:
    if not user_ids:
        return []
    return db.query(User).filter(User.id.in_(user_ids)).all()


def _with_joins(db: Session):
    return db.query(Project).options(
        joinedload(Project.customer),
        joinedload(Project.owner),
        joinedload(Project.permitted_users),
        joinedload(Project.timesheet_entries),
    )


def list_projects(db: Session) -> list[Project]:
    return _with_joins(db).order_by(Project.code).all()


def create_project(db: Session, payload: ProjectIn) -> Project:
    customer = db.query(Customer).filter(Customer.id == payload.customer_id).one_or_none()
    if customer is None:
        raise ValueError("Ügyfél nem található")
    owner = db.query(User).filter(User.id == payload.owner_id).one_or_none()
    if owner is None:
        raise ValueError("Project gazda nem található")

    sequence_no = _next_sequence_no(db, payload.customer_id)
    code = _compose_code(sequence_no, payload.short_name)
    if _code_taken(db, code):
        raise ValueError(f"Project kód '{code}' már létezik")

    record = Project(
        customer_id=payload.customer_id,
        sequence_no=sequence_no,
        short_name=payload.short_name,
        code=code,
        owner_id=payload.owner_id,
        is_active=True,
        permitted_users=_permitted_users(db, payload.permitted_user_ids),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_project(db: Session, project_id: int, payload: ProjectUpdate) -> Project | None:
    record = db.query(Project).filter(Project.id == project_id).one_or_none()
    if record is None:
        return None

    customer = db.query(Customer).filter(Customer.id == payload.customer_id).one_or_none()
    if customer is None:
        raise ValueError("Ügyfél nem található")
    owner = db.query(User).filter(User.id == payload.owner_id).one_or_none()
    if owner is None:
        raise ValueError("Project gazda nem található")

    # Changing the customer re-anchors the per-customer sequence; otherwise keep it,
    # so renaming the short_name alone doesn't bump the sequence number.
    sequence_no = (
        _next_sequence_no(db, payload.customer_id)
        if payload.customer_id != record.customer_id
        else record.sequence_no
    )
    code = _compose_code(sequence_no, payload.short_name)
    if _code_taken(db, code, exclude_id=record.id):
        raise ValueError(f"Project kód '{code}' már létezik")

    record.customer_id = payload.customer_id
    record.sequence_no = sequence_no
    record.short_name = payload.short_name
    record.code = code
    record.owner_id = payload.owner_id
    record.is_active = payload.is_active
    record.permitted_users = _permitted_users(db, payload.permitted_user_ids)

    db.commit()
    db.refresh(record)
    return record


def delete_project(db: Session, project_id: int) -> bool:
    """Hard-delete — mirrors activity_type_service.delete_activity_type.

    No usage gating here: a project with existing TimesheetEntry rows will fail
    on the FK constraint (IntegrityError) rather than being blocked up front.
    """
    record = db.query(Project).filter(Project.id == project_id).one_or_none()
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True
