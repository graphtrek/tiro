"""UI routes for the Vision dashboard."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from vision.services import dashboard_service

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(tags=["ui"])


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "home.html", {"request": request})


@router.get("/pitch")
def pitch(request: Request):
    return templates.TemplateResponse(request, "pitch.html", {"request": request})


@router.get("/dashboard")
def dashboard(request: Request):
    data = dashboard_service.get_dashboard_data()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "data": data,
            # dataclasses.asdict() needed because Jinja2's tojson filter
            # cannot serialize Python dataclass instances directly
            "cashflow_json": [dataclasses.asdict(m) for m in data.cashflow_months],
            "top_suppliers_json": [dataclasses.asdict(s) for s in data.top_suppliers],
            "status_counts_json": data.invoice_status_counts,
            "srcprofit_positions_json": data.srcprofit_positions,
        },
    )
