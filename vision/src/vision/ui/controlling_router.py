"""Controlling mockup routes — upcoming features, no backend.

Static mock pages in the Vision design (mock data hard-coded in the
templates). Remove once the real controlling backend lands.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui/controlling", tags=["controlling-ui"])

_PAGES = {
    "timesheet": "controlling_timesheet.html",
    "reports": "controlling_reports.html",
    "projects": "controlling_projects.html",
    "activity-types": "controlling_activity_types.html",
}


@router.get("/{slug}")
def controlling_page(request: Request, slug: str):
    if slug not in _PAGES:
        raise HTTPException(status_code=404, detail="Ismeretlen controlling oldal")
    return templates.TemplateResponse(request, _PAGES[slug], {})
