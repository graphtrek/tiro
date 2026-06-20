"""Internal dataclasses for the Vision dashboard service layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InvoiceKPI:
    total: int
    unpaid_count: int
    unpaid_amount: float
    linked_pdf_pct: float  # 0.0–100.0


@dataclass
class CashFlowMonth:
    month: str    # "2026-05"
    income: float
    expense: float  # abs value of negative transactions


@dataclass
class SupplierBar:
    name: str
    total_amount: float


@dataclass
class DashboardData:
    invoice_kpi: InvoiceKPI
    cashflow_months: list[CashFlowMonth]
    invoice_status_counts: dict[str, int]  # {"PAID": N, "UNPAID": N, "PARTIAL": N}
    top_suppliers: list[SupplierBar]
    srcprofit_total: float | None          # None if SrcProfit unavailable
    srcprofit_currency: str
    srcprofit_positions: list[dict]
    wise_30d_income: float
    wise_30d_expense: float
    bank_balance: float | None          # sum of latest balance per bank (WISE + ERSTE)
    bank_balance_currency: str
    latest_invoice_date: str | None
    latest_transaction_date: str | None
    latest_data_date: str | None
    invoice_core_url: str
    srcprofit_url: str
