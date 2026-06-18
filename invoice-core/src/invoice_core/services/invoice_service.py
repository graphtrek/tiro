from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from fastapi import Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from invoice_core.db import Customer, Invoice, InvoiceFile, Supplier, WiseTransaction, _PaymentStatus, _enum_str, invoice_has_wise_txn


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
    wise_count: int
    wise_transaction_ids: list[str] = field(default_factory=list)
    wise_transaction_db_ids: list[int] = field(default_factory=list)


@dataclass
class WiseTxnRow:
    id: int
    wise_transaction_id: str
    transaction_date: datetime
    amount: float
    currency: str
    description: Optional[str]
    payment_reference: Optional[str]
    partner_name: Optional[str]
    running_balance: Optional[float] = None
    exchange_from: Optional[str] = None
    exchange_to: Optional[str] = None
    exchange_rate: Optional[float] = None
    exchange_to_amount: Optional[float] = None
    payer_name: Optional[str] = None
    payee_name: Optional[str] = None
    payee_account_number: Optional[str] = None
    merchant: Optional[str] = None
    card_last_four_digits: Optional[str] = None
    card_holder_full_name: Optional[str] = None
    attachment: Optional[str] = None
    note: Optional[str] = None
    total_fees: Optional[float] = None
    transaction_type: Optional[str] = None
    transaction_details_type: Optional[str] = None
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
    wise_transactions: list[WiseTxnRow] = field(default_factory=list)


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
    wise_sub = (
        db.query(WiseTransaction.invoice_id, func.count(WiseTransaction.id).label("cnt"))
        .filter(WiseTransaction.invoice_id.isnot(None))
        .group_by(WiseTransaction.invoice_id)
        .subquery()
    )
    q = (
        db.query(Invoice, Supplier.name, Customer.name, func.coalesce(wise_sub.c.cnt, 0), InvoiceFile.filename)
        .join(Supplier, Invoice.supplier_id == Supplier.id)
        .join(Customer, Invoice.customer_id == Customer.id)
        .outerjoin(wise_sub, Invoice.id == wise_sub.c.invoice_id)
        .outerjoin(InvoiceFile, Invoice.invoice_file_id == InvoiceFile.id)
    )
    if date_from:
        q = q.filter(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(Invoice.invoice_date <= date_to)
    if payment_status == "PAID":
        # Paid = stored PAID OR settled by a linked Wise transaction.
        q = q.filter(or_(Invoice.payment_status == _PaymentStatus.PAID, invoice_has_wise_txn()))
    elif payment_status:
        try:
            # A Wise-linked invoice is paid, so it can't be UNPAID/PARTIAL.
            q = q.filter(Invoice.payment_status == _PaymentStatus[payment_status], ~invoice_has_wise_txn())
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
    for inv, sup_name, cust_name, wise_cnt, file_filename in q.all():
        status = _enum_str(inv.payment_status)
        if (wise_cnt or 0) > 0:
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
                wise_count=wise_cnt or 0,
            )
        )

    if rows:
        invoice_ids = [r.id for r in rows]
        txn_rows = (
            db.query(WiseTransaction.invoice_id, WiseTransaction.wise_transaction_id, WiseTransaction.id)
            .filter(WiseTransaction.invoice_id.in_(invoice_ids))
            .order_by(WiseTransaction.transaction_date.desc())
            .all()
        )
        txn_map: dict[int, list[str]] = {}
        db_id_map: dict[int, list[int]] = {}
        for inv_id, txn_id, db_id in txn_rows:
            txn_map.setdefault(inv_id, []).append(txn_id)
            db_id_map.setdefault(inv_id, []).append(db_id)
        for row in rows:
            row.wise_transaction_ids = txn_map.get(row.id, [])
            row.wise_transaction_db_ids = db_id_map.get(row.id, [])

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

    wise_txns = (
        db.query(WiseTransaction)
        .filter(WiseTransaction.invoice_id == invoice_id)
        .order_by(WiseTransaction.transaction_date.desc())
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
        payment_status=_PaymentStatus.PAID.value if wise_txns else _enum_str(inv.payment_status),
        direction=_enum_str(inv.direction),
        currency=inv.currency,
        invoice_operation=inv.invoice_operation,
        invoice_category=inv.invoice_category,
        nav_ins_date=inv.nav_ins_date,
        invoice_file_id=inv.invoice_file_id,
        invoice_file_filename=filename,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        wise_transactions=[
            WiseTxnRow(
                id=t.id,
                wise_transaction_id=t.wise_transaction_id,
                transaction_date=t.transaction_date,
                amount=t.amount,
                currency=t.currency,
                description=t.description,
                payment_reference=t.payment_reference,
                partner_name=t.payee_name or t.payer_name or t.merchant,
                running_balance=t.running_balance,
                exchange_from=t.exchange_from,
                exchange_to=t.exchange_to,
                exchange_rate=t.exchange_rate,
                exchange_to_amount=t.exchange_to_amount,
                payer_name=t.payer_name,
                payee_name=t.payee_name,
                payee_account_number=t.payee_account_number,
                merchant=t.merchant,
                card_last_four_digits=t.card_last_four_digits,
                card_holder_full_name=t.card_holder_full_name,
                attachment=t.attachment,
                note=t.note,
                total_fees=t.total_fees,
                transaction_type=t.transaction_type,
                transaction_details_type=t.transaction_details_type,
                invoice_file_id=t.invoice_file_id,
                invoice_file_filename=t.invoice_file.filename if t.invoice_file else None,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in wise_txns
        ],
    )
