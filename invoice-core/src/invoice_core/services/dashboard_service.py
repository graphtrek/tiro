from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from invoice_core.db import (
    BankTransaction,
    Customer,
    Invoice,
    InvoiceFile,
    Supplier,
    SyncLog,
    _PaymentStatus,
    _enum_str,
    invoice_has_bank_txn,
)


@dataclass
class DashboardKpis:
    total_invoices: int
    unpaid_invoices: int
    unpaid_amount: float
    linked_pdfs: int
    unlinked_pdfs: int
    recent_bank_count: int
    supplier_count: int
    customer_count: int


@dataclass
class RecentInvoiceRow:
    id: int
    invoice_number: str
    invoice_date: Optional[object]
    supplier_name: str
    amount_total: Optional[float]
    payment_status: str


@dataclass
class RecentTransactionRow:
    id: int
    transaction_date: datetime
    amount: float
    currency: str
    partner_name: Optional[str]
    invoice_number: Optional[str]
    invoice_id: Optional[int]


@dataclass
class SyncLogRow:
    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    mode: Optional[str]
    invoice_count: int
    bank_count: int
    error_count: int
    errors: Optional[str]
    duration_s: Optional[float]


def get_kpis(db: Session) -> DashboardKpis:
    total_invoices = db.query(func.count(Invoice.id)).scalar() or 0
    unpaid_invoices = (
        db.query(func.count(Invoice.id))
        .filter(Invoice.payment_status == _PaymentStatus.UNPAID, ~invoice_has_bank_txn())
        .scalar()
        or 0
    )
    unpaid_amount = (
        db.query(func.coalesce(func.sum(Invoice.amount_total), 0.0))
        .filter(Invoice.payment_status == _PaymentStatus.UNPAID, ~invoice_has_bank_txn())
        .scalar()
        or 0.0
    )
    linked_pdfs = (
        db.query(func.count(Invoice.id))
        .filter(Invoice.invoice_file_id.isnot(None))
        .scalar()
        or 0
    )
    unlinked_pdfs = total_invoices - linked_pdfs
    cutoff = datetime.utcnow() - timedelta(days=30)
    recent_bank_count = (
        db.query(func.count(BankTransaction.id))
        .filter(BankTransaction.transaction_date >= cutoff)
        .scalar()
        or 0
    )
    supplier_count = db.query(func.count(Supplier.id)).scalar() or 0
    customer_count = db.query(func.count(Customer.id)).scalar() or 0
    return DashboardKpis(
        total_invoices=total_invoices,
        unpaid_invoices=unpaid_invoices,
        unpaid_amount=float(unpaid_amount),
        linked_pdfs=linked_pdfs,
        unlinked_pdfs=unlinked_pdfs,
        recent_bank_count=recent_bank_count,
        supplier_count=supplier_count,
        customer_count=customer_count,
    )


def get_recent_invoices(db: Session, limit: int = 10) -> list[RecentInvoiceRow]:
    rows = (
        db.query(Invoice, Supplier.name)
        .join(Supplier, Invoice.supplier_id == Supplier.id)
        .order_by(Invoice.invoice_date.desc().nullslast(), Invoice.id.desc())
        .limit(limit)
        .all()
    )
    paid_via_bank = {
        r[0]
        for r in db.query(BankTransaction.invoice_id)
        .filter(BankTransaction.invoice_id.isnot(None))
        .distinct()
    }
    return [
        RecentInvoiceRow(
            id=inv.id,
            invoice_number=inv.invoice_number,
            invoice_date=inv.invoice_date,
            supplier_name=name,
            amount_total=inv.amount_total,
            payment_status=_PaymentStatus.PAID.value if inv.id in paid_via_bank else _enum_str(inv.payment_status),
        )
        for inv, name in rows
    ]


def get_recent_transactions(db: Session, limit: int = 5) -> list[RecentTransactionRow]:
    rows = (
        db.query(BankTransaction, Invoice.invoice_number)
        .outerjoin(Invoice, BankTransaction.invoice_id == Invoice.id)
        .order_by(BankTransaction.transaction_date.desc())
        .limit(limit)
        .all()
    )
    return [
        RecentTransactionRow(
            id=t.id,
            transaction_date=t.transaction_date,
            amount=t.amount,
            currency=t.currency,
            partner_name=t.counterparty_name,
            invoice_number=inv_num,
            invoice_id=t.invoice_id,
        )
        for t, inv_num in rows
    ]


def get_last_sync(db: Session) -> Optional[SyncLogRow]:
    try:
        log = db.query(SyncLog).order_by(SyncLog.started_at.desc()).first()
        if not log:
            return None
        return _to_sync_log_row(log)
    except Exception:
        db.rollback()
        return None


def get_sync_logs(db: Session, limit: int = 10) -> list[SyncLogRow]:
    try:
        logs = db.query(SyncLog).order_by(SyncLog.started_at.desc()).limit(limit).all()
        return [_to_sync_log_row(log) for log in logs]
    except Exception:
        db.rollback()
        return []


def _to_sync_log_row(log: SyncLog) -> SyncLogRow:
    duration = None
    if log.finished_at and log.started_at:
        duration = (log.finished_at - log.started_at).total_seconds()
    return SyncLogRow(
        id=log.id,
        started_at=log.started_at,
        finished_at=log.finished_at,
        mode=log.mode,
        invoice_count=log.invoice_count or 0,
        bank_count=log.bank_count or 0,
        error_count=log.error_count or 0,
        errors=log.errors,
        duration_s=duration,
    )
