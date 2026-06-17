"""Közös fixtures a wise-szamla tesztekhez."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from wise_invoice.models import (
    TransactionType,
    WiseAmount,
    WiseMerchant,
    WiseTransaction,
    WiseTransactionDetails,
)

# ── Minta Wise API válasz adat ────────────────────────────────────────────────

SAMPLE_STATEMENT_JSON = {
    "accountHolder": {
        "type": "BUSINESS",
        "firstName": "Graphtrek",
        "lastName": "Kft",
        "currency": "EUR",
    },
    "transactions": [
        {
            "type": "CREDIT",
            "date": "2026-05-15T10:30:00.000Z",
            "amount": {"value": 1500.00, "currency": "EUR"},
            "totalFees": {"value": 0.00, "currency": "EUR"},
            "details": {
                "type": "TRANSFER",
                "description": "Átutalás: INV-2026-42",
                "merchant": None,
                "senderName": "ACME Corp",
                "senderAccount": "GB29NWBK60161331926819",
                "paymentReference": "INV-2026-42",
            },
            "runningBalance": {"value": 3000.00, "currency": "EUR"},
            "referenceNumber": "TRANSFER-11111111",
        },
        {
            "type": "DEBIT",
            "date": "2026-05-20T08:00:00.000Z",
            "amount": {"value": 49.99, "currency": "EUR"},
            "totalFees": {"value": 0.20, "currency": "EUR"},
            "details": {
                "type": "CARD",
                "description": "Scaleway SAS",
                "merchant": {"name": "Scaleway SAS", "category": "Cloud Services"},
                "paymentReference": None,
            },
            "runningBalance": {"value": 2950.01, "currency": "EUR"},
            "referenceNumber": "CARD-22222222",
        },
    ],
    "endOfStatementBalance": {"value": 2950.01, "currency": "EUR"},
}


@pytest.fixture
def sample_statement_json() -> dict:
    return SAMPLE_STATEMENT_JSON


@pytest.fixture
def credit_transaction() -> WiseTransaction:
    return WiseTransaction(
        type=TransactionType.CREDIT,
        date=datetime(2026, 5, 15, 10, 30, 0, tzinfo=timezone.utc),
        amount=WiseAmount(value=Decimal("1500.00"), currency="EUR"),
        totalFees=WiseAmount(value=Decimal("0.00"), currency="EUR"),
        details=WiseTransactionDetails(
            type="TRANSFER",
            description="Átutalás: INV-2026-42",
            senderName="ACME Corp",
            paymentReference="INV-2026-42",
        ),
        runningBalance=WiseAmount(value=Decimal("3000.00"), currency="EUR"),
        referenceNumber="TRANSFER-11111111",
    )


@pytest.fixture
def debit_transaction() -> WiseTransaction:
    return WiseTransaction(
        type=TransactionType.DEBIT,
        date=datetime(2026, 5, 20, 8, 0, 0, tzinfo=timezone.utc),
        amount=WiseAmount(value=Decimal("49.99"), currency="EUR"),
        totalFees=WiseAmount(value=Decimal("0.20"), currency="EUR"),
        details=WiseTransactionDetails(
            type="CARD",
            description="Scaleway SAS",
            merchant=WiseMerchant(name="Scaleway SAS", category="Cloud Services"),
        ),
        runningBalance=WiseAmount(value=Decimal("2950.01"), currency="EUR"),
        referenceNumber="CARD-22222222",
    )
