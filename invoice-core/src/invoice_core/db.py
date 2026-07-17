"""SQLAlchemy engine, session, and all ORM models for invoice-core."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import Generator

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum as SAEnum,
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
    invoice_date = Column(Date, nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=False)
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


class BankTransaction(Base):
    __tablename__ = "bank_transaction"

    id = Column(Integer, primary_key=True, index=True)
    bank = Column(String, nullable=False, index=True)        # "erste" | "wise"
    transaction_id = Column(String, nullable=False, unique=True, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    direction = Column(String, nullable=False)               # "CREDIT" | "DEBIT"
    transaction_date = Column(DateTime, nullable=False)
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


# ── Business rules ──────────────────────────────────────────────────────────

def invoice_has_bank_txn():
    """Correlated EXISTS: the invoice has at least one linked bank transaction."""
    return exists().where(invoice_bank_transaction.c.invoice_id == Invoice.id)
