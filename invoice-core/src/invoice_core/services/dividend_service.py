from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from invoice_core.db import Invoice, _InvoiceDirection


@dataclass
class MonthlyRow:
    month: str
    revenue: float
    expenses: float
    gross_profit: float


@dataclass
class DividendReport:
    year: int
    revenue: float
    expenses: float
    gross_profit: float
    tao_rate: float
    tao_tax: float
    net_profit: float
    szja_rate: float
    szja_tax: float
    szocho_rate: float
    szocho_tax: float
    net_dividend_without_szocho: float
    net_dividend_with_szocho: float
    invoice_count_out: int
    invoice_count_in: int
    monthly: list[MonthlyRow] = field(default_factory=list)


def calculate_dividend(db: Session, year: int, tao_rate: float = 0.09, szja_rate: float = 0.15, szocho_rate: float = 0.13) -> DividendReport:
    rows = (
        db.query(Invoice.invoice_date, Invoice.direction, Invoice.amount_net)
        .filter(
            Invoice.invoice_date >= date(year, 1, 1),
            Invoice.invoice_date <= date(year, 12, 31),
        )
        .all()
    )

    revenue = 0.0
    expenses = 0.0
    count_out = 0
    count_in = 0
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"revenue": 0.0, "expenses": 0.0})

    for inv_date, direction, amount_net in rows:
        amt = float(amount_net or 0.0)
        month_key = inv_date.strftime("%Y-%m") if inv_date else "unknown"
        if direction == _InvoiceDirection.OUTBOUND:
            revenue += amt
            monthly[month_key]["revenue"] += amt
            count_out += 1
        elif direction == _InvoiceDirection.INBOUND:
            expenses += amt
            monthly[month_key]["expenses"] += amt
            count_in += 1

    gross_profit = revenue - expenses
    tao_tax = max(0.0, gross_profit * tao_rate)
    net_profit = gross_profit - tao_tax
    szja_tax = max(0.0, net_profit * szja_rate)
    szocho_tax = max(0.0, net_profit * szocho_rate)
    net_dividend_without_szocho = net_profit - szja_tax
    net_dividend_with_szocho = net_profit - szja_tax - szocho_tax

    monthly_rows = [
        MonthlyRow(
            month=m,
            revenue=v["revenue"],
            expenses=v["expenses"],
            gross_profit=v["revenue"] - v["expenses"],
        )
        for m, v in sorted(monthly.items())
    ]

    return DividendReport(
        year=year,
        revenue=revenue,
        expenses=expenses,
        gross_profit=gross_profit,
        tao_rate=tao_rate,
        tao_tax=tao_tax,
        net_profit=net_profit,
        szja_rate=szja_rate,
        szja_tax=szja_tax,
        szocho_rate=szocho_rate,
        szocho_tax=szocho_tax,
        net_dividend_without_szocho=net_dividend_without_szocho,
        net_dividend_with_szocho=net_dividend_with_szocho,
        invoice_count_out=count_out,
        invoice_count_in=count_in,
        monthly=monthly_rows,
    )
