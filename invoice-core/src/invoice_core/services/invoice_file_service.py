from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Query
from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction, Invoice, InvoiceFile


@dataclass
class InvoiceFileRow:
    id: int
    filename: str
    file_size: Optional[int]
    linked_invoice_id: Optional[int]
    linked_invoice_number: Optional[str]
    supplier_name: Optional[str]
    amount_total: Optional[float]
    created_at: datetime
    is_linked: bool
    bank_transaction_id: Optional[str]
    bank_amount: Optional[float]
    bank_currency: Optional[str]
    bank_date: Optional[datetime]
    bank_count: int
    is_bank_linked: bool
    words: Optional[str] = None


class InvoiceFileFilters:
    def __init__(
        self,
        linked: Optional[str] = Query(None),
    ):
        self.linked = linked  # "yes" | "no" | None


def list_invoice_files(
    db: Session,
    linked: Optional[str] = None,
    filename: Optional[str] = None,
) -> list[InvoiceFileRow]:
    from invoice_core.db import Supplier

    q = (
        db.query(InvoiceFile, Invoice, Supplier.name)
        .outerjoin(Invoice, Invoice.invoice_file_id == InvoiceFile.id)
        .outerjoin(Supplier, Invoice.supplier_id == Supplier.id)
    )
    if linked == "yes":
        q = q.filter(Invoice.id.isnot(None))
    elif linked == "no":
        q = q.filter(Invoice.id.is_(None))
    if filename:
        q = q.filter(InvoiceFile.filename.ilike(f"%{filename}%"))

    q = q.order_by(InvoiceFile.created_at.desc())
    results = q.all()

    file_ids = [f.id for f, _inv, _sup in results]
    bank_by_file: dict[int, list[BankTransaction]] = {}
    if file_ids:
        txns = (
            db.query(BankTransaction)
            .filter(BankTransaction.invoice_file_id.in_(file_ids))
            .order_by(BankTransaction.transaction_date.desc())
            .all()
        )
        for t in txns:
            bank_by_file.setdefault(t.invoice_file_id, []).append(t)

    rows: list[InvoiceFileRow] = []
    for f, inv, sup_name in results:
        btxns = bank_by_file.get(f.id, [])
        btxn = btxns[0] if btxns else None
        rows.append(
            InvoiceFileRow(
                id=f.id,
                filename=f.filename,
                file_size=f.file_size,
                linked_invoice_id=inv.id if inv else None,
                linked_invoice_number=inv.invoice_number if inv else None,
                supplier_name=sup_name,
                amount_total=inv.amount_total if inv else None,
                created_at=f.created_at,
                is_linked=inv is not None,
                bank_transaction_id=btxn.transaction_id if btxn else None,
                bank_amount=btxn.amount if btxn else None,
                bank_currency=btxn.currency if btxn else None,
                bank_date=btxn.transaction_date if btxn else None,
                bank_count=len(btxns),
                is_bank_linked=btxn is not None,
                words=f.words,
            )
        )
    return rows
