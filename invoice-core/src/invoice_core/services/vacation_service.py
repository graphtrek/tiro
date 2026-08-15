from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from invoice_core.db import User, VacationRequest
from invoice_core.models import VacationRequestIn, VacationRequestUpdate


def _assert_date_range_valid(start_date, end_date) -> None:
    if end_date < start_date:
        raise ValueError("A záró dátum nem lehet korábbi a kezdő dátumnál")


def with_joins(db: Session):
    return db.query(VacationRequest).options(joinedload(VacationRequest.user))


def list_vacation_requests(db: Session, user_id: int | None = None) -> list[VacationRequest]:
    query = with_joins(db)
    if user_id is not None:
        query = query.filter(VacationRequest.user_id == user_id)
    return query.order_by(VacationRequest.start_date, VacationRequest.id).all()


def create_vacation_request(db: Session, payload: VacationRequestIn) -> VacationRequest:
    user = db.query(User).filter(User.id == payload.user_id).one_or_none()
    if user is None:
        raise ValueError("Felhasználó nem található")

    _assert_date_range_valid(payload.start_date, payload.end_date)

    record = VacationRequest(
        user_id=payload.user_id,
        kind=payload.kind,
        start_date=payload.start_date,
        end_date=payload.end_date,
        note=payload.note,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_vacation_request(
    db: Session, request_id: int, user_id: int, payload: VacationRequestUpdate
) -> VacationRequest | None:
    record = (
        db.query(VacationRequest)
        .filter(VacationRequest.id == request_id, VacationRequest.user_id == user_id)
        .one_or_none()
    )
    if record is None:
        return None

    _assert_date_range_valid(payload.start_date, payload.end_date)

    record.kind = payload.kind
    record.start_date = payload.start_date
    record.end_date = payload.end_date
    record.note = payload.note

    db.commit()
    db.refresh(record)
    return record


def delete_vacation_request(db: Session, request_id: int, user_id: int) -> bool:
    record = (
        db.query(VacationRequest)
        .filter(VacationRequest.id == request_id, VacationRequest.user_id == user_id)
        .one_or_none()
    )
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True
