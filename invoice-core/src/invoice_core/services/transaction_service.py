from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from fastapi import Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction, Invoice, InvoiceFile, invoice_bank_transaction


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
    invoice_ids: list[int]
    invoice_numbers: list[str]
    invoice_file_id: Optional[int]
    invoice_file_filename: Optional[str]
    invoice_file_locked: bool
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
    invoice_file_id: Optional[int]
    invoice_file_filename: Optional[str]
    fees: Optional[float] = None
    invoice_file_locked: bool = False
    invoice_ids: list[int] = field(default_factory=list)
    invoice_numbers: list[str] = field(default_factory=list)
    invoice_file_preview_base64: Optional[str] = None


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
    from sqlalchemy import exists as sa_exists
    ibt = invoice_bank_transaction

    q = (
        db.query(BankTransaction, InvoiceFile.filename, InvoiceFile.preview_base64)
        .outerjoin(InvoiceFile, BankTransaction.invoice_file_id == InvoiceFile.id)
    )
    if date_from:
        q = q.filter(BankTransaction.transaction_date >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(BankTransaction.transaction_date <= datetime.combine(date_to, datetime.max.time()))
    if linked == "yes":
        q = q.filter(sa_exists().where(ibt.c.bank_transaction_id == BankTransaction.id))
    elif linked == "no":
        q = q.filter(~sa_exists().where(ibt.c.bank_transaction_id == BankTransaction.id))
    if partner_name:
        q = q.filter(BankTransaction.counterparty_name.ilike(f"%{partner_name}%"))
    if amount_min is not None:
        q = q.filter(BankTransaction.amount >= amount_min)
    if amount_max is not None:
        q = q.filter(BankTransaction.amount <= amount_max)

    q = q.order_by(BankTransaction.transaction_date.desc())
    txn_rows_raw = q.all()

    txn_ids = [t.id for t, _, _ in txn_rows_raw]
    inv_by_txn: dict[int, list[tuple[int, str]]] = {}
    if txn_ids:
        links = (
            db.query(ibt.c.bank_transaction_id, Invoice.id, Invoice.invoice_number)
            .join(Invoice, Invoice.id == ibt.c.invoice_id)
            .filter(ibt.c.bank_transaction_id.in_(txn_ids))
            .all()
        )
        for txn_id, inv_id, inv_num in links:
            inv_by_txn.setdefault(txn_id, []).append((inv_id, inv_num))

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
            invoice_file_id=t.invoice_file_id,
            invoice_file_filename=inv_file,
            fees=t.fees,
            invoice_file_locked=bool(t.invoice_file_locked),
            invoice_ids=[pair[0] for pair in inv_by_txn.get(t.id, [])],
            invoice_numbers=[pair[1] for pair in inv_by_txn.get(t.id, [])],
            invoice_file_preview_base64=inv_preview,
        )
        for t, inv_file, inv_preview in txn_rows_raw
    ]


def get_transaction(db: Session, transaction_id: int) -> Optional[TransactionDetail]:
    ibt = invoice_bank_transaction
    row = (
        db.query(BankTransaction, InvoiceFile.filename)
        .outerjoin(InvoiceFile, BankTransaction.invoice_file_id == InvoiceFile.id)
        .filter(BankTransaction.id == transaction_id)
        .first()
    )
    if not row:
        return None
    t, inv_file = row
    links = (
        db.query(Invoice.id, Invoice.invoice_number)
        .join(ibt, Invoice.id == ibt.c.invoice_id)
        .filter(ibt.c.bank_transaction_id == t.id)
        .all()
    )
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
        invoice_ids=[r[0] for r in links],
        invoice_numbers=[r[1] for r in links],
        invoice_file_id=t.invoice_file_id,
        invoice_file_filename=inv_file,
        invoice_file_locked=t.invoice_file_locked,
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
