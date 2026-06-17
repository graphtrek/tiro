from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from fastapi import Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from invoice_core.db import Customer, Invoice, Supplier, WiseTransaction, _PaymentStatus


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
    invoice_file_id: Optional[int]
    wise_count: int


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
    nav_transaction_id: Optional[str]
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
        db.query(Invoice, Supplier.name, Customer.name, func.coalesce(wise_sub.c.cnt, 0))
        .join(Supplier, Invoice.supplier_id == Supplier.id)
        .join(Customer, Invoice.customer_id == Customer.id)
        .outerjoin(wise_sub, Invoice.id == wise_sub.c.invoice_id)
    )
    if date_from:
        q = q.filter(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(Invoice.invoice_date <= date_to)
    if payment_status:
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
    for inv, sup_name, cust_name, wise_cnt in q.all():
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
                payment_status=inv.payment_status.value if hasattr(inv.payment_status, "value") else str(inv.payment_status),
                direction=inv.direction.value if hasattr(inv.direction, "value") else str(inv.direction),
                invoice_file_id=inv.invoice_file_id,
                wise_count=wise_cnt or 0,
            )
        )
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
        payment_status=inv.payment_status.value if hasattr(inv.payment_status, "value") else str(inv.payment_status),
        direction=inv.direction.value if hasattr(inv.direction, "value") else str(inv.direction),
        nav_transaction_id=inv.nav_transaction_id,
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
            )
            for t in wise_txns
        ],
    )
