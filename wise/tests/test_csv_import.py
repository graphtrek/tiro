"""CSV-import tesztek (list_statement_files, parse_statement_csv)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from wise_szamla.config import Settings
from wise_szamla.csv_import import (
    StatementCsvError,
    list_statement_files,
    parse_statement_csv,
)
from wise_szamla.models import TransactionType

CSV_HEADER = (
    '"TransferWise ID",Date,"Date Time",Amount,Currency,Description,'
    '"Payment Reference","Running Balance","Exchange From","Exchange To",'
    '"Exchange Rate","Payer Name","Payee Name","Payee Account Number",Merchant,'
    '"Card Last Four Digits","Card Holder Full Name",Attachment,Note,'
    '"Total fees","Exchange To Amount","Transaction Type","Transaction Details Type"'
)
CSV_ROWS = [
    'TRANSFER-2166707551,01-06-2026,"01-06-2026 19:57:37.833",-71440.00,HUF,'
    '"Utalás Őrszem Services Kft. részére",2026-000064,1014383.20,,,,,'
    '"Őrszem Services Kft.","11600006-00000000-94346200",,,,,,320.00,,DEBIT,TRANSFER',
    'CARD-3868107236,01-06-2026,"01-06-2026 19:21:33.766",-5434.98,HUF,'
    '"Kártyahasználat",,1085823.20,HUF,EUR,0.00281,,,,"Online PARIS",3734,'
    '"Imre Tatai",,,30.00,15.19,DEBIT,CARD',
    'TRANSFER-2141163973,19-05-2026,"19-05-2026 08:18:49.876",910000.00,HUF,'
    '"Beérkezett utalás",Atvezetes,984483.42,,,,"Graphtrek Kft",,,,,,,,0.00,,'
    "CREDIT,DEPOSIT",
]


@pytest.fixture
def statements_dir(tmp_path):
    """Ideiglenes balance-statements mappa egy minta CSV-vel."""
    csv_path = tmp_path / "statement_25546267_HUF_2026-05-19_2026-06-02.csv"
    csv_path.write_text("\n".join([CSV_HEADER, *CSV_ROWS]) + "\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings(statements_dir):
    return Settings(balance_statements_dir=str(statements_dir))


class TestListStatementFiles:
    def test_lists_all(self, settings):
        files = list_statement_files(settings=settings)
        assert len(files) == 1
        f = files[0]
        assert f.balance_id == 25546267
        assert f.currency == "HUF"
        assert f.from_date == date(2026, 5, 19)
        assert f.to_date == date(2026, 6, 2)

    def test_currency_filter_match(self, settings):
        assert len(list_statement_files(currency="huf", settings=settings)) == 1

    def test_currency_filter_no_match(self, settings):
        assert list_statement_files(currency="EUR", settings=settings) == []

    def test_from_overlap(self, settings):
        # from a fájl időszakán belül → benne van
        assert len(list_statement_files(from_date=date(2026, 5, 19), settings=settings)) == 1

    def test_from_after_period(self, settings):
        # from a fájl időszaka után → kizárva
        assert list_statement_files(from_date=date(2026, 7, 1), settings=settings) == []

    def test_to_before_period(self, settings):
        assert list_statement_files(to_date=date(2026, 1, 1), settings=settings) == []

    def test_missing_dir_returns_empty(self, tmp_path):
        s = Settings(balance_statements_dir=str(tmp_path / "nincs"))
        assert list_statement_files(settings=s) == []


class TestParseStatementCsv:
    def test_count(self, settings):
        result = parse_statement_csv(
            "statement_25546267_HUF_2026-05-19_2026-06-02.csv", settings=settings
        )
        assert result.fetched == 3
        assert result.currency == "HUF"
        assert result.balance_id == 25546267

    def test_debit_transfer(self, settings):
        result = parse_statement_csv(
            "statement_25546267_HUF_2026-05-19_2026-06-02.csv", settings=settings
        )
        txn = result.transactions[0]
        assert txn.wise_transaction_id == "TRANSFER-2166707551"
        assert txn.type == TransactionType.DEBIT
        assert txn.amount == Decimal("-71440.00")
        assert txn.counterparty_name == "Őrszem Services Kft."
        assert txn.counterparty_account == "11600006-00000000-94346200"
        assert txn.payment_reference == "2026-000064"

    def test_card_uses_merchant(self, settings):
        result = parse_statement_csv(
            "statement_25546267_HUF_2026-05-19_2026-06-02.csv", settings=settings
        )
        assert result.transactions[1].counterparty_name == "Online PARIS"

    def test_credit_from_payer(self, settings):
        result = parse_statement_csv(
            "statement_25546267_HUF_2026-05-19_2026-06-02.csv", settings=settings
        )
        txn = result.transactions[2]
        assert txn.type == TransactionType.CREDIT
        assert txn.amount == Decimal("910000.00")
        assert txn.counterparty_name == "Graphtrek Kft"

    def test_missing_file(self, settings):
        with pytest.raises(StatementCsvError, match="nem található"):
            parse_statement_csv("nincs.csv", settings=settings)

    def test_path_traversal_rejected(self, settings):
        with pytest.raises(StatementCsvError, match="Érvénytelen"):
            parse_statement_csv("../etc/passwd", settings=settings)
