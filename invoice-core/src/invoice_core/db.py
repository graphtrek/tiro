"""SQLAlchemy engine, session, and all ORM models for invoice-core."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import Generator

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
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

class _PaymentStatus(PyEnum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"


class _InvoiceDirection(PyEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


# ── ORM models ────────────────────────────────────────────────────────────────

class Supplier(Base):
    __tablename__ = "supplier"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    tax_id = Column(String, nullable=True, unique=True)
    address = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    bank_account = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    invoices = relationship("Invoice", back_populates="supplier")
    wise_transactions = relationship("WiseTransaction", back_populates="supplier")


class Customer(Base):
    __tablename__ = "customer"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    tax_id = Column(String, nullable=True, unique=True)
    address = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    payment_terms = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    invoices = relationship("Invoice", back_populates="customer")
    wise_transactions = relationship("WiseTransaction", back_populates="customer")


class InvoiceFile(Base):
    __tablename__ = "invoice_file"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False, unique=True)
    path = Column(String, nullable=True)
    words = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    invoices = relationship("Invoice", back_populates="invoice_file")
    wise_transactions = relationship("WiseTransaction", back_populates="invoice_file")


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
    nav_transaction_id = Column(String, nullable=True)
    invoice_file_id = Column(Integer, ForeignKey("invoice_file.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    supplier = relationship("Supplier", back_populates="invoices")
    customer = relationship("Customer", back_populates="invoices")
    invoice_file = relationship("InvoiceFile", back_populates="invoices")
    wise_transactions = relationship("WiseTransaction", back_populates="invoice")


class WiseTransaction(Base):
    __tablename__ = "wise_transaction"

    id = Column(Integer, primary_key=True, index=True)
    wise_transaction_id = Column(String, nullable=False, unique=True, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    transaction_date = Column(DateTime, nullable=False)
    description = Column(String, nullable=True)
    payment_reference = Column(String, nullable=True)
    running_balance = Column(Float, nullable=True)
    exchange_from = Column(String, nullable=True)
    exchange_to = Column(String, nullable=True)
    exchange_rate = Column(Float, nullable=True)
    payer_name = Column(String, nullable=True)
    payee_name = Column(String, nullable=True)
    payee_account_number = Column(String, nullable=True)
    merchant = Column(String, nullable=True)
    card_last_four_digits = Column(String, nullable=True)
    card_holder_full_name = Column(String, nullable=True)
    attachment = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    total_fees = Column(Float, nullable=True)
    exchange_to_amount = Column(Float, nullable=True)
    transaction_type = Column(String, nullable=True)
    transaction_details_type = Column(String, nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customer.id"), nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoice.id"), nullable=True)
    invoice_file_id = Column(Integer, ForeignKey("invoice_file.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    supplier = relationship("Supplier", back_populates="wise_transactions")
    customer = relationship("Customer", back_populates="wise_transactions")
    invoice = relationship("Invoice", back_populates="wise_transactions")
    invoice_file = relationship("InvoiceFile", back_populates="wise_transactions")


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    finished_at = Column(DateTime, nullable=True)
    mode = Column(String, nullable=True)
    invoice_count = Column(Integer, default=0, nullable=False)
    wise_count = Column(Integer, default=0, nullable=False)
    error_count = Column(Integer, default=0, nullable=False)
    errors = Column(Text, nullable=True)
