"""Admin UI routes served by vision — users + activity types (real data), controlling mockups."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates

from vision.clients.invoice_core import InvoiceCoreClient
from vision.ui.utils import dict_to_ns

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui/admin", tags=["admin-ui"])


def _client() -> InvoiceCoreClient:
    return InvoiceCoreClient()


@router.get("/users")
def users_page(request: Request):
    client = _client()
    rows = dict_to_ns(client.get_users())
    return templates.TemplateResponse(request, "admin_users.html", {"rows": rows})


def _activity_types_page(request: Request, error: str | None = None):
    rows = dict_to_ns(_client().get_activity_types())
    return templates.TemplateResponse(
        request, "admin_activity_types.html", {"rows": rows, "error": error}
    )


@router.get("/activity-types")
def activity_types_page(request: Request):
    return _activity_types_page(request)


@router.post("/activity-types")
def create_activity_type(request: Request, name: str = Form(...)):
    result = _client().create_activity_type(name)
    return _activity_types_page(request, error=result.get("error"))


@router.post("/activity-types/{activity_type_id}")
def update_activity_type(
    request: Request,
    activity_type_id: int,
    name: str = Form(...),
    is_active: bool = Form(False),
):
    result = _client().update_activity_type(activity_type_id, name, is_active)
    return _activity_types_page(request, error=result.get("error"))


@router.post("/activity-types/{activity_type_id}/deactivate")
def deactivate_activity_type(request: Request, activity_type_id: int, name: str = Form(...)):
    result = _client().update_activity_type(activity_type_id, name, is_active=False)
    return _activity_types_page(request, error=result.get("error"))


@router.delete("/activity-types/{activity_type_id}/delete")
def delete_activity_type(request: Request, activity_type_id: int):
    result = _client().delete_activity_type(activity_type_id)
    return _activity_types_page(request, error=result.get("error"))
