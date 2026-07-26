from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from invoice_core.db import Project, TimesheetEntry
from invoice_core.services.timesheet_service import with_joins

_HU_WEEKDAYS = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]


def _filtered_entries(
    db: Session,
    date_from: date | None,
    date_to: date | None,
    customer_id: int | None,
    project_id: int | None,
    user_id: int | None,
    activity_type_id: int | None,
) -> list[TimesheetEntry]:
    query = with_joins(db)
    if date_from is not None:
        query = query.filter(TimesheetEntry.entry_date >= date_from)
    if date_to is not None:
        query = query.filter(TimesheetEntry.entry_date <= date_to)
    if project_id is not None:
        query = query.filter(TimesheetEntry.project_id == project_id)
    if user_id is not None:
        query = query.filter(TimesheetEntry.user_id == user_id)
    if activity_type_id is not None:
        query = query.filter(TimesheetEntry.activity_type_id == activity_type_id)
    if customer_id is not None:
        query = query.filter(TimesheetEntry.project.has(Project.customer_id == customer_id))
    return query.order_by(TimesheetEntry.entry_date, TimesheetEntry.id).all()


@dataclass
class ProjectWeekRow:
    project_week: int
    week_hours: float
    cumulative_hours: float
    by_activity_type: dict[str, float] = field(default_factory=dict)


@dataclass
class ProjectReport:
    project_id: int
    project_code: str
    customer_name: str
    activity_type_names: list[str]
    weeks: list[ProjectWeekRow]
    total_hours: float


def get_project_report(
    db: Session,
    project_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: int | None = None,
    activity_type_id: int | None = None,
) -> ProjectReport:
    entries = _filtered_entries(
        db,
        date_from=date_from,
        date_to=date_to,
        customer_id=None,
        project_id=project_id,
        user_id=user_id,
        activity_type_id=activity_type_id,
    )

    project = db.query(Project).filter(Project.id == project_id).one_or_none()
    activity_type_names = sorted({e.activity_type_name for e in entries})

    by_week: dict[int, dict] = {}
    for entry in entries:
        week = by_week.setdefault(entry.project_week, {"week_hours": 0.0, "by_activity_type": {}})
        week["week_hours"] += entry.hours
        week["by_activity_type"][entry.activity_type_name] = (
            week["by_activity_type"].get(entry.activity_type_name, 0.0) + entry.hours
        )

    weeks: list[ProjectWeekRow] = []
    cumulative = 0.0
    for week_no in sorted(by_week):
        cumulative += by_week[week_no]["week_hours"]
        weeks.append(
            ProjectWeekRow(
                project_week=week_no,
                week_hours=by_week[week_no]["week_hours"],
                cumulative_hours=cumulative,
                by_activity_type=by_week[week_no]["by_activity_type"],
            )
        )

    return ProjectReport(
        project_id=project_id,
        project_code=project.code if project else "",
        customer_name=project.customer_name if project else "",
        activity_type_names=activity_type_names,
        weeks=weeks,
        total_hours=cumulative,
    )


@dataclass
class GroupTotalRow:
    key_id: int
    key_label: str
    total_hours: float
    entry_count: int
    by_activity_type: dict[str, float] = field(default_factory=dict)


@dataclass
class DetailRow:
    entry_date: str
    weekday: str
    project_week: int
    project_code: str
    customer_name: str
    user_name: str
    activity_type_name: str
    participants: str
    hours: float


@dataclass
class GroupReport:
    group_by: str
    activity_type_names: list[str]
    rows: list[GroupTotalRow]
    entries: list[DetailRow]
    total_hours: float


def get_group_report(
    db: Session,
    group_by: str,
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: int | None = None,
    project_id: int | None = None,
    user_id: int | None = None,
    activity_type_id: int | None = None,
) -> GroupReport:
    entries = _filtered_entries(
        db,
        date_from=date_from,
        date_to=date_to,
        customer_id=customer_id,
        project_id=project_id,
        user_id=user_id,
        activity_type_id=activity_type_id,
    )

    def key_and_label(entry: TimesheetEntry) -> tuple[int, str]:
        if group_by == "person":
            return entry.user_id, entry.user_name
        if group_by == "customer":
            return entry.project.customer_id, entry.customer_name
        return entry.activity_type_id, entry.activity_type_name

    pivot = group_by != "activity_type"
    activity_type_names = sorted({e.activity_type_name for e in entries}) if pivot else []

    groups: dict[int, dict] = {}
    for entry in entries:
        key_id, key_label = key_and_label(entry)
        group = groups.setdefault(
            key_id,
            {"key_label": key_label, "total_hours": 0.0, "entry_count": 0, "by_activity_type": {}},
        )
        group["total_hours"] += entry.hours
        group["entry_count"] += 1
        if pivot:
            group["by_activity_type"][entry.activity_type_name] = (
                group["by_activity_type"].get(entry.activity_type_name, 0.0) + entry.hours
            )

    rows = [
        GroupTotalRow(
            key_id=key_id,
            key_label=group["key_label"],
            total_hours=group["total_hours"],
            entry_count=group["entry_count"],
            by_activity_type=group["by_activity_type"],
        )
        for key_id, group in groups.items()
    ]
    rows.sort(key=lambda r: r.key_label)

    entries_sorted = sorted(entries, key=lambda e: (key_and_label(e)[1], e.entry_date, e.id))
    detail_rows = [
        DetailRow(
            entry_date=entry.entry_date.isoformat(),
            weekday=_HU_WEEKDAYS[entry.entry_date.weekday()],
            project_week=entry.project_week,
            project_code=entry.project_code,
            customer_name=entry.customer_name,
            user_name=entry.user_name,
            activity_type_name=entry.activity_type_name,
            participants=entry.participants or "",
            hours=entry.hours,
        )
        for entry in entries_sorted
    ]

    return GroupReport(
        group_by=group_by,
        activity_type_names=activity_type_names,
        rows=rows,
        entries=detail_rows,
        total_hours=sum(r.total_hours for r in rows),
    )
