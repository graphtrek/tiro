"""Tests for the Erste and Wise CSV parsers.

Fixtures live in tests/fixtures/: erste_sample.csv (UTF-16, mirrors the real
Erste export) and wise_sample.csv (UTF-8, mirrors the real Wise export).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from bank.parsers.erste import (
    _parse_amount as erste_parse_amount,
    _parse_balance as erste_parse_balance,
    parse_erste_csv,
)
from bank.parsers.wise import (
    _parse_amount as wise_parse_amount,
    parse_wise_csv,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestErsteParseAmount:
    def test_valid(self):
        assert erste_parse_amount("50\xa0000") == Decimal("50000")

    def test_negative(self):
        assert erste_parse_amount("-12\xa0345") == Decimal("-12345")

    def test_malformed_raises(self):
        with pytest.raises(ValueError):
            erste_parse_amount("N/A")


class TestErsteParseBalance:
    def test_valid(self):
        assert erste_parse_balance("3\xa0343\xa0587 HUF") == Decimal("3343587")

    def test_empty_returns_none(self):
        assert erste_parse_balance("") is None
        assert erste_parse_balance("   ") is None

    def test_malformed_returns_none(self):
        assert erste_parse_balance("not a number HUF") is None


class TestWiseParseAmount:
    def test_valid(self):
        assert wise_parse_amount("100.50") == Decimal("100.50")

    def test_empty_returns_none(self):
        assert wise_parse_amount("") is None

    def test_malformed_returns_none(self):
        assert wise_parse_amount("abc") is None


class TestParseErsteCsv:
    def test_row_count_skips_malformed_amount(self):
        txns = parse_erste_csv(FIXTURES_DIR / "erste_sample.csv")
        # 5 rows in the fixture, 1 has a malformed amount and is skipped.
        assert len(txns) == 4

    def test_amounts_and_currency(self):
        txns = parse_erste_csv(FIXTURES_DIR / "erste_sample.csv")
        by_id = {t.transaction_id: t for t in txns if t.transaction_id.startswith("TXN-")}
        assert by_id["TXN-001"].amount == Decimal("50000")
        assert by_id["TXN-001"].currency == "HUF"
        assert by_id["TXN-001"].balance == Decimal("3343587")

    def test_negative_amount_is_debit_and_stored_absolute(self):
        txns = parse_erste_csv(FIXTURES_DIR / "erste_sample.csv")
        txn = next(t for t in txns if t.transaction_id == "TXN-002")
        assert txn.direction == "DEBIT"
        assert txn.amount == Decimal("12345")  # stored as absolute value

    def test_missing_txn_id_gets_distinct_synthetic_ids(self):
        txns = parse_erste_csv(FIXTURES_DIR / "erste_sample.csv")
        synthetic = [t for t in txns if t.transaction_id.startswith("ERSTE-")]
        assert len(synthetic) == 2
        ids = {t.transaction_id for t in synthetic}
        assert len(ids) == 2  # the occurrence counter must make them distinct

    def test_malformed_amount_row_not_included(self):
        txns = parse_erste_csv(FIXTURES_DIR / "erste_sample.csv")
        assert all(t.transaction_id != "TXN-004" for t in txns)


class TestParseWiseCsv:
    def test_row_count_drops_missing_id_and_malformed_amount(self):
        txns = parse_wise_csv(FIXTURES_DIR / "wise_sample.csv")
        # 3 rows in the fixture: one has no TransferWise ID (dropped), one has
        # a malformed Amount (dropped) -- only the normal row survives.
        assert len(txns) == 1

    def test_no_id_row_absent_not_given_fallback_id(self):
        txns = parse_wise_csv(FIXTURES_DIR / "wise_sample.csv")
        # Unlike Erste, Wise never synthesizes an ID -- confirm no such row exists.
        assert all(t.transaction_id != "" for t in txns)
        assert not any(t.description == "Card purchase" for t in txns)

    def test_amount_and_direction(self):
        txns = parse_wise_csv(FIXTURES_DIR / "wise_sample.csv")
        txn = txns[0]
        assert txn.transaction_id == "WISE-001"
        assert txn.amount == Decimal("100.50")
        assert txn.currency == "EUR"
        assert txn.direction == "CREDIT"
