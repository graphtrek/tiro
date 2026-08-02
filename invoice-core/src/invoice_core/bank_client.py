"""HTTP client for the bank service (:8005)."""

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


class BankClientError(RuntimeError):
    """Raised when the bank service cannot fulfil a request."""


class BankClient:
    """Client for the bank /balance-statement/all endpoint.

    GET /balance-statement/all returns a ConsolidatedStatement with:
        transactions: list[BankTransaction]

    BankTransaction fields consumed by service.py:
        bank, transaction_id, date, datetime, amount, currency, direction,
        description, payment_reference, counterparty_name, counterparty_account,
        counterparty_iban, transaction_type, category, balance, fees,
        counterparty_address, sender_address, counterparty_bank_code,
        exchange_rate, exchange_to_currency, card_last_four, note
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.bank_url.rstrip("/")
        self.session = make_http_session()

    def get_transactions(self) -> list[dict]:
        """Fetch consolidated bank transactions (Erste + Wise CSV)."""
        t0 = time.monotonic()
        try:
            resp = self.session.get(
                f"{self.base_url}/balance-statement/all",
                timeout=self.settings.sync_timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise BankClientError(
                f"Failed to reach bank service at {self.base_url}: "
                f"{exc}{token_hint_for_error(exc)}{error_detail_from_response(exc)}"
            ) from exc

        data = resp.json()
        transactions = data.get("transactions", [])
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "GET %s/balance-statement/all → %d transaction(s) in %.0fms",
            self.base_url,
            len(transactions),
            elapsed_ms,
        )
        return transactions
