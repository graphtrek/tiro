"""Wise API lekérési logika."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from .client import WiseClient
from .config import Settings, get_settings
from .models import (
    SyncRequest,
    SyncResponse,
    TransactionSummary,
    WiseTransactionDetails,
)

logger = logging.getLogger(__name__)


def _default_dates(start: Optional[str], end: Optional[str]) -> tuple[str, str]:
    end_obj = date.fromisoformat(end) if end else date.today()
    start_obj = date.fromisoformat(start) if start else end_obj - timedelta(days=30)
    return start_obj.isoformat(), end_obj.isoformat()


def _partner_name(details: WiseTransactionDetails) -> Optional[str]:
    if details.senderName:
        return details.senderName
    if details.recipientName:
        return details.recipientName
    if details.merchant and details.merchant.name:
        return details.merchant.name
    return None


def _partner_account(details: WiseTransactionDetails) -> Optional[str]:
    if details.senderAccount:
        return details.senderAccount
    if details.recipientAccount:
        return details.recipientAccount
    return None


def _to_summary(txn) -> TransactionSummary:
    return TransactionSummary(
        wise_transaction_id=txn.referenceNumber,
        type=txn.type,
        transaction_date=txn.date,
        amount=txn.amount.value,
        currency=txn.amount.currency,
        description=txn.details.description,
        counterparty_name=_partner_name(txn.details),
        counterparty_account=_partner_account(txn.details),
        payment_reference=txn.details.paymentReference,
    )


def run_sync(
    request: SyncRequest, settings: Optional[Settings] = None
) -> SyncResponse:
    """Wise tranzakciók lekérése és visszaadása strukturált formában."""
    settings = settings or get_settings()
    start, end = _default_dates(request.start_date, request.end_date)
    currency = request.currency or settings.wise_account_currency

    logger.info("Wise lekérés: %s..%s (%s)", start, end, currency)

    client = WiseClient(settings)
    statement = client.get_statement(start, end, currency)
    summaries = [_to_summary(txn) for txn in statement.transactions]

    logger.info("Wise lekérés kész: %d tranzakció", len(summaries))
    return SyncResponse(
        start_date=start,
        end_date=end,
        currency=currency,
        fetched=len(summaries),
        transactions=summaries,
    )
