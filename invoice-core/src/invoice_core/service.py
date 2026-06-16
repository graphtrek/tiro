"""Orchestration logic shared by the API and CLI."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import Customer, Invoice, InvoiceFile, Supplier, WiseTransaction, _InvoiceDirection, _PaymentStatus
from .models import SyncMode, SyncRequest, SyncResponse
from .nav_client import NavClient, NavClientError
from .pdf_client import PdfClient, PdfClientError
from .wise_client import WiseClient, WiseClientError

logger = logging.getLogger(__name__)


def _default_dates(start: Optional[str], end: Optional[str]) -> tuple[str, str]:
    end_obj = date.fromisoformat(end) if end else date.today()
    start_obj = date.fromisoformat(start) if start else end_obj - timedelta(days=30)
    return start_obj.isoformat(), end_obj.isoformat()


def _upsert_supplier(db: Session, tax_id: str, name: str) -> Supplier:
    existing = db.query(Supplier).filter_by(tax_id=tax_id).first()
    if existing:
        existing.name = name
        existing.updated_at = datetime.utcnow()
        return existing
    supplier = Supplier(name=name, tax_id=tax_id)
    db.add(supplier)
    db.flush()
    return supplier


def _upsert_customer(db: Session, tax_id: str, name: str) -> Customer:
    existing = db.query(Customer).filter_by(tax_id=tax_id).first()
    if existing:
        existing.name = name
        existing.updated_at = datetime.utcnow()
        return existing
    customer = Customer(name=name, tax_id=tax_id)
    db.add(customer)
    db.flush()
    return customer


def sync_nav(start: str, end: str, db: Session, settings: Optional[Settings] = None) -> int:
    """Fetch NAV invoices and upsert suppliers, customers, and invoices."""
    settings = settings or get_settings()
    digests = NavClient(settings).get_invoices(start, end)
    count = 0
    for d in digests:
        supplier_tax = d.get("supplier_tax_number", "")
        supplier_name = d.get("supplier_name", "")
        customer_tax = d.get("customer_tax_number", "")
        customer_name = d.get("customer_name", "")
        invoice_number = d.get("invoice_number", "")
        if not invoice_number:
            continue

        supplier = _upsert_supplier(db, tax_id=supplier_tax or invoice_number, name=supplier_name)
        customer = _upsert_customer(db, tax_id=customer_tax or invoice_number, name=customer_name)

        issue_date_str = d.get("invoice_issue_date", "")
        try:
            issue_date = date.fromisoformat(issue_date_str) if issue_date_str else None
        except ValueError:
            issue_date = None

        direction_str = d.get("direction", "OUTBOUND")
        direction = _InvoiceDirection[direction_str] if direction_str in _InvoiceDirection.__members__ else _InvoiceDirection.OUTBOUND

        existing = db.query(Invoice).filter_by(invoice_number=invoice_number).first()
        if existing:
            existing.invoice_date = issue_date
            existing.amount_net = d.get("invoice_net_amount")
            existing.amount_vat = d.get("invoice_vat_amount")
            existing.direction = direction
            existing.updated_at = datetime.utcnow()
        else:
            db.add(Invoice(
                invoice_number=invoice_number,
                invoice_date=issue_date,
                supplier_id=supplier.id,
                customer_id=customer.id,
                amount_net=d.get("invoice_net_amount"),
                amount_vat=d.get("invoice_vat_amount"),
                payment_status=_PaymentStatus.UNPAID,
                direction=direction,
                nav_transaction_id=d.get("ins_date"),
            ))
            count += 1

    db.commit()
    logger.info("sync_nav: %d new invoice(s) from %d digest(s)", count, len(digests))
    return count


def sync_pdf(start: str, end: str, db: Session, settings: Optional[Settings] = None) -> int:
    """Fetch PDF file index and upsert InvoiceFile records, then link to Invoice."""
    settings = settings or get_settings()
    files = PdfClient(settings).extract(start, end)
    if not files:
        logger.warning("sync_pdf: no invoice files returned by invoice-file-filter for %s..%s", start, end)
        return 0
    count = 0
    for f in files:
        filename = f.get("filename", "")
        if not filename:
            continue
        existing = db.query(InvoiceFile).filter_by(filename=filename).first()
        if existing:
            existing.updated_at = datetime.utcnow()
            invoice_file = existing
        else:
            invoice_file = InvoiceFile(filename=filename)
            db.add(invoice_file)
            db.flush()
            count += 1

        # Link to Invoice: check if any invoice_number appears in filename
        invoices = db.query(Invoice).filter(Invoice.invoice_file_id == None).all()  # noqa: E711
        for inv in invoices:
            if inv.invoice_number and inv.invoice_number in filename:
                inv.invoice_file_id = invoice_file.id
                inv.updated_at = datetime.utcnow()
                break

    db.commit()
    logger.info("sync_pdf: %d new invoice_file record(s) from %d file(s)", count, len(files))
    return count


def sync_wise(start: str, end: str, db: Session, settings: Optional[Settings] = None) -> int:
    """Fetch Wise transactions and insert new ones with idempotency."""
    settings = settings or get_settings()
    transactions = WiseClient(settings).get_transactions()
    count = 0
    for t in transactions:
        wise_id = t.get("wise_transaction_id", "")
        if not wise_id:
            continue
        if db.query(WiseTransaction).filter_by(wise_transaction_id=wise_id).first():
            continue

        txn_date_raw = t.get("transaction_date")
        try:
            txn_date = datetime.fromisoformat(str(txn_date_raw)) if txn_date_raw else datetime.utcnow()
        except ValueError:
            txn_date = datetime.utcnow()

        amount_raw = t.get("amount", 0)
        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            amount = 0.0

        wtxn = WiseTransaction(
            wise_transaction_id=wise_id,
            amount=amount,
            currency=t.get("currency", ""),
            transaction_date=txn_date,
            description=t.get("description"),
        )

        counterparty = t.get("counterparty_name", "") or ""
        if counterparty:
            supplier = db.query(Supplier).filter(
                Supplier.name.ilike(f"%{counterparty}%")
            ).first()
            customer = db.query(Customer).filter(
                Customer.name.ilike(f"%{counterparty}%")
            ).first()
            if supplier:
                wtxn.supplier_id = supplier.id
            if customer:
                wtxn.customer_id = customer.id

        payment_ref = t.get("payment_reference", "") or ""
        if payment_ref:
            invoice = db.query(Invoice).filter_by(invoice_number=payment_ref).first()
            if invoice:
                wtxn.invoice_id = invoice.id

        db.add(wtxn)
        count += 1

    db.commit()
    logger.info("sync_wise: %d new transaction(s) from %d fetched", count, len(transactions))
    return count


def sync_all(request: SyncRequest, db: Session, settings: Optional[Settings] = None) -> SyncResponse:
    """Run the full or partial sync pipeline."""
    settings = settings or get_settings()
    start, end = _default_dates(request.start_date, request.end_date)
    mode = request.sync_mode or SyncMode.full
    errors: list[str] = []
    nav_count = pdf_count = wise_count = 0
    t0 = time.monotonic()

    if mode in (SyncMode.full, SyncMode.nav_only):
        try:
            nav_count = sync_nav(start, end, db, settings)
        except NavClientError as exc:
            logger.error("NAV sync failed: %s", exc)
            errors.append(f"NAV: {exc}")

    if mode in (SyncMode.full, SyncMode.pdf_only):
        try:
            pdf_count = sync_pdf(start, end, db, settings)
        except PdfClientError as exc:
            logger.error("PDF sync failed: %s", exc)
            errors.append(f"PDF: {exc}")

    if mode in (SyncMode.full, SyncMode.wise_only):
        try:
            wise_count = sync_wise(start, end, db, settings)
        except WiseClientError as exc:
            logger.error("Wise sync failed: %s", exc)
            errors.append(f"Wise: {exc}")

    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(
        "sync_all [%s] %s..%s: nav=%d pdf=%d wise=%d errors=%d in %.0fms",
        mode.value, start, end, nav_count, pdf_count, wise_count, len(errors), elapsed_ms,
    )
    return SyncResponse(
        start_date=start,
        end_date=end,
        nav_invoices_synced=nav_count,
        pdf_files_synced=pdf_count,
        wise_transactions_synced=wise_count,
        errors=errors,
    )
