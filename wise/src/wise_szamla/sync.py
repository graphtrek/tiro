"""Szinkronizálási logika: Wise API → szamla-db."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Optional

import requests

from .client import WiseApiError, WiseClient
from .config import Settings, get_settings
from .models import (
    SyncRequest,
    SyncResponse,
    TransactionSummary,
    TransactionType,
    WiseTransactionDetails,
)

logger = logging.getLogger(__name__)


# ── Belső segédek ─────────────────────────────────────────────────────────────


def _default_dates(start: Optional[str], end: Optional[str]) -> tuple[str, str]:
    end_obj = date.fromisoformat(end) if end else date.today()
    start_obj = date.fromisoformat(start) if start else end_obj - timedelta(days=30)
    return start_obj.isoformat(), end_obj.isoformat()


def _partner_name(details: WiseTransactionDetails) -> Optional[str]:
    """Visszaadja a releváns partner nevet a tranzakció részleteiből."""
    if details.senderName:
        return details.senderName
    if details.recipientName:
        return details.recipientName
    if details.merchant and details.merchant.name:
        return details.merchant.name
    return None


def _to_summary(txn) -> TransactionSummary:
    return TransactionSummary(
        reference_number=txn.referenceNumber,
        type=txn.type,
        date=txn.date,
        amount=txn.amount.value,
        currency=txn.amount.currency,
        description=txn.details.description,
        partner_name=_partner_name(txn.details),
        payment_reference=txn.details.paymentReference,
        synced_to_db=False,
    )


# ── szamla-db kliens ──────────────────────────────────────────────────────────


class SzamlaDbClient:
    """Tranzakciókat továbbít a szamla-db orchestrátor felé."""

    def __init__(self, settings: Settings):
        self.base_url = settings.szamla_db_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def push_transaction(self, txn: TransactionSummary) -> bool:
        """Elküldi a tranzakciót a szamla-db-nek.

        Returns:
            True  — sikeresen létrehozva
            False — már létezik (HTTP 409 Conflict → idempotens kihagyás)

        Raises:
            requests.RequestException — egyéb hálózati / szerver hiba
        """
        payload = {
            "source": "wise",
            "external_id": txn.reference_number,
            "transaction_date": txn.date.isoformat(),
            "amount_total": float(txn.amount),
            "currency": txn.currency,
            "description": txn.description,
            "partner_name": txn.partner_name,
            "payment_reference": txn.payment_reference,
            "direction": (
                "INBOUND" if txn.type == TransactionType.CREDIT else "OUTBOUND"
            ),
        }
        resp = self.session.post(
            f"{self.base_url}/api/v1/wise/transactions",
            json=payload,
            timeout=10,
        )
        if resp.status_code == 409:
            return False
        resp.raise_for_status()
        return True


# ── Fő szinkronizáló függvény ─────────────────────────────────────────────────


def run_sync(
    request: SyncRequest, settings: Optional[Settings] = None
) -> SyncResponse:
    """Wise tranzakciók lekérése és továbbítása a szamla-db-nek.

    A szamla-db elérhetetlen esetén a tranzakciók ``synced_to_db=False``
    értékkel kerülnek vissza — az API válasz így is tartalmazza a teljes
    adatot, a push hibák naplózásra kerülnek.
    """
    settings = settings or get_settings()
    start, end = _default_dates(request.start_date, request.end_date)
    currency = request.currency or settings.wise_account_currency
    t0 = time.monotonic()

    logger.info("Wise sync indítás: %s..%s (%s)", start, end, currency)

    client = WiseClient(settings)
    statement = client.get_statement(start, end, currency)
    summaries = [_to_summary(txn) for txn in statement.transactions]

    synced = skipped = errors = 0
    db_client = SzamlaDbClient(settings)

    for txn in summaries:
        try:
            pushed = db_client.push_transaction(txn)
            if pushed:
                txn.synced_to_db = True
                synced += 1
            else:
                skipped += 1
                logger.debug("Kihagyva (már létezik): %s", txn.reference_number)
        except requests.RequestException as exc:
            errors += 1
            logger.warning("szamla-db push hiba (%s): %s", txn.reference_number, exc)

    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(
        "Wise sync kész: %d lekért, %d szinkronizált, %d kihagyott, %d hiba — %.0fms",
        len(summaries),
        synced,
        skipped,
        errors,
        elapsed_ms,
    )
    return SyncResponse(
        start_date=start,
        end_date=end,
        currency=currency,
        fetched=len(summaries),
        synced=synced,
        skipped=skipped,
        errors=errors,
        transactions=summaries,
    )
