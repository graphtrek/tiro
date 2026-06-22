"""HTTP client for invoice-core REST API (:8004)."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from vision.config import Settings, get_settings, make_http_session

logger = logging.getLogger(__name__)


class InvoiceCoreClient:
    """Client for invoice-core endpoints."""

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
            logger.warning("invoice-core GET %s failed: %s", path, exc)
            return []

    def _get_one(self, path: str, params: dict | None = None) -> dict | None:
        try:
            resp = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("invoice-core GET %s failed: %s", path, exc)
            return None

    def _post(self, path: str, json: dict | None = None) -> dict | None:
        try:
            resp = self.session.post(
                f"{self.base_url}{path}",
                json=json,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("invoice-core POST %s failed: %s", path, exc)
            return None

    # ── Dashboard ──────────────────────────────────────────────────────────────

    def get_dashboard(self) -> dict:
        return self._get_one("/api/v1/dashboard") or {}

    def get_invoice_count(self) -> int:
        result = self._get_one("/api/v1/invoices/count")
        return result.get("count", 0) if result else 0

    # ── Invoices ───────────────────────────────────────────────────────────────

    def get_invoices(
        self,
        date_from=None,
        date_to=None,
        status=None,
        direction=None,
        has_pdf=None,
        supplier_name=None,
    ) -> list[dict]:
        params = {k: v for k, v in {
            "date_from": date_from,
            "date_to": date_to,
            "status": status,
            "direction": direction,
            "has_pdf": has_pdf,
            "supplier_name": supplier_name,
        }.items() if v is not None}
        return self._get("/api/v1/invoices", params or None)

    def get_invoice(self, invoice_id: int) -> dict | None:
        return self._get_one(f"/api/v1/invoices/{invoice_id}")

    # ── Invoice files ──────────────────────────────────────────────────────────

    def get_invoice_files(self, linked: str | None = None) -> list[dict]:
        params = {"linked": linked} if linked is not None else None
        return self._get("/api/v1/invoice-files", params)

    # ── Partners ───────────────────────────────────────────────────────────────

    def get_suppliers(self) -> list[dict]:
        return self._get("/api/v1/partners/suppliers")

    def get_supplier_summary(self) -> dict:
        return self._get_one("/api/v1/partners/suppliers/summary") or {}

    def get_supplier(self, supplier_id: int) -> dict | None:
        return self._get_one(f"/api/v1/partners/suppliers/{supplier_id}")

    def get_customers(self) -> list[dict]:
        return self._get("/api/v1/partners/customers")

    def get_customer(self, customer_id: int) -> dict | None:
        return self._get_one(f"/api/v1/partners/customers/{customer_id}")

    # ── Transactions ───────────────────────────────────────────────────────────

    def get_transactions(
        self,
        date_from=None,
        date_to=None,
        linked=None,
        partner_name=None,
        amount_min=None,
        amount_max=None,
    ) -> list[dict]:
        params = {k: v for k, v in {
            "date_from": date_from,
            "date_to": date_to,
            "linked": linked,
            "partner_name": partner_name,
            "amount_min": amount_min,
            "amount_max": amount_max,
        }.items() if v is not None}
        return self._get("/api/v1/transactions", params or None)

    def get_transaction(self, transaction_id: int) -> dict | None:
        return self._get_one(f"/api/v1/transactions/{transaction_id}")

    def get_bank_balances(self) -> list[dict]:
        return self._get("/api/v1/transactions/balances")

    # ── Sync ───────────────────────────────────────────────────────────────────

    def get_sync_logs(self, limit: int = 10) -> list[dict]:
        return self._get("/api/v1/sync/logs", {"limit": limit})

    def trigger_sync(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        sync_mode: str = "full",
    ) -> dict:
        return self._post("/api/v1/sync", {
            "start_date": date_from,
            "end_date": date_to,
            "sync_mode": sync_mode,
        }) or {}

    # ── Reports ────────────────────────────────────────────────────────────────

    def get_dividend_report(self, year: int | None = None, kiva_rate: float = 0.10) -> dict:
        params = {k: v for k, v in {"year": year, "kiva_rate": kiva_rate}.items() if v is not None}
        return self._get_one("/api/v1/reports/dividend", params) or {}

    def get_tax_report(self, year: int | None = None) -> dict:
        params = {"year": year} if year is not None else None
        return self._get_one("/api/v1/reports/tax", params) or {}
