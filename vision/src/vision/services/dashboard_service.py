"""Aggregates data from invoice-core and SrcProfit into dashboard KPIs."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
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
        amount = abs(tx.get("amount") or 0.0)
        direction = tx.get("direction") or ""
        if direction == "CREDIT":
            buckets[month]["income"] += amount
        elif direction == "DEBIT":
            buckets[month]["expense"] += amount
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
        if "GRAPHTREK" in name.upper():
            continue
        totals[name] = totals.get(name, 0.0) + (inv.get("amount_total") or 0.0)
    sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [SupplierBar(name=n, total_amount=round(v, 2)) for n, v in sorted_items]


def _build_bank_credit_total(transactions: list[dict]) -> float:
    return round(sum(abs(tx.get("amount") or 0.0) for tx in transactions if tx.get("direction") == "CREDIT"), 2)


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


def _build_bank_debit_total(transactions: list[dict]) -> float:
    return round(sum(abs(tx.get("amount") or 0.0) for tx in transactions if tx.get("direction") == "DEBIT"), 2)


def _build_bank_balance(transactions: list[dict]) -> tuple[float | None, str]:
    """Sum the latest balance record per bank (WISE + ERSTE).

    Returns (total_balance, currency). Returns (None, '') if no balance data.
    """
    by_bank: dict[str, dict] = {}
    for tx in transactions:
        balance = tx.get("balance")
        if balance is None:
            continue
        bank = tx.get("bank") or ""
        raw_date = tx.get("transaction_date") or ""
        if bank not in by_bank or str(raw_date) > str(by_bank[bank]["date"]):
            by_bank[bank] = {"balance": balance, "date": raw_date, "currency": tx.get("currency") or ""}
    if not by_bank:
        return None, ""
    total = round(sum(v["balance"] for v in by_bank.values()), 2)
    currency = next(iter(by_bank.values()))["currency"]
    return total, currency


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

    bank_balance, bank_balance_currency = _build_bank_balance(transactions)

    return DashboardData(
        invoice_kpi=_build_invoice_kpi(invoices),
        cashflow_months=_build_cashflow(transactions),
        invoice_status_counts=_build_status_counts(invoices),
        top_suppliers=_build_top_suppliers(invoices, suppliers),
        srcprofit_total=srcprofit_total,
        srcprofit_currency=srcprofit_currency,
        srcprofit_positions=srcprofit_positions,
        wise_30d_income=_build_bank_credit_total(transactions),
        wise_30d_expense=_build_bank_debit_total(transactions),
        bank_balance=bank_balance,
        bank_balance_currency=bank_balance_currency,
        latest_invoice_date=_build_latest_invoice_date(invoices),
        latest_transaction_date=_build_latest_transaction_date(transactions),
        latest_data_date=_build_latest_data_date(invoices, transactions),
        invoice_core_url=cfg.invoice_core_url,
        srcprofit_url=cfg.srcprofit_url,
    )
