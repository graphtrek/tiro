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

    def _put(self, path: str, json: dict | None = None) -> dict | None:
        try:
            resp = self.session.put(
                f"{self.base_url}{path}",
                json=json,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("invoice-core PUT %s failed: %s", path, exc)
            return None

    def _delete(self, path: str) -> dict | None:
        try:
            resp = self.session.delete(f"{self.base_url}{path}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("invoice-core DELETE %s failed: %s", path, exc)
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

    def patch_invoice(self, invoice_id: int, **kwargs) -> dict | None:
        try:
            resp = self.session.patch(
                f"{self.base_url}/api/v1/invoices/{invoice_id}",
                json=kwargs,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("invoice-core PATCH /api/v1/invoices/%s failed: %s", invoice_id, exc)
            return None

    # ── Invoice files ──────────────────────────────────────────────────────────

    def get_invoice_files(self, linked: str | None = None, filename: str | None = None) -> list[dict]:
        params = {k: v for k, v in {"linked": linked, "filename": filename}.items() if v is not None}
        return self._get("/api/v1/invoice-files", params or None)

    def get_invoice_file_pdf(self, file_id: int) -> requests.Response:
        resp = self.session.get(
            f"{self.base_url}/api/v1/invoice-files/{file_id}/pdf",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp

    # ── Manual link / unlink ───────────────────────────────────────────────────

    def link_invoice_to_file(self, invoice_id: int, file_id: int) -> dict | None:
        return self._put(f"/api/v1/invoices/{invoice_id}/invoice-file", {"invoice_file_id": file_id})

    def unlink_invoice_from_file(self, invoice_id: int) -> dict | None:
        return self._delete(f"/api/v1/invoices/{invoice_id}/invoice-file")

    def link_transaction_to_file(self, txn_id: int, file_id: int) -> dict | None:
        return self._put(f"/api/v1/transactions/{txn_id}/invoice-file", {"invoice_file_id": file_id})

    def unlink_transaction_from_file(self, txn_id: int) -> dict | None:
        return self._delete(f"/api/v1/transactions/{txn_id}/invoice-file")

    def link_invoice_transaction(self, invoice_id: int, txn_id: int) -> dict | None:
        return self._put(f"/api/v1/invoices/{invoice_id}/transactions/{txn_id}")

    def unlink_invoice_transaction(self, invoice_id: int, txn_id: int) -> dict | None:
        return self._delete(f"/api/v1/invoices/{invoice_id}/transactions/{txn_id}")

    # ── Invoice file delete ────────────────────────────────────────────────────

    def delete_invoice_file(self, file_id: int) -> dict | None:
        return self.patch_invoice_file(file_id, is_deleted=True)

    def patch_invoice_file(self, file_id: int, **kwargs) -> dict | None:
        try:
            resp = self.session.patch(
                f"{self.base_url}/api/v1/invoice-files/{file_id}",
                json=kwargs,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("invoice-core PATCH /api/v1/invoice-files/%s failed: %s", file_id, exc)
            return None

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

    # ── Users ──────────────────────────────────────────────────────────────────

    def get_users(self) -> list[dict]:
        return self._get("/api/v1/users")

    # ── Activity types ─────────────────────────────────────────────────────────

    def get_activity_types(self) -> list[dict]:
        return self._get("/api/v1/activity-types")

    def create_activity_type(self, name: str) -> dict:
        return self._write_json(
            "POST", "/api/v1/activity-types", {"name": name}, "Nem sikerült menteni a tevékenység típust"
        )

    def update_activity_type(self, activity_type_id: int, name: str, is_active: bool) -> dict:
        return self._write_json(
            "PUT",
            f"/api/v1/activity-types/{activity_type_id}",
            {"name": name, "is_active": is_active},
            "Nem sikerült menteni a tevékenység típust",
        )

    def delete_activity_type(self, activity_type_id: int) -> dict:
        return self._write_json(
            "DELETE",
            f"/api/v1/activity-types/{activity_type_id}",
            {},
            "Nem sikerült menteni a tevékenység típust",
        )

    # ── Projects ───────────────────────────────────────────────────────────────

    def get_projects(self) -> list[dict]:
        return self._get("/api/v1/projects")

    def create_project(
        self, customer_id: int, short_name: str, owner_id: int, permitted_user_ids: list[int]
    ) -> dict:
        return self._write_json(
            "POST",
            "/api/v1/projects",
            {
                "customer_id": customer_id,
                "short_name": short_name,
                "owner_id": owner_id,
                "permitted_user_ids": permitted_user_ids,
            },
            "Nem sikerült menteni a projektet",
        )

    def update_project(
        self,
        project_id: int,
        customer_id: int,
        short_name: str,
        owner_id: int,
        is_active: bool,
        permitted_user_ids: list[int],
    ) -> dict:
        return self._write_json(
            "PUT",
            f"/api/v1/projects/{project_id}",
            {
                "customer_id": customer_id,
                "short_name": short_name,
                "owner_id": owner_id,
                "is_active": is_active,
                "permitted_user_ids": permitted_user_ids,
            },
            "Nem sikerült menteni a projektet",
        )

    def delete_project(self, project_id: int) -> dict:
        return self._write_json(
            "DELETE", f"/api/v1/projects/{project_id}", {}, "Nem sikerült törölni a projektet"
        )

    def _write_json(self, method: str, path: str, json: dict, error_message: str) -> dict:
        """POST/PUT/DELETE that surfaces a friendly `error` key instead of swallowing failures.

        Unlike the other client methods, callers need to tell the user *why* a save
        failed (e.g. duplicate name/code -> 409), not just that it failed.
        """
        try:
            resp = self.session.request(method, f"{self.base_url}{path}", json=json, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            detail = None
            if exc.response is not None:
                try:
                    detail = exc.response.json().get("detail")
                except ValueError:
                    pass
            logger.warning("invoice-core %s %s failed: %s", method, path, exc)
            return {"error": detail or error_message}
        except requests.RequestException as exc:
            logger.warning("invoice-core %s %s failed: %s", method, path, exc)
            return {"error": "A szolgáltatás jelenleg nem érhető el"}

    # ── Reports ────────────────────────────────────────────────────────────────

    def get_dividend_report(self, year: int | None = None, kiva_rate: float = 0.10, hipa_rate: float = 0.02) -> dict:
        params = {k: v for k, v in {"year": year, "kiva_rate": kiva_rate, "hipa_rate": hipa_rate}.items() if v is not None}
        return self._get_one("/api/v1/reports/dividend", params) or {}

    def get_tax_report(self, year: int | None = None) -> dict:
        params = {"year": year} if year is not None else None
        return self._get_one("/api/v1/reports/tax", params) or {}
