from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Query
from sqlalchemy.orm import Session

from invoice_core.db import Invoice, InvoiceFile, WiseTransaction


@dataclass
class InvoiceFileRow:
    id: int
    filename: str
    linked_invoice_id: Optional[int]
    linked_invoice_number: Optional[str]
    supplier_name: Optional[str]
    amount_total: Optional[float]
    created_at: datetime
    is_linked: bool
    wise_transaction_id: Optional[str]
    wise_amount: Optional[float]
    wise_currency: Optional[str]
    wise_date: Optional[datetime]
    wise_count: int
    is_wise_linked: bool


class InvoiceFileFilters:
    def __init__(
        self,
        linked: Optional[str] = Query(None),
    ):
        self.linked = linked  # "yes" | "no" | None


def list_invoice_files(
    db: Session,
    linked: Optional[str] = None,
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

    q = q.order_by(InvoiceFile.created_at.desc())
    results = q.all()

    # Wise transactions linked to these files (set by sync_match via
    # WiseTransaction.invoice_file_id). One file may have several, so collect
    # them per file id rather than join-multiplying the file rows.
    file_ids = [f.id for f, _inv, _sup in results]
    wise_by_file: dict[int, list[WiseTransaction]] = {}
    if file_ids:
        txns = (
            db.query(WiseTransaction)
            .filter(WiseTransaction.invoice_file_id.in_(file_ids))
            .order_by(WiseTransaction.transaction_date.desc())
            .all()
        )
        for t in txns:
            wise_by_file.setdefault(t.invoice_file_id, []).append(t)

    rows: list[InvoiceFileRow] = []
    for f, inv, sup_name in results:
        wtxns = wise_by_file.get(f.id, [])
        wtxn = wtxns[0] if wtxns else None
        rows.append(
            InvoiceFileRow(
                id=f.id,
                filename=f.filename,
                linked_invoice_id=inv.id if inv else None,
                linked_invoice_number=inv.invoice_number if inv else None,
                supplier_name=sup_name,
                amount_total=inv.amount_total if inv else None,
                created_at=f.created_at,
                is_linked=inv is not None,
                wise_transaction_id=wtxn.wise_transaction_id if wtxn else None,
                wise_amount=wtxn.amount if wtxn else None,
                wise_currency=wtxn.currency if wtxn else None,
                wise_date=wtxn.transaction_date if wtxn else None,
                wise_count=len(wtxns),
                is_wise_linked=wtxn is not None,
            )
        )
    return rows
