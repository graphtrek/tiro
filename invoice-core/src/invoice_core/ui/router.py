from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from invoice_core.db import Invoice, SyncLog, get_db
from invoice_core.models import SyncMode, SyncRequest
from invoice_core.service import sync_all
from invoice_core.services import dashboard_service, invoice_file_service, invoice_service, partner_service, transaction_service
from invoice_core.services.invoice_file_service import InvoiceFileFilters
from invoice_core.services.invoice_service import InvoiceFilters
from invoice_core.services.transaction_service import TransactionFilters

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui", tags=["ui"])


def _invoice_count(db: Session) -> int:
    try:
        return db.query(func.count(Invoice.id)).scalar() or 0
    except Exception:
        db.rollback()
        return 0


def _ctx(db: Session, **kwargs) -> dict:
    return {"invoice_count": _invoice_count(db), **kwargs}


def _resp(request: Request, template: str, db: Session, **kwargs):
    return templates.TemplateResponse(request, template, _ctx(db, **kwargs))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    return _resp(request, "dashboard.html", db,
        kpis=dashboard_service.get_kpis(db),
        recent_invoices=dashboard_service.get_recent_invoices(db),
        recent_transactions=dashboard_service.get_recent_transactions(db),
        last_sync=dashboard_service.get_last_sync(db),
    )


# ── Invoices ──────────────────────────────────────────────────────────────────

@router.get("/invoices")
def invoices_page(
    request: Request,
    filters: InvoiceFilters = Depends(),
    db: Session = Depends(get_db),
):
    rows = invoice_service.list_invoices(
        db,
        date_from=filters.date_from,
        date_to=filters.date_to,
        payment_status=filters.payment_status,
        has_pdf=filters.has_pdf,
        supplier_name=filters.supplier_name,
    )
    is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "partials/invoice_table.html" if is_partial else "invoices.html"
    return _resp(request, template, db, rows=rows)


@router.get("/invoices/{invoice_id:int}")
def invoice_detail_page(request: Request, invoice_id: int, db: Session = Depends(get_db)):
    invoice = invoice_service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", db, invoice=invoice)


# ── Invoice Files ─────────────────────────────────────────────────────────────

@router.get("/invoice-files")
def invoice_files_page(
    request: Request,
    filters: InvoiceFileFilters = Depends(),
    db: Session = Depends(get_db),
):
    rows = invoice_file_service.list_invoice_files(db, linked=filters.linked)
    return _resp(request, "invoice_files.html", db, rows=rows)


# ── Suppliers ─────────────────────────────────────────────────────────────────

@router.get("/suppliers")
def suppliers_page(request: Request, db: Session = Depends(get_db)):
    rows = partner_service.list_suppliers(db)
    is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "partials/supplier_table.html" if is_partial else "suppliers.html"
    return _resp(request, template, db, rows=rows)


@router.get("/suppliers/{supplier_id:int}")
def supplier_detail_page(request: Request, supplier_id: int, db: Session = Depends(get_db)):
    supplier = partner_service.get_supplier(db, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Szállító nem található")
    return _resp(request, "supplier_detail.html", db, supplier=supplier)


# ── Customers ─────────────────────────────────────────────────────────────────

@router.get("/customers")
def customers_page(request: Request, db: Session = Depends(get_db)):
    rows = partner_service.list_customers(db)
    return _resp(request, "customers.html", db, rows=rows)


@router.get("/customers/{customer_id:int}")
def customer_detail_page(request: Request, customer_id: int, db: Session = Depends(get_db)):
    customer = partner_service.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Vevő nem található")
    return _resp(request, "customer_detail.html", db, customer=customer)


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/transactions")
def transactions_page(
    request: Request,
    filters: TransactionFilters = Depends(),
    db: Session = Depends(get_db),
):
    rows = transaction_service.list_transactions(
        db,
        date_from=filters.date_from,
        date_to=filters.date_to,
        linked=filters.linked,
        partner_name=filters.partner_name,
        amount_min=filters.amount_min,
        amount_max=filters.amount_max,
    )
    is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "partials/transaction_table.html" if is_partial else "transactions.html"
    return _resp(request, template, db, rows=rows)


# ── Sync ──────────────────────────────────────────────────────────────────────

@router.get("/sync")
def sync_page(request: Request, db: Session = Depends(get_db)):
    sync_logs = dashboard_service.get_sync_logs(db)
    return _resp(request, "sync.html", db, sync_logs=sync_logs, result=None)


@router.post("/sync/trigger")
def sync_trigger(
    request: Request,
    date_from: Optional[str] = Form(None),
    date_to: Optional[str] = Form(None),
    sync_mode: Optional[str] = Form("full"),
    db: Session = Depends(get_db),
):
    mode = SyncMode.full
    try:
        if sync_mode:
            mode = SyncMode(sync_mode)
    except ValueError:
        pass

    log = SyncLog(started_at=datetime.utcnow(), mode=mode.value)
    db.add(log)
    db.flush()

    t0 = time.monotonic()
    sync_req = SyncRequest(start_date=date_from or None, end_date=date_to or None, sync_mode=mode)
    result = sync_all(sync_req, db)
    elapsed = time.monotonic() - t0

    log.finished_at = datetime.utcnow()
    log.invoice_count = result.nav_invoices_synced
    log.wise_count = result.wise_transactions_synced
    log.error_count = len(result.errors)
    log.errors = "; ".join(result.errors) if result.errors else None
    db.commit()

    ctx = _ctx(db,
        result=result,
        duration_s=elapsed,
    )
    return templates.TemplateResponse(request, "partials/sync_result.html", ctx)
