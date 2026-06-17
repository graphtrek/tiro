from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Query
from sqlalchemy.orm import Session

from invoice_core.db import Invoice, InvoiceFile


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
    return [
        InvoiceFileRow(
            id=f.id,
            filename=f.filename,
            linked_invoice_id=inv.id if inv else None,
            linked_invoice_number=inv.invoice_number if inv else None,
            supplier_name=sup_name,
            amount_total=inv.amount_total if inv else None,
            created_at=f.created_at,
            is_linked=inv is not None,
        )
        for f, inv, sup_name in q.all()
    ]
