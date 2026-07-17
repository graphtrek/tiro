"""Controlling UI routes — Projects + Timesheet (real DB-backed CRUD) +
remaining static mockup pages (reports). Remove a mockup entry from `_PAGES`
once its own real backend lands, same as `projects` and `timesheet` did.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates

from vision.clients.invoice_core import InvoiceCoreClient

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui/controlling", tags=["controlling-ui"])

_PAGES = {
    "reports": "controlling_reports.html",
}

_HU_WEEKDAYS = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]


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
        row["hours_label"] = ("%g" % row["hours"]).replace(".", ",")

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


@router.get("/{slug}")
def controlling_page(request: Request, slug: str):
    if slug not in _PAGES:
        raise HTTPException(status_code=404, detail="Ismeretlen controlling oldal")
    return templates.TemplateResponse(request, _PAGES[slug], {})
