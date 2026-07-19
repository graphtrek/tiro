"""UI routes for the Vision dashboard."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from vision.config import Settings, get_settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(tags=["ui"])


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "pitch.html", {"request": request})


@router.get("/pitch")
def pitch():
    return RedirectResponse("/", status_code=308)


def _load_providers(settings: Settings) -> list[dict]:
    """Provider gombok az auth szerviztől; ha nem érhető el, Google fallback."""
    try:
        resp = requests.get(f"{settings.auth_service_url}/auth/providers", timeout=2)
        resp.raise_for_status()
        providers = resp.json()
        for provider in providers:
            provider["login_url"] = f"{settings.auth_public_url_or_default}{provider['login_url']}"
        if providers:
            return providers
    except requests.RequestException as exc:
        logger.warning("Auth szerviz providers nem érhető el: %s", exc)
    return [
        {
            "key": "google",
            "label": "Belépés Google-fiókkal",
            "icon": "bi-google",
            "login_url": f"{settings.auth_public_url_or_default}/auth/google/login",
        },
    ]


@router.get("/login")
def login(request: Request, next: str | None = None, error: str | None = None):
    """NiceAdmin-style login page — provider-based sign-in only."""
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "providers": _load_providers(settings),
            "next": next or "/ui/",
            "error": error,
            "auth_service_url": settings.auth_public_url_or_default,
            "current_year": date.today().year,
        },
    )


@router.get("/logout")
def logout(request: Request):
    """Kijelentkezés: refresh token visszavonása az auth szerviznél + cookie törlés."""
    settings = get_settings()
    access = request.cookies.get("mp_access_token")
    refresh = request.cookies.get("mp_refresh_token")
    if access:
        try:
            requests.post(
                f"{settings.auth_service_url}/auth/logout",
                headers={"Authorization": f"Bearer {access}"},
                cookies={"mp_refresh_token": refresh} if refresh else None,
                timeout=settings.request_timeout,
            )
        except requests.RequestException as exc:
            logger.warning("Auth szerviz logout nem érhető el: %s", exc)
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("mp_access_token", path="/")
    response.delete_cookie("mp_refresh_token", path="/")
    return response
