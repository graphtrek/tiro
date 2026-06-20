from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from fastapi import Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction, Invoice, InvoiceFile


@dataclass
class BankBalance:
    bank: str
    balance: float
    currency: str
    as_of: datetime


@dataclass
class TransactionDetail:
    id: int
    transaction_id: str
    bank: str
    transaction_date: datetime
    amount: float
    currency: str
    direction: str
    description: Optional[str]
    payment_reference: Optional[str]
    counterparty_name: Optional[str]
    counterparty_account: Optional[str]
    counterparty_iban: Optional[str]
    transaction_type: Optional[str]
    category: Optional[str]
    balance: Optional[float]
    fees: Optional[float]
    invoice_id: Optional[int]
    invoice_number: Optional[str]
    invoice_file_id: Optional[int]
    invoice_file_filename: Optional[str]
    supplier_id: Optional[int]
    supplier_name: Optional[str]
    customer_id: Optional[int]
    customer_name: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class TransactionRow:
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
    invoice_id: Optional[int]
    invoice_number: Optional[str]
    invoice_file_id: Optional[int]
    invoice_file_filename: Optional[str]
    fees: Optional[float] = None


class TransactionFilters:
    def __init__(
        self,
        date_from: Optional[date] = Query(None),
        date_to: Optional[date] = Query(None),
        linked: Optional[str] = Query(None),
        partner_name: Optional[str] = Query(None),
        amount_min: Optional[float] = Query(None),
        amount_max: Optional[float] = Query(None),
    ):
        self.date_from = date_from
        self.date_to = date_to
        self.linked = linked  # "yes" | "no" | None
        self.partner_name = partner_name
        self.amount_min = amount_min
        self.amount_max = amount_max


def list_transactions(
    db: Session,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    linked: Optional[str] = None,
    partner_name: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
) -> list[TransactionRow]:
    q = (
        db.query(BankTransaction, Invoice.invoice_number, InvoiceFile.filename)
        .outerjoin(Invoice, BankTransaction.invoice_id == Invoice.id)
        .outerjoin(InvoiceFile, BankTransaction.invoice_file_id == InvoiceFile.id)
    )
    if date_from:
        q = q.filter(BankTransaction.transaction_date >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(BankTransaction.transaction_date <= datetime.combine(date_to, datetime.max.time()))
    if linked == "yes":
        q = q.filter(BankTransaction.invoice_id.isnot(None))
    elif linked == "no":
        q = q.filter(BankTransaction.invoice_id.is_(None))
    if partner_name:
        q = q.filter(BankTransaction.counterparty_name.ilike(f"%{partner_name}%"))
    if amount_min is not None:
        q = q.filter(BankTransaction.amount >= amount_min)
    if amount_max is not None:
        q = q.filter(BankTransaction.amount <= amount_max)

    q = q.order_by(BankTransaction.transaction_date.desc())
    return [
        TransactionRow(
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
            invoice_id=t.invoice_id,
            invoice_number=inv_num,
            invoice_file_id=t.invoice_file_id,
            invoice_file_filename=inv_file,
            fees=t.fees,
        )
        for t, inv_num, inv_file in q.all()
    ]


def get_transaction(db: Session, transaction_id: int) -> Optional[TransactionDetail]:
    row = (
        db.query(BankTransaction, Invoice.invoice_number, InvoiceFile.filename)
        .outerjoin(Invoice, BankTransaction.invoice_id == Invoice.id)
        .outerjoin(InvoiceFile, BankTransaction.invoice_file_id == InvoiceFile.id)
        .filter(BankTransaction.id == transaction_id)
        .first()
    )
    if not row:
        return None
    t, inv_num, inv_file = row
    return TransactionDetail(
        id=t.id,
        transaction_id=t.transaction_id,
        bank=t.bank,
        transaction_date=t.transaction_date,
        amount=t.amount,
        currency=t.currency,
        direction=t.direction,
        description=t.description,
        payment_reference=t.payment_reference,
        counterparty_name=t.counterparty_name,
        counterparty_account=t.counterparty_account,
        counterparty_iban=t.counterparty_iban,
        transaction_type=t.transaction_type,
        category=t.category,
        balance=t.balance,
        fees=t.fees,
        invoice_id=t.invoice_id,
        invoice_number=inv_num,
        invoice_file_id=t.invoice_file_id,
        invoice_file_filename=inv_file,
        supplier_id=t.supplier_id,
        supplier_name=t.supplier.name if t.supplier else None,
        customer_id=t.customer_id,
        customer_name=t.customer.name if t.customer else None,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def get_bank_balances(db: Session) -> list[BankBalance]:
    """Return the latest balance record for each bank that has balance data."""
    subq = (
        db.query(BankTransaction.bank, func.max(BankTransaction.transaction_date).label("max_date"))
        .filter(BankTransaction.balance.isnot(None))
        .group_by(BankTransaction.bank)
        .subquery()
    )
    rows = (
        db.query(BankTransaction)
        .join(subq, (BankTransaction.bank == subq.c.bank) & (BankTransaction.transaction_date == subq.c.max_date))
        .filter(BankTransaction.balance.isnot(None))
        .all()
    )
    return [BankBalance(bank=r.bank, balance=r.balance, currency=r.currency, as_of=r.transaction_date) for r in rows]
