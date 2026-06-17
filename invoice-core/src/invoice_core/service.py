"""Orchestration logic shared by the API and CLI."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
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

        existing = db.query(Invoice).filter_by(invoice_number=invoice_number).first()
        if existing:
            existing.invoice_date = issue_date
            existing.amount_net = amount_net
            existing.amount_vat = amount_vat
            existing.amount_total = amount_total
            existing.direction = direction
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

            def _opt_float(key: str) -> Optional[float]:
                raw = t.get(key)
                if raw is None:
                    return None
                try:
                    v = float(raw)
                    return v if v != 0.0 else None
                except (TypeError, ValueError):
                    return None

            wtxn = WiseTransaction(
                wise_transaction_id=wise_id,
                amount=amount,
                currency=t.get("currency", ""),
                transaction_date=txn_date,
                description=t.get("description"),
                payment_reference=t.get("payment_reference"),
                running_balance=_opt_float("running_balance"),
                exchange_from=t.get("exchange_from"),
                exchange_to=t.get("exchange_to"),
                exchange_rate=_opt_float("exchange_rate"),
                payer_name=t.get("payer_name"),
                payee_name=t.get("payee_name"),
                payee_account_number=t.get("payee_account_number"),
                merchant=t.get("merchant"),
                card_last_four_digits=t.get("card_last_four_digits"),
                card_holder_full_name=t.get("card_holder_full_name"),
                attachment=t.get("attachment"),
                note=t.get("note"),
                total_fees=_opt_float("total_fees"),
                exchange_to_amount=_opt_float("exchange_to_amount"),
                transaction_type=t.get("type"),
                transaction_details_type=t.get("transaction_details_type"),
            )
            db.add(wtxn)
            db.flush()  # make visible to subsequent queries (handles duplicate wise_transaction_ids in CSV)
            count += 1

        # ── Link invoice ──────────────────────────────────────────────────────
        payment_ref = t.get("payment_reference", "") or ""
        if payment_ref and not wtxn.invoice_id:
            invoice = _find_invoice_by_ref(db, payment_ref)
            if invoice:
                wtxn.invoice_id = invoice.id
                # A Wise transaction settles the invoice → mark it paid.
                invoice.payment_status = _PaymentStatus.PAID
                invoice.updated_at = datetime.utcnow()
                logger.info("Linked Wise txn %s → invoice %s (paid)", wise_id, invoice.invoice_number)

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

    # Backfill: any invoice with a linked Wise transaction is paid. Covers links
    # made in prior syncs (or this run) that are not yet reflected on the column.
    db.query(Invoice).filter(
        Invoice.payment_status != _PaymentStatus.PAID,
        Invoice.id.in_(
            db.query(WiseTransaction.invoice_id).filter(WiseTransaction.invoice_id.isnot(None))
        ),
    ).update(
        {Invoice.payment_status: _PaymentStatus.PAID, Invoice.updated_at: datetime.utcnow()},
        synchronize_session=False,
    )

    db.commit()
    logger.info("sync_wise: %d new transaction(s) from %d fetched", count, len(transactions))
    return count


# ── Wise ↔ invoice_file matching ───────────────────────────────────────────────

# Generic tokens that must never count as a vendor signal: corporate-form words,
# cities, payment boilerplate, and our own company (appears in most PDFs).
_VENDOR_STOPWORDS = {
    "kommunikacios", "ugynokseg", "zartkoruen", "mukodo", "reszvenytarsasag",
    "subscription", "payment", "fizetes", "budapest", "paris", "dublin",
    "graphtrek", "graphtre", "invoice", "receipt", "szamla",
}

# A number (optionally grouped with space/.,) immediately followed by a currency.
_CURRENCY_RE = re.compile(r"(\d[\d\s.,]*\d|\d)\s*(?:EUR|USD|HUF|GBP|CHF)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_MATCH_THRESHOLD = 0.6
_W_VENDOR = 0.4
_W_AMOUNT = 0.4


def _amount_candidates(txn: WiseTransaction) -> set[str]:
    """Substrings to look for in a PDF's word list that would prove an amount match.

    Covers both the HUF ``amount`` field (plain + Hungarian-grouped) and the
    original amount embedded in the description for foreign card payments
    (``"15,19 EUR …"`` → file uses ``15,19``; ``"3,25 EUR …"`` → file uses ``€3.25``).
    """
    cands: set[str] = set()

    def _variants(num: str) -> None:
        s = num.strip()
        if not s:
            return
        cands.add(s)
        cands.add(s.replace(" ", ""))
        cands.add(s.replace(" ", "."))
        # decimal-comma → decimal-dot, e.g. "3,25" matches "€3.25"
        if "," in s and "." not in s:
            cands.add(s.replace(",", "."))

    for m in _CURRENCY_RE.finditer(txn.description or ""):
        _variants(m.group(1))

    def _int_variants(n: float) -> None:
        ival = int(round(n))
        cands.add(str(ival))
        grouped = f"{ival:,}".replace(",", ".")  # 3400 → "3.400"
        cands.add(grouped)
        cands.add(f"{grouped},00")               # "3.400,00"

    amt = abs(txn.amount or 0.0)
    if amt >= 1:
        _int_variants(amt)
        fees = abs(txn.total_fees or 0.0)
        if fees > 0:
            net = amt - fees
            if net >= 1:
                _int_variants(net)

    return {c for c in cands if len(c) >= 2 and c not in ("0", "00")}


def _vendor_tokens(txn: WiseTransaction) -> set[str]:
    """Distinctive vendor name tokens from merchant / payee / payer fields."""
    raw = " ".join(filter(None, [txn.merchant, txn.payee_name, txn.payer_name]))
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
) -> tuple[float, bool, bool]:
    """Weighted match score for one (transaction, file) pair.

    ``haystack`` is the accent-stripped, lowercased ``filename + words`` blob.
    Returns ``(score, hit_vendor, hit_amount)``.
    """
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
    return score, hit_vendor, hit_amount


def sync_match(db: Session, settings: Optional[Settings] = None) -> int:
    """Best-match unlinked Wise transactions to invoice files.

    1. Transitive shortcut: if the txn already links to an invoice that has a PDF,
       reuse that file (highest confidence).
    2. Authoritative reference: a bank transfer with an explicit invoice-like
       ``payment_reference`` (contains a digit) must match a file that *contains*
       that reference. If no file does, the txn is left unlinked rather than
       guessed from a coincidental amount/name — the reference is ground truth.
    3. Otherwise score every (txn, file) pair on vendor name, amount, and date
       proximity; greedily assign in descending-score order so each file is
       claimed by at most one transaction. Only links at or above the confidence
       threshold (and never on date alone) are written; the rest stay NULL for
       the manual ``link-wise`` fallback.
    """
    settings = settings or get_settings()  # noqa: F841 — kept for signature parity
    unmatched = db.query(WiseTransaction).filter(
        WiseTransaction.invoice_file_id == None  # noqa: E711
    ).all()

    files = db.query(InvoiceFile).all()
    file_feats = {
        f.id: (_ascii_lower(f.filename) + " " + _ascii_lower(f.words or ""),
               _norm(f.filename) + " " + _norm(f.words or ""), _file_date(f.filename))
        for f in files
    }
    used_files: set[int] = set()
    count = 0

    def _assign(txn: WiseTransaction, file_id: int, why: str) -> None:
        nonlocal count
        txn.invoice_file_id = file_id
        txn.updated_at = datetime.utcnow()
        used_files.add(file_id)
        count += 1
        logger.info("Matched Wise txn %s → file_id %s (%s)", txn.wise_transaction_id, file_id, why)

    # ── Phase 1: transitive shortcut + authoritative payment reference ───────
    remaining: list[WiseTransaction] = []
    for txn in unmatched:
        # 1a. via the already-linked invoice
        if txn.invoice_id:
            invoice = db.query(Invoice).filter_by(id=txn.invoice_id).first()
            if invoice and invoice.invoice_file_id:
                _assign(txn, invoice.invoice_file_id, f"via invoice {invoice.invoice_number}")
                continue

        # 1b. explicit invoice-like reference → require a file that contains it.
        # Try the full normalized reference first; if that fails, try each
        # space-separated subtoken that contains digits (handles refs like
        # "Graphtrek 87/2026" where the PDF only stores "87/2026").
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
                     if f.id not in used_files and part in file_feats[f.id][1]),
                    None,
                )
                if hit is not None:
                    break
            if hit is not None:
                _assign(txn, hit, f"reference {ref}")
            else:
                logger.warning(
                    "Wise txn %s reference %s not found in any file — left unlinked",
                    txn.wise_transaction_id, ref,
                )
            continue

        remaining.append(txn)

    # ── Phase 2: scored candidates ───────────────────────────────────────────
    candidates: list[tuple[float, int, int]] = []  # (score, txn_id, file_id)
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

    # Greedy 1:1 assignment: highest-scoring pairs win first.
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
            "Matched Wise txn %s → file_id %s (score %.2f)",
            txn.wise_transaction_id, file_id, score,
        )

    for txn in remaining:
        if txn.id not in used_txns:
            logger.warning(
                "No confident invoice_file match for Wise txn %s (%s)",
                txn.wise_transaction_id, txn.merchant or txn.payee_name or txn.payer_name or "",
            )

    # ── Phase 3: back-link transactions to invoices via shared invoice_file ────
    # Covers both transactions whose file was just assigned (Phases 1/2) and
    # pre-existing file links that were never reconciled against an invoice.
    to_backlink = db.query(WiseTransaction).filter(
        WiseTransaction.invoice_file_id.isnot(None),
        WiseTransaction.invoice_id.is_(None),
    ).all()
    for txn in to_backlink:
        invoice = db.query(Invoice).filter_by(invoice_file_id=txn.invoice_file_id).first()
        if invoice:
            txn.invoice_id = invoice.id
            txn.updated_at = datetime.utcnow()
            invoice.payment_status = _PaymentStatus.PAID
            invoice.updated_at = datetime.utcnow()
            logger.info(
                "Backlinked Wise txn %s → invoice %s via shared file_id %s",
                txn.wise_transaction_id, invoice.invoice_number, txn.invoice_file_id,
            )

    db.commit()
    logger.info("sync_match: %d Wise transaction(s) linked to a file", count)
    return count


def sync_all(request: SyncRequest, db: Session, settings: Optional[Settings] = None) -> SyncResponse:
    """Run the full or partial sync pipeline."""
    settings = settings or get_settings()
    start, end = _default_dates(request.start_date, request.end_date)
    mode = request.sync_mode or SyncMode.full
    errors: list[str] = []
    nav_count = pdf_count = wise_count = match_count = 0
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

    if mode in (SyncMode.full, SyncMode.match_only):
        try:
            match_count = sync_match(db, settings)
        except Exception as exc:  # noqa: BLE001 — matching is local DB work; never fail the whole sync
            logger.error("Wise↔file matching failed: %s", exc)
            errors.append(f"Match: {exc}")

    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(
        "sync_all [%s] %s..%s: nav=%d pdf=%d wise=%d match=%d errors=%d in %.0fms",
        mode.value, start, end, nav_count, pdf_count, wise_count, match_count, len(errors), elapsed_ms,
    )
    return SyncResponse(
        start_date=start,
        end_date=end,
        nav_invoices_synced=nav_count,
        pdf_files_synced=pdf_count,
        wise_transactions_synced=wise_count,
        wise_files_matched=match_count,
        errors=errors,
    )
