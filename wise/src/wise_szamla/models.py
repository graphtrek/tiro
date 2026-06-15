"""Pydantic modellek a wise-szamla mikroszervizhez."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field, field_serializer


# ── Wise API válasz modellek ─────────────────────────────────────────────────


class TransactionType(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class WiseAmount(BaseModel):
    value: Decimal
    currency: str


class WiseMerchant(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    categoryCode: Optional[str] = None


class WiseTransactionDetails(BaseModel):
    type: str
    description: Optional[str] = None
    merchant: Optional[WiseMerchant] = None
    senderName: Optional[str] = None
    senderAccount: Optional[str] = None
    recipientName: Optional[str] = None
    recipientAccount: Optional[str] = None
    paymentReference: Optional[str] = None


class WiseTransaction(BaseModel):
    type: TransactionType
    date: datetime
    amount: WiseAmount
    totalFees: Optional[WiseAmount] = None
    details: WiseTransactionDetails
    exchangeDetails: Optional[Dict[str, Any]] = None
    runningBalance: Optional[WiseAmount] = None
    referenceNumber: str


class WiseAccountHolder(BaseModel):
    type: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    currency: Optional[str] = None


class WiseStatement(BaseModel):
    accountHolder: Optional[WiseAccountHolder] = None
    transactions: List[WiseTransaction] = Field(default_factory=list)
    endOfStatementBalance: Optional[WiseAmount] = None


# ── API kérés/válasz modellek ────────────────────────────────────────────────


class SyncRequest(BaseModel):
    """Szinkronizálási kérés paraméterei."""

    start_date: Optional[str] = Field(
        None, description="Szűrés kezdete (YYYY-MM-DD); default 30 napja"
    )
    end_date: Optional[str] = Field(
        None, description="Szűrés vége (YYYY-MM-DD); default ma"
    )
    currency: Optional[str] = Field(
        None, description="Pénznem (pl. EUR, GBP, HUF); default: WISE_ACCOUNT_CURRENCY"
    )


class TransactionSummary(BaseModel):
    """Egy feldolgozott Wise tranzakció összefoglalója."""

    wise_transaction_id: str
    type: TransactionType
    transaction_date: datetime
    amount: Decimal
    currency: str
    description: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_account: Optional[str] = None
    payment_reference: Optional[str] = None

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
    transactions: List[TransactionSummary] = Field(default_factory=list)


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
    balance_id: Optional[int] = None
    currency: Optional[str] = None
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    fetched: int = 0
    transactions: List[TransactionSummary] = Field(default_factory=list)
