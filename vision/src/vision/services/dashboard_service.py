"""Aggregates data from invoice-core and SrcProfit into dashboard KPIs."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from vision.clients.invoice_core import InvoiceCoreClient
from vision.clients.srcprofit import SrcProfitClient
from vision.config import Settings, get_settings
from vision.models import CashFlowMonth, DashboardData, InvoiceKPI, SupplierBar

logger = logging.getLogger(__name__)


def _build_invoice_kpi(invoices: list[dict]) -> InvoiceKPI:
    total = len(invoices)
    unpaid = [i for i in invoices if i.get("payment_status") == "UNPAID"]
    unpaid_amount = sum(i.get("amount_total") or 0.0 for i in unpaid)
    linked = sum(1 for i in invoices if i.get("invoice_file_id") is not None)
    linked_pct = (linked / total * 100) if total else 0.0
    return InvoiceKPI(
        total=total,
        unpaid_count=len(unpaid),
        unpaid_amount=unpaid_amount,
        linked_pdf_pct=round(linked_pct, 1),
    )


def _build_cashflow(transactions: list[dict], months: int = 6) -> list[CashFlowMonth]:
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for tx in transactions:
        raw_date = tx.get("transaction_date", "") or ""
        month = str(raw_date)[:7]
        if len(month) != 7:
            continue
        amount = tx.get("amount") or 0.0
        if amount >= 0:
            buckets[month]["income"] += amount
        else:
            buckets[month]["expense"] += abs(amount)
    sorted_months = sorted(buckets.keys())[-months:]
    return [
        CashFlowMonth(month=m, income=buckets[m]["income"], expense=buckets[m]["expense"])
        for m in sorted_months
    ]


def _build_status_counts(invoices: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {"PAID": 0, "UNPAID": 0, "PARTIAL": 0}
    for inv in invoices:
        status = inv.get("payment_status", "UNPAID")
        if status in counts:
            counts[status] += 1
    return counts


def _build_top_suppliers(invoices: list[dict], suppliers: list[dict], top_n: int = 10) -> list[SupplierBar]:
    supplier_map = {s["id"]: s["name"] for s in suppliers}
    totals: dict[str, float] = {}
    for inv in invoices:
        name = supplier_map.get(inv.get("supplier_id"), "Ismeretlen")
        totals[name] = totals.get(name, 0.0) + (inv.get("amount_total") or 0.0)
    sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [SupplierBar(name=n, total_amount=round(v, 2)) for n, v in sorted_items]


def _build_wise_30d_income(transactions: list[dict]) -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    total = 0.0
    for tx in transactions:
        raw_date = tx.get("transaction_date", "") or ""
        try:
            dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        amount = tx.get("amount") or 0.0
        if dt >= cutoff and amount > 0:
            total += amount
    return round(total, 2)


def _build_latest_invoice_date(invoices: list[dict]) -> str | None:
    dates = [str(inv.get("invoice_date", "") or "")[:10] for inv in invoices]
    valid = [d for d in dates if len(d) == 10]
    return max(valid) if valid else None


def _build_latest_transaction_date(transactions: list[dict]) -> str | None:
    dates = [str(tx.get("transaction_date", "") or "")[:10] for tx in transactions]
    valid = [d for d in dates if len(d) == 10]
    return max(valid) if valid else None


def _build_latest_data_date(invoices: list[dict], transactions: list[dict]) -> str | None:
    dates: list[str] = []
    for inv in invoices:
        d = str(inv.get("invoice_date", "") or "")[:10]
        if len(d) == 10:
            dates.append(d)
    for tx in transactions:
        d = str(tx.get("transaction_date", "") or "")[:10]
        if len(d) == 10:
            dates.append(d)
    return max(dates) if dates else None


def _build_wise_30d_expense(transactions: list[dict]) -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    total = 0.0
    for tx in transactions:
        raw_date = tx.get("transaction_date", "") or ""
        try:
            dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        amount = tx.get("amount") or 0.0
        if dt >= cutoff and amount < 0:
            total += abs(amount)
    return round(total, 2)


def get_dashboard_data(settings: Optional[Settings] = None) -> DashboardData:
    cfg = settings or get_settings()
    inv_client = InvoiceCoreClient(cfg)
    src_client = SrcProfitClient(cfg)

    invoices = inv_client.get_invoices()
    transactions = inv_client.get_transactions()
    suppliers = inv_client.get_suppliers()

    src_summary = src_client.get_summary()
    src_portfolio = src_client.get_portfolio()

    srcprofit_total = None
    srcprofit_currency = "USD"
    srcprofit_positions: list[dict] = []

    if src_summary:
        srcprofit_total = src_summary.get("total_value") or src_summary.get("totalValue")
        srcprofit_currency = src_summary.get("currency", "USD")
    if src_portfolio:
        srcprofit_positions = src_portfolio.get("positions", [])

    return DashboardData(
        invoice_kpi=_build_invoice_kpi(invoices),
        cashflow_months=_build_cashflow(transactions),
        invoice_status_counts=_build_status_counts(invoices),
        top_suppliers=_build_top_suppliers(invoices, suppliers),
        srcprofit_total=srcprofit_total,
        srcprofit_currency=srcprofit_currency,
        srcprofit_positions=srcprofit_positions,
        wise_30d_income=_build_wise_30d_income(transactions),
        wise_30d_expense=_build_wise_30d_expense(transactions),
        latest_invoice_date=_build_latest_invoice_date(invoices),
        latest_transaction_date=_build_latest_transaction_date(transactions),
        latest_data_date=_build_latest_data_date(invoices, transactions),
        invoice_core_url=cfg.invoice_core_url,
        srcprofit_url=cfg.srcprofit_url,
    )
