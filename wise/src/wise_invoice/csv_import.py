"""Wise kivonat CSV-k beolvasása és listázása.

A Wise webfelületéről kézzel letöltött kivonat CSV-ket dolgozza fel, amikor a
balance-statements API nem érhető el (EU/UK personal token, PSD2). A fájlok a
``balance_statements_dir`` mappában vannak, fájlnév-séma:

    statement_<balanceId>_<currency>_<from>_<to>.csv
    pl. statement_25546267_HUF_2026-05-19_2026-06-02.csv
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .config import Settings, get_settings
from .models import StatementFile, StatementImport, TransactionSummary, TransactionType

logger = logging.getLogger(__name__)


class StatementCsvError(RuntimeError):
    """CSV beolvasás vagy listázás sikertelen."""


# ── Konstansok ────────────────────────────────────────────────────────────────

# statement_<balanceId>_<currency>_<from>_<to>.csv
_FILENAME_RE = re.compile(
    r"^statement_(?P<balance_id>\d+)_(?P<currency>[A-Za-z]{3})_"
    r"(?P<from>\d{4}-\d{2}-\d{2})_(?P<to>\d{4}-\d{2}-\d{2})\.csv$"
)

# Wise CSV dátumformátumok, legpontosabbtól kevésbé pontos felé
_DATE_FORMATS = ("%d-%m-%Y %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y")

# Wise CSV oszlopnevek
_COL_ID = "TransferWise ID"
_COL_DATE_TIME = "Date Time"
_COL_DATE = "Date"
_COL_AMOUNT = "Amount"
_COL_CURRENCY = "Currency"
_COL_DESCRIPTION = "Description"
_COL_PAYMENT_REF = "Payment Reference"
_COL_RUNNING_BALANCE = "Running Balance"
_COL_EXCHANGE_FROM = "Exchange From"
_COL_EXCHANGE_TO = "Exchange To"
_COL_EXCHANGE_RATE = "Exchange Rate"
_COL_EXCHANGE_TO_AMOUNT = "Exchange To Amount"
_COL_PAYER_NAME = "Payer Name"
_COL_PAYEE_NAME = "Payee Name"
_COL_PAYEE_ACCOUNT = "Payee Account Number"
_COL_MERCHANT = "Merchant"
_COL_CARD_DIGITS = "Card Last Four Digits"
_COL_CARD_HOLDER = "Card Holder Full Name"
_COL_ATTACHMENT = "Attachment"
_COL_NOTE = "Note"
_COL_TOTAL_FEES = "Total fees"
_COL_TXN_TYPE = "Transaction Type"
_COL_TXN_DETAILS_TYPE = "Transaction Details Type"


def _statements_dir(settings: Settings) -> Path:
    return Path(settings.balance_statements_dir)


def resolve_statement_path(
    filename: str, settings: Settings | None = None
) -> Path:
    """Biztonságosan feloldja egy kivonat CSV elérési útját a mappán belül.

    Raises:
        StatementCsvError: érvénytelen fájlnév vagy nem létező fájl esetén.
    """
    settings = settings or get_settings()
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        raise StatementCsvError(f"Érvénytelen fájlnév: {filename!r}")
    path = _statements_dir(settings) / filename
    if not path.is_file():
        raise StatementCsvError(f"CSV fájl nem található: {filename}")
    return path


def list_statement_files(
    from_date: date | None = None,
    to_date: date | None = None,
    currency: str | None = None,
    settings: Settings | None = None,
) -> list[StatementFile]:
    """Listázza a mappában lévő kivonat CSV-ket, opcionális szűréssel.

    A szűrés a fájlnévbe kódolt időszak [from_date, to_date] alapján,
    átfedés-logikával történik: egy fájl akkor illeszkedik, ha az időszaka
    átfed a kért [from_date, to_date] intervallummal.

    Args:
        from_date: csak azokat add vissza, amelyek tartalmaznak ettől kezdődő
            adatot (fájl ``to_date`` >= from_date).
        to_date:   csak azokat, amelyek tartalmaznak eddig tartó adatot
            (fájl ``from_date`` <= to_date).
        currency:  pénznem szűrő (pl. HUF), kis/nagybetű érzéketlen.

    Returns:
        :class:`StatementFile` lista, ``from_date`` szerint csökkenő sorrendben.
    """
    settings = settings or get_settings()
    directory = _statements_dir(settings)
    if not directory.is_dir():
        logger.warning("Kivonat mappa nem létezik: %s", directory)
        return []

    want_currency = currency.upper() if currency else None
    result: list[StatementFile] = []

    for path in directory.glob("statement_*.csv"):
        m = _FILENAME_RE.match(path.name)
        if not m:
            logger.debug("Kihagyott (séma nem illik): %s", path.name)
            continue

        f_from = date.fromisoformat(m.group("from"))
        f_to = date.fromisoformat(m.group("to"))
        f_currency = m.group("currency").upper()

        if want_currency and f_currency != want_currency:
            continue
        if from_date and f_to < from_date:
            continue
        if to_date and f_from > to_date:
            continue

        stat = path.stat()
        result.append(
            StatementFile(
                filename=path.name,
                balance_id=int(m.group("balance_id")),
                currency=f_currency,
                from_date=f_from,
                to_date=f_to,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            )
        )

    result.sort(key=lambda f: f.from_date, reverse=True)
    return result


def _parse_date(value: str) -> datetime:
    """Wise CSV dátum parszolása (``Date Time`` vagy ``Date`` oszlop)."""
    value = (value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            # Local bank-statement time: normalize to aware UTC, value preserved.
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise StatementCsvError(f"Ismeretlen dátumformátum: {value!r}")


def _parse_amount(value: str) -> Decimal:
    try:
        return Decimal((value or "0").strip())
    except InvalidOperation as exc:
        raise StatementCsvError(f"Hibás összeg: {value!r}") from exc


def _row_type(row: dict, amount: Decimal) -> TransactionType:
    raw = (row.get(_COL_TXN_TYPE) or "").strip().upper()
    if raw in ("CREDIT", "DEBIT"):
        return TransactionType(raw)
    return TransactionType.CREDIT if amount >= 0 else TransactionType.DEBIT


def _opt_str(row: dict, col: str) -> str | None:
    return (row.get(col) or "").strip() or None


def _opt_decimal(row: dict, col: str) -> Decimal | None:
    raw = (row.get(col) or "").strip()
    if not raw:
        return None
    try:
        v = Decimal(raw)
        return v if v != 0 else None
    except InvalidOperation:
        return None


def _row_to_summary(row: dict) -> TransactionSummary:
    amount = _parse_amount(row.get(_COL_AMOUNT, "0"))
    raw_date = row.get(_COL_DATE_TIME) or row.get(_COL_DATE) or ""
    payer_name = _opt_str(row, _COL_PAYER_NAME)
    payee_name = _opt_str(row, _COL_PAYEE_NAME)
    merchant = _opt_str(row, _COL_MERCHANT)
    counterparty_name = payer_name or payee_name or merchant
    return TransactionSummary(
        wise_transaction_id=(row.get(_COL_ID) or "").strip(),
        type=_row_type(row, amount),
        transaction_date=_parse_date(raw_date),
        amount=amount,
        currency=(row.get(_COL_CURRENCY) or "").strip(),
        description=_opt_str(row, _COL_DESCRIPTION),
        payment_reference=_opt_str(row, _COL_PAYMENT_REF),
        running_balance=_opt_decimal(row, _COL_RUNNING_BALANCE),
        exchange_from=_opt_str(row, _COL_EXCHANGE_FROM),
        exchange_to=_opt_str(row, _COL_EXCHANGE_TO),
        exchange_rate=_opt_decimal(row, _COL_EXCHANGE_RATE),
        payer_name=payer_name,
        payee_name=payee_name,
        payee_account_number=_opt_str(row, _COL_PAYEE_ACCOUNT),
        merchant=merchant,
        card_last_four_digits=_opt_str(row, _COL_CARD_DIGITS),
        card_holder_full_name=_opt_str(row, _COL_CARD_HOLDER),
        attachment=_opt_str(row, _COL_ATTACHMENT),
        note=_opt_str(row, _COL_NOTE),
        total_fees=_opt_decimal(row, _COL_TOTAL_FEES),
        exchange_to_amount=_opt_decimal(row, _COL_EXCHANGE_TO_AMOUNT),
        transaction_details_type=_opt_str(row, _COL_TXN_DETAILS_TYPE),
        counterparty_name=counterparty_name,
    )


def parse_statement_csv(
    filename: str, settings: Settings | None = None
) -> StatementImport:
    """Beolvas egy kivonat CSV-t a mappából és tranzakciókká alakítja.

    Args:
        filename: a fájl neve a ``balance_statements_dir`` mappán belül.
            Útvonal-komponensek (``/``, ``..``) nem engedélyezettek.

    Returns:
        :class:`StatementImport` a beolvasott tranzakciókkal.
    """
    settings = settings or get_settings()
    path = resolve_statement_path(filename, settings)

    transactions: list[TransactionSummary] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not (row.get(_COL_ID) or "").strip():
                continue
            transactions.append(_row_to_summary(row))

    meta = _FILENAME_RE.match(filename)
    logger.info("CSV import: %s — %d tranzakció", filename, len(transactions))
    return StatementImport(
        filename=filename,
        balance_id=int(meta.group("balance_id")) if meta else None,
        currency=meta.group("currency").upper() if meta else None,
        from_date=date.fromisoformat(meta.group("from")) if meta else None,
        to_date=date.fromisoformat(meta.group("to")) if meta else None,
        fetched=len(transactions),
        transactions=transactions,
    )
