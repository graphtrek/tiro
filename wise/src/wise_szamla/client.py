"""Wise API HTTP kliens."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings, get_settings
from .models import WiseStatement

logger = logging.getLogger(__name__)


class WiseApiError(RuntimeError):
    """Wise API hívás sikertelen."""


class WiseClient:
    """Wise REST API kliens.

    Támogatja a live és sandbox környezeteket, automatikus újrapróbálással.
    """

    LIVE_URL = "https://api.wise.com"
    SANDBOX_URL = "https://api.sandbox.transferwise.tech"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = (
            self.SANDBOX_URL if self.settings.wise_sandbox else self.LIVE_URL
        )
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {self.settings.wise_api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        retry = Retry(
            total=self.settings.max_retries,
            backoff_factor=self.settings.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        return session

    # ── Publikus metódusok ────────────────────────────────────────────────────

    def get_profiles(self) -> List[Dict[str, Any]]:
        """Visszaadja a hitelesített felhasználó profillistáját."""
        return self._get("/v2/profiles").json()

    def get_statement(
        self,
        start_date: str,
        end_date: str,
        currency: Optional[str] = None,
    ) -> WiseStatement:
        """Letölti a megadott pénznemű bankszámlakivonatot.

        Args:
            start_date: Kezdő dátum (YYYY-MM-DD)
            end_date:   Záró dátum (YYYY-MM-DD)
            currency:   Pénznem (pl. EUR); default: WISE_ACCOUNT_CURRENCY

        Returns:
            Parszolt :class:`WiseStatement` objektum.
        """
        currency = currency or self.settings.wise_account_currency
        profile_id = self.settings.wise_profile_id
        params = {
            "intervalStart": f"{start_date}T00:00:00.000Z",
            "intervalEnd": f"{end_date}T23:59:59.999Z",
        }
        t0 = time.monotonic()
        resp = self._get(
            f"/v1/profiles/{profile_id}/statements/{currency}",
            params=params,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        statement = WiseStatement.model_validate(resp.json())
        logger.info(
            "Wise statement %s..%s (%s): %d tranzakció %.0fms alatt",
            start_date,
            end_date,
            currency,
            len(statement.transactions),
            elapsed_ms,
        )
        return statement

    # ── Belső segéd ──────────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(
                url, params=params, timeout=self.settings.request_timeout
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            body = exc.response.text[:300] if exc.response is not None else ""
            status = exc.response.status_code if exc.response is not None else "?"
            raise WiseApiError(
                f"Wise API HTTP {status} {path}: {body}"
            ) from exc
        except requests.RequestException as exc:
            raise WiseApiError(f"Wise API kapcsolati hiba {path}: {exc}") from exc
        return resp
