from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from invoice_core.config import get_settings
from invoice_core.db import (
    BankTransaction,
    Invoice,
    InvoiceVatSummary,
    TaxEstimateOverride,
    _InvoiceDirection,
)
from invoice_core.timeutil import today

STANDARD_VAT_RATE = 0.27  # Hungarian standard VAT rate, used to derive net from a gross override


@dataclass
class TaxTransaction:
    id: int
    transaction_date: datetime
    counterparty_name: str | None
    tax_label: str
    amount: float
    currency: str


@dataclass
class TaxMonthRow:
    month: str
    gross_revenue: float
    totals: dict[str, float]
    row_total: float


@dataclass
class TaxReport:
    year: int
    grand_total: float
    gross_revenue: float
    totals_by_type: dict[str, float]
    monthly: list[TaxMonthRow]
    transactions: list[TaxTransaction]
    tax_labels: list[str] = field(default_factory=list)


def get_tax_report(db: Session, year: int) -> TaxReport:
    """Summarize *year*'s outgoing bank payments to known tax-authority accounts.

    Matches transactions by counterparty account number against
    `settings.tax_accounts` (see config.py) to label each payment with the tax
    type it represents (e.g. "NAV ÁFA" = VAT, "NAV TAO" = corporate tax), then
    totals them by month and by tax type.
    """
    tax_accounts = get_settings().tax_accounts
    # Naive-UTC year boundaries for filtering the naive `transaction_date`
    # column (see timeutil). datetime.combine keeps the result naive without
    # tripping DTZ001 the way datetime(year, 1, 1) would.
    year_start = datetime.combine(date(year, 1, 1), time.min)
    year_end = datetime.combine(date(year + 1, 1, 1), time.min)
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.counterparty_account.in_(list(tax_accounts.keys())),
            BankTransaction.direction == "DEBIT",
            BankTransaction.transaction_date >= year_start,
            BankTransaction.transaction_date < year_end,
        )
        .order_by(BankTransaction.transaction_date.desc())
        .all()
    )

    credit_rows = (
        db.query(BankTransaction.transaction_date, BankTransaction.amount)
        .filter(
            BankTransaction.direction == "CREDIT",
            BankTransaction.transaction_date >= year_start,
            BankTransaction.transaction_date < year_end,
        )
        .all()
    )
    monthly_gross_revenue: dict[str, float] = defaultdict(float)
    gross_revenue = 0.0
    for tx_date, amount in credit_rows:
        amt = float(amount or 0.0)
        gross_revenue += amt
        month_key = tx_date.strftime("%Y-%m") if tx_date else "unknown"
        monthly_gross_revenue[month_key] += amt

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
            gross_revenue=monthly_gross_revenue.get(m, 0.0),
            totals={label: monthly_data[m].get(label, 0.0) for label in tax_labels},
            row_total=sum(monthly_data[m].values()),
        )
        for m in sorted(monthly_data.keys())
    ]

    return TaxReport(
        year=year,
        grand_total=grand_total,
        gross_revenue=gross_revenue,
        totals_by_type=dict(totals_by_type),
        monthly=monthly,
        transactions=transactions,
        tax_labels=tax_labels,
    )


@dataclass
class TaxEstimateMonthRow:
    month: str
    is_projected: bool
    revenue: float
    gross_revenue: float
    expenses: float
    vat_payable: float
    tao_tax: float
    hipa_tax: float
    szja_tax: float
    szocho_tax: float
    total: float
    is_override: bool = False


@dataclass
class TaxEstimateReport:
    year: int
    tao_rate: float
    hipa_rate: float
    szja_rate: float
    szocho_rate: float
    monthly: list[TaxEstimateMonthRow]
    totals: TaxEstimateMonthRow


def _tax_row(
    month: str,
    is_projected: bool,
    revenue: float,
    gross_revenue: float,
    expenses: float,
    vat_payable: float,
    tao_rate: float,
    hipa_rate: float,
    szja_rate: float,
    szocho_rate: float,
) -> TaxEstimateMonthRow:
    gross_profit = revenue - expenses
    tao_tax = max(0.0, gross_profit * tao_rate)
    hipa_tax = max(0.0, revenue * hipa_rate)
    net_profit = gross_profit - tao_tax - hipa_tax
    szja_tax = max(0.0, net_profit * szja_rate)
    szocho_tax = max(0.0, net_profit * szocho_rate)
    total = vat_payable + tao_tax + hipa_tax + szja_tax + szocho_tax
    return TaxEstimateMonthRow(
        month=month,
        is_projected=is_projected,
        revenue=revenue,
        gross_revenue=gross_revenue,
        expenses=expenses,
        vat_payable=vat_payable,
        tao_tax=tao_tax,
        hipa_tax=hipa_tax,
        szja_tax=szja_tax,
        szocho_tax=szocho_tax,
        total=total,
    )


def get_estimate_overrides(db: Session, year: int) -> dict[int, float]:
    """Return {month: gross_revenue} for all saved overrides in *year*."""
    rows = db.query(TaxEstimateOverride).filter(TaxEstimateOverride.year == year).all()
    return {row.month: row.gross_revenue for row in rows}


def save_estimate_overrides(
    db: Session, year: int, overrides: dict[int, float]
) -> dict[int, float]:
    """Upsert each {month: gross_revenue} pair for *year* and return the full saved set.

    Months present in *overrides* are inserted/updated; months already saved
    for *year* but absent from *overrides* are left untouched (never deleted).
    """
    for month, gross_revenue in overrides.items():
        existing = (
            db.query(TaxEstimateOverride)
            .filter(TaxEstimateOverride.year == year, TaxEstimateOverride.month == month)
            .one_or_none()
        )
        if existing is not None:
            existing.gross_revenue = gross_revenue
        else:
            db.add(TaxEstimateOverride(year=year, month=month, gross_revenue=gross_revenue))
    db.commit()
    return get_estimate_overrides(db, year)


def get_tax_estimate(
    db: Session,
    year: int,
    tao_rate: float = 0.10,
    hipa_rate: float = 0.02,
    szja_rate: float = 0.15,
    szocho_rate: float = 0.13,
) -> TaxEstimateReport:
    """Estimate monthly tax liability for *year* from invoice data.

    Unlike `get_tax_report` (actual money already paid to tax accounts), this
    projects what's *accruing*: ÁFA (output VAT - input VAT, from
    `InvoiceVatSummary`), TAO/KIVA and HIPA (from gross profit / revenue),
    and SZJA/SZOCHÓ on the resulting dividend base — mirroring
    `dividend_service.calculate_dividend`'s yearly formula, applied per month.

    For the current year, months after "now" have no invoices yet, so they're
    filled with the trailing average of the year's actual (nonzero) months and
    flagged `is_projected=True`. Other years are returned as real/zero-filled
    data for all 12 months with no projection.

    Any month with a saved `TaxEstimateOverride` (user-entered "Becsult
    bevetel") substitutes its revenue inputs -- gross_revenue = the override,
    revenue (net) = gross / 1.27, expenses = 0.0, vat_payable = gross - net --
    before the row is built, and is flagged `is_override=True`. This takes
    precedence over both real invoice data and the trailing-average
    projection, for elapsed and future months alike, and overridden months
    are excluded from the trailing-average pool so non-overridden months'
    projections are unaffected.
    """
    invoice_rows = (
        db.query(Invoice.invoice_date, Invoice.direction, Invoice.amount_net, Invoice.amount_total)
        .filter(
            Invoice.invoice_date >= date(year, 1, 1),
            Invoice.invoice_date <= date(year, 12, 31),
        )
        .all()
    )

    monthly_rev_exp: dict[str, dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "gross_revenue": 0.0, "expenses": 0.0}
    )
    for inv_date, direction, amount_net, amount_total in invoice_rows:
        amt = float(amount_net or 0.0)
        month_key = inv_date.strftime("%Y-%m") if inv_date else "unknown"
        if direction == _InvoiceDirection.OUTBOUND:
            monthly_rev_exp[month_key]["revenue"] += amt
            monthly_rev_exp[month_key]["gross_revenue"] += float(amount_total or 0.0)
        elif direction == _InvoiceDirection.INBOUND:
            monthly_rev_exp[month_key]["expenses"] += amt

    vat_rows = (
        db.query(Invoice.invoice_date, Invoice.direction, InvoiceVatSummary.vat_rate_vat_amount)
        .join(Invoice, InvoiceVatSummary.invoice_id == Invoice.id)
        .filter(
            Invoice.invoice_date >= date(year, 1, 1),
            Invoice.invoice_date <= date(year, 12, 31),
        )
        .all()
    )

    monthly_vat: dict[str, float] = defaultdict(float)
    for inv_date, direction, vat_amount in vat_rows:
        amt = float(vat_amount or 0.0)
        month_key = inv_date.strftime("%Y-%m") if inv_date else "unknown"
        if direction == _InvoiceDirection.OUTBOUND:
            monthly_vat[month_key] += amt
        elif direction == _InvoiceDirection.INBOUND:
            monthly_vat[month_key] -= amt

    today_date = today()
    is_current_year = year == today_date.year
    real_month_count = today_date.month if is_current_year else 12

    overrides = get_estimate_overrides(db, year)

    monthly: list[TaxEstimateMonthRow] = []
    for m in range(1, real_month_count + 1):
        month_key = f"{year:04d}-{m:02d}"
        override_gross = overrides.get(m)
        if override_gross is not None:
            net_revenue = override_gross / (1 + STANDARD_VAT_RATE)
            row = _tax_row(
                month_key,
                False,
                net_revenue,
                override_gross,
                0.0,
                override_gross - net_revenue,
                tao_rate,
                hipa_rate,
                szja_rate,
                szocho_rate,
            )
            row.is_override = True
        else:
            rev_exp = monthly_rev_exp.get(
                month_key, {"revenue": 0.0, "gross_revenue": 0.0, "expenses": 0.0}
            )
            row = _tax_row(
                month_key,
                False,
                rev_exp["revenue"],
                rev_exp["gross_revenue"],
                rev_exp["expenses"],
                monthly_vat.get(month_key, 0.0),
                tao_rate,
                hipa_rate,
                szja_rate,
                szocho_rate,
            )
        monthly.append(row)

    if is_current_year and real_month_count < 12:
        active = [row for row in monthly if not row.is_override and (row.revenue or row.expenses)]
        if active:
            avg_revenue = sum(row.revenue for row in active) / len(active)
            avg_gross_revenue = sum(row.gross_revenue for row in active) / len(active)
            avg_expenses = sum(row.expenses for row in active) / len(active)
            avg_vat_payable = sum(row.vat_payable for row in active) / len(active)
        else:
            avg_revenue = avg_gross_revenue = avg_expenses = avg_vat_payable = 0.0

        for m in range(real_month_count + 1, 13):
            month_key = f"{year:04d}-{m:02d}"
            override_gross = overrides.get(m)
            if override_gross is not None:
                net_revenue = override_gross / (1 + STANDARD_VAT_RATE)
                row = _tax_row(
                    month_key,
                    True,
                    net_revenue,
                    override_gross,
                    0.0,
                    override_gross - net_revenue,
                    tao_rate,
                    hipa_rate,
                    szja_rate,
                    szocho_rate,
                )
                row.is_override = True
            else:
                row = _tax_row(
                    month_key,
                    True,
                    avg_revenue,
                    avg_gross_revenue,
                    avg_expenses,
                    avg_vat_payable,
                    tao_rate,
                    hipa_rate,
                    szja_rate,
                    szocho_rate,
                )
            monthly.append(row)

    totals = TaxEstimateMonthRow(
        month="Összesen",
        is_projected=False,
        revenue=sum(row.revenue for row in monthly),
        gross_revenue=sum(row.gross_revenue for row in monthly),
        expenses=sum(row.expenses for row in monthly),
        vat_payable=sum(row.vat_payable for row in monthly),
        tao_tax=sum(row.tao_tax for row in monthly),
        hipa_tax=sum(row.hipa_tax for row in monthly),
        szja_tax=sum(row.szja_tax for row in monthly),
        szocho_tax=sum(row.szocho_tax for row in monthly),
        total=sum(row.total for row in monthly),
    )

    return TaxEstimateReport(
        year=year,
        tao_rate=tao_rate,
        hipa_rate=hipa_rate,
        szja_rate=szja_rate,
        szocho_rate=szocho_rate,
        monthly=monthly,
        totals=totals,
    )
