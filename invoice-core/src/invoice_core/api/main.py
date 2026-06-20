"""FastAPI app for invoice-core."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from invoice_core.config import configure_logging, get_settings
from invoice_core.db import BankTransaction, Customer, Invoice, Supplier, get_db, invoice_has_bank_txn
from invoice_core.models import (
    BankTransactionOut,
    CustomerOut,
    InvoiceDirection,
    InvoiceOut,
    PaymentStatus,
    SupplierOut,
    SyncMode,
    SyncRequest,
    SyncResponse,
)
from invoice_core.service import sync_all
from invoice_core.ui.router import router as ui_router

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(
    title="Invoice Core",
    description="Master orchestrator for the Moneypenny invoice automation pipeline.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
app.include_router(ui_router)


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


@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ── Sync endpoints ────────────────────────────────────────────────────────────

@app.post("/api/v1/sync", response_model=SyncResponse)
def full_sync(request: SyncRequest, db: Session = Depends(get_db)):
    return sync_all(request, db)


@app.post("/api/v1/sync/nav", response_model=SyncResponse)
def nav_sync(request: SyncRequest, db: Session = Depends(get_db)):
    request.sync_mode = SyncMode.nav_only
    return sync_all(request, db)


@app.post("/api/v1/sync/pdf", response_model=SyncResponse)
def pdf_sync(request: SyncRequest, db: Session = Depends(get_db)):
    request.sync_mode = SyncMode.pdf_only
    return sync_all(request, db)


@app.post("/api/v1/sync/bank", response_model=SyncResponse)
def bank_sync(request: SyncRequest, db: Session = Depends(get_db)):
    request.sync_mode = SyncMode.bank_only
    return sync_all(request, db)


@app.post("/api/v1/sync/match", response_model=SyncResponse)
def match_sync(request: SyncRequest, db: Session = Depends(get_db)):
    request.sync_mode = SyncMode.match_only
    return sync_all(request, db)


# ── Query endpoints ───────────────────────────────────────────────────────────

@app.get("/api/v1/invoices", response_model=List[InvoiceOut])
def list_invoices(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    status: Optional[PaymentStatus] = Query(None),
    direction: Optional[InvoiceDirection] = Query(None),
    db: Session = Depends(get_db),
):
    from sqlalchemy import or_

    from invoice_core.db import _InvoiceDirection, _PaymentStatus
    q = db.query(Invoice)
    if date_from:
        q = q.filter(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(Invoice.invoice_date <= date_to)
    if status == PaymentStatus.PAID:
        q = q.filter(or_(Invoice.payment_status == _PaymentStatus.PAID, invoice_has_bank_txn()))
    elif status:
        q = q.filter(Invoice.payment_status == _PaymentStatus[status.value], ~invoice_has_bank_txn())
    if direction:
        q = q.filter(Invoice.direction == _InvoiceDirection[direction.value])

    invoices = q.all()
    paid_via_bank = {
        r[0]
        for r in db.query(BankTransaction.invoice_id)
        .filter(BankTransaction.invoice_id.isnot(None))
        .distinct()
    }
    from invoice_core.db import _PaymentStatus
    for inv in invoices:
        if inv.id in paid_via_bank:
            inv.payment_status = _PaymentStatus.PAID
    return invoices


@app.get("/api/v1/invoices/{invoice_number}", response_model=InvoiceOut)
def get_invoice(invoice_number: str, db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter_by(invoice_number=invoice_number).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@app.get("/api/v1/partners/suppliers", response_model=List[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)):
    return db.query(Supplier).all()


@app.get("/api/v1/partners/customers", response_model=List[CustomerOut])
def list_customers(db: Session = Depends(get_db)):
    return db.query(Customer).all()


@app.get("/api/v1/transactions", response_model=List[BankTransactionOut])
def list_transactions(db: Session = Depends(get_db)):
    return db.query(BankTransaction).all()


# ── Reports ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/reports/dividend")
def dividend_report(
    year: Optional[int] = Query(None, description="Year (default: current year)"),
    kiva_rate: float = Query(0.10, description="KIVA tax rate (default 0.10)"),
    db: Session = Depends(get_db),
):
    import dataclasses
    from datetime import date as _date
    from invoice_core.services.dividend_service import calculate_dividend
    effective_year = year or _date.today().year
    report = calculate_dividend(db, effective_year, kiva_rate)
    return dataclasses.asdict(report)


def run_server():
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "invoice_core.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    run_server()
