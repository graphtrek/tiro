"""Controlling UI routes — Projects (real DB-backed CRUD) + remaining static
mockup pages (timesheet, reports). Remove a mockup entry from `_PAGES` once its
own real backend lands, same as `projects` just did.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates

from vision.clients.invoice_core import InvoiceCoreClient

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui/controlling", tags=["controlling-ui"])

_PAGES = {
    "timesheet": "controlling_timesheet.html",
    "reports": "controlling_reports.html",
}


def _client() -> InvoiceCoreClient:
    return InvoiceCoreClient()


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


@router.get("/{slug}")
def controlling_page(request: Request, slug: str):
    if slug not in _PAGES:
        raise HTTPException(status_code=404, detail="Ismeretlen controlling oldal")
    return templates.TemplateResponse(request, _PAGES[slug], {})
