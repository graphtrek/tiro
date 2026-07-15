"""UI routes for the Vision dashboard."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from vision.config import get_settings

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(tags=["ui"])


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "pitch.html", {"request": request})


@router.get("/pitch")
def pitch():
    return RedirectResponse("/", status_code=308)


@router.get("/login")
def login(request: Request, next: str | None = None, error: str | None = None):
    """NiceAdmin-style login page — provider-based sign-in only.

    Extend the list below to enable further providers (Microsoft, GitHub, ...);
    the template renders one button per entry.
    """
    settings = get_settings()
    providers = [
        {
            "key": "google",
            "label": "Belépés Google-fiókkal",
            "icon": "bi-google",
            "login_url": f"{settings.auth_service_url}/auth/google/login",
        },
    ]
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "providers": providers,
            "next": next,
            "error": error,
            "current_year": date.today().year,
        },
    )
