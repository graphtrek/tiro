"""FastAPI application for NAV Online Számla."""

import logging
import time
from datetime import UTC, date, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from nav_invoice import cache as _cache
from nav_invoice.auth import login
from nav_invoice.client import NavApiError
from nav_invoice.config import configure_logging, get_settings
from nav_invoice.invoice_data import parse_invoice_data
from nav_invoice.jwt_auth import require_auth
from nav_invoice.models import (
    DigestQueryParams,
    InvoiceDigest,
    InvoiceDirection,
    SubmitInvoiceRequest,
    SubmitInvoiceResponse,
)
from nav_invoice.query import query_invoice_data, query_invoice_digest
from nav_invoice.reporting import submit_invoice

configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NAV Online Számla API",
    description="REST API for querying and submitting NAV invoices.",
    version="0.1.0",
    dependencies=[Depends(require_auth)],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    logger.info("%s %s → %d in %.0fms", request.method, path, response.status_code, elapsed_ms)
    return response


# ── Health check ───────────────────────────────────────

@app.get("/health")
def health_check():
    """Service health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(tz=UTC).isoformat()}


# ── Authentication ─────────────────────────────────────

@app.post("/auth/login")
def auth_login():
    """Authenticate with NAV (Bejelentkezés)."""
    result = login()

    if not result.get("success"):
        raise HTTPException(status_code=401, detail=result.get("error", "Login failed"))

    return result


# ── Invoice listing (queryInvoiceDigest) ───────────────

@app.get("/invoices", response_model=list[InvoiceDigest])
def get_invoices(
    from_date: date | None = Query(None, description="Start date"),
    to_date: date | None = Query(None, description="End date"),
    direction: InvoiceDirection = Query(InvoiceDirection.OUTBOUND),
    page: int = Query(1, ge=1),
):
    """List invoices from NAV (queryInvoiceDigest)."""
    params = DigestQueryParams(
        from_date=from_date or (datetime.now(tz=UTC).astimezone().date() - timedelta(days=30)),
        to_date=to_date or datetime.now(tz=UTC).astimezone().date(),
        direction=direction,
        page=page,
    )

    try:
        return query_invoice_digest(params)
    except NavApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/invoices/{szamlaszam}")
def get_invoice(
    szamlaszam: str,
    direction: InvoiceDirection = Query(InvoiceDirection.OUTBOUND),
    supplier_tax_number: str | None = Query(None),
):
    """Get a single invoice's decoded XML + parsed detail fields (queryInvoiceData)."""
    try:
        invoice_xml = query_invoice_data(
            szamlaszam, direction, supplier_tax_number=supplier_tax_number or ""
        )
    except NavApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not invoice_xml:
        raise HTTPException(status_code=404, detail=f"Invoice {szamlaszam} not found")

    detail = parse_invoice_data(invoice_xml, invoice_number=szamlaszam)
    return {"szamlaszam": szamlaszam, "invoice_xml": invoice_xml, **detail.model_dump()}


# ── Reporting (Adatszolgáltatás) ───────────────────────

@app.post("/report", response_model=SubmitInvoiceResponse)
def report_invoice(request: SubmitInvoiceRequest):
    """Submit an invoice to NAV (Adatszolgáltatás)."""
    result = submit_invoice(request)

    if not result.success:
        raise HTTPException(status_code=502, detail=result.message)

    return result


# ── Cache ──────────────────────────────────────────────

@app.post("/cache/clear")
def cache_clear():
    """Clear the in-memory query cache."""
    cleared = _cache.clear()
    return {"cleared": cleared, "message": f"{cleared} bejegyzés törölve a cache-ből"}


# ── Settings info ──────────────────────────────────────

@app.get("/settings")
def get_settings_info():
    """Return current configuration."""
    settings = get_settings()

    return {
        "username": settings.username,
        "environment": settings.environment,
        "endpoint": settings.endpoint,
        "is_production": settings.is_production,
    }


# ── Run server ─────────────────────────────────────────

def run_server():
    """Start the FastAPI development server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "nav_invoice.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    run_server()