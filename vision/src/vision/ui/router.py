"""UI routes for the Vision dashboard."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from vision.clients.invoice_core import InvoiceCoreClient
from vision.services import dashboard_service

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"])


def _invoice_count() -> int:
    try:
        return InvoiceCoreClient().get_invoice_count()
    except Exception as exc:
        logger.warning("invoice_count fetch failed: %s", exc)
        return 0


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "home.html", {
        "request": request,
        "invoice_count": _invoice_count(),
    })


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
            "invoice_count": _invoice_count(),
            "data": data,
            # dataclasses.asdict() needed because Jinja2's tojson filter
            # cannot serialize Python dataclass instances directly
            "cashflow_json": [dataclasses.asdict(m) for m in data.cashflow_months],
            "top_suppliers_json": [dataclasses.asdict(s) for s in data.top_suppliers],
            "status_counts_json": data.invoice_status_counts,
            "srcprofit_positions_json": data.srcprofit_positions,
        },
    )
