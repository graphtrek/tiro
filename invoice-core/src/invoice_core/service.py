"""Orchestration logic shared by the API and CLI."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from typing import NamedTuple, Optional

from sqlalchemy.orm import Session

from .bank_client import BankClient, BankClientError
from .config import Settings, get_settings
from .db import BankTransaction, Customer, Invoice, InvoiceFile, Supplier, _InvoiceDirection, _PaymentStatus
from .models import SyncMode, SyncRequest, SyncResponse
from .nav_client import NavClient, NavClientError
from .pdf_client import PdfClient, PdfClientError

logger = logging.getLogger(__name__)


class _FileScore(NamedTuple):
    score: float
    hit_vendor: bool
    hit_amount: bool


def _opt_float(d: dict, key: str) -> Optional[float]:
    """Parse a float from dict *d* at *key*, returning None for 0.0 or invalid."""
    raw = d.get(key)
    if raw is None:
        return None
    try:
        v = float(raw)
        return v if v != 0.0 else None
    except (TypeError, ValueError):
        return None


def _norm(s: str) -> str:
    """Normalize an invoice number or text for fuzzy matching.

    Collapses whitespace around separators and maps /, \\, -, _, ., space → -
    so that "87/2026", "87-2026", "87 / 2026" all compare equal.
    """
    return re.sub(r"\s*[/\\\-_.]\s*", "-", s).lower()


def _token_match(needle: str, haystack: str) -> bool:
    """True iff *needle* appears in *haystack* as a complete token.

    Treats hyphens and whitespace as equivalent separators, then wraps in ~
    so a plain substring check is sufficient.  Prevents "grpht-2026-1" from
    matching inside "grpht-2026-12", and allows "87-2026" to match "87/2026"
    in a normalized haystack regardless of whether the surrounding boundary is
    a dash, underscore, or space.
    """
    _sep = re.compile(r"[-\s]+")
    n = "~" + _sep.sub("~", needle) + "~"
    h = "~" + _sep.sub("~", haystack) + "~"
    return n in h


def _ascii_lower(s: str) -> str:
    """Lowercase and strip accents so 'ÜGYNÖKSÉG' → 'ugynokseg'."""
    decomposed = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


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

        amount_net = d.get("invoice_net_amount")
        amount_vat = d.get("invoice_vat_amount")
        amount_total = (
            (amount_net or 0.0) + (amount_vat or 0.0)
            if amount_net is not None or amount_vat is not None
            else None
        )
        currency = d.get("currency") or None
        invoice_operation = d.get("invoice_operation") or None
        invoice_category = d.get("invoice_category") or None

        existing = db.query(Invoice).filter_by(invoice_number=invoice_number).first()
        if existing:
            existing.invoice_date = issue_date
            existing.amount_net = amount_net
            existing.amount_vat = amount_vat
            existing.amount_total = amount_total
            existing.direction = direction
            existing.currency = currency
            existing.invoice_operation = invoice_operation
            existing.invoice_category = invoice_category
            existing.updated_at = datetime.utcnow()
        else:
            db.add(Invoice(
                invoice_number=invoice_number,
                invoice_date=issue_date,
                supplier_id=supplier.id,
                customer_id=customer.id,
                amount_net=amount_net,
                amount_vat=amount_vat,
                amount_total=amount_total,
                payment_status=_PaymentStatus.UNPAID,
                direction=direction,
                currency=currency,
                invoice_operation=invoice_operation,
                invoice_category=invoice_category,
                nav_ins_date=d.get("ins_date"),
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
        size = f.get("file_size")
        existing = db.query(InvoiceFile).filter_by(filename=filename).first()
        if existing:
            existing.path = path or existing.path
            if size is not None:
                existing.file_size = size
            existing.updated_at = datetime.utcnow()
            invoice_file = existing
        else:
            invoice_file = InvoiceFile(filename=filename, path=path, file_size=size)
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
            if _token_match(inv_num, _norm(invoice_file.filename)):
                inv.invoice_file_id = invoice_file.id
                inv.updated_at = datetime.utcnow()
                logger.info("Linked %s → %s (filename match)", inv.invoice_number, invoice_file.filename)
                break
            # Fallback: search inside PDF text (normalizes OCR-split separators too)
            if path:
                pdf_text = invoice_file.words or pdf_client.get_words_text(path)
                if not invoice_file.words and pdf_text:
                    invoice_file.words = pdf_text.replace("\x00", "")
                if _token_match(inv_num, _norm(pdf_text)):
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


def sync_bank(start: str, end: str, db: Session, settings: Optional[Settings] = None) -> int:
    """Fetch bank transactions, insert new ones, and link to invoice/supplier/customer."""
    settings = settings or get_settings()
    transactions = BankClient(settings).get_transactions()
    count = 0
    for t in transactions:
        txn_id = t.get("transaction_id", "")
        if not txn_id:
            continue

        existing = db.query(BankTransaction).filter_by(transaction_id=txn_id).first()
        if existing:
            btxn = existing
        else:
            # Use datetime if available, fall back to date
            txn_dt_raw = t.get("datetime") or t.get("date")
            try:
                txn_date = datetime.fromisoformat(str(txn_dt_raw)) if txn_dt_raw else datetime.utcnow()
            except ValueError:
                txn_date = datetime.utcnow()

            amount_raw = t.get("amount", 0)
            try:
                amount = float(amount_raw)
            except (TypeError, ValueError):
                amount = 0.0

            btxn = BankTransaction(
                bank=t.get("bank", ""),
                transaction_id=txn_id,
                amount=amount,
                currency=t.get("currency", ""),
                direction=t.get("direction", ""),
                transaction_date=txn_date,
                description=t.get("description"),
                payment_reference=t.get("payment_reference"),
                counterparty_name=t.get("counterparty_name"),
                counterparty_account=t.get("counterparty_account"),
                counterparty_iban=t.get("counterparty_iban"),
                transaction_type=t.get("transaction_type"),
                category=t.get("category"),
                balance=_opt_float(t, "balance"),
                fees=_opt_float(t, "fees"),
            )
            db.add(btxn)
            db.flush()
            count += 1

        # ── Link invoice via payment_reference ────────────────────────────────
        payment_ref = t.get("payment_reference", "") or ""
        if payment_ref and not btxn.invoice_id:
            invoice = _find_invoice_by_ref(db, payment_ref)
            if invoice:
                btxn.invoice_id = invoice.id
                invoice.payment_status = _PaymentStatus.PAID
                invoice.updated_at = datetime.utcnow()
                logger.info("Linked bank txn %s → invoice %s (paid)", txn_id, invoice.invoice_number)

        # ── Derive supplier/customer from linked invoice ───────────────────────
        if btxn.invoice_id and (not btxn.supplier_id or not btxn.customer_id):
            invoice = db.query(Invoice).filter_by(id=btxn.invoice_id).first()
            if invoice:
                if not btxn.supplier_id:
                    btxn.supplier_id = invoice.supplier_id
                if not btxn.customer_id:
                    btxn.customer_id = invoice.customer_id

        # ── Link supplier/customer by counterparty name (fallback) ────────────
        counterparty = t.get("counterparty_name", "") or ""
        if counterparty:
            if not btxn.supplier_id:
                supplier = db.query(Supplier).filter(
                    Supplier.name.ilike(f"%{counterparty}%")
                ).first()
                if supplier:
                    btxn.supplier_id = supplier.id
            if not btxn.customer_id:
                customer = db.query(Customer).filter(
                    Customer.name.ilike(f"%{counterparty}%")
                ).first()
                if customer:
                    btxn.customer_id = customer.id

    # Backfill: any invoice with a linked bank transaction is paid.
    db.query(Invoice).filter(
        Invoice.payment_status != _PaymentStatus.PAID,
        Invoice.id.in_(
            db.query(BankTransaction.invoice_id).filter(BankTransaction.invoice_id.isnot(None))
        ),
    ).update(
        {Invoice.payment_status: _PaymentStatus.PAID, Invoice.updated_at: datetime.utcnow()},
        synchronize_session=False,
    )

    db.commit()
    logger.info("sync_bank: %d new transaction(s) from %d fetched", count, len(transactions))
    return count


# ── BankTransaction ↔ invoice_file matching ────────────────────────────────────

_VENDOR_STOPWORDS = {
    "kommunikacios", "ugynokseg", "zartkoruen", "mukodo", "reszvenytarsasag",
    "subscription", "payment", "fizetes", "budapest", "paris", "dublin",
    "graphtrek", "graphtre", "invoice", "receipt", "szamla",
}

_CURRENCY_RE = re.compile(r"(\d[\d\s.,]*\d|\d)\s*(?:EUR|USD|HUF|GBP|CHF)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_MATCH_THRESHOLD = 0.6
_W_VENDOR = 0.4
_W_AMOUNT = 0.4


def _amount_str_variants(num: str) -> set[str]:
    s = num.strip()
    if not s:
        return set()
    variants = {s, s.replace(" ", ""), s.replace(" ", ".")}
    if "," in s and "." not in s:
        variants.add(s.replace(",", "."))
    return variants


def _int_amount_variants(n: float) -> set[str]:
    ival = int(round(n))
    grouped = f"{ival:,}".replace(",", ".")  # 3400 → "3.400"
    return {str(ival), grouped, f"{grouped},00"}


def _amount_candidates(txn: BankTransaction) -> set[str]:
    """Substrings to look for in a PDF's word list that would prove an amount match."""
    cands: set[str] = set()
    for m in _CURRENCY_RE.finditer(txn.description or ""):
        cands |= _amount_str_variants(m.group(1))
    amt = abs(txn.amount or 0.0)
    if amt >= 1:
        cands |= _int_amount_variants(amt)
        fees = abs(txn.fees or 0.0)
        if fees > 0:
            net = amt - fees
            if net >= 1:
                cands |= _int_amount_variants(net)
    return {c for c in cands if len(c) >= 2 and c not in ("0", "00")}


def _vendor_tokens(txn: BankTransaction) -> set[str]:
    """Distinctive vendor name tokens from counterparty_name."""
    raw = txn.counterparty_name or ""
    return {
        tok for tok in _TOKEN_RE.findall(_ascii_lower(raw))
        if len(tok) >= 4 and tok not in _VENDOR_STOPWORDS
    }


def _file_date(filename: str) -> Optional[date]:
    """Parse the ``YYYY-MM-DD`` prefix that invoice-file-filter prepends."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", filename or "")
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _file_score(
    amount_cands: set[str],
    vendor_toks: set[str],
    txn_date: Optional[date],
    haystack: str,
    filename_norm: str,
    file_date: Optional[date],
) -> _FileScore:
    """Weighted match score for one (transaction, file) pair."""
    hit_vendor = any(t in haystack for t in vendor_toks)
    hit_amount = any(a in haystack for a in amount_cands)

    score = 0.0
    if hit_vendor:
        score += _W_VENDOR
    if hit_amount:
        score += _W_AMOUNT
    if file_date and txn_date:
        days = abs((file_date - txn_date).days)
        if days == 0:
            score += 0.2
        elif days <= 3:
            score += 0.1
        elif days <= 7:
            score += 0.05
    return _FileScore(score=score, hit_vendor=hit_vendor, hit_amount=hit_amount)


def sync_match(db: Session, settings: Optional[Settings] = None) -> int:
    """Best-match unlinked bank transactions to invoice files.

    1. Transitive shortcut: if the txn already links to an invoice that has a PDF,
       reuse that file (highest confidence).
    2. Authoritative reference: a bank transfer with an explicit invoice-like
       ``payment_reference`` (contains a digit) must match a file that *contains*
       that reference. If no file does, the txn is left unlinked.
    3. Otherwise score every (txn, file) pair on vendor name, amount, and date
       proximity; greedily assign in descending-score order.
    """
    settings = settings or get_settings()  # noqa: F841
    unmatched = db.query(BankTransaction).filter(
        BankTransaction.invoice_file_id == None  # noqa: E711
    ).all()

    files = db.query(InvoiceFile).all()
    file_feats = {
        f.id: (_ascii_lower(f.filename) + " " + _ascii_lower(f.words or ""),
               _norm(f.filename) + " " + _norm(f.words or ""), _file_date(f.filename))
        for f in files
    }
    used_files: set[int] = set()
    count = 0

    def _assign(txn: BankTransaction, file_id: int, why: str) -> None:
        nonlocal count
        txn.invoice_file_id = file_id
        txn.updated_at = datetime.utcnow()
        used_files.add(file_id)
        count += 1
        logger.info("Matched bank txn %s → file_id %s (%s)", txn.transaction_id, file_id, why)

    # ── Phase 1: transitive shortcut + authoritative payment reference ───────
    remaining: list[BankTransaction] = []
    for txn in unmatched:
        if txn.invoice_id:
            invoice = db.query(Invoice).filter_by(id=txn.invoice_id).first()
            if invoice and invoice.invoice_file_id:
                _assign(txn, invoice.invoice_file_id, f"via invoice {invoice.invoice_number}")
                continue

        ref = (txn.payment_reference or "").strip()
        if ref and any(ch.isdigit() for ch in ref):
            norm_ref = _norm(ref)
            subtokens = [
                p for p in norm_ref.split()
                if any(ch.isdigit() for ch in p) and p not in _VENDOR_STOPWORDS
            ]
            search_parts = list(dict.fromkeys([norm_ref] + subtokens))
            hit = None
            for part in search_parts:
                hit = next(
                    (f.id for f in files
                     if f.id not in used_files and _token_match(part, file_feats[f.id][1])),
                    None,
                )
                if hit is not None:
                    break
            if hit is not None:
                _assign(txn, hit, f"reference {ref}")
            else:
                logger.warning(
                    "Bank txn %s reference %s not found in any file — left unlinked",
                    txn.transaction_id, ref,
                )
            continue

        remaining.append(txn)

    # ── Phase 2: scored candidates ───────────────────────────────────────────
    candidates: list[tuple[float, int, int]] = []
    txn_by_id = {t.id: t for t in remaining}
    for txn in remaining:
        amount_cands = _amount_candidates(txn)
        vendor_toks = _vendor_tokens(txn)
        txn_date = txn.transaction_date.date() if txn.transaction_date else None
        for f in files:
            haystack, fname_norm, fdate = file_feats[f.id]
            score, hit_vendor, hit_amount = _file_score(
                amount_cands, vendor_toks, txn_date, haystack, fname_norm, fdate
            )
            if score >= _MATCH_THRESHOLD and (hit_vendor or hit_amount):
                candidates.append((score, txn.id, f.id))

    candidates.sort(key=lambda c: c[0], reverse=True)
    used_txns: set[int] = set()
    for score, txn_id, file_id in candidates:
        if txn_id in used_txns or file_id in used_files:
            continue
        txn = txn_by_id[txn_id]
        txn.invoice_file_id = file_id
        txn.updated_at = datetime.utcnow()
        used_txns.add(txn_id)
        used_files.add(file_id)
        count += 1
        logger.info(
            "Matched bank txn %s → file_id %s (score %.2f)",
            txn.transaction_id, file_id, score,
        )

    for txn in remaining:
        if txn.id not in used_txns:
            logger.warning(
                "No confident invoice_file match for bank txn %s (%s)",
                txn.transaction_id, txn.counterparty_name or "",
            )

    # ── Phase 3: back-link transactions to invoices via shared invoice_file ────
    to_backlink = db.query(BankTransaction).filter(
        BankTransaction.invoice_file_id.isnot(None),
        BankTransaction.invoice_id.is_(None),
    ).all()
    for txn in to_backlink:
        invoice = db.query(Invoice).filter_by(invoice_file_id=txn.invoice_file_id).first()
        if invoice:
            txn.invoice_id = invoice.id
            txn.updated_at = datetime.utcnow()
            invoice.payment_status = _PaymentStatus.PAID
            invoice.updated_at = datetime.utcnow()
            logger.info(
                "Backlinked bank txn %s → invoice %s via shared file_id %s",
                txn.transaction_id, invoice.invoice_number, txn.invoice_file_id,
            )

    db.commit()
    logger.info("sync_match: %d bank transaction(s) linked to a file", count)
    return count


def sync_all(request: SyncRequest, db: Session, settings: Optional[Settings] = None) -> SyncResponse:
    """Run the full or partial sync pipeline."""
    settings = settings or get_settings()
    start, end = _default_dates(request.start_date, request.end_date)
    mode = request.sync_mode or SyncMode.full
    errors: list[str] = []
    nav_count = pdf_count = bank_count = match_count = 0
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

    if mode in (SyncMode.full, SyncMode.bank_only):
        try:
            bank_count = sync_bank(start, end, db, settings)
        except BankClientError as exc:
            logger.error("Bank sync failed: %s", exc)
            errors.append(f"Bank: {exc}")

    if mode in (SyncMode.full, SyncMode.match_only):
        try:
            match_count = sync_match(db, settings)
        except Exception as exc:  # noqa: BLE001
            logger.error("Bank↔file matching failed: %s", exc)
            errors.append(f"Match: {exc}")

    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(
        "sync_all [%s] %s..%s: nav=%d pdf=%d bank=%d match=%d errors=%d in %.0fms",
        mode.value, start, end, nav_count, pdf_count, bank_count, match_count, len(errors), elapsed_ms,
    )
    return SyncResponse(
        start_date=start,
        end_date=end,
        nav_invoices_synced=nav_count,
        pdf_files_synced=pdf_count,
        bank_transactions_synced=bank_count,
        bank_files_matched=match_count,
        errors=errors,
    )
