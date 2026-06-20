from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from invoice_core.config import get_settings
from invoice_core.db import BankTransaction


@dataclass
class TaxTransaction:
    id: int
    transaction_date: datetime
    counterparty_name: Optional[str]
    tax_label: str
    amount: float
    currency: str


@dataclass
class TaxMonthRow:
    month: str
    totals: dict[str, float]
    row_total: float


@dataclass
class TaxReport:
    year: int
    grand_total: float
    totals_by_type: dict[str, float]
    monthly: list[TaxMonthRow]
    transactions: list[TaxTransaction]
    tax_labels: list[str] = field(default_factory=list)


def get_tax_report(db: Session, year: int) -> TaxReport:
    tax_accounts = get_settings().tax_accounts
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.counterparty_account.in_(list(tax_accounts.keys())),
            BankTransaction.direction == "DEBIT",
            BankTransaction.transaction_date >= datetime(year, 1, 1),
            BankTransaction.transaction_date < datetime(year + 1, 1, 1),
        )
        .order_by(BankTransaction.transaction_date.desc())
        .all()
    )

    tax_labels = list(tax_accounts.values())
    totals_by_type: dict[str, float] = defaultdict(float)
    monthly_data: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    transactions: list[TaxTransaction] = []

    for tx in rows:
        label = tax_accounts.get(tx.counterparty_account or "", "")
        if not label:
            continue
        amt = float(tx.amount or 0.0)
        month_key = tx.transaction_date.strftime("%Y-%m") if tx.transaction_date else "unknown"
        totals_by_type[label] += amt
        monthly_data[month_key][label] += amt
        transactions.append(
            TaxTransaction(
                id=tx.id,
                transaction_date=tx.transaction_date,
                counterparty_name=tx.counterparty_name,
                tax_label=label,
                amount=amt,
                currency=tx.currency or "HUF",
            )
        )

    grand_total = sum(totals_by_type.values())

    monthly = [
        TaxMonthRow(
            month=m,
            totals={label: monthly_data[m].get(label, 0.0) for label in tax_labels},
            row_total=sum(monthly_data[m].values()),
        )
        for m in sorted(monthly_data.keys())
    ]

    return TaxReport(
        year=year,
        grand_total=grand_total,
        totals_by_type=dict(totals_by_type),
        monthly=monthly,
        transactions=transactions,
        tax_labels=tax_labels,
    )
