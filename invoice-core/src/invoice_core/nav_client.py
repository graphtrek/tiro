"""HTTP client for the nav-invoice service (:8002)."""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


class NavClientError(RuntimeError):
    """Raised when nav-invoice cannot fulfil a request."""


class NavClient:
    """Thin client over nav-invoice's GET /invoices endpoint.

    Returns raw dicts (InvoiceDigest fields) — no cross-package Pydantic import.
    Fields consumed by service.py:
        invoice_number, invoice_issue_date, supplier_tax_number, supplier_name,
        customer_tax_number, customer_name, invoice_net_amount, invoice_vat_amount, currency
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.nav_invoice_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

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
                f"Failed to reach nav-invoice at {self.base_url}: {exc}"
            ) from exc
        data = resp.json()
        for item in data:
            item["direction"] = direction
        return data

    def get_invoices(self, start_date: str, end_date: str) -> list[dict]:
        """Fetch both INBOUND and OUTBOUND invoices and return the combined list."""
        t0 = time.monotonic()
        outbound = self._fetch(start_date, end_date, "OUTBOUND")
        inbound = self._fetch(start_date, end_date, "INBOUND")
        combined = outbound + inbound
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "GET %s/invoices → %d outbound + %d inbound = %d invoice(s) in %.0fms",
            self.base_url, len(outbound), len(inbound), len(combined), elapsed_ms,
        )
        return combined
