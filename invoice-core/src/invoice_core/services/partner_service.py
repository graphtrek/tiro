from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction, Customer, Invoice, Supplier, _PaymentStatus, _enum_str


@dataclass
class SupplierRow:
    id: int
    name: str
    tax_id: Optional[str]
    invoice_count: int
    unpaid_count: int
    bank_count: int
    last_invoice_date: Optional[date]


@dataclass
class PartnerInvoiceRow:
    id: int
    invoice_number: str
    invoice_date: Optional[date]
    amount_total: Optional[float]
    payment_status: str
    invoice_file_id: Optional[int]
    bank_txn_db_id: Optional[int] = None
    bank_txn_external_id: Optional[str] = None


@dataclass
class PartnerTxnRow:
    id: int
    transaction_id: str
    bank: str
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
    bank_transactions: list[PartnerTxnRow] = field(default_factory=list)


@dataclass
class CustomerRow:
    id: int
    name: str
    tax_id: Optional[str]
    invoice_count: int
    unpaid_count: int
    bank_count: int
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
    bank_transactions: list[PartnerTxnRow] = field(default_factory=list)


def _partner_invoice_rows(invoices: list) -> list[PartnerInvoiceRow]:
    rows = []
    for i in invoices:
        txn = i.bank_transactions[0] if i.bank_transactions else None
        rows.append(PartnerInvoiceRow(
            id=i.id,
            invoice_number=i.invoice_number,
            invoice_date=i.invoice_date,
            amount_total=i.amount_total,
            payment_status=_enum_str(i.payment_status),
            invoice_file_id=i.invoice_file_id,
            bank_txn_db_id=txn.id if txn else None,
            bank_txn_external_id=txn.transaction_id if txn else None,
        ))
    return rows


def list_suppliers(db: Session) -> list[SupplierRow]:
    inv_stats = (
        db.query(
            Invoice.supplier_id,
            func.count(Invoice.id).label("inv_count"),
            func.count(case((Invoice.payment_status == _PaymentStatus.UNPAID, Invoice.id))).label("unpaid_count"),
            func.max(Invoice.invoice_date).label("last_date"),
        )
        .group_by(Invoice.supplier_id)
        .all()
    )
    inv_map = {r.supplier_id: r for r in inv_stats}

    bank_map = {
        r.supplier_id: r.bank_count
        for r in db.query(
            BankTransaction.supplier_id,
            func.count(BankTransaction.id).label("bank_count"),
        )
        .filter(BankTransaction.supplier_id.isnot(None))
        .group_by(BankTransaction.supplier_id)
        .all()
    }

    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return [
        SupplierRow(
            id=sup.id,
            name=sup.name,
            tax_id=sup.tax_id,
            invoice_count=inv_map[sup.id].inv_count if sup.id in inv_map else 0,
            unpaid_count=inv_map[sup.id].unpaid_count if sup.id in inv_map else 0,
            bank_count=bank_map.get(sup.id, 0),
            last_invoice_date=inv_map[sup.id].last_date if sup.id in inv_map else None,
        )
        for sup in suppliers
    ]


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
    bank_txns = (
        db.query(BankTransaction)
        .filter(BankTransaction.supplier_id == supplier_id)
        .order_by(BankTransaction.transaction_date.desc())
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
        invoices=_partner_invoice_rows(invoices),
        bank_transactions=[
            PartnerTxnRow(
                id=t.id,
                transaction_id=t.transaction_id,
                bank=t.bank,
                transaction_date=t.transaction_date,
                amount=t.amount,
                currency=t.currency,
                description=t.description,
            )
            for t in bank_txns
        ],
    )


def list_customers(db: Session) -> list[CustomerRow]:
    inv_stats = (
        db.query(
            Invoice.customer_id,
            func.count(Invoice.id).label("inv_count"),
            func.count(case((Invoice.payment_status == _PaymentStatus.UNPAID, Invoice.id))).label("unpaid_count"),
            func.max(Invoice.invoice_date).label("last_date"),
        )
        .group_by(Invoice.customer_id)
        .all()
    )
    inv_map = {r.customer_id: r for r in inv_stats}

    bank_map = {
        r.customer_id: r.bank_count
        for r in db.query(
            BankTransaction.customer_id,
            func.count(BankTransaction.id).label("bank_count"),
        )
        .filter(BankTransaction.customer_id.isnot(None))
        .group_by(BankTransaction.customer_id)
        .all()
    }

    customers = db.query(Customer).order_by(Customer.name).all()
    return [
        CustomerRow(
            id=cust.id,
            name=cust.name,
            tax_id=cust.tax_id,
            invoice_count=inv_map[cust.id].inv_count if cust.id in inv_map else 0,
            unpaid_count=inv_map[cust.id].unpaid_count if cust.id in inv_map else 0,
            bank_count=bank_map.get(cust.id, 0),
            last_invoice_date=inv_map[cust.id].last_date if cust.id in inv_map else None,
        )
        for cust in customers
    ]


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
    bank_txns = (
        db.query(BankTransaction)
        .filter(BankTransaction.customer_id == customer_id)
        .order_by(BankTransaction.transaction_date.desc())
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
        invoices=_partner_invoice_rows(invoices),
        bank_transactions=[
            PartnerTxnRow(
                id=t.id,
                transaction_id=t.transaction_id,
                bank=t.bank,
                transaction_date=t.transaction_date,
                amount=t.amount,
                currency=t.currency,
                description=t.description,
            )
            for t in bank_txns
        ],
    )
