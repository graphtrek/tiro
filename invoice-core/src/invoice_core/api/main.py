"""FastAPI app for invoice-core."""

from __future__ import annotations

import dataclasses
import logging
import time
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy import insert as sa_insert
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from invoice_core.auth import require_auth
from invoice_core.config import configure_logging, get_settings
from invoice_core.db import (
    BankTransaction,
    Customer,
    Invoice,
    InvoiceFile,
    SessionLocal,
    Supplier,
    _PaymentStatus,
    get_db,
    invoice_bank_transaction,
)
from invoice_core.models import (
    ActivityTypeIn,
    ActivityTypeOut,
    ActivityTypeUpdate,
    AuditLogOut,
    CustomerIn,
    CustomerOut,
    CustomerUpdate,
    InvoiceOut,
    LinkCustomerRequest,
    LinkFileRequest,
    LinkSupplierRequest,
    PatchInvoiceRequest,
    ProjectIn,
    ProjectOut,
    ProjectUpdate,
    SupplierIn,
    SupplierOut,
    SupplierUpdate,
    SyncMode,
    SyncRequest,
    SyncResponse,
    TimesheetEntryIn,
    TimesheetEntryOut,
    TimesheetEntryUpdate,
    UserIn,
    UserOut,
)
from invoice_core.service import (
    SyncInProgressError,
    _recompute_payment_status,
    get_pending_sync_counts,
    sync_all,
)
from invoice_core.services import (
    activity_type_service,
    audit_service,
    dashboard_service,
    dividend_service,
    invoice_file_service,
    invoice_service,
    partner_service,
    project_service,
    report_service,
    tax_service,
    timesheet_service,
    transaction_service,
    user_service,
)
from invoice_core.timeutil import today, utcnow

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Invoice Core",
    description="Master orchestrator for the Moneypenny invoice automation pipeline.",
    version="0.1.0",
    dependencies=[Depends(require_auth)],
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


# In-process debounce so a single page view (which fires several backend calls)
# doesn't turn into that many "last_login_at" writes — only bump once per user
# per window.
_LAST_TOUCH_WINDOW_S = 60.0
_last_touch: dict[tuple[str, str], float] = {}


@app.middleware("http")
async def touch_last_login(request: Request, call_next):
    response = await call_next(request)
    claims = getattr(request.state, "user", None)
    if claims:
        provider, sub = claims.get("provider"), claims.get("sub")
        if provider and sub:
            now = time.monotonic()
            key = (provider, sub)
            if now - _last_touch.get(key, 0.0) >= _LAST_TOUCH_WINDOW_S:
                _last_touch[key] = now
                db = SessionLocal()
                try:
                    user_service.touch_last_login(db, provider, sub)
                except Exception as exc:  # noqa: BLE001 - best-effort, must never break the request
                    logger.warning("Nem sikerült frissíteni a last_login_at mezőt: %s", exc)
                finally:
                    db.close()
    return response


@app.middleware("http")
async def record_audit_log(request: Request, call_next):
    # Resolved *before* the mutation runs: a DELETE removes the row, so
    # looking up its name/number afterwards would find nothing.
    db = SessionLocal()
    try:
        prepared = audit_service.prepare_record(db, request)
    except Exception as exc:  # noqa: BLE001 - best-effort audit, must never break the request
        logger.warning("Nem sikerült előkészíteni az audit bejegyzést: %s", exc)
        prepared = None
    finally:
        db.close()

    response = await call_next(request)

    if prepared is not None:
        db = SessionLocal()
        try:
            audit_service.finalize_record(db, request, response, prepared)
        except Exception as exc:  # noqa: BLE001 - best-effort audit, must never break the request
            logger.warning("Nem sikerült audit logot rögzíteni: %s", exc)
        finally:
            db.close()
    return response


@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


# ── Sync endpoints ────────────────────────────────────────────────────────────


def _run_guarded_sync(request: SyncRequest, db: Session) -> SyncResponse:
    """Shared wrapper: sync_all raises SyncInProgressError (DEF-012) when
    another sync already holds the DB-backed lock -- surface that as a clean
    409 with a Hungarian message rather than letting a second concurrent sync
    contend for the same rows.
    """
    try:
        return sync_all(request, db)
    except SyncInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/sync", response_model=SyncResponse)
def full_sync(request: SyncRequest, db: Session = Depends(get_db)):
    return _run_guarded_sync(request, db)


@app.post("/api/v1/sync/nav", response_model=SyncResponse)
def nav_sync(request: SyncRequest, db: Session = Depends(get_db)):
    request.sync_mode = SyncMode.nav_only
    return _run_guarded_sync(request, db)


@app.post("/api/v1/sync/pdf", response_model=SyncResponse)
def pdf_sync(request: SyncRequest, db: Session = Depends(get_db)):
    request.sync_mode = SyncMode.pdf_only
    return _run_guarded_sync(request, db)


@app.post("/api/v1/sync/bank", response_model=SyncResponse)
def bank_sync(request: SyncRequest, db: Session = Depends(get_db)):
    request.sync_mode = SyncMode.bank_only
    return _run_guarded_sync(request, db)


@app.post("/api/v1/sync/match", response_model=SyncResponse)
def match_sync(request: SyncRequest, db: Session = Depends(get_db)):
    request.sync_mode = SyncMode.match_only
    return _run_guarded_sync(request, db)


@app.get("/api/v1/sync/pending")
def sync_pending(db: Session = Depends(get_db)):
    unmatched_invoices, unmatched_transactions = get_pending_sync_counts(db)
    return {
        "unmatched_invoices": unmatched_invoices,
        "unmatched_transactions": unmatched_transactions,
    }


@app.get("/api/v1/sync/logs")
def sync_logs(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    logs = dashboard_service.get_sync_logs(db, limit=limit)
    return [dataclasses.asdict(log) for log in logs]


# ── Audit log endpoint ───────────────────────────────────────────────────────


@app.get("/api/v1/audit-log", response_model=list[AuditLogOut])
def audit_log(
    user_email: str | None = None,
    page: str | None = None,
    date_from: _date | None = None,
    date_to: _date | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return audit_service.list_audit_log(db, user_email, page, date_from, date_to, limit)


# ── Dashboard endpoint ────────────────────────────────────────────────────────


@app.get("/api/v1/dashboard")
def dashboard(db: Session = Depends(get_db)):
    """Aggregate the KPI cards, recent lists, and last-sync info shown on the dashboard page."""
    last_sync = dashboard_service.get_last_sync(db)
    return {
        "kpis": dataclasses.asdict(dashboard_service.get_kpis(db)),
        "recent_invoices": [
            dataclasses.asdict(r) for r in dashboard_service.get_recent_invoices(db)
        ],
        "recent_transactions": [
            dataclasses.asdict(r) for r in dashboard_service.get_recent_transactions(db)
        ],
        "last_sync": dataclasses.asdict(last_sync) if last_sync else None,
        "top_suppliers": [dataclasses.asdict(r) for r in dashboard_service.get_top_suppliers(db)],
        "top_customers": [dataclasses.asdict(r) for r in dashboard_service.get_top_customers(db)],
        "monthly_finance": [
            dataclasses.asdict(r) for r in dashboard_service.get_monthly_finance(db)
        ],
    }


# ── Invoice endpoints ─────────────────────────────────────────────────────────


@app.get("/api/v1/invoices/count")
def invoice_count(db: Session = Depends(get_db)):
    count = db.query(func.count(Invoice.id)).scalar() or 0
    return {"count": count}


@app.get("/api/v1/invoices")
def list_invoices(
    date_from: _date | None = Query(None, description="YYYY-MM-DD"),
    date_to: _date | None = Query(None, description="YYYY-MM-DD"),
    status: str | None = Query(None, description="PAID | UNPAID | PARTIAL"),
    direction: str | None = Query(None, description="INBOUND | OUTBOUND"),
    has_pdf: str | None = Query(None, description="true | false"),
    supplier_name: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    db: Session = Depends(get_db),
):
    rows = invoice_service.list_invoices(
        db,
        date_from=date_from,
        date_to=date_to,
        payment_status=status,
        has_pdf=has_pdf,
        supplier_name=supplier_name,
        limit=limit,
        offset=offset,
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
            raise HTTPException(
                status_code=422, detail=f"Invalid payment_status: {req.payment_status}"
            ) from None
    inv.updated_at = utcnow()
    db.commit()
    return {"ok": True}


# ── Invoice file endpoints ────────────────────────────────────────────────────


@app.get("/api/v1/invoice-files")
def list_invoice_files(
    linked: str | None = Query(None, description="yes | no"),
    filename: str | None = Query(None, description="filename substring filter"),
    limit: int = Query(1000, ge=1, le=5000, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    db: Session = Depends(get_db),
):
    rows = invoice_file_service.list_invoice_files(
        db, linked=linked, filename=filename, limit=limit, offset=offset
    )
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
    invoice_file.updated_at = utcnow()
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


@app.post("/api/v1/partners/suppliers", response_model=SupplierOut)
def create_supplier(payload: SupplierIn, db: Session = Depends(get_db)):
    try:
        return partner_service.create_supplier(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/v1/partners/suppliers/{supplier_id:int}", response_model=SupplierOut)
def update_supplier(supplier_id: int, payload: SupplierUpdate, db: Session = Depends(get_db)):
    try:
        record = partner_service.update_supplier(db, supplier_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return record


@app.delete("/api/v1/partners/suppliers/{supplier_id:int}")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    try:
        deleted = partner_service.delete_supplier(db, supplier_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"status": "deleted"}


@app.post("/api/v1/partners/customers", response_model=CustomerOut)
def create_customer(payload: CustomerIn, db: Session = Depends(get_db)):
    try:
        return partner_service.create_customer(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/v1/partners/customers/{customer_id:int}", response_model=CustomerOut)
def update_customer(customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db)):
    try:
        record = partner_service.update_customer(db, customer_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return record


@app.delete("/api/v1/partners/customers/{customer_id:int}")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    try:
        deleted = partner_service.delete_customer(db, customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"status": "deleted"}


# ── User endpoints ────────────────────────────────────────────────────────────
# Called by the auth service on every successful login to persist a login record.


@app.post("/api/v1/users", response_model=UserOut)
def upsert_user(payload: UserIn, db: Session = Depends(get_db)):
    return user_service.upsert_user(db, payload)


@app.get("/api/v1/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return user_service.list_users(db)


# ── Activity type endpoints ───────────────────────────────────────────────────


@app.post("/api/v1/activity-types", response_model=ActivityTypeOut)
def create_activity_type(payload: ActivityTypeIn, db: Session = Depends(get_db)):
    try:
        return activity_type_service.create_activity_type(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/activity-types", response_model=list[ActivityTypeOut])
def list_activity_types(db: Session = Depends(get_db)):
    return activity_type_service.list_activity_types(db)


@app.put("/api/v1/activity-types/{activity_type_id}", response_model=ActivityTypeOut)
def update_activity_type(
    activity_type_id: int, payload: ActivityTypeUpdate, db: Session = Depends(get_db)
):
    try:
        record = activity_type_service.update_activity_type(db, activity_type_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Activity type not found")
    return record


@app.delete("/api/v1/activity-types/{activity_type_id}")
def delete_activity_type(activity_type_id: int, db: Session = Depends(get_db)):
    if not activity_type_service.delete_activity_type(db, activity_type_id):
        raise HTTPException(status_code=404, detail="Activity type not found")
    return {"status": "deleted"}


# ── Project endpoints ──────────────────────────────────────────────────────────


@app.post("/api/v1/projects", response_model=ProjectOut)
def create_project(payload: ProjectIn, db: Session = Depends(get_db)):
    try:
        return project_service.create_project(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return project_service.list_projects(db)


@app.put("/api/v1/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    try:
        record = project_service.update_project(db, project_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return record


@app.delete("/api/v1/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    if not project_service.delete_project(db, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted"}


# ── Timesheet endpoints ────────────────────────────────────────────────────────


@app.post("/api/v1/timesheet-entries", response_model=TimesheetEntryOut)
def create_timesheet_entry(payload: TimesheetEntryIn, db: Session = Depends(get_db)):
    try:
        return timesheet_service.create_timesheet_entry(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/timesheet-entries", response_model=list[TimesheetEntryOut])
def list_timesheet_entries(user_id: int = Query(...), db: Session = Depends(get_db)):
    return timesheet_service.list_timesheet_entries(db, user_id)


@app.put("/api/v1/timesheet-entries/{entry_id}", response_model=TimesheetEntryOut)
def update_timesheet_entry(
    entry_id: int,
    payload: TimesheetEntryUpdate,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    try:
        record = timesheet_service.update_timesheet_entry(db, entry_id, user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Timesheet rekord nem található")
    return record


@app.delete("/api/v1/timesheet-entries/{entry_id}")
def delete_timesheet_entry(entry_id: int, user_id: int = Query(...), db: Session = Depends(get_db)):
    if not timesheet_service.delete_timesheet_entry(db, entry_id, user_id):
        raise HTTPException(status_code=404, detail="Timesheet rekord nem található")
    return {"status": "deleted"}


# ── Transaction endpoints ─────────────────────────────────────────────────────


@app.get("/api/v1/transactions/balances")
def transaction_balances(db: Session = Depends(get_db)):
    balances = transaction_service.get_bank_balances(db)
    return [dataclasses.asdict(b) for b in balances]


@app.get("/api/v1/transactions")
def list_transactions(
    date_from: _date | None = Query(None, description="YYYY-MM-DD"),
    date_to: _date | None = Query(None, description="YYYY-MM-DD"),
    linked: str | None = Query(None, description="yes | no"),
    partner_name: str | None = Query(None),
    amount_min: float | None = Query(None),
    amount_max: float | None = Query(None),
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


@app.put("/api/v1/invoices/{invoice_id}/supplier")
def link_invoice_to_supplier(
    invoice_id: int, req: LinkSupplierRequest, db: Session = Depends(get_db)
):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if not db.get(Supplier, req.supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    inv.supplier_id = req.supplier_id
    inv.supplier_locked = True
    inv.updated_at = utcnow()
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/invoices/{invoice_id}/supplier")
def unlink_invoice_from_supplier(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv.supplier_id = None
    inv.supplier_locked = True
    inv.updated_at = utcnow()
    db.commit()
    return {"ok": True}


@app.put("/api/v1/invoices/{invoice_id}/customer")
def link_invoice_to_customer(
    invoice_id: int, req: LinkCustomerRequest, db: Session = Depends(get_db)
):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if not db.get(Customer, req.customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    inv.customer_id = req.customer_id
    inv.customer_locked = True
    inv.updated_at = utcnow()
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/invoices/{invoice_id}/customer")
def unlink_invoice_from_customer(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv.customer_id = None
    inv.customer_locked = True
    inv.updated_at = utcnow()
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


@app.put("/api/v1/transactions/{txn_id}/supplier")
def link_transaction_to_supplier(
    txn_id: int, req: LinkSupplierRequest, db: Session = Depends(get_db)
):
    txn = db.get(BankTransaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if not db.get(Supplier, req.supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    txn.supplier_id = req.supplier_id
    txn.supplier_locked = True
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/transactions/{txn_id}/supplier")
def unlink_transaction_from_supplier(txn_id: int, db: Session = Depends(get_db)):
    txn = db.get(BankTransaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    txn.supplier_id = None
    txn.supplier_locked = True
    db.commit()
    return {"ok": True}


@app.put("/api/v1/transactions/{txn_id}/customer")
def link_transaction_to_customer(
    txn_id: int, req: LinkCustomerRequest, db: Session = Depends(get_db)
):
    txn = db.get(BankTransaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if not db.get(Customer, req.customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    txn.customer_id = req.customer_id
    txn.customer_locked = True
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/transactions/{txn_id}/customer")
def unlink_transaction_from_customer(txn_id: int, db: Session = Depends(get_db)):
    txn = db.get(BankTransaction, txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    txn.customer_id = None
    txn.customer_locked = True
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
        db.execute(
            sa_insert(invoice_bank_transaction).values(
                invoice_id=invoice_id,
                bank_transaction_id=txn_id,
                manual=True,
            )
        )
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
    year: int | None = Query(None, description="Year (default: current year)"),
    kiva_rate: float = Query(0.10, description="KIVA tax rate (default 0.10)"),
    hipa_rate: float = Query(0.02, description="HIPA (local business tax) rate (default 0.02)"),
    db: Session = Depends(get_db),
):
    """Estimate dividend advance for *year*, defaulting to the current year if omitted.

    `kiva_rate` is passed in as the corporate-level tax rate instead of the
    9% TAO default inside `calculate_dividend`: in Hungary a company pays
    either TAO (corporate income tax) or KIVA (a small-business flat-tax
    alternative), never both, so this lets a KIVA-taxed company get an
    accurate estimate using their own rate instead of the TAO default.
    """
    effective_year = year or today().year
    report = dividend_service.calculate_dividend(db, effective_year, kiva_rate, hipa_rate=hipa_rate)
    return dataclasses.asdict(report)


@app.get("/api/v1/reports/tax")
def tax_report(
    year: int | None = Query(None, description="Year (default: current year)"),
    db: Session = Depends(get_db),
):
    """Summarize *year*'s payments to tax-authority accounts, defaulting to the current year."""
    effective_year = year or today().year
    report = tax_service.get_tax_report(db, effective_year)
    return dataclasses.asdict(report)


@app.get("/api/v1/reports/tax-estimate")
def tax_estimate_report(
    year: int | None = Query(None, description="Year (default: current year)"),
    tao_rate: float = Query(0.10, description="TAO/KIVA rate (default 0.10)"),
    hipa_rate: float = Query(0.02, description="HIPA rate (default 0.02)"),
    szja_rate: float = Query(0.15, description="SZJA rate on dividend (default 0.15)"),
    szocho_rate: float = Query(0.13, description="SZOCHÓ rate on dividend (default 0.13)"),
    db: Session = Depends(get_db),
):
    """Estimate monthly tax liability for *year*.

    Projects remaining months of the current year from a trailing average.
    """
    effective_year = year or today().year
    report = tax_service.get_tax_estimate(
        db, effective_year, tao_rate, hipa_rate, szja_rate, szocho_rate
    )
    return dataclasses.asdict(report)


@app.get("/api/v1/reports/timesheet")
def timesheet_report(
    report_type: str = Query(..., description="project | person | customer | activity_type"),
    date_from: _date | None = Query(None, description="YYYY-MM-DD"),
    date_to: _date | None = Query(None, description="YYYY-MM-DD"),
    customer_id: int | None = Query(None),
    project_id: int | None = Query(None),
    user_id: int | None = Query(None),
    activity_type_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    if report_type == "project":
        if project_id is None:
            raise HTTPException(
                status_code=400, detail="A projekt riporthoz projekt kiválasztása kötelező"
            )
        report = report_service.get_project_report(
            db,
            project_id,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            activity_type_id=activity_type_id,
        )
    elif report_type in ("person", "customer", "activity_type"):
        report = report_service.get_group_report(
            db,
            report_type,
            date_from=date_from,
            date_to=date_to,
            customer_id=customer_id,
            project_id=project_id,
            user_id=user_id,
            activity_type_id=activity_type_id,
        )
    else:
        raise HTTPException(status_code=400, detail="Ismeretlen riport típus")
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
