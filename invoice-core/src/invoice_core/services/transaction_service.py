from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from fastapi import Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction, Customer, Invoice, InvoiceFile, Supplier, invoice_bank_transaction


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
    counterparty_address: Optional[str]
    sender_address: Optional[str]
    counterparty_bank_code: Optional[str]
    exchange_rate: Optional[float]
    exchange_to_currency: Optional[str]
    card_last_four: Optional[str]
    note: Optional[str]
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
    supplier_id: Optional[int] = None
    customer_id: Optional[int] = None
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
        db.query(BankTransaction, InvoiceFile.filename, InvoiceFile.preview_base64, Supplier.name, Customer.name)
        .outerjoin(InvoiceFile, BankTransaction.invoice_file_id == InvoiceFile.id)
        .outerjoin(Supplier, BankTransaction.supplier_id == Supplier.id)
        .outerjoin(Customer, BankTransaction.customer_id == Customer.id)
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

    txn_ids = [t.id for t, _, _, _, _ in txn_rows_raw]
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
            partner_name=supplier_name if t.direction == "DEBIT" else customer_name,
            invoice_file_id=t.invoice_file_id,
            invoice_file_filename=inv_file,
            supplier_id=t.supplier_id,
            customer_id=t.customer_id,
            fees=t.fees,
            invoice_file_locked=bool(t.invoice_file_locked),
            invoice_ids=[pair[0] for pair in inv_by_txn.get(t.id, [])],
            invoice_numbers=[pair[1] for pair in inv_by_txn.get(t.id, [])],
            invoice_file_preview_base64=inv_preview,
        )
        for t, inv_file, inv_preview, supplier_name, customer_name in txn_rows_raw
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
        counterparty_address=t.counterparty_address,
        sender_address=t.sender_address,
        counterparty_bank_code=t.counterparty_bank_code,
        exchange_rate=t.exchange_rate,
        exchange_to_currency=t.exchange_to_currency,
        card_last_four=t.card_last_four,
        note=t.note,
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


def _latest_of_same_day(rows: list[BankTransaction]) -> BankTransaction:
    """Pick the chronologically last transaction among rows sharing one bank+date.

    Row insertion order (id) is not a reliable proxy for real chronological order —
    source CSVs are sometimes newest-first, sometimes oldest-first, depending on the
    export. Instead, reconstruct the running-balance chain: undo each row's own
    amount/direction to get the balance that must have existed immediately before it
    (its "prior"). The row whose balance is never anyone else's "prior" is the one
    nothing in the group comes after — i.e. the latest. Falls back to max(id) if the
    chain doesn't resolve to exactly one terminal row (e.g. unrelated/duplicate rows).
    """
    if len(rows) == 1:
        return rows[0]
    priors = {
        round((r.balance - r.amount) if r.direction == "CREDIT" else (r.balance + r.amount), 2)
        for r in rows
    }
    terminal = [r for r in rows if round(r.balance, 2) not in priors]
    if len(terminal) == 1:
        return terminal[0]
    return max(rows, key=lambda r: r.id)


def get_bank_balances(db: Session) -> list[BankBalance]:
    """Return the single latest balance record for each bank that has balance data.

    Multiple transactions can share the same transaction_date (e.g. Erste rows
    without a time component all land on midnight of the same day), so picking
    every row that matches the max date would double-count balances — resolve
    same-day ties via _latest_of_same_day to get exactly one row per bank.
    """
    banks = [r[0] for r in db.query(BankTransaction.bank).filter(BankTransaction.balance.isnot(None)).distinct()]
    result = []
    for bank in banks:
        max_date = (
            db.query(func.max(BankTransaction.transaction_date))
            .filter(BankTransaction.bank == bank, BankTransaction.balance.isnot(None))
            .scalar()
        )
        if max_date is None:
            continue
        rows = (
            db.query(BankTransaction)
            .filter(
                BankTransaction.bank == bank,
                BankTransaction.transaction_date == max_date,
                BankTransaction.balance.isnot(None),
            )
            .all()
        )
        r = _latest_of_same_day(rows)
        result.append(BankBalance(bank=r.bank, balance=r.balance, currency=r.currency, as_of=r.transaction_date))
    return result
