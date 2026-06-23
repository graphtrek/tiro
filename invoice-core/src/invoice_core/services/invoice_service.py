from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from fastapi import Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction, Customer, Invoice, InvoiceFile, Supplier, _PaymentStatus, _enum_str, invoice_bank_transaction, invoice_has_bank_txn


@dataclass
class InvoiceRow:
    id: int
    invoice_number: str
    invoice_date: Optional[date]
    supplier_id: int
    supplier_name: str
    customer_id: int
    customer_name: str
    amount_net: Optional[float]
    amount_vat: Optional[float]
    amount_total: Optional[float]
    payment_status: str
    direction: str
    currency: Optional[str]
    invoice_file_id: Optional[int]
    invoice_file_filename: Optional[str]
    bank_count: int
    bank_transaction_ids: list[str] = field(default_factory=list)
    bank_transaction_db_ids: list[int] = field(default_factory=list)


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
    invoice_file_id: Optional[int] = None
    invoice_file_filename: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class InvoiceDetail:
    id: int
    invoice_number: str
    invoice_date: Optional[date]
    supplier_id: int
    supplier_name: str
    supplier_tax_id: Optional[str]
    customer_id: int
    customer_name: str
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
    created_at: datetime
    updated_at: datetime
    bank_transactions: list[BankTxnRow] = field(default_factory=list)


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
    bank_sub = (
        db.query(invoice_bank_transaction.c.invoice_id, func.count(invoice_bank_transaction.c.bank_transaction_id).label("cnt"))
        .group_by(invoice_bank_transaction.c.invoice_id)
        .subquery()
    )
    q = (
        db.query(Invoice, Supplier.name, Customer.name, func.coalesce(bank_sub.c.cnt, 0), InvoiceFile.filename)
        .join(Supplier, Invoice.supplier_id == Supplier.id)
        .join(Customer, Invoice.customer_id == Customer.id)
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
    for inv, sup_name, cust_name, bank_cnt, file_filename in q.all():
        status = _enum_str(inv.payment_status)
        if (bank_cnt or 0) > 0 and status == _PaymentStatus.UNPAID.value:
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
            )
        )

    if rows:
        invoice_ids = [r.id for r in rows]
        txn_rows = (
            db.query(invoice_bank_transaction.c.invoice_id, BankTransaction.transaction_id, BankTransaction.id)
            .join(BankTransaction, BankTransaction.id == invoice_bank_transaction.c.bank_transaction_id)
            .filter(invoice_bank_transaction.c.invoice_id.in_(invoice_ids))
            .order_by(BankTransaction.transaction_date.desc())
            .all()
        )
        txn_map: dict[int, list[str]] = {}
        db_id_map: dict[int, list[int]] = {}
        for inv_id, txn_id, db_id in txn_rows:
            txn_map.setdefault(inv_id, []).append(txn_id)
            db_id_map.setdefault(inv_id, []).append(db_id)
        for row in rows:
            row.bank_transaction_ids = txn_map.get(row.id, [])
            row.bank_transaction_db_ids = db_id_map.get(row.id, [])

    return rows


def get_invoice(db: Session, invoice_id: int) -> Optional[InvoiceDetail]:
    from invoice_core.db import InvoiceFile

    row = (
        db.query(Invoice, Supplier, Customer)
        .join(Supplier, Invoice.supplier_id == Supplier.id)
        .join(Customer, Invoice.customer_id == Customer.id)
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

    return InvoiceDetail(
        id=inv.id,
        invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        supplier_id=sup.id,
        supplier_name=sup.name,
        supplier_tax_id=sup.tax_id,
        customer_id=cust.id,
        customer_name=cust.name,
        customer_tax_id=cust.tax_id,
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
        created_at=inv.created_at,
        updated_at=inv.updated_at,
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
                invoice_file_id=t.invoice_file_id,
                invoice_file_filename=t.invoice_file.filename if t.invoice_file else None,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in bank_txns
        ],
    )
