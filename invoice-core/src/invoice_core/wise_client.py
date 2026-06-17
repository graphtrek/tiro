"""HTTP client for the wise service (:8003)."""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from .config import Settings, get_settings, make_http_session

logger = logging.getLogger(__name__)


class WiseClientError(RuntimeError):
    """Raised when the wise service cannot fulfil a request."""


class WiseClient:
    """Client for the wise balance-statements endpoint.

    GET /balance-statements returns either:
    - A StatementImport dict (has 'transactions' key) when a file is auto-selected, or
    - A list of StatementFile dicts when no file is auto-selected.

    If a list is returned, the most recent file (by to_date) is fetched via
    GET /balance-statements/{filename}.

    TransactionSummary fields consumed by service.py:
        wise_transaction_id, type, transaction_date, amount, currency,
        description, counterparty_name, counterparty_account, payment_reference
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.wise_url.rstrip("/")
        self.session = make_http_session()

    def get_transactions(self) -> list[dict]:
        """Fetch the most recent statement's transactions."""
        t0 = time.monotonic()
        try:
            resp = self.session.get(
                f"{self.base_url}/balance-statements",
                timeout=self.settings.sync_timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise WiseClientError(
                f"Failed to reach wise at {self.base_url}: {exc}"
            ) from exc

        data = resp.json()

        if isinstance(data, list):
            # List[StatementFile] — pick the file with the most recent to_date
            if not data:
                logger.warning("wise /balance-statements returned empty file list")
                return []
            latest = max(data, key=lambda f: f.get("to_date", ""))
            filename = latest["filename"]
            logger.info("wise returned %d file(s); fetching most recent: %s", len(data), filename)
            try:
                resp2 = self.session.get(
                    f"{self.base_url}/balance-statements/{filename}",
                    timeout=self.settings.sync_timeout,
                )
                resp2.raise_for_status()
            except requests.RequestException as exc:
                raise WiseClientError(
                    f"Failed to fetch statement {filename}: {exc}"
                ) from exc
            data = resp2.json()

        transactions = data.get("transactions", [])
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "GET %s/balance-statements → %d transaction(s) in %.0fms",
            self.base_url, len(transactions), elapsed_ms,
        )
        return transactions
