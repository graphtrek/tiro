"""Wise CSV bankkivonat beolvasása → BankTransaction lista.

Fájljellemzők:
- Kódolás: UTF-8
- Elválasztó: , (vesszős)
- Dátumformátum: DD-MM-YYYY
- Datetime formátum: DD-MM-YYYY HH:MM:SS.mmm
- Direction: Transaction Type oszlop (CREDIT / DEBIT)
"""

from __future__ import annotations

import csv
import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..models import BankTransaction

logger = logging.getLogger(__name__)

_COL_ID = "TransferWise ID"
_COL_DATE = "Date"
_COL_DATETIME = "Date Time"
_COL_AMOUNT = "Amount"
_COL_CURRENCY = "Currency"
_COL_DESCRIPTION = "Description"
_COL_PAYMENT_REF = "Payment Reference"
_COL_RUNNING_BALANCE = "Running Balance"
_COL_PAYER_NAME = "Payer Name"
_COL_PAYEE_NAME = "Payee Name"
_COL_PAYEE_ACCOUNT = "Payee Account Number"
_COL_MERCHANT = "Merchant"
_COL_TOTAL_FEES = "Total fees"
_COL_TXN_TYPE = "Transaction Type"
_COL_TXN_DETAILS_TYPE = "Transaction Details Type"
_COL_EXCHANGE_RATE = "Exchange Rate"
_COL_EXCHANGE_TO = "Exchange To"
_COL_CARD_LAST_FOUR = "Card Last Four Digits"
_COL_NOTE = "Note"

_DATE_FORMATS = (
    "%d-%m-%Y %H:%M:%S.%f",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y",
)


def _parse_date(raw: str) -> date | None:
    if not raw or not raw.strip():
        return None
    for fmt in _DATE_FORMATS:
        try:
            # Local bank-statement date: aware-then-normalized to keep the date value.
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    return None


def _parse_datetime(raw: str) -> datetime | None:
    if not raw or not raw.strip():
        return None
    for fmt in _DATE_FORMATS:
        try:
            # Local bank-statement time: normalize to aware UTC, value preserved.
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Decimal | None:
    if not raw or not raw.strip():
        return None
    try:
        return Decimal(raw.strip())
    except InvalidOperation:
        return None


def _opt_str(row: dict, col: str) -> str | None:
    return (row.get(col) or "").strip() or None


def parse_wise_csv(path: Path) -> list[BankTransaction]:
    """Beolvas egy Wise CSV fájlt és BankTransaction listát ad vissza."""
    transactions: list[BankTransaction] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            txn_id = _opt_str(row, _COL_ID)
            if not txn_id:
                continue

            raw_date = _opt_str(row, _COL_DATE) or ""
            parsed_date = _parse_date(raw_date)
            if not parsed_date:
                logger.warning("Érvénytelen dátum (%s), sor kihagyva", raw_date)
                continue

            raw_amount = _opt_str(row, _COL_AMOUNT) or "0"
            amount = _parse_amount(raw_amount)
            if amount is None:
                logger.warning("Érvénytelen összeg: %s", raw_amount)
                continue

            raw_direction = (_opt_str(row, _COL_TXN_TYPE) or "").upper()
            if raw_direction in ("CREDIT", "DEBIT"):
                direction = raw_direction
            else:
                direction = "CREDIT" if amount >= 0 else "DEBIT"

            payer_name = _opt_str(row, _COL_PAYER_NAME)
            payee_name = _opt_str(row, _COL_PAYEE_NAME)
            merchant = _opt_str(row, _COL_MERCHANT)
            counterparty_name = payer_name or payee_name or merchant

            fees_raw = _opt_str(row, _COL_TOTAL_FEES)
            fees = _parse_amount(fees_raw) if fees_raw else None
            if fees is not None and fees == 0:
                fees = None

            balance_raw = _opt_str(row, _COL_RUNNING_BALANCE)
            balance = _parse_amount(balance_raw) if balance_raw else None

            exchange_rate_raw = _opt_str(row, _COL_EXCHANGE_RATE)
            exchange_rate = _parse_amount(exchange_rate_raw) if exchange_rate_raw else None

            transactions.append(
                BankTransaction(
                    bank="wise",
                    transaction_id=txn_id,
                    date=parsed_date,
                    datetime=_parse_datetime(_opt_str(row, _COL_DATETIME) or ""),
                    amount=abs(amount),
                    currency=(_opt_str(row, _COL_CURRENCY) or ""),
                    direction=direction,
                    description=_opt_str(row, _COL_DESCRIPTION),
                    payment_reference=_opt_str(row, _COL_PAYMENT_REF),
                    counterparty_name=counterparty_name,
                    counterparty_account=_opt_str(row, _COL_PAYEE_ACCOUNT),
                    counterparty_iban=None,
                    transaction_type=_opt_str(row, _COL_TXN_DETAILS_TYPE),
                    category=None,
                    balance=balance,
                    fees=fees,
                    exchange_rate=exchange_rate,
                    exchange_to_currency=_opt_str(row, _COL_EXCHANGE_TO),
                    card_last_four=_opt_str(row, _COL_CARD_LAST_FOUR),
                    note=_opt_str(row, _COL_NOTE),
                )
            )

    logger.info("Wise CSV: %s — %d tranzakció", path.name, len(transactions))
    return transactions
