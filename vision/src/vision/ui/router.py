"""UI routes for the Vision dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(tags=["ui"])


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "pitch.html", {"request": request})


@router.get("/pitch")
def pitch():
    return RedirectResponse("/", status_code=308)
