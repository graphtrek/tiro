"""FastAPI app for invoice-core."""

from __future__ import annotations

import dataclasses
import logging
import time
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy import insert as sa_insert
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from invoice_core.config import configure_logging, get_settings
from invoice_core.db import (
    BankTransaction,
    Customer,
    Invoice,
    InvoiceFile,
    Supplier,
    _PaymentStatus,
    get_db,
    invoice_bank_transaction,
)
from invoice_core.models import (
    CustomerOut,
    InvoiceOut,
    LinkFileRequest,
    PatchInvoiceRequest,
    SupplierOut,
    SyncMode,
    SyncRequest,
    SyncResponse,
)
from invoice_core.service import _recompute_payment_status, sync_all
from invoice_core.services import (
    dashboard_service,
    dividend_service,
    invoice_file_service,
    invoice_service,
    partner_service,
    tax_service,
    transaction_service,
)

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Invoice Core",
    description="Master orchestrator for the Moneypenny invoice automation pipeline.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8009"],
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/api/v1/sync/logs")
def sync_logs(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    logs = dashboard_service.get_sync_logs(db, limit=limit)
    return [dataclasses.asdict(log) for log in logs]


# ── Dashboard endpoint ────────────────────────────────────────────────────────

@app.get("/api/v1/dashboard")
def dashboard(db: Session = Depends(get_db)):
    """Aggregate the KPI cards, recent lists, and last-sync info shown on the dashboard page."""
    last_sync = dashboard_service.get_last_sync(db)
    return {
        "kpis": dataclasses.asdict(dashboard_service.get_kpis(db)),
        "recent_invoices": [dataclasses.asdict(r) for r in dashboard_service.get_recent_invoices(db)],
        "recent_transactions": [dataclasses.asdict(r) for r in dashboard_service.get_recent_transactions(db)],
        "last_sync": dataclasses.asdict(last_sync) if last_sync else None,
        "top_suppliers": [dataclasses.asdict(r) for r in dashboard_service.get_top_suppliers(db)],
    }


# ── Invoice endpoints ─────────────────────────────────────────────────────────

@app.get("/api/v1/invoices/count")
def invoice_count(db: Session = Depends(get_db)):
    count = db.query(func.count(Invoice.id)).scalar() or 0
    return {"count": count}


@app.get("/api/v1/invoices")
def list_invoices(
    date_from: Optional[_date] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[_date] = Query(None, description="YYYY-MM-DD"),
    status: Optional[str] = Query(None, description="PAID | UNPAID | PARTIAL"),
    direction: Optional[str] = Query(None, description="INBOUND | OUTBOUND"),
    has_pdf: Optional[str] = Query(None, description="true | false"),
    supplier_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    rows = invoice_service.list_invoices(
        db,
        date_from=date_from,
        date_to=date_to,
        payment_status=status,
        has_pdf=has_pdf,
        supplier_name=supplier_name,
    )
    if direction:
        rows = [r for r in rows if r.direction == direction]
    return [dataclasses.asdict(r) for r in rows]


# Two routes exist for fetching a single invoice: one by numeric database id
# ("/invoices/42") and one by the invoice's business number ("/invoices/HU-42").
# FastAPI matches routes in the order they're declared, so the `{invoice_id:int}`
# route (which only matches all-digit paths) MUST be declared before the more
# general `{invoice_number}` route below it — otherwise every request would be
# swallowed by the string route and the int route would never match.
@app.get("/api/v1/invoices/{invoice_id:int}")
def get_invoice_by_id(invoice_id: int, db: Session = Depends(get_db)):
    inv = invoice_service.get_invoice(db, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return dataclasses.asdict(inv)


@app.get("/api/v1/invoices/{invoice_number}", response_model=InvoiceOut)
def get_invoice(invoice_number: str, db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter_by(invoice_number=invoice_number).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@app.patch("/api/v1/invoices/{invoice_id:int}")
def patch_invoice(invoice_id: int, req: PatchInvoiceRequest, db: Session = Depends(get_db)):
    """Apply up to three independent, optional edits to one invoice.

    Each field on `req` is handled separately and only touched if the caller
    actually sent it (`is not None`) — so a request can update just the note,
    just the lock flag, just the status, or any combination, without needing
    to resend the invoice's other current values.
    """
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if req.note is not None:
        inv.note = req.note or None
    if req.payment_status_locked is not None:
        inv.payment_status_locked = req.payment_status_locked
    if req.payment_status is not None:
        try:
            inv.payment_status = _PaymentStatus[req.payment_status]
        except KeyError:
            raise HTTPException(status_code=422, detail=f"Invalid payment_status: {req.payment_status}")
    inv.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


# ── Invoice file endpoints ────────────────────────────────────────────────────

@app.get("/api/v1/invoice-files")
def list_invoice_files(
    linked: Optional[str] = Query(None, description="yes | no"),
    filename: Optional[str] = Query(None, description="filename substring filter"),
    db: Session = Depends(get_db),
):
    rows = invoice_file_service.list_invoice_files(db, linked=linked, filename=filename)
    return [dataclasses.asdict(r) for r in rows]


@app.get("/api/v1/invoice-files/{file_id:int}/pdf")
def invoice_file_pdf(file_id: int, db: Session = Depends(get_db)):
    invoice_file = db.get(InvoiceFile, file_id)
    if not invoice_file or not invoice_file.path:
        raise HTTPException(status_code=404, detail="PDF nem található")
    p = Path(invoice_file.path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="PDF fájl nem elérhető")
    return FileResponse(
        p,
        media_type="application/pdf",
        filename=invoice_file.filename,
        content_disposition_type="inline",
    )


@app.patch("/api/v1/invoice-files/{file_id:int}")
def delete_invoice_file(file_id: int, db: Session = Depends(get_db)):
    """Soft-delete an invoice file: mark it hidden without removing the DB row or the PDF on disk.

    This is a PATCH (not a DELETE) on purpose — the file record and the
    physical PDF both stay in place, only the `is_deleted` flag flips to True,
    so the file simply stops appearing in file lists but can still be
    inspected/restored later if needed.
    """
    invoice_file = db.get(InvoiceFile, file_id)
    if not invoice_file:
        raise HTTPException(status_code=404, detail="Invoice file not found")
    if invoice_file.is_deleted:
        raise HTTPException(status_code=409, detail="This invoice file is already deleted")
    invoice_file.is_deleted = True
    invoice_file.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "id": file_id, "filename": invoice_file.filename}


# ── Partner endpoints ─────────────────────────────────────────────────────────

@app.get("/api/v1/partners/suppliers/summary")
def supplier_summary(db: Session = Depends(get_db)):
    return dataclasses.asdict(partner_service.get_supplier_summary(db))


@app.get("/api/v1/partners/suppliers")
def list_suppliers(db: Session = Depends(get_db)):
    return [dataclasses.asdict(r) for r in partner_service.list_suppliers(db)]


@app.get("/api/v1/partners/suppliers/{supplier_id:int}")
def get_supplier(supplier_id: int, db: Session = Depends(get_db)):
    supplier = partner_service.get_supplier(db, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return dataclasses.asdict(supplier)


@app.get("/api/v1/partners/customers")
def list_customers(db: Session = Depends(get_db)):
    return [dataclasses.asdict(r) for r in partner_service.list_customers(db)]


@app.get("/api/v1/partners/customers/{customer_id:int}")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = partner_service.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return dataclasses.asdict(customer)


# ── Transaction endpoints ─────────────────────────────────────────────────────

@app.get("/api/v1/transactions/balances")
def transaction_balances(db: Session = Depends(get_db)):
    balances = transaction_service.get_bank_balances(db)
    return [dataclasses.asdict(b) for b in balances]


@app.get("/api/v1/transactions")
def list_transactions(
    date_from: Optional[_date] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[_date] = Query(None, description="YYYY-MM-DD"),
    linked: Optional[str] = Query(None, description="yes | no"),
    partner_name: Optional[str] = Query(None),
    amount_min: Optional[float] = Query(None),
    amount_max: Optional[float] = Query(None),
    db: Session = Depends(get_db),
):
    rows = transaction_service.list_transactions(
        db,
        date_from=date_from,
        date_to=date_to,
        linked=linked,
        partner_name=partner_name,
        amount_min=amount_min,
        amount_max=amount_max,
    )
    return [dataclasses.asdict(r) for r in rows]


@app.get("/api/v1/transactions/{transaction_id:int}")
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    tx = transaction_service.get_transaction(db, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return dataclasses.asdict(tx)


# ── Manual link / unlink endpoints ───────────────────────────────────────────

@app.put("/api/v1/invoices/{invoice_id}/invoice-file")
def link_invoice_to_file(invoice_id: int, req: LinkFileRequest, db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    f = db.get(InvoiceFile, req.invoice_file_id)
    if not f:
        raise HTTPException(status_code=404, detail="InvoiceFile not found")
    inv.invoice_file_id = req.invoice_file_id
    inv.invoice_file_locked = True
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/invoices/{invoice_id}/invoice-file")
def unlink_invoice_from_file(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv.invoice_file_id = None
    inv.invoice_file_locked = False
    db.commit()
    return {"ok": True}


@app.put("/api/v1/transactions/{txn_id}/invoice-file")
def link_transaction_to_file(txn_id: int, req: LinkFileRequest, db: Session = Depends(get_db)):
    txn = db.get(BankTransaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    f = db.get(InvoiceFile, req.invoice_file_id)
    if not f:
        raise HTTPException(status_code=404, detail="InvoiceFile not found")
    txn.invoice_file_id = req.invoice_file_id
    txn.invoice_file_locked = True
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/transactions/{txn_id}/invoice-file")
def unlink_transaction_from_file(txn_id: int, db: Session = Depends(get_db)):
    txn = db.get(BankTransaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    txn.invoice_file_id = None
    txn.invoice_file_locked = False
    db.commit()
    return {"ok": True}


@app.put("/api/v1/invoices/{invoice_id}/transactions/{txn_id}")
def link_invoice_to_transaction(invoice_id: int, txn_id: int, db: Session = Depends(get_db)):
    if not db.get(Invoice, invoice_id):
        raise HTTPException(status_code=404, detail="Invoice not found")
    if not db.get(BankTransaction, txn_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    existing = db.execute(
        sa_select(invoice_bank_transaction).where(
            invoice_bank_transaction.c.invoice_id == invoice_id,
            invoice_bank_transaction.c.bank_transaction_id == txn_id,
        )
    ).first()
    if not existing:
        db.execute(sa_insert(invoice_bank_transaction).values(
            invoice_id=invoice_id, bank_transaction_id=txn_id, manual=True,
        ))
    inv = db.get(Invoice, invoice_id)
    _recompute_payment_status(db, inv)
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/invoices/{invoice_id}/transactions/{txn_id}")
def unlink_invoice_from_transaction(invoice_id: int, txn_id: int, db: Session = Depends(get_db)):
    if not db.get(Invoice, invoice_id):
        raise HTTPException(status_code=404, detail="Invoice not found")
    db.execute(
        sa_delete(invoice_bank_transaction).where(
            invoice_bank_transaction.c.invoice_id == invoice_id,
            invoice_bank_transaction.c.bank_transaction_id == txn_id,
        )
    )
    inv = db.get(Invoice, invoice_id)
    _recompute_payment_status(db, inv)
    db.commit()
    return {"ok": True}


# ── Report endpoints ──────────────────────────────────────────────────────────

@app.get("/api/v1/reports/dividend")
def dividend_report(
    year: Optional[int] = Query(None, description="Year (default: current year)"),
    kiva_rate: float = Query(0.10, description="KIVA tax rate (default 0.10)"),
    db: Session = Depends(get_db),
):
    """Estimate dividend for *year*, defaulting to the current year if omitted.

    `kiva_rate` is passed in as the corporate-level tax rate instead of the
    9% TAO default inside `calculate_dividend`: in Hungary a company pays
    either TAO (corporate income tax) or KIVA (a small-business flat-tax
    alternative), never both, so this lets a KIVA-taxed company get an
    accurate estimate using their own rate instead of the TAO default.
    """
    effective_year = year or _date.today().year
    report = dividend_service.calculate_dividend(db, effective_year, kiva_rate)
    return dataclasses.asdict(report)


@app.get("/api/v1/reports/tax")
def tax_report(
    year: Optional[int] = Query(None, description="Year (default: current year)"),
    db: Session = Depends(get_db),
):
    """Summarize *year*'s payments to tax-authority accounts, defaulting to the current year."""
    effective_year = year or _date.today().year
    report = tax_service.get_tax_report(db, effective_year)
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
