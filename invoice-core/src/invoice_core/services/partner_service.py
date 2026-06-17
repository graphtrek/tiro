from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from invoice_core.db import Customer, Invoice, Supplier, WiseTransaction, _PaymentStatus


@dataclass
class SupplierRow:
    id: int
    name: str
    tax_id: Optional[str]
    invoice_count: int
    unpaid_count: int
    wise_count: int
    last_invoice_date: Optional[date]


@dataclass
class PartnerInvoiceRow:
    id: int
    invoice_number: str
    invoice_date: Optional[date]
    amount_total: Optional[float]
    payment_status: str
    invoice_file_id: Optional[int]


@dataclass
class PartnerTxnRow:
    id: int
    wise_transaction_id: str
    transaction_date: datetime
    amount: float
    currency: str
    description: Optional[str]


@dataclass
class SupplierDetail:
    id: int
    name: str
    tax_id: Optional[str]
    address: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    bank_account: Optional[str]
    invoices: list[PartnerInvoiceRow] = field(default_factory=list)
    wise_transactions: list[PartnerTxnRow] = field(default_factory=list)


@dataclass
class CustomerRow:
    id: int
    name: str
    tax_id: Optional[str]
    invoice_count: int
    unpaid_count: int
    wise_count: int
    last_invoice_date: Optional[date]


@dataclass
class CustomerDetail:
    id: int
    name: str
    tax_id: Optional[str]
    address: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    payment_terms: Optional[int]
    invoices: list[PartnerInvoiceRow] = field(default_factory=list)
    wise_transactions: list[PartnerTxnRow] = field(default_factory=list)


def _invoice_stats(db: Session, supplier_id: int = None, customer_id: int = None):
    q_total = db.query(func.count(Invoice.id))
    q_unpaid = db.query(func.count(Invoice.id)).filter(Invoice.payment_status == _PaymentStatus.UNPAID)
    q_last = db.query(func.max(Invoice.invoice_date))
    if supplier_id is not None:
        q_total = q_total.filter(Invoice.supplier_id == supplier_id)
        q_unpaid = q_unpaid.filter(Invoice.supplier_id == supplier_id)
        q_last = q_last.filter(Invoice.supplier_id == supplier_id)
    if customer_id is not None:
        q_total = q_total.filter(Invoice.customer_id == customer_id)
        q_unpaid = q_unpaid.filter(Invoice.customer_id == customer_id)
        q_last = q_last.filter(Invoice.customer_id == customer_id)
    return (q_total.scalar() or 0), (q_unpaid.scalar() or 0), q_last.scalar()


def list_suppliers(db: Session) -> list[SupplierRow]:
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    result = []
    for sup in suppliers:
        inv_count, unpaid, last_date = _invoice_stats(db, supplier_id=sup.id)
        wise_cnt = (
            db.query(func.count(WiseTransaction.id))
            .filter(WiseTransaction.supplier_id == sup.id)
            .scalar()
            or 0
        )
        result.append(
            SupplierRow(
                id=sup.id,
                name=sup.name,
                tax_id=sup.tax_id,
                invoice_count=inv_count,
                unpaid_count=unpaid,
                wise_count=wise_cnt,
                last_invoice_date=last_date,
            )
        )
    return result


def get_supplier(db: Session, supplier_id: int) -> Optional[SupplierDetail]:
    sup = db.query(Supplier).filter_by(id=supplier_id).first()
    if not sup:
        return None
    invoices = (
        db.query(Invoice)
        .filter(Invoice.supplier_id == supplier_id)
        .order_by(Invoice.invoice_date.desc().nullslast())
        .all()
    )
    wise_txns = (
        db.query(WiseTransaction)
        .filter(WiseTransaction.supplier_id == supplier_id)
        .order_by(WiseTransaction.transaction_date.desc())
        .all()
    )
    return SupplierDetail(
        id=sup.id,
        name=sup.name,
        tax_id=sup.tax_id,
        address=sup.address,
        email=sup.email,
        phone=sup.phone,
        bank_account=sup.bank_account,
        invoices=[
            PartnerInvoiceRow(
                id=i.id,
                invoice_number=i.invoice_number,
                invoice_date=i.invoice_date,
                amount_total=i.amount_total,
                payment_status=i.payment_status.value if hasattr(i.payment_status, "value") else str(i.payment_status),
                invoice_file_id=i.invoice_file_id,
            )
            for i in invoices
        ],
        wise_transactions=[
            PartnerTxnRow(
                id=t.id,
                wise_transaction_id=t.wise_transaction_id,
                transaction_date=t.transaction_date,
                amount=t.amount,
                currency=t.currency,
                description=t.description,
            )
            for t in wise_txns
        ],
    )


def list_customers(db: Session) -> list[CustomerRow]:
    customers = db.query(Customer).order_by(Customer.name).all()
    result = []
    for cust in customers:
        inv_count, unpaid, last_date = _invoice_stats(db, customer_id=cust.id)
        wise_cnt = (
            db.query(func.count(WiseTransaction.id))
            .filter(WiseTransaction.customer_id == cust.id)
            .scalar()
            or 0
        )
        result.append(
            CustomerRow(
                id=cust.id,
                name=cust.name,
                tax_id=cust.tax_id,
                invoice_count=inv_count,
                unpaid_count=unpaid,
                wise_count=wise_cnt,
                last_invoice_date=last_date,
            )
        )
    return result


def get_customer(db: Session, customer_id: int) -> Optional[CustomerDetail]:
    cust = db.query(Customer).filter_by(id=customer_id).first()
    if not cust:
        return None
    invoices = (
        db.query(Invoice)
        .filter(Invoice.customer_id == customer_id)
        .order_by(Invoice.invoice_date.desc().nullslast())
        .all()
    )
    wise_txns = (
        db.query(WiseTransaction)
        .filter(WiseTransaction.customer_id == customer_id)
        .order_by(WiseTransaction.transaction_date.desc())
        .all()
    )
    return CustomerDetail(
        id=cust.id,
        name=cust.name,
        tax_id=cust.tax_id,
        address=cust.address,
        email=cust.email,
        phone=cust.phone,
        payment_terms=cust.payment_terms,
        invoices=[
            PartnerInvoiceRow(
                id=i.id,
                invoice_number=i.invoice_number,
                invoice_date=i.invoice_date,
                amount_total=i.amount_total,
                payment_status=i.payment_status.value if hasattr(i.payment_status, "value") else str(i.payment_status),
                invoice_file_id=i.invoice_file_id,
            )
            for i in invoices
        ],
        wise_transactions=[
            PartnerTxnRow(
                id=t.id,
                wise_transaction_id=t.wise_transaction_id,
                transaction_date=t.transaction_date,
                amount=t.amount,
                currency=t.currency,
                description=t.description,
            )
            for t in wise_txns
        ],
    )
