"""Controlling UI routes — Projects + Timesheet + Reports (all real DB-backed,
calling invoice-core)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates

from vision.clients.invoice_core import InvoiceCoreClient
from vision.ui.utils import local_today

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui/controlling", tags=["controlling-ui"])

_HU_WEEKDAYS = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]

_REPORT_TYPES = ["project", "person", "customer", "activity_type"]
_REPORT_TYPE_LABELS = {
    "project": "Projekt riport (heti + kumulált)",
    "person": "Személy riport",
    "customer": "Ügyfél riport",
    "activity_type": "Tevékenység típus riport",
}
_DATE_RANGES = ["project_start", "current_month", "current_week", "custom"]
_DATE_RANGE_LABELS = {
    "project_start": "Projekt kezdete óta",
    "current_month": "Aktuális hónap",
    "current_week": "Aktuális hét",
    "custom": "Egyéni dátumtartomány",
}


def _client() -> InvoiceCoreClient:
    return InvoiceCoreClient()


def _current_user(client: InvoiceCoreClient, request: Request) -> dict | None:
    """Resolve the invoice-core User row for the logged-in vision session.

    Vision only holds JWT claims (email/name/sub); invoice-core's `user` table
    is the source of truth for `User.id`, upserted by the auth service on
    every login. Reuses the existing get_users() list-fetch (already called
    for the Projects owner/permitted-user dropdowns) instead of adding a new
    filtered endpoint, given low user counts.
    """
    claims = getattr(request.state, "user", None)
    if claims is None:
        return None
    email = claims.get("email")
    return next((u for u in client.get_users() if u["email"] == email), None)


def _projects_page(request: Request, error: str | None = None):
    client = _client()
    return templates.TemplateResponse(
        request,
        "controlling_projects.html",
        {
            "rows": client.get_projects(),
            "customers": client.get_customers(),
            "users": client.get_users(),
            "error": error,
        },
    )


@router.get("/projects")
def projects_page(request: Request):
    return _projects_page(request)


@router.post("/projects")
def create_project(
    request: Request,
    customer_id: int = Form(...),
    short_name: str = Form(...),
    owner_id: int = Form(...),
    permitted_user_ids: list[int] = Form([]),
):
    result = _client().create_project(customer_id, short_name, owner_id, permitted_user_ids)
    return _projects_page(request, error=result.get("error"))


@router.post("/projects/{project_id}")
def update_project(
    request: Request,
    project_id: int,
    customer_id: int = Form(...),
    short_name: str = Form(...),
    owner_id: int = Form(...),
    is_active: bool = Form(False),
    permitted_user_ids: list[int] = Form([]),
):
    result = _client().update_project(
        project_id, customer_id, short_name, owner_id, is_active, permitted_user_ids
    )
    return _projects_page(request, error=result.get("error"))


@router.delete("/projects/{project_id}")
def delete_project(request: Request, project_id: int):
    result = _client().delete_project(project_id)
    return _projects_page(request, error=result.get("error"))


def _timesheet_page(request: Request, error: str | None = None):
    client = _client()
    user = _current_user(client, request)
    if user is None:
        return templates.TemplateResponse(
            request,
            "controlling_timesheet.html",
            {
                "rows": [],
                "projects": [],
                "activity_types": [],
                "current_user": None,
                "error": error or "Felhasználó azonosítása sikertelen",
            },
        )

    all_projects = client.get_projects()
    permitted_projects = [
        p
        for p in all_projects
        if p["is_active"] and (p["owner_id"] == user["id"] or user["id"] in p["permitted_user_ids"])
    ]

    rows = client.get_timesheet_entries(user["id"])
    for row in rows:
        entry_date = date.fromisoformat(row["entry_date"])
        row["weekday_hu"] = _HU_WEEKDAYS[entry_date.weekday()]
        row["hours_label"] = f"{row['hours']:g}".replace(".", ",")

    return templates.TemplateResponse(
        request,
        "controlling_timesheet.html",
        {
            "rows": rows,
            "projects": permitted_projects,
            "activity_types": [a for a in client.get_activity_types() if a["is_active"]],
            "current_user": user,
            "error": error,
        },
    )


@router.get("/timesheet")
def timesheet_page(request: Request):
    return _timesheet_page(request)


@router.post("/timesheet")
def create_timesheet_entry(
    request: Request,
    project_id: int = Form(...),
    activity_type_id: int = Form(...),
    entry_date: str = Form(...),
    hours: float = Form(...),
    participants: str = Form(""),
    description: str = Form(""),
):
    client = _client()
    user = _current_user(client, request)
    if user is None:
        return _timesheet_page(request, error="Felhasználó azonosítása sikertelen")
    result = client.create_timesheet_entry(
        user["id"],
        project_id,
        activity_type_id,
        entry_date,
        hours,
        participants or None,
        description or None,
    )
    return _timesheet_page(request, error=result.get("error"))


@router.post("/timesheet/{entry_id}")
def update_timesheet_entry(
    request: Request,
    entry_id: int,
    project_id: int = Form(...),
    activity_type_id: int = Form(...),
    entry_date: str = Form(...),
    hours: float = Form(...),
    participants: str = Form(""),
    description: str = Form(""),
):
    client = _client()
    user = _current_user(client, request)
    if user is None:
        return _timesheet_page(request, error="Felhasználó azonosítása sikertelen")
    result = client.update_timesheet_entry(
        entry_id,
        user["id"],
        project_id,
        activity_type_id,
        entry_date,
        hours,
        participants or None,
        description or None,
    )
    return _timesheet_page(request, error=result.get("error"))


@router.delete("/timesheet/{entry_id}")
def delete_timesheet_entry(request: Request, entry_id: int):
    client = _client()
    user = _current_user(client, request)
    if user is None:
        return _timesheet_page(request, error="Felhasználó azonosítása sikertelen")
    result = client.delete_timesheet_entry(entry_id, user["id"])
    return _timesheet_page(request, error=result.get("error"))


def _resolve_date_range(
    date_range: str,
    date_from: str | None,
    date_to: str | None,
    project: dict | None,
    today: date,
) -> tuple[date | None, date | None]:
    if date_range == "custom":
        return (
            date.fromisoformat(date_from) if date_from else None,
            date.fromisoformat(date_to) if date_to else None,
        )
    if date_range == "project_start":
        if project is None:
            return None, None
        return date.fromisoformat(project["created_at"][:10]), None
    if date_range == "current_week":
        monday = today - timedelta(days=today.weekday())
        return monday, monday + timedelta(days=6)
    # current_month (also the fallback for an unrecognized value)
    first = today.replace(day=1)
    next_first = (
        first.replace(year=first.year + 1, month=1)
        if first.month == 12
        else first.replace(month=first.month + 1)
    )
    return first, next_first - timedelta(days=1)


def _parse_id(v: str | None) -> int | None:
    """Parse an optional numeric query param, treating "" (the "mind" option) as unset."""
    return int(v) if v else None


def _fmt_hours(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def _format_report_hours(report: dict) -> None:
    if "weeks" in report:
        for row in report["weeks"]:
            row["week_hours"] = _fmt_hours(row["week_hours"])
            row["cumulative_hours"] = _fmt_hours(row["cumulative_hours"])
            row["by_activity_type"] = {k: _fmt_hours(v) for k, v in row["by_activity_type"].items()}
        report["total_hours"] = _fmt_hours(report["total_hours"])
    elif "rows" in report:
        for row in report["rows"]:
            row["total_hours"] = _fmt_hours(row["total_hours"])
            row["by_activity_type"] = {k: _fmt_hours(v) for k, v in row["by_activity_type"].items()}
        for entry in report.get("entries", []):
            entry["hours"] = _fmt_hours(entry["hours"])
        report["total_hours"] = _fmt_hours(report["total_hours"])


def _format_period_label(
    date_range: str, resolved_from: date | None, resolved_to: date | None
) -> str:
    label = _DATE_RANGE_LABELS.get(date_range, date_range)
    if resolved_from and resolved_to:
        return f"{label} ({resolved_from.isoformat()} \N{EN DASH} {resolved_to.isoformat()})"
    if resolved_from:
        return f"{label} ({resolved_from.isoformat()}\N{EN DASH})"
    return label


def _reports_page(
    request: Request,
    report_type: str = "project",
    date_range: str = "current_month",
    date_from: str | None = None,
    date_to: str | None = None,
    customer_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    activity_type_id: str | None = None,
):
    customer_id = _parse_id(customer_id)
    project_id = _parse_id(project_id)
    user_id = _parse_id(user_id)
    activity_type_id = _parse_id(activity_type_id)

    client = _client()
    customers = client.get_customers()
    projects = client.get_projects()
    users = client.get_users()
    activity_types = [a for a in client.get_activity_types() if a["is_active"]]

    if report_type not in _REPORT_TYPES:
        report_type = "project"
    if date_range not in _DATE_RANGES:
        date_range = "current_month"

    if report_type == "project" and project_id is None and projects:
        project_id = projects[0]["id"]

    selected_project = next((p for p in projects if p["id"] == project_id), None)
    selected_customer = next((c for c in customers if c["id"] == customer_id), None)
    selected_user = next((u for u in users if u["id"] == user_id), None)
    selected_activity_type = next((a for a in activity_types if a["id"] == activity_type_id), None)

    header_project_label = selected_project["code"] if selected_project else "Összes projekt"
    if selected_customer is not None:
        header_customer_label = selected_customer["name"]
    elif selected_project is not None:
        header_customer_label = selected_project["customer_name"]
    else:
        header_customer_label = "Összes ügyfél"
    header_person_label = (
        (selected_user["name"] or selected_user["email"]) if selected_user else "Összes személy"
    )
    header_activity_type_label = (
        selected_activity_type["name"] if selected_activity_type else "Összes tevékenység típus"
    )

    ctx = {
        "report_type": report_type,
        "date_range": date_range,
        "date_from": date_from,
        "date_to": date_to,
        "customer_id": customer_id,
        "project_id": project_id,
        "user_id": user_id,
        "activity_type_id": activity_type_id,
        "customers": customers,
        "projects": projects,
        "users": users,
        "activity_types": activity_types,
        "report_types": _REPORT_TYPES,
        "report_type_labels": _REPORT_TYPE_LABELS,
        "date_ranges": _DATE_RANGES,
        "date_range_labels": _DATE_RANGE_LABELS,
        "selected_project": selected_project,
        "header_project_label": header_project_label,
        "header_customer_label": header_customer_label,
        "header_person_label": header_person_label,
        "header_activity_type_label": header_activity_type_label,
        "report": None,
        "error": None,
    }

    if report_type == "project" and selected_project is None:
        ctx["error"] = "Válasszon projektet a projekt riporthoz"
        return templates.TemplateResponse(request, "controlling_reports.html", ctx)

    resolved_from, resolved_to = _resolve_date_range(
        date_range, date_from, date_to, selected_project, local_today()
    )
    ctx["header_period_label"] = _format_period_label(date_range, resolved_from, resolved_to)
    report = client.get_timesheet_report(
        report_type,
        date_from=resolved_from.isoformat() if resolved_from else None,
        date_to=resolved_to.isoformat() if resolved_to else None,
        customer_id=customer_id,
        project_id=project_id,
        user_id=user_id,
        activity_type_id=activity_type_id,
    )
    if report_type == "project":
        report.setdefault("weeks", [])
    else:
        report.setdefault("rows", [])
        report.setdefault("entries", [])
    report.setdefault("activity_type_names", [])
    report.setdefault("total_hours", 0.0)

    _format_report_hours(report)
    ctx["report"] = report
    return templates.TemplateResponse(request, "controlling_reports.html", ctx)


@router.get("/reports")
def reports_page(
    request: Request,
    report_type: str = "project",
    date_range: str = "current_month",
    date_from: str | None = None,
    date_to: str | None = None,
    customer_id: str | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    activity_type_id: str | None = None,
):
    return _reports_page(
        request,
        report_type,
        date_range,
        date_from,
        date_to,
        customer_id,
        project_id,
        user_id,
        activity_type_id,
    )
