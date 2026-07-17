"""HTTP kliens az invoice-core /api/v1/users végpontjához (login rekord mentése)."""

from __future__ import annotations

import logging

import httpx

from auth_service.config import Settings, get_settings
from auth_service.models import UserInfo

logger = logging.getLogger(__name__)


class InvoiceCoreClientError(RuntimeError):
    """Az invoice-core nem érhető el, vagy a kérés sikertelen volt."""


class InvoiceCoreClient:
    """A login rekordot invoice-core-ban tárolja — auth-nak nincs saját DB-je."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.invoice_core_url.rstrip("/")

    def save_user(self, user: UserInfo, access_token: str) -> None:
        """POST /api/v1/users — upsert (provider, sub) alapján."""
        try:
            resp = httpx.post(
                f"{self.base_url}/api/v1/users",
                json=user.model_dump(),
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise InvoiceCoreClientError(str(exc)) from exc
