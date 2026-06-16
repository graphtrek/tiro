"""Orchestration logic shared by the API and CLI."""

from __future__ import annotations

import logging
import re
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

def _norm(s: str) -> str:
    """Normalize an invoice number or text for fuzzy matching.

    Collapses whitespace around separators and maps /, \\, -, _, ., space → -
    so that "87/2026", "87-2026", "87 / 2026" all compare equal.
    """
    return re.sub(r"\s*[/\\\-_.]\s*", "-", s).lower()


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
    """Fetch PDF file index and upsert InvoiceFile records, then link to Invoice.

    Linking strategy (in order):
    1. Fast: invoice_number appears as substring of filename.
    2. Fallback: invoice_number appears anywhere in the PDF word list
       (via invoice-file-filter POST /api/v1/pdf/words).
    """
    settings = settings or get_settings()
    pdf_client = PdfClient(settings)
    files = pdf_client.extract(start, end)
    if not files:
        logger.warning("sync_pdf: no invoice files returned by invoice-file-filter for %s..%s", start, end)
        return 0

    # ── Phase 1: upsert InvoiceFile rows, keep (record, path) for link pass ──
    count = 0
    records: list[tuple[InvoiceFile, str]] = []
    for f in files:
        filename = f.get("filename", "")
        path = f.get("path", "")
        if not filename:
            continue
        existing = db.query(InvoiceFile).filter_by(filename=filename).first()
        if existing:
            existing.path = path or existing.path
            existing.updated_at = datetime.utcnow()
            invoice_file = existing
        else:
            invoice_file = InvoiceFile(filename=filename, path=path)
            db.add(invoice_file)
            db.flush()
            count += 1
        records.append((invoice_file, path))

    # ── Phase 2: link unmatched invoices ─────────────────────────────────────
    unlinked = db.query(Invoice).filter(Invoice.invoice_file_id == None).all()  # noqa: E711
    for inv in unlinked:
        if not inv.invoice_number:
            continue
        inv_num = _norm(inv.invoice_number)
        for invoice_file, path in records:
            # Fast path: invoice number (separator-normalized) in filename
            if inv_num in _norm(invoice_file.filename):
                inv.invoice_file_id = invoice_file.id
                inv.updated_at = datetime.utcnow()
                logger.info("Linked %s → %s (filename match)", inv.invoice_number, invoice_file.filename)
                break
            # Fallback: search inside PDF text (normalizes OCR-split separators too)
            if path:
                pdf_text = invoice_file.words or pdf_client.get_words_text(path)
                if not invoice_file.words and pdf_text:
                    invoice_file.words = pdf_text.replace("\x00", "")
                if inv_num in _norm(pdf_text):
                    inv.invoice_file_id = invoice_file.id
                    inv.updated_at = datetime.utcnow()
                    logger.info("Linked %s → %s (word search)", inv.invoice_number, invoice_file.filename)
                    break
        else:
            logger.warning("No PDF match found for invoice %s", inv.invoice_number)

    db.commit()
    logger.info("sync_pdf: %d new invoice_file record(s) from %d file(s)", count, len(files))
    return count


def _find_invoice_by_ref(db: Session, payment_ref: str) -> Optional[Invoice]:
    """Exact match first, then separator-normalized fallback."""
    invoice = db.query(Invoice).filter_by(invoice_number=payment_ref).first()
    if invoice:
        return invoice
    norm_ref = _norm(payment_ref)
    like_pattern = re.sub(r"[-/\\\\_. ]+", "%", payment_ref)
    candidates = db.query(Invoice).filter(
        Invoice.invoice_number.ilike(f"%{like_pattern}%")
    ).all()
    return next((inv for inv in candidates if _norm(inv.invoice_number) == norm_ref), None)


def sync_wise(start: str, end: str, db: Session, settings: Optional[Settings] = None) -> int:
    """Fetch Wise transactions, insert new ones, and link to invoice/supplier/customer."""
    settings = settings or get_settings()
    transactions = WiseClient(settings).get_transactions()
    count = 0
    for t in transactions:
        wise_id = t.get("wise_transaction_id", "")
        if not wise_id:
            continue

        existing = db.query(WiseTransaction).filter_by(wise_transaction_id=wise_id).first()
        if existing:
            wtxn = existing
        else:
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
            db.add(wtxn)
            count += 1

        # ── Link invoice ──────────────────────────────────────────────────────
        payment_ref = t.get("payment_reference", "") or ""
        if payment_ref and not wtxn.invoice_id:
            invoice = _find_invoice_by_ref(db, payment_ref)
            if invoice:
                wtxn.invoice_id = invoice.id
                logger.info("Linked Wise txn %s → invoice %s", wise_id, invoice.invoice_number)

        # ── Derive supplier/customer from linked invoice ───────────────────────
        if wtxn.invoice_id and (not wtxn.supplier_id or not wtxn.customer_id):
            invoice = db.query(Invoice).filter_by(id=wtxn.invoice_id).first()
            if invoice:
                if not wtxn.supplier_id:
                    wtxn.supplier_id = invoice.supplier_id
                if not wtxn.customer_id:
                    wtxn.customer_id = invoice.customer_id

        # ── Link supplier/customer by counterparty name (fallback) ────────────
        counterparty = t.get("counterparty_name", "") or ""
        if counterparty:
            if not wtxn.supplier_id:
                supplier = db.query(Supplier).filter(
                    Supplier.name.ilike(f"%{counterparty}%")
                ).first()
                if supplier:
                    wtxn.supplier_id = supplier.id
            if not wtxn.customer_id:
                customer = db.query(Customer).filter(
                    Customer.name.ilike(f"%{counterparty}%")
                ).first()
                if customer:
                    wtxn.customer_id = customer.id

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

    if request.clear_cache:
        logger.info("Clearing downstream caches before sync")
        NavClient(settings).clear_cache()
        PdfClient(settings).clear_cache()

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
