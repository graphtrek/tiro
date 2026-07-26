from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi import Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from invoice_core.db import (
    BankTransaction,
    Customer,
    Invoice,
    InvoiceFile,
    InvoiceLine,
    InvoiceVatSummary,
    Supplier,
    _enum_str,
    _PaymentStatus,
    invoice_bank_transaction,
    invoice_has_bank_txn,
)
from invoice_core.db import InvoiceDetail as InvoiceDetailRow


@dataclass
class InvoiceRow:
    id: int
    invoice_number: str
    invoice_date: date | None
    supplier_id: int | None
    supplier_name: str | None
    customer_id: int | None
    customer_name: str | None
    amount_net: float | None
    amount_vat: float | None
    amount_total: float | None
    payment_status: str
    direction: str
    currency: str | None
    invoice_file_id: int | None
    invoice_file_filename: str | None
    bank_count: int
    note: str | None = None
    payment_status_locked: bool = False
    invoice_file_locked: bool = False
    supplier_locked: bool = False
    customer_locked: bool = False
    has_manual_bank_link: bool = False
    bank_transaction_ids: list[str] = field(default_factory=list)
    bank_transaction_db_ids: list[int] = field(default_factory=list)
    invoice_file_preview_base64: str | None = None


@dataclass
class BankTxnRow:
    id: int
    transaction_id: str
    bank: str
    transaction_date: datetime
    amount: float
    currency: str
    direction: str
    description: str | None
    payment_reference: str | None
    partner_name: str | None
    counterparty_account: str | None = None
    counterparty_iban: str | None = None
    transaction_type: str | None = None
    category: str | None = None
    balance: float | None = None
    fees: float | None = None
    counterparty_address: str | None = None
    sender_address: str | None = None
    counterparty_bank_code: str | None = None
    exchange_rate: float | None = None
    exchange_to_currency: str | None = None
    card_last_four: str | None = None
    note: str | None = None
    invoice_file_id: int | None = None
    invoice_file_filename: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class InvoiceDetail:
    id: int
    invoice_number: str
    invoice_date: date | None
    supplier_id: int | None
    supplier_name: str | None
    supplier_tax_id: str | None
    customer_id: int | None
    customer_name: str | None
    customer_tax_id: str | None
    amount_net: float | None
    amount_vat: float | None
    amount_total: float | None
    payment_status: str
    direction: str
    currency: str | None
    invoice_operation: str | None
    invoice_category: str | None
    nav_ins_date: str | None
    invoice_file_id: int | None
    invoice_file_filename: str | None
    invoice_file_locked: bool
    note: str | None
    payment_status_locked: bool
    supplier_locked: bool
    customer_locked: bool
    created_at: datetime
    updated_at: datetime
    payment_method: str | None = None
    payment_due_date: date | None = None
    bank_transactions: list[BankTxnRow] = field(default_factory=list)
    # Full NAV detail-call data (excludes raw_xml — large, not needed here;
    # see a dedicated xml endpoint if that's ever required).
    detail: dict | None = None
    lines: list[dict] = field(default_factory=list)
    vat_summary: list[dict] = field(default_factory=list)


def _bank_derived_status(amount_total: float | None, paid_sum: float) -> str:
    """Amount-based PAID/PARTIAL derivation from a currency-matched sum of
    linked bank-transaction amounts. Shared by both \`_derive_payment_status\`
    (detail view) and \`list_invoices\` so they compute the identical value.
    """
    total = amount_total or 0.0
    if total <= 0 or paid_sum >= total:
        return _PaymentStatus.PAID.value
    return _PaymentStatus.PARTIAL.value


def _effective_payment_status(
    stored_status: str,
    payment_status_locked: bool,
    derived_status: str,
) -> str:
    """Single shared rule for reconciling a stored \`payment_status\` with what
    linked bank transactions would otherwise imply.

    A manually locked invoice (\`payment_status_locked\`) must never have its
    displayed status overwritten by anything derived from bank transactions --
    it stays exactly as the user left it, per REQUIREMENTS.md's "manual paid
    flag" guarantee. An unlocked invoice is upgrade-only: linked transactions
    can only move it from UNPAID towards PAID/PARTIAL, never downgrade an
    already-PAID/PARTIAL stored status.

    Used by both \`list_invoices\` and \`get_invoice\` (via \`_derive_payment_status\`)
    so the two views can never disagree about the same invoice.
    """
    if payment_status_locked:
        return stored_status
    if stored_status == _PaymentStatus.UNPAID.value:
        return derived_status
    return stored_status


def _derive_payment_status(inv: Invoice, bank_txns: list) -> str:
    stored_status = _enum_str(inv.payment_status)
    if not bank_txns:
        return stored_status
    currency = inv.currency
    paid_sum = sum(abs(t.amount) for t in bank_txns if not currency or t.currency == currency)
    derived_status = _bank_derived_status(inv.amount_total, paid_sum)
    return _effective_payment_status(
        stored_status, bool(inv.payment_status_locked), derived_status
    )


class InvoiceFilters:
    def __init__(
        self,
        date_from: date | None = Query(None),
        date_to: date | None = Query(None),
        payment_status: str | None = Query(None),
        has_pdf: str | None = Query(None),
        supplier_name: str | None = Query(None),
    ):
        self.date_from = date_from
        self.date_to = date_to
        self.payment_status = payment_status
        self.has_pdf = has_pdf  # "true" | "false" | None
        self.supplier_name = supplier_name


def list_invoices(
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    payment_status: str | None = None,
    has_pdf: str | None = None,
    supplier_name: str | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[InvoiceRow]:
    """Return invoices matching the given filters, joined with supplier/customer/file info.

    Non-obvious rule: an invoice whose stored `payment_status` is still UNPAID
    is derived here (PAID or PARTIAL, via `_bank_derived_status`) from the
    currency-matched sum of its linked bank transactions, but only if its
    status hasn't been manually locked (`payment_status_locked`) -- see
    `_effective_payment_status`. This keeps the list in sync with reality
    even if `_recompute_payment_status()` (in service.py) hasn't run since
    the transaction was linked, without needing to write to the database on
    every read. A manually locked invoice is never auto-overridden this way,
    and the same rule is shared with `get_invoice`'s `_derive_payment_status`
    so the two views can never disagree about the same invoice.
    """
    bank_sub = (
        db.query(
            invoice_bank_transaction.c.invoice_id,
            func.count(invoice_bank_transaction.c.bank_transaction_id).label("cnt"),
        )
        .group_by(invoice_bank_transaction.c.invoice_id)
        .subquery()
    )
    # Currency-matched sum of linked transaction amounts per invoice, used
    # together with _bank_derived_status/_effective_payment_status so this
    # list can derive the exact same PAID/PARTIAL status as the detail view
    # (see invoice_service._derive_payment_status) instead of only ever
    # upgrading to PAID.
    paid_sub = (
        db.query(
            invoice_bank_transaction.c.invoice_id,
            func.sum(func.abs(BankTransaction.amount)).label("paid_sum"),
        )
        .select_from(invoice_bank_transaction)
        .join(
            BankTransaction,
            BankTransaction.id == invoice_bank_transaction.c.bank_transaction_id,
        )
        .join(Invoice, Invoice.id == invoice_bank_transaction.c.invoice_id)
        .filter(or_(Invoice.currency.is_(None), BankTransaction.currency == Invoice.currency))
        .group_by(invoice_bank_transaction.c.invoice_id)
        .subquery()
    )
    q = (
        db.query(
            Invoice,
            Supplier.name,
            Customer.name,
            func.coalesce(bank_sub.c.cnt, 0),
            InvoiceFile.filename,
            InvoiceFile.preview_base64,
            func.coalesce(paid_sub.c.paid_sum, 0.0),
        )
        # outerjoin: an invoice can now have no matched supplier/customer yet
        # (sync no longer auto-creates one — see service.py's _find_supplier)
        # and must still show up here rather than being silently dropped.
        .outerjoin(Supplier, Invoice.supplier_id == Supplier.id)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .outerjoin(bank_sub, Invoice.id == bank_sub.c.invoice_id)
        .outerjoin(InvoiceFile, Invoice.invoice_file_id == InvoiceFile.id)
        .outerjoin(paid_sub, Invoice.id == paid_sub.c.invoice_id)
    )
    if date_from:
        q = q.filter(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(Invoice.invoice_date <= date_to)
    if payment_status == "PAID":
        q = q.filter(or_(Invoice.payment_status == _PaymentStatus.PAID, invoice_has_bank_txn()))
    elif payment_status == "PARTIAL":
        q = q.filter(Invoice.payment_status == _PaymentStatus.PARTIAL)
    elif payment_status == "UNPAID":
        q = q.filter(Invoice.payment_status == _PaymentStatus.UNPAID, ~invoice_has_bank_txn())
    elif payment_status:
        with contextlib.suppress(KeyError):
            q = q.filter(Invoice.payment_status == _PaymentStatus[payment_status])
    if has_pdf == "true":
        q = q.filter(Invoice.invoice_file_id.isnot(None))
    elif has_pdf == "false":
        q = q.filter(Invoice.invoice_file_id.is_(None))
    if supplier_name:
        q = q.filter(Supplier.name.ilike(f"%{supplier_name}%"))

    q = q.order_by(Invoice.invoice_date.desc().nullslast(), Invoice.id.desc())
    q = q.offset(offset).limit(limit)
    rows = []
    for inv, sup_name, cust_name, bank_cnt, file_filename, file_preview, paid_sum in q.all():
        stored_status = _enum_str(inv.payment_status)
        derived_status = (
            _bank_derived_status(inv.amount_total, paid_sum or 0.0)
            if (bank_cnt or 0) > 0
            else stored_status
        )
        status = _effective_payment_status(
            stored_status, bool(inv.payment_status_locked), derived_status
        )
        rows.append(
            InvoiceRow(
                id=inv.id,
                invoice_number=inv.invoice_number,
                invoice_date=inv.invoice_date,
                supplier_id=inv.supplier_id,
                supplier_name=sup_name,
                customer_id=inv.customer_id,
                customer_name=cust_name,
                amount_net=inv.amount_net,
                amount_vat=inv.amount_vat,
                amount_total=inv.amount_total,
                payment_status=status,
                direction=_enum_str(inv.direction),
                currency=inv.currency,
                invoice_file_id=inv.invoice_file_id,
                invoice_file_filename=file_filename,
                bank_count=bank_cnt or 0,
                note=inv.note,
                payment_status_locked=bool(inv.payment_status_locked),
                invoice_file_locked=bool(inv.invoice_file_locked),
                supplier_locked=bool(inv.supplier_locked),
                customer_locked=bool(inv.customer_locked),
                invoice_file_preview_base64=file_preview,
            )
        )

    if rows:
        invoice_ids = [r.id for r in rows]
        txn_rows = (
            db.query(
                invoice_bank_transaction.c.invoice_id,
                BankTransaction.transaction_id,
                BankTransaction.id,
                invoice_bank_transaction.c.manual,
            )
            .join(
                BankTransaction,
                BankTransaction.id == invoice_bank_transaction.c.bank_transaction_id,
            )
            .filter(invoice_bank_transaction.c.invoice_id.in_(invoice_ids))
            .order_by(BankTransaction.transaction_date.desc())
            .all()
        )
        txn_map: dict[int, list[str]] = {}
        db_id_map: dict[int, list[int]] = {}
        manual_set: set[int] = set()
        for inv_id, txn_id, db_id, manual in txn_rows:
            txn_map.setdefault(inv_id, []).append(txn_id)
            db_id_map.setdefault(inv_id, []).append(db_id)
            if manual:
                manual_set.add(inv_id)
        for row in rows:
            row.bank_transaction_ids = txn_map.get(row.id, [])
            row.bank_transaction_db_ids = db_id_map.get(row.id, [])
            row.has_manual_bank_link = row.id in manual_set

    return rows


def get_invoice(db: Session, invoice_id: int) -> InvoiceDetail | None:
    row = (
        db.query(Invoice, Supplier, Customer)
        # outerjoin: see list_invoices — an invoice's partner may be unmatched.
        .outerjoin(Supplier, Invoice.supplier_id == Supplier.id)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if not row:
        return None
    inv, sup, cust = row

    filename = None
    if inv.invoice_file_id:
        f = db.query(InvoiceFile).filter_by(id=inv.invoice_file_id).first()
        filename = f.filename if f else None

    bank_txns = (
        db.query(BankTransaction)
        .join(
            invoice_bank_transaction,
            BankTransaction.id == invoice_bank_transaction.c.bank_transaction_id,
        )
        .filter(invoice_bank_transaction.c.invoice_id == invoice_id)
        .order_by(BankTransaction.transaction_date.desc())
        .all()
    )

    detail_row = db.query(InvoiceDetailRow).filter_by(invoice_id=invoice_id).first()
    detail_dict = None
    if detail_row:
        detail_dict = {
            "supplier_name": detail_row.supplier_name,
            "supplier_tax_number": detail_row.supplier_tax_number,
            "supplier_address": detail_row.supplier_address,
            "supplier_bank_account": detail_row.supplier_bank_account,
            "customer_name": detail_row.customer_name,
            "customer_tax_number": detail_row.customer_tax_number,
            "customer_address": detail_row.customer_address,
            "customer_bank_account": detail_row.customer_bank_account,
            "invoice_category": detail_row.invoice_category,
            "delivery_date": detail_row.delivery_date,
            "currency_code": detail_row.currency_code,
            "exchange_rate": detail_row.exchange_rate,
            "invoice_appearance": detail_row.invoice_appearance,
            "invoice_net_amount": detail_row.invoice_net_amount,
            "invoice_vat_amount": detail_row.invoice_vat_amount,
            "invoice_gross_amount": detail_row.invoice_gross_amount,
        }
    line_rows = (
        db.query(InvoiceLine).filter_by(invoice_id=invoice_id).order_by(InvoiceLine.id).all()
    )
    vat_summary_rows = (
        db.query(InvoiceVatSummary)
        .filter_by(invoice_id=invoice_id)
        .order_by(InvoiceVatSummary.id)
        .all()
    )

    return InvoiceDetail(
        id=inv.id,
        invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        supplier_id=sup.id if sup else None,
        supplier_name=sup.name if sup else None,
        supplier_tax_id=sup.tax_id if sup else None,
        customer_id=cust.id if cust else None,
        customer_name=cust.name if cust else None,
        customer_tax_id=cust.tax_id if cust else None,
        amount_net=inv.amount_net,
        amount_vat=inv.amount_vat,
        amount_total=inv.amount_total,
        payment_status=_derive_payment_status(inv, bank_txns),
        direction=_enum_str(inv.direction),
        currency=inv.currency,
        invoice_operation=inv.invoice_operation,
        invoice_category=inv.invoice_category,
        nav_ins_date=inv.nav_ins_date,
        invoice_file_id=inv.invoice_file_id,
        invoice_file_filename=filename,
        invoice_file_locked=inv.invoice_file_locked,
        note=inv.note,
        payment_status_locked=bool(inv.payment_status_locked),
        supplier_locked=bool(inv.supplier_locked),
        customer_locked=bool(inv.customer_locked),
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        payment_method=inv.payment_method,
        payment_due_date=inv.payment_due_date,
        detail=detail_dict,
        lines=[
            {
                "line_number": ln.line_number,
                "line_description": ln.line_description,
                "quantity": ln.quantity,
                "unit_of_measure": ln.unit_of_measure,
                "unit_price": ln.unit_price,
                "line_net_amount": ln.line_net_amount,
                "line_vat_rate": ln.line_vat_rate,
                "line_vat_amount": ln.line_vat_amount,
                "line_gross_amount": ln.line_gross_amount,
            }
            for ln in line_rows
        ],
        vat_summary=[
            {
                "vat_rate": row.vat_rate,
                "vat_rate_net_amount": row.vat_rate_net_amount,
                "vat_rate_vat_amount": row.vat_rate_vat_amount,
            }
            for row in vat_summary_rows
        ],
        bank_transactions=[
            BankTxnRow(
                id=t.id,
                transaction_id=t.transaction_id,
                bank=t.bank,
                transaction_date=t.transaction_date,
                amount=t.amount,
                currency=t.currency,
                direction=t.direction,
                description=t.description,
                payment_reference=t.payment_reference,
                partner_name=t.counterparty_name,
                counterparty_account=t.counterparty_account,
                counterparty_iban=t.counterparty_iban,
                transaction_type=t.transaction_type,
                category=t.category,
                balance=t.balance,
                fees=t.fees,
                counterparty_address=t.counterparty_address,
                sender_address=t.sender_address,
                counterparty_bank_code=t.counterparty_bank_code,
                exchange_rate=t.exchange_rate,
                exchange_to_currency=t.exchange_to_currency,
                card_last_four=t.card_last_four,
                note=t.note,
                invoice_file_id=t.invoice_file_id,
                invoice_file_filename=t.invoice_file.filename if t.invoice_file else None,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in bank_txns
        ],
    )
