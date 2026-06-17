"""Pydantic modellek a wise-invoice mikroszervizhez."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field, field_serializer


# ── Wise API válasz modellek ─────────────────────────────────────────────────


class TransactionType(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class WiseAmount(BaseModel):
    value: Decimal
    currency: str


class WiseMerchant(BaseModel):
    name: str | None = None
    category: str | None = None
    categoryCode: str | None = None


class WiseTransactionDetails(BaseModel):
    type: str
    description: str | None = None
    merchant: WiseMerchant | None = None
    senderName: str | None = None
    senderAccount: str | None = None
    recipientName: str | None = None
    recipientAccount: str | None = None
    paymentReference: str | None = None


class WiseTransaction(BaseModel):
    type: TransactionType
    date: datetime
    amount: WiseAmount
    totalFees: WiseAmount | None = None
    details: WiseTransactionDetails
    exchangeDetails: dict[str, Any] | None = None
    runningBalance: WiseAmount | None = None
    referenceNumber: str


class WiseAccountHolder(BaseModel):
    type: str | None = None
    address: dict[str, Any] | None = None
    firstName: str | None = None
    lastName: str | None = None
    currency: str | None = None


class WiseStatement(BaseModel):
    accountHolder: WiseAccountHolder | None = None
    transactions: list[WiseTransaction] = Field(default_factory=list)
    endOfStatementBalance: WiseAmount | None = None


# ── API kérés/válasz modellek ────────────────────────────────────────────────


class SyncRequest(BaseModel):
    """Szinkronizálási kérés paraméterei."""

    start_date: str | None = Field(
        None, description="Szűrés kezdete (YYYY-MM-DD); default 30 napja"
    )
    end_date: str | None = Field(
        None, description="Szűrés vége (YYYY-MM-DD); default ma"
    )
    currency: str | None = Field(
        None, description="Pénznem (pl. EUR, GBP, HUF); default: WISE_ACCOUNT_CURRENCY"
    )


class TransactionSummary(BaseModel):
    """Egy feldolgozott Wise tranzakció összefoglalója."""

    wise_transaction_id: str
    type: TransactionType
    transaction_date: datetime
    amount: Decimal
    currency: str
    description: str | None = None
    payment_reference: str | None = None
    running_balance: Decimal | None = None
    exchange_from: str | None = None
    exchange_to: str | None = None
    exchange_rate: Decimal | None = None
    payer_name: str | None = None
    payee_name: str | None = None
    payee_account_number: str | None = None
    merchant: str | None = None
    card_last_four_digits: str | None = None
    card_holder_full_name: str | None = None
    attachment: str | None = None
    note: str | None = None
    total_fees: Decimal | None = None
    exchange_to_amount: Decimal | None = None
    transaction_details_type: str | None = None
    counterparty_name: str | None = None

    @field_serializer("transaction_date")
    def _serialize_datetime(self, value: datetime) -> str:
        """``Date Time`` formátum: yyyy-mm-dd hh:mm:ss."""
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def date(self) -> str:
        """``Date`` formátum: yyyy-mm-dd (a tranzakció napja)."""
        return self.transaction_date.strftime("%Y-%m-%d")


class SyncResponse(BaseModel):
    """Wise lekérés eredménye."""

    start_date: str
    end_date: str
    currency: str
    fetched: int = 0
    transactions: list[TransactionSummary] = Field(default_factory=list)


# ── CSV-import modellek ───────────────────────────────────────────────────────


class StatementFile(BaseModel):
    """Egy letöltött Wise kivonat CSV fájl metaadatai.

    A fájlnév-sémából (``statement_<balanceId>_<currency>_<from>_<to>.csv``)
    parszolva.
    """

    filename: str
    balance_id: int
    currency: str
    from_date: date
    to_date: date
    size_bytes: int
    modified_at: datetime


class StatementImport(BaseModel):
    """Egy CSV fájlból beolvasott tranzakciók."""

    filename: str
    balance_id: int | None = None
    currency: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    fetched: int = 0
    transactions: list[TransactionSummary] = Field(default_factory=list)
