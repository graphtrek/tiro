"""HTTP client for the SrcProfit external service (IBKR portfolio)."""

from __future__ import annotations

import logging
from typing import Optional

from vision.config import Settings, get_settings, make_http_session

logger = logging.getLogger(__name__)


class SrcProfitClient:
    """Defensive client for SrcProfit — returns None on any error."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.srcprofit_url.rstrip("/")
        self.timeout = self.settings.request_timeout
        self.session = make_http_session()
        self._auth = (self.settings.srcprofit_user, self.settings.srcprofit_password)

    def get_summary(self) -> dict | None:
        try:
            resp = self.session.get(
                f"{self.base_url}/api/summary",
                timeout=self.timeout,
                auth=self._auth,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.warning("SrcProfit /api/summary unavailable", exc_info=True)
            return None

    def get_portfolio(self) -> dict | None:
        try:
            resp = self.session.get(
                f"{self.base_url}/api/portfolio",
                timeout=self.timeout,
                auth=self._auth,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.warning("SrcProfit /api/portfolio unavailable", exc_info=True)
            return None
