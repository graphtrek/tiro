from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from fastapi import Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction, Customer, Invoice, InvoiceDetail as InvoiceDetailRow, InvoiceFile, InvoiceLine, InvoiceVatSummary, Supplier, _PaymentStatus, _enum_str, invoice_bank_transaction, invoice_has_bank_txn


@dataclass
class InvoiceRow:
    id: int
    invoice_number: str
    invoice_date: Optional[date]
    supplier_id: Optional[int]
    supplier_name: Optional[str]
    customer_id: Optional[int]
    customer_name: Optional[str]
    amount_net: Optional[float]
    amount_vat: Optional[float]
    amount_total: Optional[float]
    payment_status: str
    direction: str
    currency: Optional[str]
    invoice_file_id: Optional[int]
    invoice_file_filename: Optional[str]
    bank_count: int
    note: Optional[str] = None
    payment_status_locked: bool = False
    invoice_file_locked: bool = False
    supplier_locked: bool = False
    customer_locked: bool = False
    has_manual_bank_link: bool = False
    bank_transaction_ids: list[str] = field(default_factory=list)
    bank_transaction_db_ids: list[int] = field(default_factory=list)
    invoice_file_preview_base64: Optional[str] = None


@dataclass
class BankTxnRow:
    id: int
    transaction_id: str
    bank: str
    transaction_date: datetime
    amount: float
    currency: str
    direction: str
    description: Optional[str]
    payment_reference: Optional[str]
    partner_name: Optional[str]
    counterparty_account: Optional[str] = None
    counterparty_iban: Optional[str] = None
    transaction_type: Optional[str] = None
    category: Optional[str] = None
    balance: Optional[float] = None
    fees: Optional[float] = None
    counterparty_address: Optional[str] = None
    sender_address: Optional[str] = None
    counterparty_bank_code: Optional[str] = None
    exchange_rate: Optional[float] = None
    exchange_to_currency: Optional[str] = None
    card_last_four: Optional[str] = None
    note: Optional[str] = None
    invoice_file_id: Optional[int] = None
    invoice_file_filename: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class InvoiceDetail:
    id: int
    invoice_number: str
    invoice_date: Optional[date]
    supplier_id: Optional[int]
    supplier_name: Optional[str]
    supplier_tax_id: Optional[str]
    customer_id: Optional[int]
    customer_name: Optional[str]
    customer_tax_id: Optional[str]
    amount_net: Optional[float]
    amount_vat: Optional[float]
    amount_total: Optional[float]
    payment_status: str
    direction: str
    currency: Optional[str]
    invoice_operation: Optional[str]
    invoice_category: Optional[str]
    nav_ins_date: Optional[str]
    invoice_file_id: Optional[int]
    invoice_file_filename: Optional[str]
    invoice_file_locked: bool
    note: Optional[str]
    payment_status_locked: bool
    supplier_locked: bool
    customer_locked: bool
    created_at: datetime
    updated_at: datetime
    payment_method: Optional[str] = None
    payment_due_date: Optional[date] = None
    bank_transactions: list[BankTxnRow] = field(default_factory=list)
    # Full NAV detail-call data (excludes raw_xml — large, not needed here;
    # see a dedicated xml endpoint if that's ever required).
    detail: Optional[dict] = None
    lines: list[dict] = field(default_factory=list)
    vat_summary: list[dict] = field(default_factory=list)


def _derive_payment_status(inv: Invoice, bank_txns: list) -> str:
    if not bank_txns:
        return _enum_str(inv.payment_status)
    total = inv.amount_total or 0.0
    currency = inv.currency
    paid_sum = sum(abs(t.amount) for t in bank_txns if not currency or t.currency == currency)
    if total <= 0 or paid_sum >= total:
        return _PaymentStatus.PAID.value
    return _PaymentStatus.PARTIAL.value


class InvoiceFilters:
    def __init__(
        self,
        date_from: Optional[date] = Query(None),
        date_to: Optional[date] = Query(None),
        payment_status: Optional[str] = Query(None),
        has_pdf: Optional[str] = Query(None),
        supplier_name: Optional[str] = Query(None),
    ):
        self.date_from = date_from
        self.date_to = date_to
        self.payment_status = payment_status
        self.has_pdf = has_pdf  # "true" | "false" | None
        self.supplier_name = supplier_name


def list_invoices(
    db: Session,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    payment_status: Optional[str] = None,
    has_pdf: Optional[str] = None,
    supplier_name: Optional[str] = None,
) -> list[InvoiceRow]:
    """Return invoices matching the given filters, joined with supplier/customer/file info.

    Non-obvious rule: an invoice whose stored `payment_status` is still UNPAID
    is reported as PAID here if it has at least one linked bank transaction
    (`bank_cnt > 0`) and its status hasn't been manually locked
    (`payment_status_locked`). This keeps the list in sync with reality even
    if `_recompute_payment_status()` (in service.py) hasn't run since the
    transaction was linked, without needing to write to the database on every
    read. A manually locked invoice is never auto-overridden this way.
    """
    bank_sub = (
        db.query(invoice_bank_transaction.c.invoice_id, func.count(invoice_bank_transaction.c.bank_transaction_id).label("cnt"))
        .group_by(invoice_bank_transaction.c.invoice_id)
        .subquery()
    )
    q = (
        db.query(Invoice, Supplier.name, Customer.name, func.coalesce(bank_sub.c.cnt, 0), InvoiceFile.filename, InvoiceFile.preview_base64)
        # outerjoin: an invoice can now have no matched supplier/customer yet
        # (sync no longer auto-creates one — see service.py's _find_supplier)
        # and must still show up here rather than being silently dropped.
        .outerjoin(Supplier, Invoice.supplier_id == Supplier.id)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .outerjoin(bank_sub, Invoice.id == bank_sub.c.invoice_id)
        .outerjoin(InvoiceFile, Invoice.invoice_file_id == InvoiceFile.id)
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
        try:
            q = q.filter(Invoice.payment_status == _PaymentStatus[payment_status])
        except KeyError:
            pass
    if has_pdf == "true":
        q = q.filter(Invoice.invoice_file_id.isnot(None))
    elif has_pdf == "false":
        q = q.filter(Invoice.invoice_file_id.is_(None))
    if supplier_name:
        q = q.filter(Supplier.name.ilike(f"%{supplier_name}%"))

    q = q.order_by(Invoice.invoice_date.desc().nullslast(), Invoice.id.desc())
    rows = []
    for inv, sup_name, cust_name, bank_cnt, file_filename, file_preview in q.all():
        status = _enum_str(inv.payment_status)
        if (bank_cnt or 0) > 0 and status == _PaymentStatus.UNPAID.value and not inv.payment_status_locked:
            status = _PaymentStatus.PAID.value
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
            .join(BankTransaction, BankTransaction.id == invoice_bank_transaction.c.bank_transaction_id)
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


def get_invoice(db: Session, invoice_id: int) -> Optional[InvoiceDetail]:
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
        .join(invoice_bank_transaction, BankTransaction.id == invoice_bank_transaction.c.bank_transaction_id)
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
        db.query(InvoiceVatSummary).filter_by(invoice_id=invoice_id).order_by(InvoiceVatSummary.id).all()
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
