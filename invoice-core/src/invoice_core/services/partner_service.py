from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction, Customer, Invoice, Supplier, _PaymentStatus, _enum_str
from invoice_core.services._helpers import OWN_COMPANY_NAME_FILTER


@dataclass
class AmountByCurrency:
    currency: str
    total: float


@dataclass
class SupplierSummary:
    supplier_count: int
    invoice_count: int
    unpaid_count: int
    bank_count: int
    invoice_totals: list[AmountByCurrency]
    bank_totals: list[AmountByCurrency]


@dataclass
class SupplierRow:
    id: int
    name: str
    tax_id: Optional[str]
    invoice_count: int
    unpaid_count: int
    bank_count: int
    last_invoice_date: Optional[date]
    invoice_total: Optional[float] = None
    bank_total: Optional[float] = None


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
    iban: Optional[str]
    bban: Optional[str]
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
    invoice_total: Optional[float] = None
    bank_total: Optional[float] = None


@dataclass
class CustomerDetail:
    id: int
    name: str
    tax_id: Optional[str]
    address: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    payment_terms: Optional[int]
    iban: Optional[str]
    bban: Optional[str]
    invoices: list[PartnerInvoiceRow] = field(default_factory=list)
    bank_transactions: list[PartnerTxnRow] = field(default_factory=list)


def _partner_invoice_rows(invoices: list[Invoice]) -> list[PartnerInvoiceRow]:
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


# list_suppliers() and list_customers() below are intentionally near-identical
# (same stats-join shape, just Supplier vs. Customer) — with only 2 call sites,
# sharing that logic isn't worth the extra indirection. If you change one,
# check whether the other needs the same change.
def list_suppliers(db: Session) -> list[SupplierRow]:
    inv_stats = (
        db.query(
            Invoice.supplier_id,
            func.count(Invoice.id).label("inv_count"),
            func.count(case((Invoice.payment_status == _PaymentStatus.UNPAID, Invoice.id))).label("unpaid_count"),
            func.max(Invoice.invoice_date).label("last_date"),
            func.sum(Invoice.amount_total).label("inv_total"),
        )
        .group_by(Invoice.supplier_id)
        .all()
    )
    inv_map = {r.supplier_id: r for r in inv_stats}

    bank_stats = (
        db.query(
            BankTransaction.supplier_id,
            func.count(BankTransaction.id).label("bank_count"),
            func.sum(BankTransaction.amount).label("bank_total"),
        )
        .filter(BankTransaction.supplier_id.isnot(None))
        .group_by(BankTransaction.supplier_id)
        .all()
    )
    bank_map = {r.supplier_id: r for r in bank_stats}

    suppliers = db.query(Supplier).filter(~Supplier.name.ilike(OWN_COMPANY_NAME_FILTER)).order_by(Supplier.name).all()
    return [
        SupplierRow(
            id=sup.id,
            name=sup.name,
            tax_id=sup.tax_id,
            invoice_count=inv_map[sup.id].inv_count if sup.id in inv_map else 0,
            unpaid_count=inv_map[sup.id].unpaid_count if sup.id in inv_map else 0,
            bank_count=bank_map[sup.id].bank_count if sup.id in bank_map else 0,
            last_invoice_date=inv_map[sup.id].last_date if sup.id in inv_map else None,
            invoice_total=inv_map[sup.id].inv_total if sup.id in inv_map else None,
            bank_total=bank_map[sup.id].bank_total if sup.id in bank_map else None,
        )
        for sup in suppliers
    ]


def get_supplier_summary(db: Session) -> SupplierSummary:
    # `excluded` is the mirror image of the filter used elsewhere: it collects
    # the IDs of suppliers that ARE our own company, so they can be subtracted
    # out of every count/sum below via `~Supplier.id.in_(excluded)`.
    excluded = db.query(Supplier.id).filter(Supplier.name.ilike(OWN_COMPANY_NAME_FILTER)).subquery()

    supplier_count = (
        db.query(func.count(Supplier.id))
        .filter(~Supplier.id.in_(excluded))
        .scalar() or 0
    )

    inv_q = (
        db.query(
            Invoice.currency,
            func.count(Invoice.id).label("cnt"),
            func.count(case((Invoice.payment_status == _PaymentStatus.UNPAID, Invoice.id))).label("unpaid"),
            func.sum(Invoice.amount_total).label("total"),
        )
        .join(Supplier, Invoice.supplier_id == Supplier.id)
        .filter(~Supplier.id.in_(excluded))
        .group_by(Invoice.currency)
        .all()
    )
    invoice_count = sum(r.cnt for r in inv_q)
    unpaid_count = sum(r.unpaid for r in inv_q)
    invoice_totals = [
        AmountByCurrency(currency=r.currency or "?", total=r.total or 0)
        for r in sorted(inv_q, key=lambda r: r.currency or "")
        if r.total
    ]

    bank_q = (
        db.query(
            BankTransaction.currency,
            func.count(BankTransaction.id).label("cnt"),
            func.sum(BankTransaction.amount).label("total"),
        )
        .join(Supplier, BankTransaction.supplier_id == Supplier.id)
        .filter(~Supplier.id.in_(excluded))
        .group_by(BankTransaction.currency)
        .all()
    )
    bank_count = sum(r.cnt for r in bank_q)
    bank_totals = [
        AmountByCurrency(currency=r.currency, total=r.total or 0)
        for r in sorted(bank_q, key=lambda r: r.currency)
        if r.total
    ]

    return SupplierSummary(
        supplier_count=supplier_count,
        invoice_count=invoice_count,
        unpaid_count=unpaid_count,
        bank_count=bank_count,
        invoice_totals=invoice_totals,
        bank_totals=bank_totals,
    )


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
        iban=sup.iban,
        bban=sup.bban,
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
            func.sum(Invoice.amount_total).label("inv_total"),
        )
        .group_by(Invoice.customer_id)
        .all()
    )
    inv_map = {r.customer_id: r for r in inv_stats}

    bank_stats = (
        db.query(
            BankTransaction.customer_id,
            func.count(BankTransaction.id).label("bank_count"),
            func.sum(BankTransaction.amount).label("bank_total"),
        )
        .filter(BankTransaction.customer_id.isnot(None))
        .group_by(BankTransaction.customer_id)
        .all()
    )
    bank_map = {r.customer_id: r for r in bank_stats}

    customers = db.query(Customer).filter(~Customer.name.ilike(OWN_COMPANY_NAME_FILTER)).order_by(Customer.name).all()
    return [
        CustomerRow(
            id=cust.id,
            name=cust.name,
            tax_id=cust.tax_id,
            invoice_count=inv_map[cust.id].inv_count if cust.id in inv_map else 0,
            unpaid_count=inv_map[cust.id].unpaid_count if cust.id in inv_map else 0,
            bank_count=bank_map[cust.id].bank_count if cust.id in bank_map else 0,
            last_invoice_date=inv_map[cust.id].last_date if cust.id in inv_map else None,
            invoice_total=inv_map[cust.id].inv_total if cust.id in inv_map else None,
            bank_total=bank_map[cust.id].bank_total if cust.id in bank_map else None,
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
        iban=cust.iban,
        bban=cust.bban,
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
