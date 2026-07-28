"""Pydantic request/response models for invoice-core (no SQLAlchemy)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ── Sync ─────────────────────────────────────────────────────────────────────


class SyncMode(StrEnum):
    full = "full"
    nav_only = "nav_only"
    pdf_only = "pdf_only"
    bank_only = "bank_only"
    match_only = "match_only"


class SyncRequest(BaseModel):
    start_date: str | None = Field(None, description="YYYY-MM-DD; default 30 days ago")
    end_date: str | None = Field(None, description="YYYY-MM-DD; default today")
    sync_mode: SyncMode | None = None
    clear_cache: bool = Field(
        False, description="Clear all downstream service caches before syncing"
    )


class SyncResponse(BaseModel):
    start_date: str
    end_date: str
    nav_invoices_synced: int = 0
    pdf_files_synced: int = 0
    bank_transactions_synced: int = 0
    bank_files_matched: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── Read DTOs (from_attributes=True for ORM → Pydantic) ─────────────────────


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tax_id: str | None = None
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    iban: str | None = None
    bban: str | None = None
    created_at: datetime
    updated_at: datetime


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tax_id: str | None = None
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    payment_terms: int | None = None
    iban: str | None = None
    bban: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Write DTOs (manual create/edit of partners) ─────────────────────────────


class SupplierIn(BaseModel):
    name: str
    tax_id: str | None = None
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    iban: str | None = None
    bban: str | None = None


class SupplierUpdate(SupplierIn):
    pass


class CustomerIn(BaseModel):
    name: str
    tax_id: str | None = None
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    payment_terms: int | None = None
    iban: str | None = None
    bban: str | None = None


class CustomerUpdate(CustomerIn):
    pass


class InvoiceFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    path: str | None = None
    words: str | None = None
    preview_base64: str | None = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


# These mirror `db.py`'s `_PaymentStatus`/`_InvoiceDirection` SQLAlchemy enums
# (same member names/values), just re-declared here so the API layer doesn't need
# to import the "private" ORM enums directly. Keep both pairs in sync by hand.
class PaymentStatus(StrEnum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"


class InvoiceDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


# Mirrors `db.py`'s `_ProjectType` SQLAlchemy enum (same member names/values).
class ProjectType(StrEnum):
    OTLET = "OTLET"
    SZAMLAZHATO = "SZAMLAZHATO"
    PRESALES = "PRESALES"


# Mirrors `db.py`'s `_ProjectStatus` SQLAlchemy enum (same member names/values).
class ProjectStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ONHOLD = "ONHOLD"


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_number: str
    invoice_date: date | None = None
    supplier_id: int | None = None
    customer_id: int | None = None
    amount_net: float | None = None
    amount_vat: float | None = None
    amount_total: float | None = None
    payment_status: PaymentStatus
    direction: InvoiceDirection
    currency: str | None = None
    invoice_operation: str | None = None
    invoice_category: str | None = None
    nav_ins_date: str | None = None
    payment_method: str | None = None
    payment_due_date: date | None = None
    invoice_file_id: int | None = None
    invoice_file_locked: bool = False
    supplier_locked: bool = False
    customer_locked: bool = False
    created_at: datetime
    updated_at: datetime


class UserIn(BaseModel):
    provider: str
    sub: str
    email: str
    name: str | None = None
    picture: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    sub: str
    email: str
    name: str | None = None
    picture: str | None = None
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


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_email: str | None = None
    impersonator_email: str | None = None
    method: str
    path: str
    page: str
    record: str | None = None
    label: str | None = None
    action: str
    status_code: int
    created_at: datetime


class ProjectIn(BaseModel):
    customer_id: int
    short_name: str
    owner_id: int
    status: ProjectStatus = ProjectStatus.OPEN
    start_date: date
    project_type: ProjectType
    permitted_user_ids: list[int] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    customer_id: int
    short_name: str
    owner_id: int
    status: ProjectStatus
    start_date: date
    project_type: ProjectType
    permitted_user_ids: list[int] = Field(default_factory=list)


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
    status: ProjectStatus
    start_date: date
    project_type: ProjectType
    permitted_user_ids: list[int]
    usage_hours: float
    first_entry_date: date | None
    created_at: datetime
    updated_at: datetime


class TimesheetEntryIn(BaseModel):
    user_id: int
    project_id: int
    activity_type_id: int
    entry_date: date
    hours: float
    participants: str | None = None
    description: str | None = None


class TimesheetEntryUpdate(BaseModel):
    project_id: int
    activity_type_id: int
    entry_date: date
    hours: float
    participants: str | None = None
    description: str | None = None


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
    participants: str | None = None
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class LinkFileRequest(BaseModel):
    invoice_file_id: int


class LinkSupplierRequest(BaseModel):
    supplier_id: int


class LinkCustomerRequest(BaseModel):
    customer_id: int


class PatchInvoiceRequest(BaseModel):
    note: str | None = None
    payment_status_locked: bool | None = None
    payment_status: str | None = None


class BankTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank: str
    transaction_id: str
    amount: float
    currency: str
    direction: str
    transaction_date: datetime
    description: str | None = None
    payment_reference: str | None = None
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    counterparty_iban: str | None = None
    transaction_type: str | None = None
    category: str | None = None
    balance: float | None = None
    fees: float | None = None
    counterparty_address: str | None = None
    sender_address: str | None = None
    counterparty_bank_code: str | None = None
    exchange_rate: float | None = None
    exchange_to_currency: str | None = None
    card_last_four: str | None = None
    note: str | None = None
    supplier_id: int | None = None
    customer_id: int | None = None
    invoice_ids: list[int] = []
    invoice_numbers: list[str] = []
    invoice_file_id: int | None = None
    created_at: datetime
    updated_at: datetime
