"""Pydantic request/response models for invoice-core (no SQLAlchemy)."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Sync ─────────────────────────────────────────────────────────────────────


class SyncMode(str, Enum):
    full = "full"
    nav_only = "nav_only"
    pdf_only = "pdf_only"
    wise_only = "wise_only"
    match_only = "match_only"


class SyncRequest(BaseModel):
    start_date: Optional[str] = Field(None, description="YYYY-MM-DD; default 30 days ago")
    end_date: Optional[str] = Field(None, description="YYYY-MM-DD; default today")
    sync_mode: Optional[SyncMode] = None
    clear_cache: bool = Field(False, description="Clear all downstream service caches before syncing")


class SyncResponse(BaseModel):
    start_date: str
    end_date: str
    nav_invoices_synced: int = 0
    pdf_files_synced: int = 0
    wise_transactions_synced: int = 0
    wise_files_matched: int = 0
    errors: List[str] = Field(default_factory=list)


# ── Read DTOs (from_attributes=True for ORM → Pydantic) ─────────────────────


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tax_id: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    bank_account: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tax_id: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    payment_terms: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class InvoiceFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    path: Optional[str] = None
    words: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PaymentStatus(str, Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"


class InvoiceDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_number: str
    invoice_date: Optional[date] = None
    supplier_id: int
    customer_id: int
    amount_net: Optional[float] = None
    amount_vat: Optional[float] = None
    amount_total: Optional[float] = None
    payment_status: PaymentStatus
    direction: InvoiceDirection
    nav_transaction_id: Optional[str] = None
    invoice_file_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class WiseTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    wise_transaction_id: str
    amount: float
    currency: str
    transaction_date: datetime
    description: Optional[str] = None
    payment_reference: Optional[str] = None
    running_balance: Optional[float] = None
    exchange_from: Optional[str] = None
    exchange_to: Optional[str] = None
    exchange_rate: Optional[float] = None
    payer_name: Optional[str] = None
    payee_name: Optional[str] = None
    payee_account_number: Optional[str] = None
    merchant: Optional[str] = None
    card_last_four_digits: Optional[str] = None
    card_holder_full_name: Optional[str] = None
    attachment: Optional[str] = None
    note: Optional[str] = None
    total_fees: Optional[float] = None
    exchange_to_amount: Optional[float] = None
    transaction_type: Optional[str] = None
    transaction_details_type: Optional[str] = None
    supplier_id: Optional[int] = None
    customer_id: Optional[int] = None
    invoice_id: Optional[int] = None
    invoice_file_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
