"""SQLAlchemy engine, session, and all ORM models for invoice-core."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, timedelta
from enum import Enum as PyEnum
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    exists,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from .config import get_settings

# ── Engine + session ──────────────────────────────────────────────────────────


def _make_engine():
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session; use as a FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Enums ─────────────────────────────────────────────────────────────────────
#
# These two enums are the ORM/database-facing versions used by SQLAlchemy columns
# below. `models.py` defines its own `PaymentStatus`/`InvoiceDirection` enums for
# the Pydantic API layer (they must have the exact same member names/values as
# these). If you add or rename a member here, update `models.py` too, or the
# two layers will silently drift apart.


class _PaymentStatus(PyEnum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"


class _InvoiceDirection(PyEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class _ProjectType(PyEnum):
    OTLET = "OTLET"
    SZAMLAZHATO = "SZAMLAZHATO"
    PRESALES = "PRESALES"


class _ProjectStatus(PyEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ONHOLD = "ONHOLD"


class _VacationKind(StrEnum):
    VACATION = "vacation"
    OUT_OF_OFFICE = "out_of_office"
    NOTE = "note"


def _enum_str(value) -> str:
    """Return the string value of a SQLAlchemy enum column (may be Enum or str)."""
    return value.value if isinstance(value, PyEnum) else str(value)


# ── ORM models ────────────────────────────────────────────────────────────────


class Supplier(Base):
    __tablename__ = "supplier"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    tax_id = Column(String, nullable=True, unique=True)
    address = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    iban = Column(String, nullable=True)
    bban = Column(String, nullable=True)
    # Comma-separated list of every distinct bank account number bank sync
    # has observed a counterparty paying this supplier from/to (see
    # service.py's _record_partner_bank_account) — distinct from iban/bban
    # above, which hold the single NAV-reported account.
    bank_accounts = Column(Text, nullable=True)
    # Comma-separated list of every distinct counterparty name a bank
    # transaction has been linked to this supplier under — either matched
    # automatically by sync_bank or recorded when a user manually links a
    # transaction (see service.py's _record_partner_known_name) — so a
    # counterparty name that doesn't exactly match this supplier's own name
    # can still be recognized on a later sync.
    known_names = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    invoices = relationship("Invoice", back_populates="supplier")
    bank_transactions = relationship("BankTransaction", back_populates="supplier")


class Customer(Base):
    __tablename__ = "customer"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    tax_id = Column(String, nullable=True, unique=True)
    address = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    payment_terms = Column(Integer, nullable=True)
    iban = Column(String, nullable=True)
    bban = Column(String, nullable=True)
    # See Supplier.bank_accounts.
    bank_accounts = Column(Text, nullable=True)
    # See Supplier.known_names.
    known_names = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    invoices = relationship("Invoice", back_populates="customer")
    bank_transactions = relationship("BankTransaction", back_populates="customer")


class InvoiceFile(Base):
    __tablename__ = "invoice_file"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False, unique=True)
    path = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    words = Column(Text, nullable=True)
    preview_base64 = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    invoices = relationship("Invoice", back_populates="invoice_file")
    bank_transactions = relationship("BankTransaction", back_populates="invoice_file")


invoice_bank_transaction = Table(
    "invoice_bank_transaction",
    Base.metadata,
    Column("invoice_id", Integer, ForeignKey("invoice.id"), primary_key=True),
    Column("bank_transaction_id", Integer, ForeignKey("bank_transaction.id"), primary_key=True),
    Column("manual", Boolean, nullable=False, default=False),
)


class Invoice(Base):
    __tablename__ = "invoice"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String, nullable=False, unique=True, index=True)
    invoice_date = Column(Date, nullable=True, index=True)
    # Nullable: an unmatched NAV digest may not resolve to an existing
    # supplier/customer at sync time (see service.py's _find_supplier) — the
    # invoice still imports, left unlinked until a match is found or one is
    # created manually. Sync itself does create partners when a match isn't
    # found; nullability just covers the case where even that fails.
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    amount_net = Column(Float, nullable=True)
    amount_vat = Column(Float, nullable=True)
    amount_total = Column(Float, nullable=True)
    # native_enum=False: VARCHAR in both PostgreSQL and SQLite (test-compat)
    payment_status = Column(
        SAEnum(_PaymentStatus, native_enum=False),
        nullable=False,
        default=_PaymentStatus.UNPAID,
    )
    direction = Column(
        SAEnum(_InvoiceDirection, native_enum=False),
        nullable=False,
        default=_InvoiceDirection.OUTBOUND,
    )
    currency = Column(String, nullable=True)
    invoice_operation = Column(String, nullable=True)
    invoice_category = Column(String, nullable=True)
    nav_ins_date = Column(String, nullable=True)
    payment_method = Column(String, nullable=True)
    payment_due_date = Column(Date, nullable=True)
    invoice_file_id = Column(Integer, ForeignKey("invoice_file.id"), nullable=True)
    invoice_file_locked = Column(Boolean, nullable=False, default=False)
    note = Column(Text, nullable=True)
    payment_status_locked = Column(Boolean, nullable=False, default=False)
    supplier_locked = Column(Boolean, nullable=False, default=False)
    customer_locked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    supplier = relationship("Supplier", back_populates="invoices")
    customer = relationship("Customer", back_populates="invoices")
    invoice_file = relationship("InvoiceFile", back_populates="invoices")
    bank_transactions = relationship(
        "BankTransaction",
        secondary=invoice_bank_transaction,
        back_populates="invoices",
        lazy="select",
    )
    detail = relationship("InvoiceDetail", back_populates="invoice", uselist=False)
    lines = relationship("InvoiceLine", back_populates="invoice", order_by="InvoiceLine.id")
    vat_summaries = relationship(
        "InvoiceVatSummary", back_populates="invoice", order_by="InvoiceVatSummary.id"
    )


class InvoiceDetail(Base):
    """Full NAV queryInvoiceData detail captured during sync — 1:1 with Invoice."""

    __tablename__ = "invoice_detail"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoice.id"), nullable=False, unique=True, index=True)
    raw_xml = Column(Text, nullable=True)
    # Snapshot of the NAV-reported supplier/customer, independent of whether a
    # local Supplier/Customer could be matched — lets the Sync/Invoice page
    # show who still needs to be created/linked for an unmatched invoice.
    supplier_name = Column(String, nullable=True)
    supplier_tax_number = Column(String, nullable=True)
    supplier_address = Column(String, nullable=True)
    supplier_bank_account = Column(String, nullable=True)
    customer_name = Column(String, nullable=True)
    customer_tax_number = Column(String, nullable=True)
    customer_address = Column(String, nullable=True)
    customer_bank_account = Column(String, nullable=True)
    invoice_category = Column(String, nullable=True)
    delivery_date = Column(Date, nullable=True)
    currency_code = Column(String, nullable=True)
    exchange_rate = Column(Float, nullable=True)
    invoice_appearance = Column(String, nullable=True)
    invoice_net_amount = Column(Float, nullable=True)
    invoice_vat_amount = Column(Float, nullable=True)
    invoice_gross_amount = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    invoice = relationship("Invoice", back_populates="detail")


class InvoiceLine(Base):
    """A single NAV invoice line item captured during sync."""

    __tablename__ = "invoice_line"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoice.id"), nullable=False, index=True)
    line_number = Column(String, nullable=True)
    line_description = Column(Text, nullable=True)
    quantity = Column(Float, nullable=True)
    unit_of_measure = Column(String, nullable=True)
    unit_price = Column(Float, nullable=True)
    line_net_amount = Column(Float, nullable=True)
    line_vat_rate = Column(Float, nullable=True)
    line_vat_amount = Column(Float, nullable=True)
    line_gross_amount = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    invoice = relationship("Invoice", back_populates="lines")


class InvoiceVatSummary(Base):
    """A per-VAT-rate summary row captured during sync."""

    __tablename__ = "invoice_vat_summary"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoice.id"), nullable=False, index=True)
    vat_rate = Column(Float, nullable=True)
    vat_rate_net_amount = Column(Float, nullable=True)
    vat_rate_vat_amount = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    invoice = relationship("Invoice", back_populates="vat_summaries")


class BankTransaction(Base):
    __tablename__ = "bank_transaction"

    id = Column(Integer, primary_key=True, index=True)
    bank = Column(String, nullable=False, index=True)  # "erste" | "wise"
    transaction_id = Column(String, nullable=False, unique=True, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # "CREDIT" | "DEBIT"
    transaction_date = Column(DateTime, nullable=False, index=True)
    description = Column(String, nullable=True)
    payment_reference = Column(String, nullable=True)
    counterparty_name = Column(String, nullable=True)
    counterparty_account = Column(String, nullable=True)
    counterparty_iban = Column(String, nullable=True)
    transaction_type = Column(String, nullable=True)
    category = Column(String, nullable=True)
    balance = Column(Float, nullable=True)
    fees = Column(Float, nullable=True)
    counterparty_address = Column(String, nullable=True)
    sender_address = Column(String, nullable=True)
    counterparty_bank_code = Column(String, nullable=True)
    exchange_rate = Column(Float, nullable=True)
    exchange_to_currency = Column(String, nullable=True)
    card_last_four = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    invoice_file_id = Column(Integer, ForeignKey("invoice_file.id"), nullable=True, index=True)
    invoice_file_locked = Column(Boolean, nullable=False, default=False)
    supplier_locked = Column(Boolean, nullable=False, default=False)
    customer_locked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    supplier = relationship("Supplier", back_populates="bank_transactions")
    customer = relationship("Customer", back_populates="bank_transactions")
    invoices = relationship(
        "Invoice",
        secondary=invoice_bank_transaction,
        back_populates="bank_transactions",
        lazy="select",
    )
    invoice_file = relationship("InvoiceFile", back_populates="bank_transactions")


class User(Base):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("provider", "sub", name="uq_user_provider_sub"),)

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False)  # "google"
    sub = Column(String, nullable=False)  # provider-beli user id
    email = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    picture = Column(String, nullable=True)  # avatar URL
    role = Column(String, nullable=False, server_default="read_write")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    last_login_at = Column(DateTime, server_default=func.now(), nullable=False)


class ActivityType(Base):
    __tablename__ = "activity_type"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


project_permitted_user = Table(
    "project_permitted_user",
    Base.metadata,
    Column("project_id", Integer, ForeignKey("project.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("user.id"), primary_key=True),
)


class Project(Base):
    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("customer_id", "sequence_no", name="uq_project_customer_seq"),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=False, index=True)
    sequence_no = Column(Integer, nullable=False)
    short_name = Column(String, nullable=False)
    code = Column(String, nullable=False, unique=True, index=True)
    owner_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    # native_enum=False: VARCHAR in both PostgreSQL and SQLite (test-compat)
    project_type = Column(
        SAEnum(_ProjectType, native_enum=False),
        nullable=False,
        default=_ProjectType.SZAMLAZHATO,
    )
    status = Column(
        SAEnum(_ProjectStatus, native_enum=False),
        nullable=False,
        default=_ProjectStatus.OPEN,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    customer = relationship("Customer")
    owner = relationship("User", foreign_keys=[owner_id])
    permitted_users = relationship("User", secondary=project_permitted_user)
    timesheet_entries = relationship("TimesheetEntry", back_populates="project")

    @property
    def customer_name(self) -> str:
        return self.customer.name if self.customer else ""

    @property
    def owner_name(self) -> str:
        return (self.owner.name or self.owner.email) if self.owner else ""

    @property
    def permitted_user_ids(self) -> list[int]:
        return [u.id for u in self.permitted_users]

    @property
    def usage_hours(self) -> float:
        return sum(e.hours for e in self.timesheet_entries)

    @property
    def first_entry_date(self) -> date | None:
        dates = [e.entry_date for e in self.timesheet_entries]
        return min(dates) if dates else None


class TimesheetEntry(Base):
    __tablename__ = "timesheet_entry"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("project.id"), nullable=False, index=True)
    activity_type_id = Column(Integer, ForeignKey("activity_type.id"), nullable=False, index=True)
    entry_date = Column(Date, nullable=False, index=True)
    hours = Column(Float, nullable=False)
    participants = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    project = relationship("Project", back_populates="timesheet_entries")
    activity_type = relationship("ActivityType")

    @property
    def user_name(self) -> str:
        return (self.user.name or self.user.email) if self.user else ""

    @property
    def project_code(self) -> str:
        return self.project.code if self.project else ""

    @property
    def customer_name(self) -> str:
        return self.project.customer_name if self.project else ""

    @property
    def activity_type_name(self) -> str:
        return self.activity_type.name if self.activity_type else ""

    @property
    def project_week(self) -> int:
        if not self.project:
            return 1
        anchor = self.project.first_entry_date or (
            self.project.created_at.date() if self.project.created_at else self.entry_date
        )
        # Calendar weeks (Mon-Sun), not a rolling 7-day window from the anchor —
        # so e.g. a Friday anchor and the following Monday land in different weeks.
        anchor_monday = anchor - timedelta(days=anchor.weekday())
        entry_monday = self.entry_date - timedelta(days=self.entry_date.weekday())
        weeks_between = (entry_monday - anchor_monday).days // 7
        return max(weeks_between, 0) + 1


class VacationRequest(Base):
    __tablename__ = "vacation_request"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    # values_callable: store/read the enum's *value* (e.g. "out_of_office") rather
    # than its member name (e.g. "OUT_OF_OFFICE") — needed because this enum's
    # member names and values intentionally differ (unlike the other enums here).
    kind = Column(
        SAEnum(
            _VacationKind,
            native_enum=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", foreign_keys=[user_id])

    @property
    def user_name(self) -> str:
        return (self.user.name or self.user.email) if self.user else ""


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    finished_at = Column(DateTime, nullable=True)
    mode = Column(String, nullable=True)
    invoice_count = Column(Integer, default=0, nullable=False)
    bank_count = Column(Integer, default=0, nullable=False)
    error_count = Column(Integer, default=0, nullable=False)
    errors = Column(Text, nullable=True)
    warning_count = Column(Integer, default=0, nullable=False)
    warnings = Column(Text, nullable=True)


class SyncLock(Base):
    """Single-row DB-backed mutex guarding sync_all against concurrent runs (DEF-012).

    Deliberately a DB row, not an in-process threading.Lock/asyncio.Lock module
    global: uvicorn can run multiple worker processes, each with its own Python
    interpreter and memory space, so an in-process lock would only serialize
    requests within one worker, not across workers. A PostgreSQL
    pg_advisory_lock would also work but is Postgres-only and would need a
    separate no-op/fallback code path for the SQLite in-memory DB the test
    suite runs on. This single row instead is acquired via one atomic
    ``UPDATE ... WHERE`` (a compare-and-swap on locked_at), which behaves
    identically -- and correctly serializes concurrent acquirers -- on both
    PostgreSQL and SQLite, so the exact same code path is exercised in tests
    and in production. There is always exactly one row, with a fixed id
    (see service.py's SYNC_LOCK_ID).
    """

    __tablename__ = "sync_lock"

    id = Column(Integer, primary_key=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String, nullable=True)


class AuditLog(Base):
    """One row per successful user-initiated mutation, for the admin Audit page."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, nullable=True, index=True)
    impersonator_email = Column(
        String, nullable=True
    )  # set when the mutation happened during support impersonation
    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    page = Column(String, nullable=False, index=True)  # menu the mutation belongs to
    record = Column(
        String, nullable=True
    )  # human-readable record identifier (invoice number, partner name, ...)
    label = Column(String, nullable=True)  # button/action name the user clicked, if sent
    action = Column(String, nullable=False)  # create | update | delete
    # [{"field": ..., "old": ..., "new": ...}, ...] for update mutations whose
    # resolved record is a single ORM row — see audit_service._snapshot.
    changes = Column(JSON, nullable=True)
    status_code = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)


class TaxEstimateOverride(Base):
    """User-entered override for a single month's "Becsült bevétel" (estimated
    gross revenue) shown in vision's tax-estimate card.

    Holds only hand-entered facts the user has typed in to replace a
    projected/real month in `tax_service.get_tax_estimate` -- never written by
    `sync_all` or any other pipeline stage, per the "never let sync overwrite
    a fact the user set by hand" rule.
    """

    __tablename__ = "tax_estimate_override"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_tax_estimate_override_year_month"),
    )

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False)  # 1-12
    gross_revenue = Column(Float, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class FizetesKalkulatorState(Base):
    """Persisted inputs for vision's Fizetés Calculator (wage vs. dividend
    optimizer) page, so they survive across browsers/devices instead of
    living only in the browser's localStorage. Single shared row -- this is
    an internal company tool, not per-user state.
    """

    __tablename__ = "fizetes_kalkulator_state"

    id = Column(Integer, primary_key=True, index=True)
    net_wage = Column(Float, nullable=False)
    revenue = Column(Float, nullable=False)
    revenue_touched = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


# ── Business rules ──────────────────────────────────────────────────────────


def invoice_has_bank_txn():
    """Correlated EXISTS: the invoice has at least one linked bank transaction."""
    return exists().where(invoice_bank_transaction.c.invoice_id == Invoice.id)
