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
    warnings: List[str] = Field(default_factory=list)


# ── Read DTOs (from_attributes=True for ORM → Pydantic) ─────────────────────


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tax_id: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    iban: Optional[str] = None
    bban: Optional[str] = None
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
    iban: Optional[str] = None
    bban: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ── Write DTOs (manual create/edit of partners) ─────────────────────────────


class SupplierIn(BaseModel):
    name: str
    tax_id: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    iban: Optional[str] = None
    bban: Optional[str] = None


class SupplierUpdate(SupplierIn):
    pass


class CustomerIn(BaseModel):
    name: str
    tax_id: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    payment_terms: Optional[int] = None
    iban: Optional[str] = None
    bban: Optional[str] = None


class CustomerUpdate(CustomerIn):
    pass


class InvoiceFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    path: Optional[str] = None
    words: Optional[str] = None
    preview_base64: Optional[str] = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


# These mirror `db.py`'s `_PaymentStatus`/`_InvoiceDirection` SQLAlchemy enums
# (same member names/values), just re-declared here so the API layer doesn't need
# to import the "private" ORM enums directly. Keep both pairs in sync by hand.
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
    payment_method: Optional[str] = None
    payment_due_date: Optional[date] = None
    invoice_file_id: Optional[int] = None
    invoice_file_locked: bool = False
    supplier_locked: bool = False
    customer_locked: bool = False
    created_at: datetime
    updated_at: datetime


class UserIn(BaseModel):
    provider: str
    sub: str
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    sub: str
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime


class ActivityTypeIn(BaseModel):
    name: str


class ActivityTypeUpdate(BaseModel):
    name: str
    is_active: bool


class ActivityTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectIn(BaseModel):
    customer_id: int
    short_name: str
    owner_id: int
    permitted_user_ids: List[int] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    customer_id: int
    short_name: str
    owner_id: int
    is_active: bool
    permitted_user_ids: List[int] = Field(default_factory=list)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_name: str
    sequence_no: int
    short_name: str
    code: str
    owner_id: int
    owner_name: str
    is_active: bool
    permitted_user_ids: List[int]
    usage_hours: float
    created_at: datetime
    updated_at: datetime


class TimesheetEntryIn(BaseModel):
    user_id: int
    project_id: int
    activity_type_id: int
    entry_date: date
    hours: float
    participants: Optional[str] = None
    description: Optional[str] = None


class TimesheetEntryUpdate(BaseModel):
    project_id: int
    activity_type_id: int
    entry_date: date
    hours: float
    participants: Optional[str] = None
    description: Optional[str] = None


class TimesheetEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: str
    project_id: int
    project_code: str
    customer_name: str
    activity_type_id: int
    activity_type_name: str
    entry_date: date
    project_week: int
    hours: float
    participants: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class LinkFileRequest(BaseModel):
    invoice_file_id: int


class LinkSupplierRequest(BaseModel):
    supplier_id: int


class LinkCustomerRequest(BaseModel):
    customer_id: int


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
    counterparty_address: Optional[str] = None
    sender_address: Optional[str] = None
    counterparty_bank_code: Optional[str] = None
    exchange_rate: Optional[float] = None
    exchange_to_currency: Optional[str] = None
    card_last_four: Optional[str] = None
    note: Optional[str] = None
    supplier_id: Optional[int] = None
    customer_id: Optional[int] = None
    invoice_ids: list[int] = []
    invoice_numbers: list[str] = []
    invoice_file_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
