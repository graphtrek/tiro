"""Orchestration logic shared by the API and CLI."""

from __future__ import annotations

import logging
import os
import re
import socket
import time
import unicodedata
from datetime import date, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session, joinedload, selectinload

from .bank_client import BankClient, BankClientError
from .config import Settings, get_settings
from .db import (
    BankTransaction,
    Customer,
    Invoice,
    InvoiceDetail,
    InvoiceFile,
    InvoiceLine,
    InvoiceVatSummary,
    Supplier,
    SyncLock,
    SyncLog,
    _InvoiceDirection,
    _PaymentStatus,
    invoice_bank_transaction,
)
from .models import SyncMode, SyncRequest, SyncResponse
from .nav_client import NavClient, NavClientError
from .pdf_client import PdfClient, PdfClientError
from .timeutil import today, utcnow

logger = logging.getLogger(__name__)


class _FileScore(NamedTuple):
    score: float
    hit_vendor: bool
    hit_amount: bool


def _opt_float(d: dict, key: str) -> float | None:
    """Parse a float from dict *d* at *key*, returning None for 0.0 or invalid."""
    raw = d.get(key)
    if raw is None:
        return None
    try:
        v = float(raw)
        return v if v != 0.0 else None
    except (TypeError, ValueError):
        return None


_IBAN_RE = re.compile(r"^[A-Za-z]{2}\d{2}")


def classify_bank_account(raw: str | None) -> tuple[str | None, str | None]:
    """Split a single NAV bank-account string into (iban, bban).

    NAV exposes exactly one string per party (supplierBankAccountNumber /
    customerBankAccountNumber) with no separate IBAN/BBAN fields, unlike bank
    CSV data. An IBAN starts with a 2-letter country code + 2 check digits
    (e.g. "HU42..."); anything else is treated as a domestic account number (BBAN).
    """
    value = (raw or "").strip()
    if not value:
        return None, None
    if _IBAN_RE.match(value):
        return value, None
    return None, value


def _is_tax_account(account: str | None, settings: Settings) -> bool:
    """Return True if the bank account number belongs to a configured tax authority."""
    return bool(account and account in settings.tax_accounts)


def _link_txn_to_invoice(txn: BankTransaction, invoice: Invoice) -> None:
    if invoice not in txn.invoices:
        txn.invoices.append(invoice)


def _recompute_payment_status(db: Session, invoice: Invoice) -> None:
    """Set PAID/PARTIAL/UNPAID from the sum of linked transaction amounts.

    Skipped when payment_status_locked is set (manually overridden status).
    Compares against invoice.amount_total using only transactions whose currency
    matches the invoice currency (if set). Falls back to PAID when amount_total
    is unknown.
    """
    if getattr(invoice, "payment_status_locked", False):
        return
    linked = invoice.bank_transactions
    if not linked:
        if invoice.payment_status != _PaymentStatus.UNPAID:
            invoice.payment_status = _PaymentStatus.UNPAID
            invoice.updated_at = utcnow()
        return
    total = invoice.amount_total or 0.0
    currency = invoice.currency
    paid_sum = sum(abs(t.amount) for t in linked if not currency or t.currency == currency)
    if total <= 0 or paid_sum >= total:
        new_status = _PaymentStatus.PAID
    elif paid_sum > 0:
        new_status = _PaymentStatus.PARTIAL
    else:
        new_status = _PaymentStatus.UNPAID
    if invoice.payment_status != new_status:
        invoice.payment_status = new_status
        invoice.updated_at = utcnow()


# ── Fuzzy-matching helpers used by _link_invoices_to_files() and sync_match() ──
#
# Invoice numbers and filenames rarely match character-for-character (different
# separators, missing separators, extra text), so matching is tried through a
# cascade of increasingly loose comparisons, stopping at the first one that
# succeeds:
#   1. _norm()              — normalize separators (/, \, -, _, ., space → "-")
#   2. _token_match()       — exact match once the string is split into tokens
#   3. _norm_year_collapsed() — retry after joining the trailing "-2026" year
#                                onto the previous number (for filenames that
#                                dropped that separator)
#   4. _stripped_match()    — last resort: strip all separators and search for
#                                the digits as a plain substring
# Both invoice→file linking (_link_invoices_to_files) and transaction→file
# linking (sync_match) run candidates through this same cascade.


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


def _norm_year_collapsed(inv_num_norm: str) -> str | None:
    """Return a variant where the sequence number and 4-digit year are concatenated.

    Handles filenames where the separator before the year was dropped:
    e.g. 'wsph-203-00506-2026' → 'wsph-203-005062026'
    """
    m = re.match(r"^(.+)-(\d+)-(\d{4})$", inv_num_norm)
    if m:
        return f"{m.group(1)}-{m.group(2)}{m.group(3)}"
    return None


_STRIP_SEPS_RE = re.compile(r"[-_/#]")
# Hungarian tax number (adószám): 8digits-1digit-2digits — appears in every
# invoice as buyer/seller; useless as payment reference.
_HU_TAX_NUMBER_RE = re.compile(r"^\d{8}-\d-\d{2}$")


def _stripped_match(needle: str, haystack: str) -> bool:
    """Fallback: strip separator chars and match with alphanumeric boundaries.

    Handles text where separators were omitted entirely, e.g. 'GRPHT-2026-1'
    finding 'GRPHT20261' in a filename.  The boundary assertions prevent
    'grpht20261' from matching inside 'grpht202612'.
    """
    n = _STRIP_SEPS_RE.sub("", needle.lower())
    h = _STRIP_SEPS_RE.sub("", haystack.lower())
    if not n:
        return False
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", h))


def _ascii_lower(s: str) -> str:
    """Lowercase and strip accents so 'ÜGYNÖKSÉG' → 'ugynokseg'."""
    decomposed = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _link_invoices_to_files(
    db: Session,
    files: list[InvoiceFile],
    pdf_client: object | None = None,
) -> int:
    """Link unmatched invoices to files by filename then PDF text.

    Works against any list of InvoiceFile objects (e.g. freshly fetched or all from DB).
    Returns the number of invoices newly linked.
    """
    # SQLAlchemy builds a SQL "IS NULL" / "IS FALSE" expression from `== None` /
    # `== False` comparisons on a Column — it only works because Column.__eq__ is
    # overridden. Python's own `is None`/`is False` would NOT work here (SQLAlchemy
    # would never see it), so the "== None" style is intentional despite normally
    # being bad Python style; the noqa directives on the two lines below tell the
    # linter not to flag them.
    unlinked = (
        db.query(Invoice)
        .filter(
            Invoice.invoice_file_id == None,  # noqa: E711
            Invoice.invoice_file_locked == False,  # noqa: E712
        )
        .all()
    )
    linked = 0
    for inv in unlinked:
        if not inv.invoice_number:
            continue
        inv_num = _norm(inv.invoice_number)
        inv_num_yc = _norm_year_collapsed(inv_num)
        for invoice_file in files:
            fn_norm = _norm(invoice_file.filename)
            if (
                _token_match(inv_num, fn_norm)
                or (inv_num_yc and _token_match(inv_num_yc, fn_norm))
                or _stripped_match(inv_num, fn_norm)
            ):
                inv.invoice_file_id = invoice_file.id
                inv.updated_at = utcnow()
                logger.info(
                    "Linked %s → %s (filename match)", inv.invoice_number, invoice_file.filename
                )
                linked += 1
                break
            if invoice_file.path:
                pdf_text = invoice_file.words
                if not pdf_text and pdf_client is not None:
                    pdf_text = pdf_client.get_words_text(invoice_file.path)  # type: ignore[attr-defined]
                    if pdf_text:
                        invoice_file.words = pdf_text.replace("\x00", "")
                if pdf_text:
                    words_norm = _norm(pdf_text)
                    if (
                        _token_match(inv_num, words_norm)
                        or (inv_num_yc and _token_match(inv_num_yc, words_norm))
                        or _stripped_match(inv_num, words_norm)
                    ):
                        inv.invoice_file_id = invoice_file.id
                        inv.updated_at = utcnow()
                        logger.info(
                            "Linked %s → %s (word search)",
                            inv.invoice_number,
                            invoice_file.filename,
                        )
                        linked += 1
                        break
        # This `else` belongs to the "for invoice_file in files" loop right above
        # it (a for/else, not an if/else) — it only runs when that inner loop
        # finished *without* hitting a `break`, i.e. no file matched this invoice.
        else:
            logger.warning("No PDF match found for invoice %s", inv.invoice_number)
    return linked


def _default_dates(start: str | None, end: str | None) -> tuple[str, str]:
    end_obj = date.fromisoformat(end) if end else today()
    start_obj = date.fromisoformat(start) if start else end_obj - timedelta(days=30)
    return start_obj.isoformat(), end_obj.isoformat()


def _normalize_tax_number(raw: str | None) -> str | None:
    """The 8-digit "torzsszam" core of a Hungarian tax number, digits only.

    NAV tax numbers are formatted XXXXXXXX-Y-ZZ (8-digit core + VAT code +
    county code); the suffix can legitimately differ between sources/branches
    of the same taxpayer, so the 8-digit core is the stable identifying key
    used to match partners across re-syncs regardless of exact formatting.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits[:8] if len(digits) >= 8 else None


def _normalize_name(name: str | None) -> str | None:
    """Collapse whitespace and lower-case a partner name for fuzzy matching."""
    if not name:
        return None
    collapsed = " ".join(name.split())
    return collapsed.lower() or None


def _find_supplier(
    db: Session,
    tax_id: str,
    name: str,
    address: str | None = None,
    iban: str | None = None,
    bban: str | None = None,
) -> Supplier | None:
    """Look up (never create) the supplier a NAV digest refers to.

    Matches first by tax number — exact string, then by normalized 8-digit
    core (so differing dash formatting/VAT-code suffixes don't spawn
    duplicates) — falling back to a normalized name match against rows with
    no tax number yet (manually created placeholders, whose tax_id gets
    backfilled once NAV reports one). See `_find_or_create_supplier` for the
    create half of the upsert. A match is only ever augmented, never
    overwritten: fields the user already set by hand are left untouched, and
    only currently-empty fields get filled in from NAV data.
    """
    existing = db.query(Supplier).filter_by(tax_id=tax_id).first() if tax_id else None
    if not existing and tax_id:
        core = _normalize_tax_number(tax_id)
        if core:
            for candidate in db.query(Supplier).filter(Supplier.tax_id.isnot(None)):
                if _normalize_tax_number(candidate.tax_id) == core:
                    existing = candidate
                    break
    if not existing:
        name_norm = _normalize_name(name)
        if name_norm:
            for candidate in db.query(Supplier).filter(Supplier.tax_id.is_(None)):
                if _normalize_name(candidate.name) == name_norm:
                    existing = candidate
                    break
        if existing and tax_id:
            existing.tax_id = tax_id
    if existing:
        if not existing.name and name:
            existing.name = name
        if not existing.address and address:
            existing.address = address
        if not existing.iban and iban:
            existing.iban = iban
        if not existing.bban and bban:
            existing.bban = bban
        existing.updated_at = utcnow()
    return existing


def _find_or_create_supplier(
    db: Session,
    tax_id: str,
    name: str,
    address: str | None = None,
    iban: str | None = None,
    bban: str | None = None,
) -> Supplier | None:
    """Look up (see `_find_supplier`) or create the supplier a NAV digest refers to.

    Only creates a new row when NAV actually supplied identifying data (a tax
    number or a name) — a digest with neither returns None so sync_nav's
    existing warning path still fires instead of a junk row being created.
    """
    supplier = _find_supplier(db, tax_id=tax_id, name=name, address=address, iban=iban, bban=bban)
    if supplier is not None:
        return supplier
    if not tax_id and not name:
        return None
    supplier = Supplier(
        name=name or tax_id,
        tax_id=tax_id or None,
        address=address,
        iban=iban,
        bban=bban,
    )
    db.add(supplier)
    db.flush()  # populate supplier.id for use as a FK below
    return supplier


def _find_customer(
    db: Session,
    tax_id: str,
    name: str,
    address: str | None = None,
    iban: str | None = None,
    bban: str | None = None,
) -> Customer | None:
    """Look up (never create) the customer a NAV digest refers to — see _find_supplier."""
    existing = db.query(Customer).filter_by(tax_id=tax_id).first() if tax_id else None
    if not existing and tax_id:
        core = _normalize_tax_number(tax_id)
        if core:
            for candidate in db.query(Customer).filter(Customer.tax_id.isnot(None)):
                if _normalize_tax_number(candidate.tax_id) == core:
                    existing = candidate
                    break
    if not existing:
        name_norm = _normalize_name(name)
        if name_norm:
            for candidate in db.query(Customer).filter(Customer.tax_id.is_(None)):
                if _normalize_name(candidate.name) == name_norm:
                    existing = candidate
                    break
        if existing and tax_id:
            existing.tax_id = tax_id
    if existing:
        if not existing.name and name:
            existing.name = name
        if not existing.address and address:
            existing.address = address
        if not existing.iban and iban:
            existing.iban = iban
        if not existing.bban and bban:
            existing.bban = bban
        existing.updated_at = utcnow()
    return existing


def _find_or_create_customer(
    db: Session,
    tax_id: str,
    name: str,
    address: str | None = None,
    iban: str | None = None,
    bban: str | None = None,
) -> Customer | None:
    """Look up (see `_find_customer`) or create the customer a NAV digest refers to.

    See `_find_or_create_supplier` — only creates when NAV gave identifying
    data, and never overwrites a field the user already set by hand.
    """
    customer = _find_customer(db, tax_id=tax_id, name=name, address=address, iban=iban, bban=bban)
    if customer is not None:
        return customer
    if not tax_id and not name:
        return None
    customer = Customer(
        name=name or tax_id,
        tax_id=tax_id or None,
        address=address,
        iban=iban,
        bban=bban,
    )
    db.add(customer)
    db.flush()  # populate customer.id for use as a FK below
    return customer


def _persist_invoice_detail(
    db: Session,
    invoice_id: int,
    detail: dict,
    supplier_name: str = "",
    supplier_tax_number: str = "",
    customer_name: str = "",
    customer_tax_number: str = "",
) -> None:
    """Upsert InvoiceDetail's partner snapshot (always) and full NAV detail (when fetched).

    supplier/customer name+tax_number come from the digest and are always
    available, so they're refreshed on every sync regardless of whether the
    (bounded) enrichment call ran this time — an unmatched invoice must still
    tell the user exactly who needs to be created, even if the fuller detail
    call hasn't happened yet or failed. address/bank_account/lines/VAT
    summary/etc. only come from the detail call, so those are only touched
    when *detail* is non-empty — leaving them untouched (rather than
    overwriting with blanks) on runs where the detail call was skipped.
    NAV data for a given invoice_number is immutable once issued (modifications
    arrive as a distinct new invoice_number, see sync_nav's docstring) so
    delete-then-reinsert per invoice on each enrichment fetch is safe and
    simpler than diffing line-by-line.
    """
    partner_fields = {
        "supplier_name": supplier_name or None,
        "supplier_tax_number": supplier_tax_number or None,
        "customer_name": customer_name or None,
        "customer_tax_number": customer_tax_number or None,
    }
    existing_row = db.query(InvoiceDetail).filter_by(invoice_id=invoice_id).first()
    if existing_row:
        for key, value in partner_fields.items():
            setattr(existing_row, key, value)
    else:
        existing_row = InvoiceDetail(invoice_id=invoice_id, **partner_fields)
        db.add(existing_row)

    if detail:
        delivery_date_str = detail.get("delivery_date") or ""
        try:
            delivery_date = date.fromisoformat(delivery_date_str) if delivery_date_str else None
        except ValueError:
            delivery_date = None

        detail_only_fields = {
            "raw_xml": detail.get("invoice_xml"),
            "supplier_address": detail.get("supplier_address") or None,
            "supplier_bank_account": detail.get("supplier_bank_account") or None,
            "customer_address": detail.get("customer_address") or None,
            "customer_bank_account": detail.get("customer_bank_account") or None,
            "invoice_category": detail.get("invoice_category") or None,
            "delivery_date": delivery_date,
            "currency_code": detail.get("currency_code") or None,
            "exchange_rate": detail.get("exchange_rate"),
            "invoice_appearance": detail.get("invoice_appearance") or None,
            "invoice_net_amount": detail.get("invoice_net_amount"),
            "invoice_vat_amount": detail.get("invoice_vat_amount"),
            "invoice_gross_amount": detail.get("invoice_gross_amount"),
        }
        for key, value in detail_only_fields.items():
            setattr(existing_row, key, value)

        db.query(InvoiceLine).filter_by(invoice_id=invoice_id).delete()
        for line in detail.get("lines") or []:
            db.add(
                InvoiceLine(
                    invoice_id=invoice_id,
                    line_number=line.get("line_number") or None,
                    line_description=line.get("line_description") or None,
                    quantity=line.get("quantity"),
                    unit_of_measure=line.get("unit_of_measure") or None,
                    unit_price=line.get("unit_price"),
                    line_net_amount=line.get("line_net_amount"),
                    line_vat_rate=line.get("line_vat_rate"),
                    line_vat_amount=line.get("line_vat_amount"),
                    line_gross_amount=line.get("line_gross_amount"),
                )
            )

        db.query(InvoiceVatSummary).filter_by(invoice_id=invoice_id).delete()
        for row in detail.get("vat_summary") or []:
            db.add(
                InvoiceVatSummary(
                    invoice_id=invoice_id,
                    vat_rate=row.get("vat_rate"),
                    vat_rate_net_amount=row.get("vat_rate_net_amount"),
                    vat_rate_vat_amount=row.get("vat_rate_vat_amount"),
                )
            )

    existing_row.updated_at = utcnow()


def sync_nav(
    start: str, end: str, db: Session, settings: Settings | None = None
) -> tuple[int, list[str]]:
    """Fetch NAV invoices, upsert invoices, and upsert suppliers/customers.

    Suppliers/customers referenced by a digest are looked up first and only
    created when missing (see `_find_or_create_supplier`/
    `_find_or_create_customer`), so re-syncs never spawn duplicates and a
    partner's manually-edited fields are never overwritten. A digest that
    gives NAV no usable identifying data (neither a tax number nor a name)
    still can't be linked or created — the invoice is still imported (with
    that side left unlinked) and a warning is returned for the Sync page to
    surface.
    """
    settings = settings or get_settings()
    nav_client = NavClient(settings)
    digests = nav_client.get_invoices(start, end)
    count = 0
    warnings: list[str] = []
    for digest in digests:
        supplier_tax = digest.get("supplier_tax_number", "")
        supplier_name = digest.get("supplier_name", "")
        customer_tax = digest.get("customer_tax_number", "")
        customer_name = digest.get("customer_name", "")
        invoice_number = digest.get("invoice_number", "")
        if not invoice_number:
            continue

        direction_str = digest.get("direction", "OUTBOUND")
        direction = (
            _InvoiceDirection[direction_str]
            if direction_str in _InvoiceDirection.__members__
            else _InvoiceDirection.OUTBOUND
        )

        existing = db.query(Invoice).filter_by(invoice_number=invoice_number).first()
        existing_detail = (
            db.query(InvoiceDetail).filter_by(invoice_id=existing.id).first() if existing else None
        )

        # Fetch enriched per-invoice data (address/bank account/payment terms,
        # full detail/lines/VAT summary) only for invoices that need it — new
        # ones, ones synced before this enrichment existed, or ones whose
        # detail row exists but was never actually populated (raw_xml is only
        # ever set inside _persist_invoice_detail's `if detail:` branch, so
        # its absence means the enrichment call was skipped or came back
        # empty last time) — to bound the extra NAV round-trips per sync run
        # while still self-healing incomplete rows on the next sync.
        detail: dict = {}
        if (
            not existing
            or not existing.payment_method
            or not existing_detail
            or not existing_detail.raw_xml
        ):
            detail = (
                nav_client.get_invoice_detail(
                    invoice_number, direction_str, supplier_tax_number=supplier_tax
                )
                or {}
            )

        supplier_iban, supplier_bban = classify_bank_account(detail.get("supplier_bank_account"))
        customer_iban, customer_bban = classify_bank_account(detail.get("customer_bank_account"))

        supplier = _find_or_create_supplier(
            db,
            tax_id=supplier_tax,
            name=supplier_name,
            address=detail.get("supplier_address") or None,
            iban=supplier_iban,
            bban=supplier_bban,
        )
        customer = _find_or_create_customer(
            db,
            tax_id=customer_tax,
            name=customer_name,
            address=detail.get("customer_address") or None,
            iban=customer_iban,
            bban=customer_bban,
        )
        if not supplier:
            warnings.append(
                f"Számla {invoice_number}: ismeretlen szállító '{supplier_name}' "
                f"(adószám: {supplier_tax or '—'}) — hozza létre a Szállítók oldalon"
            )
        if not customer:
            warnings.append(
                f"Számla {invoice_number}: ismeretlen vevő '{customer_name}' "
                f"(adószám: {customer_tax or '—'}) — hozza létre a Vevők oldalon"
            )

        issue_date_str = digest.get("invoice_issue_date", "")
        try:
            issue_date = date.fromisoformat(issue_date_str) if issue_date_str else None
        except ValueError:
            issue_date = None

        amount_net = digest.get("invoice_net_amount")
        amount_vat = digest.get("invoice_vat_amount")
        amount_total = (
            (amount_net or 0.0) + (amount_vat or 0.0)
            if amount_net is not None or amount_vat is not None
            else None
        )
        currency = digest.get("currency") or None
        invoice_operation = digest.get("invoice_operation") or None
        invoice_category = digest.get("invoice_category") or None

        payment_method = detail.get("payment_method") or None
        payment_due_date_str = detail.get("payment_due_date") or ""
        try:
            payment_due_date = (
                date.fromisoformat(payment_due_date_str) if payment_due_date_str else None
            )
        except ValueError:
            payment_due_date = None

        if existing:
            inv_obj = existing
            existing.invoice_date = issue_date
            existing.amount_net = amount_net
            existing.amount_vat = amount_vat
            existing.amount_total = amount_total
            existing.direction = direction
            existing.currency = currency
            existing.invoice_operation = invoice_operation
            existing.invoice_category = invoice_category
            if payment_method:
                existing.payment_method = payment_method
            if payment_due_date:
                existing.payment_due_date = payment_due_date
            # Self-heal: a previously-pending invoice (no partner match at the
            # time) picks up the link once the user manually creates the
            # missing supplier/customer and this invoice syncs again.
            # Skipped when the field was manually set/cleared (locked) — a
            # manual decision always wins over automatic (re-)association.
            if (
                existing.supplier_id is None
                and supplier is not None
                and not existing.supplier_locked
            ):
                existing.supplier_id = supplier.id
            if (
                existing.customer_id is None
                and customer is not None
                and not existing.customer_locked
            ):
                existing.customer_id = customer.id
            existing.updated_at = utcnow()
        else:
            inv_obj = Invoice(
                invoice_number=invoice_number,
                invoice_date=issue_date,
                supplier_id=supplier.id if supplier else None,
                customer_id=customer.id if customer else None,
                amount_net=amount_net,
                amount_vat=amount_vat,
                amount_total=amount_total,
                payment_status=_PaymentStatus.UNPAID,
                direction=direction,
                currency=currency,
                invoice_operation=invoice_operation,
                invoice_category=invoice_category,
                nav_ins_date=digest.get("ins_date"),
                payment_method=payment_method,
                payment_due_date=payment_due_date,
            )
            db.add(inv_obj)
            db.flush()  # populate inv_obj.id for use as a FK below
            count += 1

        # Always refresh the partner-name/tax-number snapshot (from the
        # digest); detail-derived fields inside are only touched when a
        # detail fetch happened this run (see _persist_invoice_detail).
        _persist_invoice_detail(
            db,
            inv_obj.id,
            detail,
            supplier_name=supplier_name,
            supplier_tax_number=supplier_tax,
            customer_name=customer_name,
            customer_tax_number=customer_tax,
        )

    db.commit()
    logger.info(
        "sync_nav: %d new invoice(s) from %d digest(s), %d warning(s)",
        count,
        len(digests),
        len(warnings),
    )
    return count, warnings


def _is_deleted(db: Session, filename: str) -> bool:
    """Check if an InvoiceFile record exists with is_deleted=True."""
    existing = db.query(InvoiceFile).filter(InvoiceFile.filename.ilike(filename)).first()
    return existing is not None and existing.is_deleted


def sync_pdf(start: str, end: str, db: Session, settings: Settings | None = None) -> int:
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
        logger.warning(
            "sync_pdf: no invoice files returned by invoice-file-filter for %s..%s", start, end
        )
        return 0

    # Skip any already-deleted files (is_deleted=True)
    files = [pdf_entry for pdf_entry in files if not _is_deleted(db, pdf_entry.get("filename", ""))]

    if not files:
        logger.info("sync_pdf: all files for %s..%s already deleted or not found")
        return 0

    # ── Phase 1: upsert InvoiceFile rows, keep (record, path) for link pass ──
    count = 0
    records: list[tuple[InvoiceFile, str]] = []
    for pdf_entry in files:
        filename = pdf_entry.get("filename", "")
        path = pdf_entry.get("path", "")
        if not filename:
            continue
        size = pdf_entry.get("file_size")
        preview_base64 = pdf_entry.get("preview_base64")

        existing = db.query(InvoiceFile).filter(InvoiceFile.filename.ilike(filename)).first()
        if existing:
            existing.path = path or existing.path
            if size is not None:
                existing.file_size = size
            existing.preview_base64 = preview_base64
            existing.updated_at = utcnow()
            db.flush()
            invoice_file = existing
        else:
            invoice_file = InvoiceFile(
                filename=filename, path=path, file_size=size, preview_base64=preview_base64
            )
            db.add(invoice_file)
            db.flush()
            count += 1
        records.append((invoice_file, path))

    # ── Phase 2: link unmatched invoices ─────────────────────────────────────
    _link_invoices_to_files(db, [invoice_file for invoice_file, _ in records], pdf_client)

    db.commit()
    logger.info("sync_pdf: %d new invoice_file record(s) from %d file(s)", count, len(files))
    return count


def _find_invoice_by_ref(db: Session, payment_ref: str) -> Invoice | None:
    """Exact → norm → stripped → subtoken search against invoice numbers."""
    invoice = db.query(Invoice).filter_by(invoice_number=payment_ref).first()
    if invoice:
        return invoice

    def _search(token: str) -> Invoice | None:
        norm_tok = _norm(token)
        stripped_tok = _STRIP_SEPS_RE.sub("", token.lower())
        like_pattern = re.sub(r"[-/\\\\_. ]+", "%", token)
        candidates = (
            db.query(Invoice).filter(Invoice.invoice_number.ilike(f"%{like_pattern}%")).all()
        )
        return next(
            (
                inv
                for inv in candidates
                if _norm(inv.invoice_number) == norm_tok
                or _STRIP_SEPS_RE.sub("", (inv.invoice_number or "").lower()) == stripped_tok
            ),
            None,
        )

    hit = _search(payment_ref)
    if hit:
        return hit

    # Payment references often carry extra text after the invoice number
    # (e.g. "KE26/42278 Graphtrek Kft").  Try each whitespace-separated token
    # that contains at least one digit as a candidate invoice number.
    for token in payment_ref.split():
        if token == payment_ref or not any(c.isdigit() for c in token):
            continue
        hit = _search(token)
        if hit:
            return hit

    return None


_BANK_FEE_KEYWORDS = ("fee", "díj", "kamat")


def _is_bank_fee_or_interest(txn_dict: dict) -> bool:
    """True if a transaction's description/type/category names it as a bank fee or interest."""
    haystack = " ".join(
        str(txn_dict.get(field) or "") for field in ("description", "transaction_type", "category")
    ).lower()
    return any(keyword in haystack for keyword in _BANK_FEE_KEYWORDS)


def _get_or_create_bank_supplier(db: Session, bank_code: str, settings: Settings) -> Supplier:
    """Return the Supplier representing the bank itself, creating it if needed."""
    name = settings.bank_supplier_names.get(bank_code, bank_code.capitalize())
    supplier = db.query(Supplier).filter_by(name=name).first()
    if supplier:
        return supplier
    supplier = Supplier(name=name)
    db.add(supplier)
    db.flush()
    return supplier


def sync_bank(
    start: str, end: str, db: Session, settings: Settings | None = None
) -> tuple[int, list[str]]:
    """Fetch bank transactions, insert new ones, and link to invoice/supplier/customer.

    Runs through several phases in order, each handling transactions the
    previous one couldn't:
    1. Ensure every configured bank has its own "supplier" record (for fees/interest).
    2. Clear stale links on tax-authority transactions (rules can change over time).
    3. Insert/update each fetched transaction, then try to link it via:
       a. an exact `payment_reference` match against an invoice number,
       b. the supplier/customer already on the linked invoice (if any),
       c. the counterparty name, as a fallback partner lookup,
       d. bank-fee/interest detection, linking the transaction to the bank itself.
    4. Recompute PAID/PARTIAL/UNPAID for every invoice that gained a new link.

    Never creates a new Supplier/Customer for an unmatched counterparty (only
    looks one up by name) — an unmatched transaction is left unlinked and
    reported in the returned warnings list instead.
    """
    settings = settings or get_settings()

    # Ensure every configured bank has a supplier record, ready to receive
    # fee/interest transactions even before any such transaction exists.
    for bank_code in settings.bank_supplier_names:
        _get_or_create_bank_supplier(db, bank_code, settings)
    db.commit()

    # Clear any previously created links on tax-account transactions.
    tax_keys = list(settings.tax_accounts.keys())
    if tax_keys:
        tax_txns = (
            db.query(BankTransaction)
            .filter(BankTransaction.counterparty_account.in_(tax_keys))
            .all()
        )
        wrongly_linked = [
            tax_txn
            for tax_txn in tax_txns
            if (tax_txn.invoices or tax_txn.invoice_file_id) and not tax_txn.invoice_file_locked
        ]
        affected_invoices = {inv for tax_txn in wrongly_linked for inv in tax_txn.invoices}
        for btxn in wrongly_linked:
            btxn.invoices.clear()
            btxn.invoice_file_id = None
            if not btxn.supplier_locked:
                btxn.supplier_id = None
            if not btxn.customer_locked:
                btxn.customer_id = None
        for inv in affected_invoices:
            _recompute_payment_status(db, inv)
        if wrongly_linked:
            logger.info("Cleared links from %d tax-account transaction(s)", len(wrongly_linked))

    transactions = BankClient(settings).get_transactions()
    count = 0
    warnings: list[str] = []
    for txn_dict in transactions:
        txn_id = txn_dict.get("transaction_id", "")
        if not txn_id:
            continue

        existing = db.query(BankTransaction).filter_by(transaction_id=txn_id).first()
        if existing:
            btxn = existing
            # Refresh fields the bank service may only be able to supply on a
            # later re-export (e.g. address/FX data added to the CSV after
            # the transaction was first synced) — never overwrite with blanks.
            if txn_dict.get("counterparty_address"):
                btxn.counterparty_address = txn_dict["counterparty_address"]
            if txn_dict.get("sender_address"):
                btxn.sender_address = txn_dict["sender_address"]
            if txn_dict.get("counterparty_bank_code"):
                btxn.counterparty_bank_code = txn_dict["counterparty_bank_code"]
            if txn_dict.get("exchange_rate") is not None:
                btxn.exchange_rate = _opt_float(txn_dict, "exchange_rate")
            if txn_dict.get("exchange_to_currency"):
                btxn.exchange_to_currency = txn_dict["exchange_to_currency"]
            if txn_dict.get("card_last_four"):
                btxn.card_last_four = txn_dict["card_last_four"]
            if txn_dict.get("note"):
                btxn.note = txn_dict["note"]
            btxn.updated_at = utcnow()
        else:
            # Use datetime if available, fall back to date
            txn_dt_raw = txn_dict.get("datetime") or txn_dict.get("date")
            try:
                txn_date = datetime.fromisoformat(str(txn_dt_raw)) if txn_dt_raw else utcnow()
            except ValueError:
                txn_date = utcnow()

            amount_raw = txn_dict.get("amount", 0)
            try:
                amount = float(amount_raw)
            except (TypeError, ValueError):
                amount = 0.0

            btxn = BankTransaction(
                bank=txn_dict.get("bank", ""),
                transaction_id=txn_id,
                amount=amount,
                currency=txn_dict.get("currency", ""),
                direction=txn_dict.get("direction", ""),
                transaction_date=txn_date,
                description=txn_dict.get("description"),
                payment_reference=txn_dict.get("payment_reference"),
                counterparty_name=txn_dict.get("counterparty_name"),
                counterparty_account=txn_dict.get("counterparty_account"),
                counterparty_iban=txn_dict.get("counterparty_iban"),
                transaction_type=txn_dict.get("transaction_type"),
                category=txn_dict.get("category"),
                balance=_opt_float(txn_dict, "balance"),
                fees=_opt_float(txn_dict, "fees"),
                counterparty_address=txn_dict.get("counterparty_address"),
                sender_address=txn_dict.get("sender_address"),
                counterparty_bank_code=txn_dict.get("counterparty_bank_code"),
                exchange_rate=_opt_float(txn_dict, "exchange_rate"),
                exchange_to_currency=txn_dict.get("exchange_to_currency"),
                card_last_four=txn_dict.get("card_last_four"),
                note=txn_dict.get("note"),
            )
            db.add(btxn)
            db.flush()
            count += 1

        # ── Skip all linking for tax-authority payments ───────────────────────
        if _is_tax_account(btxn.counterparty_account, settings):
            continue

        # ── Link invoice via payment_reference ────────────────────────────────
        payment_ref = txn_dict.get("payment_reference", "") or ""
        if payment_ref and not btxn.invoices:
            invoice = _find_invoice_by_ref(db, payment_ref)
            if invoice:
                _link_txn_to_invoice(btxn, invoice)
                _recompute_payment_status(db, invoice)
                logger.info(
                    "Linked bank txn %s → invoice %s (paid)", txn_id, invoice.invoice_number
                )

        # ── Derive supplier/customer from linked invoice ───────────────────────
        if btxn.invoices and (
            (not btxn.supplier_id and not btxn.supplier_locked)
            or (not btxn.customer_id and not btxn.customer_locked)
        ):
            invoice = btxn.invoices[0]
            if not btxn.supplier_id and not btxn.supplier_locked:
                btxn.supplier_id = invoice.supplier_id
            if not btxn.customer_id and not btxn.customer_locked:
                btxn.customer_id = invoice.customer_id

        # ── Link supplier/customer by counterparty name (fallback) ────────────
        counterparty = txn_dict.get("counterparty_name", "") or ""
        if counterparty:
            if not btxn.supplier_id and not btxn.supplier_locked:
                supplier = (
                    db.query(Supplier).filter(Supplier.name.ilike(f"%{counterparty}%")).first()
                )
                if supplier:
                    btxn.supplier_id = supplier.id
            if not btxn.customer_id and not btxn.customer_locked:
                customer = (
                    db.query(Customer).filter(Customer.name.ilike(f"%{counterparty}%")).first()
                )
                if customer:
                    btxn.customer_id = customer.id

        # ── Link bank fee/interest transactions to the bank's own supplier ────
        if not btxn.supplier_id and not btxn.supplier_locked and _is_bank_fee_or_interest(txn_dict):
            bank_supplier = _get_or_create_bank_supplier(db, btxn.bank, settings)
            btxn.supplier_id = bank_supplier.id

        # ── Warn if still unmatched after every attempt above ─────────────────
        if not btxn.supplier_id and not btxn.customer_id:
            warnings.append(
                f"Bank tranzakció {txn_id}: nem sikerült partnerhez rendelni "
                f"('{counterparty or txn_dict.get('description') or '—'}')"
            )

    # Recompute payment status for all invoices with linked transactions.
    db.flush()
    linked_ids_q = select(invoice_bank_transaction.c.invoice_id).distinct()
    invoices_to_recompute = (
        db.query(Invoice)
        .options(joinedload(Invoice.bank_transactions))
        .filter(Invoice.id.in_(linked_ids_q))
        .all()
    )
    for inv in invoices_to_recompute:
        _recompute_payment_status(db, inv)

    db.commit()
    logger.info(
        "sync_bank: %d new transaction(s) from %d fetched, %d warning(s)",
        count,
        len(transactions),
        len(warnings),
    )
    return count, warnings


# ── BankTransaction ↔ invoice_file matching ────────────────────────────────────

_VENDOR_STOPWORDS = {
    "kommunikacios",
    "ugynokseg",
    "zartkoruen",
    "mukodo",
    "reszvenytarsasag",
    "subscription",
    "payment",
    "fizetes",
    "budapest",
    "paris",
    "dublin",
    "graphtrek",
    "graphtre",
    "invoice",
    "receipt",
    "szamla",
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
    ival = round(n)
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
        tok
        for tok in _TOKEN_RE.findall(_ascii_lower(raw))
        if len(tok) >= 4 and tok not in _VENDOR_STOPWORDS
    }


def _names_overlap(a_toks: set[str], b_toks: set[str]) -> bool:
    """True if any token pair shares a 4-char prefix (e.g. 'alza' matches 'alzahu')."""
    for a in a_toks:
        for b in b_toks:
            short, long = (a, b) if len(a) <= len(b) else (b, a)
            if len(short) >= 4 and long.startswith(short):
                return True
    return False


def _find_invoice_by_supplier_amount(
    txn: BankTransaction,
    candidates: list[Invoice],
    used_ids: set[int],
    amount_abs_tol: float = 5.0,
    amount_pct_tol: float = 0.01,
    max_days: int = 60,
) -> Invoice | None:
    """Match a transaction to an invoice by supplier-name prefix + close amount + date proximity.

    Used when no payment_reference is present and PDF-text scoring fails (e.g. e-commerce).
    Currencies must match; amount must be within abs_tol HUF or pct_tol %.
    """
    if not txn.counterparty_name or not txn.amount:
        return None
    txn_toks = {
        t
        for t in _TOKEN_RE.findall(_ascii_lower(txn.counterparty_name))
        if len(t) >= 4 and t not in _VENDOR_STOPWORDS
    }
    if not txn_toks:
        return None
    txn_amt = abs(txn.amount)
    txn_date = txn.transaction_date.date() if txn.transaction_date else None

    best: Invoice | None = None
    best_days = max_days + 1

    for inv in candidates:
        if inv.id in used_ids:
            continue
        if not inv.amount_total or not inv.supplier:
            continue
        if inv.currency and txn.currency and inv.currency != txn.currency:
            continue
        inv_amt = abs(inv.amount_total)
        diff = abs(inv_amt - txn_amt)
        if diff > amount_abs_tol and (txn_amt == 0 or diff / txn_amt > amount_pct_tol):
            continue
        sup_toks = {
            t
            for t in _TOKEN_RE.findall(_ascii_lower(inv.supplier.name))
            if len(t) >= 4 and t not in _VENDOR_STOPWORDS
        }
        if not _names_overlap(txn_toks, sup_toks):
            continue
        days = (
            abs((txn_date - inv.invoice_date).days)
            if (txn_date and inv.invoice_date)
            else max_days + 1
        )
        if days > max_days:
            continue
        if days < best_days:
            best_days = days
            best = inv

    return best


def _file_date(filename: str) -> date | None:
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
    txn_date: date | None,
    haystack: str,
    filename_norm: str,
    file_date: date | None,
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


def sync_match(db: Session, settings: Settings | None = None) -> int:
    """Best-match unlinked bank transactions to invoice files.

    1. Transitive shortcut: if the txn already links to an invoice that has a PDF,
       reuse that file (highest confidence).
    2. Authoritative reference: a bank transfer with an explicit invoice-like
       ``payment_reference`` (contains a digit) must match a file that *contains*
       that reference. If no file does, the txn is left unlinked.
    3. Otherwise score every (txn, file) pair on vendor name, amount, and date
       proximity; greedily assign in descending-score order.
    """
    # `settings` is used further down (PdfClient, tax_accounts, etc.); the

    settings = settings or get_settings()

    files = db.query(InvoiceFile).all()

    # ── Phase 0: link unmatched invoices to all known files ───────────────────
    pdf_client = PdfClient(settings)
    _link_invoices_to_files(db, files, pdf_client)

    tax_keys = list(settings.tax_accounts.keys())
    # Same reason as in _link_invoices_to_files(): SQLAlchemy needs `== None` /
    # `== False` (not `is None`/`is False`) to build the SQL WHERE clause.
    unmatched_q = db.query(BankTransaction).filter(
        BankTransaction.invoice_file_id == None,  # noqa: E711
        BankTransaction.invoice_file_locked == False,  # noqa: E712
    )
    if tax_keys:
        # `NOT IN` is SQL-NULL-unsafe: a row with counterparty_account IS NULL
        # would otherwise be silently dropped (`NULL IN (...)` is UNKNOWN, and
        # so is its negation), so the "or IS NULL" arm is required, not optional.
        unmatched_q = unmatched_q.filter(
            or_(
                BankTransaction.counterparty_account.is_(None),
                ~BankTransaction.counterparty_account.in_(tax_keys),
            )
        )
    unmatched = unmatched_q.all()
    file_feats = {
        f.id: (
            _ascii_lower(f.filename) + " " + _ascii_lower(f.words or ""),
            _norm(f.filename) + " " + _norm(f.words or ""),
            _file_date(f.filename),
        )
        for f in files
    }
    used_files: set[int] = set()
    count = 0

    def _assign(txn: BankTransaction, file_id: int, why: str) -> None:
        nonlocal count
        txn.invoice_file_id = file_id
        txn.updated_at = utcnow()
        used_files.add(file_id)
        count += 1
        logger.info("Matched bank txn %s → file_id %s (%s)", txn.transaction_id, file_id, why)

    # ── Phase 1: transitive shortcut + authoritative payment reference ───────
    remaining: list[BankTransaction] = []
    for txn in unmatched:
        if txn.invoices:
            invoice = txn.invoices[0]
            if invoice.invoice_file_id:
                _assign(txn, invoice.invoice_file_id, f"via invoice {invoice.invoice_number}")
                continue

        ref = (txn.payment_reference or "").strip()
        if ref and any(ch.isdigit() for ch in ref) and not _HU_TAX_NUMBER_RE.match(ref):
            norm_ref = _norm(ref)
            subtokens = [
                p
                for p in norm_ref.split()
                if any(ch.isdigit() for ch in p) and p not in _VENDOR_STOPWORDS
            ]
            search_parts = list(dict.fromkeys([norm_ref, *subtokens]))
            hit = None
            for part in search_parts:
                hit = next(
                    (
                        f.id
                        for f in files
                        if f.id not in used_files and _token_match(part, file_feats[f.id][1])
                    ),
                    None,
                )
                if hit is not None:
                    break
            if hit is not None:
                _assign(txn, hit, f"reference {ref}")
            else:
                logger.warning(
                    "Bank txn %s reference %s not found in any file — left unlinked",
                    txn.transaction_id,
                    ref,
                )
            continue

        remaining.append(txn)

    # ── Phase 1.5: supplier-name + amount match for reference-less transactions ──
    linked_invoice_ids: set[int] = {
        row[0] for row in db.execute(select(invoice_bank_transaction.c.invoice_id).distinct())
    }
    inv_pool = (
        db.query(Invoice)
        # _find_invoice_by_supplier_amount reads inv.supplier.name per
        # (txn, inv) pair — without selectinload that's one query per
        # invoice in the pool (N+1 across the whole scored pass).
        .options(selectinload(Invoice.supplier))
        .filter(Invoice.id.notin_(linked_invoice_ids))
        .all()
    )
    used_inv_ids: set[int] = set()
    remaining_after_15: list[BankTransaction] = []

    for txn in remaining:
        if _is_tax_account(txn.counterparty_account, settings):
            remaining_after_15.append(txn)
            continue
        matched = _find_invoice_by_supplier_amount(txn, inv_pool, used_inv_ids)
        if matched:
            _link_txn_to_invoice(txn, matched)
            if not txn.supplier_id and not txn.supplier_locked:
                txn.supplier_id = matched.supplier_id
            if not txn.customer_id and not txn.customer_locked:
                txn.customer_id = matched.customer_id
            _recompute_payment_status(db, matched)
            used_inv_ids.add(matched.id)
            if matched.invoice_file_id and matched.invoice_file_id not in used_files:
                _assign(txn, matched.invoice_file_id, f"supplier+amount {txn.counterparty_name}")
            else:
                txn.updated_at = utcnow()
                logger.info(
                    "Linked bank txn %s → invoice %s (supplier+amount, no file)",
                    txn.transaction_id,
                    matched.invoice_number,
                )
        else:
            remaining_after_15.append(txn)

    remaining = remaining_after_15

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
        txn.updated_at = utcnow()
        used_txns.add(txn_id)
        used_files.add(file_id)
        count += 1
        logger.info(
            "Matched bank txn %s → file_id %s (score %.2f)",
            txn.transaction_id,
            file_id,
            score,
        )

    for txn in remaining:
        if txn.id not in used_txns:
            logger.warning(
                "No confident invoice_file match for bank txn %s (%s)",
                txn.transaction_id,
                txn.counterparty_name or "",
            )

    # ── Phase 3: back-link transactions to invoices via shared invoice_file ────
    # selectinload(BankTransaction.invoices): the `not t.invoices` filter below
    # touches the relationship per row — without it that's one query per
    # transaction (N+1) just to check emptiness.
    to_backlink_all = (
        db.query(BankTransaction)
        .options(selectinload(BankTransaction.invoices))
        .filter(BankTransaction.invoice_file_id.isnot(None))
        .all()
    )
    to_backlink = [t for t in to_backlink_all if not t.invoices]
    # Batch the invoice-by-file_id lookups: the old code ran one
    # `db.query(Invoice).filter_by(invoice_file_id=...)` per txn (N queries).
    # Now a single query fetches every distinct invoice and
    # selectinload(Invoice.bank_transactions) preloads the relationship that
    # _recompute_payment_status reads, so no per-invoice lazy load either.
    backlink_file_ids = {t.invoice_file_id for t in to_backlink if t.invoice_file_id}
    invoice_by_file_id: dict[int, Invoice] = {}
    if backlink_file_ids:
        inv_rows = (
            db.query(Invoice)
            .options(selectinload(Invoice.bank_transactions))
            .filter(Invoice.invoice_file_id.in_(backlink_file_ids))
            .all()
        )
        invoice_by_file_id = {inv.invoice_file_id: inv for inv in inv_rows}
    for txn in to_backlink:
        invoice = invoice_by_file_id.get(txn.invoice_file_id)
        if invoice:
            _link_txn_to_invoice(txn, invoice)
            txn.updated_at = utcnow()
            _recompute_payment_status(db, invoice)
            logger.info(
                "Backlinked bank txn %s → invoice %s via shared file_id %s",
                txn.transaction_id,
                invoice.invoice_number,
                txn.invoice_file_id,
            )

    # ── Backfill supplier_id / customer_id from linked invoice ───────────────
    needs_backfill = (
        db.query(BankTransaction)
        .join(BankTransaction.invoices)
        .filter((BankTransaction.supplier_id.is_(None)) | (BankTransaction.customer_id.is_(None)))
        .all()
    )
    for txn in needs_backfill:
        invoice = txn.invoices[0] if txn.invoices else None
        if invoice:
            if not txn.supplier_id and not txn.supplier_locked:
                txn.supplier_id = invoice.supplier_id
            if not txn.customer_id and not txn.customer_locked:
                txn.customer_id = invoice.customer_id
            txn.updated_at = utcnow()

    db.commit()
    logger.info("sync_match: %d bank transaction(s) linked to a file", count)
    return count


def get_pending_sync_counts(db: Session, settings: Settings | None = None) -> tuple[int, int]:
    """Durable counts of invoices/bank transactions still missing a partner match.

    Unlike the per-run `errors`/warnings (transient — only shown right after a
    sync), this reflects current DB state regardless of when sync last ran,
    so the Sync page can show it's still pending even days later.
    """
    settings = settings or get_settings()
    unmatched_invoices = (
        db.query(Invoice)
        .filter(or_(Invoice.supplier_id.is_(None), Invoice.customer_id.is_(None)))
        .count()
    )
    tax_keys = list(settings.tax_accounts.keys())
    unmatched_txn_q = db.query(BankTransaction).filter(
        BankTransaction.supplier_id.is_(None), BankTransaction.customer_id.is_(None)
    )
    if tax_keys:
        unmatched_txn_q = unmatched_txn_q.filter(
            or_(
                BankTransaction.counterparty_account.is_(None),
                BankTransaction.counterparty_account.notin_(tax_keys),
            )
        )
    return unmatched_invoices, unmatched_txn_q.count()


# ── sync_all concurrency guard (DEF-012) ─────────────────────────────────────
#
# See SyncLock's docstring in db.py for why this is a DB row rather than an
# in-process lock or a PostgreSQL advisory lock.

SYNC_LOCK_ID = 1

# How long a lock is honored before a later caller is allowed to steal it back.
# Must comfortably exceed a legitimate full sync's real-world duration (NAV +
# PDF + bank + match, each with its own sync_timeout=300s downstream HTTP
# budget) while still self-healing in a bounded time if the process holding
# the lock dies (killed, crashed, host rebooted) without reaching the
# `finally` that would have released it -- see _release_sync_lock. No manual
# intervention (e.g. a DB UPDATE) is ever required to recover from that case;
# the next sync attempt after this timeout simply takes the lock over.
SYNC_LOCK_STALE_SECONDS = 1800  # 30 minutes

SYNC_IN_PROGRESS_MESSAGE = (
    "Szinkronizálás már folyamatban van, kérjük várja meg a jelenlegi "
    "folyamat befejezését, mielőtt újat indítana."
)


class SyncInProgressError(RuntimeError):
    """Raised when sync_all is invoked while another sync already holds the lock."""


def _acquire_sync_lock(db: Session) -> None:
    """Atomically acquire the singleton sync_lock row, or raise SyncInProgressError.

    The acquire itself is a single ``UPDATE ... WHERE (unlocked OR stale)``
    statement, so two concurrent callers racing for the same row can never
    both succeed: on PostgreSQL the second UPDATE blocks on the first's row
    lock until it commits and then re-evaluates the WHERE clause (and loses,
    because locked_at is no longer NULL/stale); SQLite serializes writers at
    the database level the same way. Whichever caller's UPDATE actually
    matches a row (rowcount == 1) holds the lock; the other gets rowcount == 0
    and must fail fast and cleanly rather than queue or retry.
    """
    now = utcnow()
    stale_cutoff = now - timedelta(seconds=SYNC_LOCK_STALE_SECONDS)

    if db.get(SyncLock, SYNC_LOCK_ID) is None:
        # First sync ever attempted against this database: create the
        # singleton row up front. Harmless if another process races us here
        # and inserts it first -- we just retry the lookup.
        db.add(SyncLock(id=SYNC_LOCK_ID, locked_at=None, locked_by=None))
        try:
            db.commit()
        except Exception:  # noqa: BLE001 -- unique-violation race, row already exists
            db.rollback()

    owner = f"{socket.gethostname()}:{os.getpid()}"
    result = db.execute(
        sa_update(SyncLock)
        .where(
            SyncLock.id == SYNC_LOCK_ID,
            or_(SyncLock.locked_at.is_(None), SyncLock.locked_at < stale_cutoff),
        )
        .values(locked_at=now, locked_by=owner)
    )
    db.commit()
    if result.rowcount == 0:
        logger.warning("sync_all rejected: another sync is already in progress")
        raise SyncInProgressError(SYNC_IN_PROGRESS_MESSAGE)


def _release_sync_lock(db: Session) -> None:
    """Release the sync_all lock. Called from a `finally`, so this runs on both
    success and failure -- the lock is never held past the end of the request
    that acquired it (short of the process being killed outright; see
    SYNC_LOCK_STALE_SECONDS above for that case).
    """
    db.execute(
        sa_update(SyncLock)
        .where(SyncLock.id == SYNC_LOCK_ID)
        .values(locked_at=None, locked_by=None)
    )
    db.commit()


def sync_all(request: SyncRequest, db: Session, settings: Settings | None = None) -> SyncResponse:
    """Run the full or partial sync pipeline.

    Guarded by a DB-backed mutex (see _acquire_sync_lock) so a second
    concurrent call -- from a second API request or a second CLI invocation,
    possibly against a different uvicorn worker process -- fails fast with
    SyncInProgressError instead of racing this one for the same DB rows.
    """
    settings = settings or get_settings()
    _acquire_sync_lock(db)
    try:
        start, end = _default_dates(request.start_date, request.end_date)
        mode = request.sync_mode or SyncMode.full
        errors: list[str] = []
        warnings: list[str] = []
        nav_count = pdf_count = bank_count = match_count = 0
        t0 = time.monotonic()

        log = SyncLog(started_at=utcnow(), mode=mode.value)
        db.add(log)
        db.flush()

        if request.clear_cache:
            logger.info("Clearing downstream caches before sync")
            NavClient(settings).clear_cache()
            PdfClient(settings).clear_cache()

        if mode in (SyncMode.full, SyncMode.nav_only):
            try:
                nav_count, nav_warnings = sync_nav(start, end, db, settings)
                warnings.extend(nav_warnings)
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
                bank_count, bank_warnings = sync_bank(start, end, db, settings)
                warnings.extend(bank_warnings)
            except BankClientError as exc:
                logger.error("Bank sync failed: %s", exc)
                errors.append(f"Bank: {exc}")

        if mode in (SyncMode.full, SyncMode.match_only):
            try:
                match_count = sync_match(db, settings)
            # Catching the broad `Exception` (not a specific *ClientError) is
            # deliberate here: sync_match has no dedicated exception type of its own,
            # and any unexpected error in it must not abort the whole sync run —
            # the other phases above already succeeded and their results should
            # still be reported. The noqa on the except line below silences BLE001.
            except Exception as exc:  # noqa: BLE001
                logger.error("Bank↔file matching failed: %s", exc)
                errors.append(f"Match: {exc}")

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.finished_at = utcnow()
        log.invoice_count = nav_count
        log.bank_count = bank_count
        log.error_count = len(errors)
        log.errors = "; ".join(errors) if errors else None
        log.warning_count = len(warnings)
        log.warnings = "; ".join(warnings) if warnings else None
        db.commit()

        logger.info(
            "sync_all [%s] %s..%s: nav=%d pdf=%d bank=%d match=%d errors=%d warnings=%d in %.0fms",
            mode.value,
            start,
            end,
            nav_count,
            pdf_count,
            bank_count,
            match_count,
            len(errors),
            len(warnings),
            elapsed_ms,
        )
        return SyncResponse(
            start_date=start,
            end_date=end,
            nav_invoices_synced=nav_count,
            pdf_files_synced=pdf_count,
            bank_transactions_synced=bank_count,
            bank_files_matched=match_count,
            errors=errors,
            warnings=warnings,
        )
    finally:
        _release_sync_lock(db)
