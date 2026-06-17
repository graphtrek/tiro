from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from fastapi import Query
from sqlalchemy.orm import Session

from invoice_core.db import Invoice, InvoiceFile, WiseTransaction


@dataclass
class TransactionDetail:
    id: int
    wise_transaction_id: str
    transaction_date: datetime
    amount: float
    currency: str
    description: Optional[str]
    payment_reference: Optional[str]
    running_balance: Optional[float]
    exchange_from: Optional[str]
    exchange_to: Optional[str]
    exchange_rate: Optional[float]
    exchange_to_amount: Optional[float]
    payer_name: Optional[str]
    payee_name: Optional[str]
    payee_account_number: Optional[str]
    merchant: Optional[str]
    card_last_four_digits: Optional[str]
    card_holder_full_name: Optional[str]
    attachment: Optional[str]
    note: Optional[str]
    total_fees: Optional[float]
    transaction_type: Optional[str]
    transaction_details_type: Optional[str]
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
    wise_transaction_id: str
    transaction_date: datetime
    amount: float
    currency: str
    description: Optional[str]
    payment_reference: Optional[str]
    partner_name: Optional[str]
    invoice_id: Optional[int]
    invoice_number: Optional[str]
    invoice_file_id: Optional[int]
    invoice_file_filename: Optional[str]
    total_fees: Optional[float] = None


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
        db.query(WiseTransaction, Invoice.invoice_number, InvoiceFile.filename)
        .outerjoin(Invoice, WiseTransaction.invoice_id == Invoice.id)
        .outerjoin(InvoiceFile, WiseTransaction.invoice_file_id == InvoiceFile.id)
    )
    if date_from:
        q = q.filter(WiseTransaction.transaction_date >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(WiseTransaction.transaction_date <= datetime.combine(date_to, datetime.max.time()))
    if linked == "yes":
        q = q.filter(WiseTransaction.invoice_id.isnot(None))
    elif linked == "no":
        q = q.filter(WiseTransaction.invoice_id.is_(None))
    if partner_name:
        q = q.filter(
            (WiseTransaction.payee_name.ilike(f"%{partner_name}%"))
            | (WiseTransaction.payer_name.ilike(f"%{partner_name}%"))
            | (WiseTransaction.merchant.ilike(f"%{partner_name}%"))
        )
    if amount_min is not None:
        q = q.filter(WiseTransaction.amount >= amount_min)
    if amount_max is not None:
        q = q.filter(WiseTransaction.amount <= amount_max)

    q = q.order_by(WiseTransaction.transaction_date.desc())
    return [
        TransactionRow(
            id=t.id,
            wise_transaction_id=t.wise_transaction_id,
            transaction_date=t.transaction_date,
            amount=t.amount,
            currency=t.currency,
            description=t.description,
            payment_reference=t.payment_reference,
            partner_name=t.payee_name or t.payer_name or t.merchant,
            invoice_id=t.invoice_id,
            invoice_number=inv_num,
            invoice_file_id=t.invoice_file_id,
            invoice_file_filename=inv_file,
            total_fees=t.total_fees,
        )
        for t, inv_num, inv_file in q.all()
    ]


def get_transaction(db: Session, transaction_id: int) -> Optional[TransactionDetail]:
    row = (
        db.query(WiseTransaction, Invoice.invoice_number, InvoiceFile.filename)
        .outerjoin(Invoice, WiseTransaction.invoice_id == Invoice.id)
        .outerjoin(InvoiceFile, WiseTransaction.invoice_file_id == InvoiceFile.id)
        .filter(WiseTransaction.id == transaction_id)
        .first()
    )
    if not row:
        return None
    t, inv_num, inv_file = row
    return TransactionDetail(
        id=t.id,
        wise_transaction_id=t.wise_transaction_id,
        transaction_date=t.transaction_date,
        amount=t.amount,
        currency=t.currency,
        description=t.description,
        payment_reference=t.payment_reference,
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
