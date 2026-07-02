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
    bank_only = "bank_only"
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
    bank_transactions_synced: int = 0
    bank_files_matched: int = 0
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
    preview_base64: Optional[str] = None
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
    currency: Optional[str] = None
    invoice_operation: Optional[str] = None
    invoice_category: Optional[str] = None
    nav_ins_date: Optional[str] = None
    invoice_file_id: Optional[int] = None
    invoice_file_locked: bool = False
    created_at: datetime
    updated_at: datetime


class LinkFileRequest(BaseModel):
    invoice_file_id: int


class PatchInvoiceRequest(BaseModel):
    note: Optional[str] = None
    payment_status_locked: Optional[bool] = None
    payment_status: Optional[str] = None


class BankTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank: str
    transaction_id: str
    amount: float
    currency: str
    direction: str
    transaction_date: datetime
    description: Optional[str] = None
    payment_reference: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_account: Optional[str] = None
    counterparty_iban: Optional[str] = None
    transaction_type: Optional[str] = None
    category: Optional[str] = None
    balance: Optional[float] = None
    fees: Optional[float] = None
    supplier_id: Optional[int] = None
    customer_id: Optional[int] = None
    invoice_ids: list[int] = []
    invoice_numbers: list[str] = []
    invoice_file_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
