"""Bank mikroszerviz adatmodellek."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class BankTransaction(BaseModel):
    bank: str
    transaction_id: str
    date: date
    datetime: datetime | None
    amount: Decimal
    currency: str
    direction: Literal["CREDIT", "DEBIT"]
    description: str | None
    payment_reference: str | None
    counterparty_name: str | None
    counterparty_account: str | None
    counterparty_iban: str | None
    transaction_type: str | None
    category: str | None
    balance: Decimal | None
    fees: Decimal | None
    counterparty_address: str | None = None       # Erste "Partner címe"
    sender_address: str | None = None              # Erste "Küldő címe"
    counterparty_bank_code: str | None = None       # Erste "Partner bankkódja"
    exchange_rate: Decimal | None = None            # Wise "Exchange Rate"
    exchange_to_currency: str | None = None         # Wise "Exchange To"
    card_last_four: str | None = None               # Wise "Card Last Four Digits"
    note: str | None = None                         # Wise "Note"


class StatementFile(BaseModel):
    bank: str
    filename: str
    account_id: str
    currency: str | None
    from_date: date
    to_date: date
    path: str


class BankStatement(BaseModel):
    bank: str
    filename: str
    account_id: str
    currency: str | None
    from_date: date
    to_date: date
    fetched: int
    transactions: list[BankTransaction]


class ConsolidatedStatement(BaseModel):
    from_date: date | None
    to_date: date | None
    banks: list[str]
    total: int
    transactions: list[BankTransaction]
