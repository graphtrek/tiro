"""HTTP client for the nav-invoice service (:8002)."""

from __future__ import annotations

import logging
import time

import requests

from .config import (
    Settings,
    error_detail_from_response,
    get_settings,
    make_http_session,
    token_hint_for_error,
)

logger = logging.getLogger(__name__)


class NavClientError(RuntimeError):
    """Raised when nav-invoice cannot fulfil a request."""


class NavClient:
    """Thin client over nav-invoice's GET /invoices endpoint.

    Returns raw dicts (InvoiceDigest fields) — no cross-package Pydantic import.
    Fields consumed by service.py from get_invoices():
        invoice_number, invoice_issue_date, supplier_tax_number, supplier_name,
        customer_tax_number, customer_name, invoice_net_amount, invoice_vat_amount,
        currency, invoice_operation, invoice_category, ins_date
    Fields consumed by service.py from get_invoice_detail() (InvoiceDetailData
    plus the invoice_xml sibling key nav-invoice's API adds):
        supplier_address, supplier_bank_account, customer_address,
        customer_bank_account, payment_method, payment_due_date,
        invoice_category, delivery_date, currency_code, exchange_rate,
        invoice_appearance, invoice_net_amount, invoice_vat_amount,
        invoice_gross_amount, lines, vat_summary, invoice_xml
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.nav_invoice_url.rstrip("/")
        self.session = make_http_session()

    def _fetch(self, start_date: str, end_date: str, direction: str) -> list[dict]:
        try:
            resp = self.session.get(
                f"{self.base_url}/invoices",
                params={"from_date": start_date, "to_date": end_date, "direction": direction},
                timeout=self.settings.sync_timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise NavClientError(
                f"Failed to reach nav-invoice at {self.base_url}: "
                f"{exc}{token_hint_for_error(exc)}{error_detail_from_response(exc)}"
            ) from exc
        data = resp.json()
        for item in data:
            item["direction"] = direction
        return data

    def get_invoice_detail(
        self, invoice_number: str, direction: str, supplier_tax_number: str = ""
    ) -> dict | None:
        """GET /invoices/{invoice_number} → enriched dict (address/bank account/payment fields).

        Returns None on any failure (404, network error) so callers can degrade
        gracefully rather than aborting the whole sync.
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/invoices/{invoice_number}",
                params={"direction": direction, "supplier_tax_number": supplier_tax_number},
                timeout=self.settings.sync_timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning(
                "Could not fetch full invoice data for %s: %s%s",
                invoice_number,
                exc,
                error_detail_from_response(exc),
            )
            return None

    def clear_cache(self) -> int:
        """POST /cache/clear → number of cleared entries (0 on error)."""
        try:
            resp = self.session.post(
                f"{self.base_url}/cache/clear",
                timeout=self.settings.sync_timeout,
            )
            resp.raise_for_status()
            cleared = resp.json().get("cleared", 0)
            logger.info("nav-invoice cache cleared: %d entry(s)", cleared)
            return cleared
        except requests.RequestException as exc:
            logger.warning(
                "Could not clear nav-invoice cache: %s%s", exc, error_detail_from_response(exc)
            )
            return 0

    def get_invoices(self, start_date: str, end_date: str) -> list[dict]:
        """Fetch both INBOUND and OUTBOUND invoices, chunking the range into ≤35-day windows.

        NAV's queryInvoiceDigest API rejects ranges longer than 35 days, so wide
        date spans are split automatically and the results are concatenated.
        """
        from datetime import date as _date
        from datetime import timedelta as _timedelta

        chunk_days = 35
        start = _date.fromisoformat(start_date)
        end = _date.fromisoformat(end_date)
        combined: list[dict] = []
        chunk_start = start

        while chunk_start <= end:
            chunk_end = min(chunk_start + _timedelta(days=chunk_days - 1), end)
            t0 = time.monotonic()
            outbound = self._fetch(chunk_start.isoformat(), chunk_end.isoformat(), "OUTBOUND")
            inbound = self._fetch(chunk_start.isoformat(), chunk_end.isoformat(), "INBOUND")
            chunk = outbound + inbound
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "GET %s/invoices [%s → %s] → %d outbound + %d inbound = %d invoice(s) in %.0fms",
                self.base_url,
                chunk_start,
                chunk_end,
                len(outbound),
                len(inbound),
                len(chunk),
                elapsed_ms,
            )
            combined.extend(chunk)
            chunk_start = chunk_end + _timedelta(days=1)

        return combined
