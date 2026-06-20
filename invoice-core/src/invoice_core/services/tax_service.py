from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from invoice_core.db import BankTransaction

TAX_ACCOUNTS: dict[str, str] = {
    "10032000-01076868-00000000": "NAV ÁFA",
    "10032000-01076301-00000000": "NAV Bírság",
    "10032000-06055950-00000000": "NAV SZJA",
    "10032000-06055912-00000000": "NAV Szochó",
    "10032000-01076019-00000000": "NAV TAO",
    "10032000-06055819-00000000": "NAV TB",
    "12001008-00272513-00100005": "HIPA",
    "12001008-00335345-00100002": "HIPA - Késedelmi",
    "12100011-10639683-00000000": "Iparkamara",
}


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
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.counterparty_account.in_(list(TAX_ACCOUNTS.keys())),
            BankTransaction.direction == "DEBIT",
            BankTransaction.transaction_date >= datetime(year, 1, 1),
            BankTransaction.transaction_date < datetime(year + 1, 1, 1),
        )
        .order_by(BankTransaction.transaction_date.desc())
        .all()
    )

    tax_labels = list(TAX_ACCOUNTS.values())
    totals_by_type: dict[str, float] = defaultdict(float)
    monthly_data: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    transactions: list[TaxTransaction] = []

    for tx in rows:
        label = TAX_ACCOUNTS.get(tx.counterparty_account or "", "")
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
