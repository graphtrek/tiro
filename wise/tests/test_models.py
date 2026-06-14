"""Pydantic modellek tesztjei."""

from __future__ import annotations

from decimal import Decimal

from wise_szamla.models import (
    SyncRequest,
    SyncResponse,
    TransactionSummary,
    TransactionType,
    WiseAmount,
    WiseStatement,
    WiseTransaction,
    WiseTransactionDetails,
)
from wise_szamla.sync import _partner_name, _to_summary


class TestWiseAmount:
    def test_decimal_precision(self):
        a = WiseAmount(value=Decimal("1234.56"), currency="EUR")
        assert a.value == Decimal("1234.56")
        assert a.currency == "EUR"


class TestWiseStatement:
    def test_parse_from_json(self, sample_statement_json):
        stmt = WiseStatement.model_validate(sample_statement_json)
        assert len(stmt.transactions) == 2
        assert stmt.endOfStatementBalance.value == Decimal("2950.01")

    def test_empty_transactions(self):
        stmt = WiseStatement()
        assert stmt.transactions == []

    def test_credit_type(self, sample_statement_json):
        stmt = WiseStatement.model_validate(sample_statement_json)
        assert stmt.transactions[0].type == TransactionType.CREDIT

    def test_debit_type(self, sample_statement_json):
        stmt = WiseStatement.model_validate(sample_statement_json)
        assert stmt.transactions[1].type == TransactionType.DEBIT


class TestPartnerName:
    def test_sender_name_preferred(self, credit_transaction):
        name = _partner_name(credit_transaction.details)
        assert name == "ACME Corp"

    def test_merchant_name_fallback(self, debit_transaction):
        name = _partner_name(debit_transaction.details)
        assert name == "Scaleway SAS"

    def test_none_when_no_partner(self):
        details = WiseTransactionDetails(type="FEE", description="Monthly fee")
        assert _partner_name(details) is None


class TestToSummary:
    def test_credit_summary(self, credit_transaction):
        summary = _to_summary(credit_transaction)
        assert summary.wise_transaction_id == "TRANSFER-11111111"
        assert summary.type == TransactionType.CREDIT
        assert summary.amount == Decimal("1500.00")
        assert summary.currency == "EUR"
        assert summary.counterparty_name == "ACME Corp"
        assert summary.payment_reference == "INV-2026-42"

    def test_debit_summary(self, debit_transaction):
        summary = _to_summary(debit_transaction)
        assert summary.type == TransactionType.DEBIT
        assert summary.amount == Decimal("49.99")
        assert summary.counterparty_name == "Scaleway SAS"


class TestSyncRequest:
    def test_defaults(self):
        req = SyncRequest()
        assert req.start_date is None
        assert req.end_date is None
        assert req.currency is None

    def test_with_dates(self):
        req = SyncRequest(start_date="2026-05-01", end_date="2026-05-31", currency="EUR")
        assert req.start_date == "2026-05-01"
        assert req.currency == "EUR"


class TestSyncResponse:
    def test_defaults(self):
        resp = SyncResponse(start_date="2026-05-01", end_date="2026-05-31", currency="EUR")
        assert resp.fetched == 0
        assert resp.transactions == []

    def test_with_transactions(self, credit_transaction):
        summary = _to_summary(credit_transaction)
        resp = SyncResponse(
            start_date="2026-05-01",
            end_date="2026-05-31",
            currency="EUR",
            fetched=1,
            transactions=[summary],
        )
        assert resp.fetched == 1
        assert resp.transactions[0].wise_transaction_id == "TRANSFER-11111111"
