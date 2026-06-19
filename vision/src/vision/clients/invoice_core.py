"""HTTP client for invoice-core REST API (:8004)."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from vision.config import Settings, get_settings, make_http_session

logger = logging.getLogger(__name__)


class InvoiceCoreClient:
    """Read-only client for invoice-core endpoints consumed by the dashboard."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.invoice_core_url.rstrip("/")
        self.timeout = self.settings.request_timeout
        self.session = make_http_session()

    def _get(self, path: str, params: dict | None = None) -> list[dict]:
        try:
            resp = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("invoice-core %s failed: %s", path, exc)
            return []

    def get_invoices(self) -> list[dict]:
        return self._get("/api/v1/invoices")

    def get_transactions(self) -> list[dict]:
        return self._get("/api/v1/transactions")

    def get_suppliers(self) -> list[dict]:
        return self._get("/api/v1/partners/suppliers")
