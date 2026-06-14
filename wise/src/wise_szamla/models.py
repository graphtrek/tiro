"""Pydantic modellek a wise-szamla mikroszervizhez."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class SyncResponse(BaseModel):
    """Wise lekérés eredménye."""

    start_date: str
    end_date: str
    currency: str
    fetched: int = 0
    transactions: List[TransactionSummary] = Field(default_factory=list)
