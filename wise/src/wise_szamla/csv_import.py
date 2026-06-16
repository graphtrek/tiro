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
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

from .config import Settings, get_settings
from .models import StatementFile, StatementImport, TransactionSummary, TransactionType

logger = logging.getLogger(__name__)


class StatementCsvError(RuntimeError):
    """CSV beolvasás vagy listázás sikertelen."""


# statement_<balanceId>_<currency>_<from>_<to>.csv
_FILENAME_RE = re.compile(
    r"^statement_(?P<balance_id>\d+)_(?P<currency>[A-Za-z]{3})_"
    r"(?P<from>\d{4}-\d{2}-\d{2})_(?P<to>\d{4}-\d{2}-\d{2})\.csv$"
)


def _statements_dir(settings: Settings) -> Path:
    return Path(settings.balance_statements_dir)


def resolve_statement_path(
    filename: str, settings: Optional[Settings] = None
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
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    currency: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> List[StatementFile]:
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
    result: List[StatementFile] = []

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
                modified_at=datetime.fromtimestamp(stat.st_mtime),
            )
        )

    result.sort(key=lambda f: f.from_date, reverse=True)
    return result


def _parse_date(value: str) -> datetime:
    """Wise CSV dátum parszolása (``Date Time`` vagy ``Date`` oszlop)."""
    value = (value or "").strip()
    for fmt in ("%d-%m-%Y %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise StatementCsvError(f"Ismeretlen dátumformátum: {value!r}")


def _parse_amount(value: str) -> Decimal:
    try:
        return Decimal((value or "0").strip())
    except InvalidOperation as exc:
        raise StatementCsvError(f"Hibás összeg: {value!r}") from exc


def _row_type(row: dict, amount: Decimal) -> TransactionType:
    raw = (row.get("Transaction Type") or "").strip().upper()
    if raw in ("CREDIT", "DEBIT"):
        return TransactionType(raw)
    return TransactionType.CREDIT if amount >= 0 else TransactionType.DEBIT



def _opt_str(row: dict, col: str) -> Optional[str]:
    return (row.get(col) or "").strip() or None


def _opt_decimal(row: dict, col: str) -> Optional[Decimal]:
    raw = (row.get(col) or "").strip()
    if not raw:
        return None
    try:
        v = Decimal(raw)
        return v if v != 0 else None
    except InvalidOperation:
        return None


def _row_to_summary(row: dict) -> TransactionSummary:
    amount = _parse_amount(row.get("Amount", "0"))
    raw_date = row.get("Date Time") or row.get("Date") or ""
    payer_name = _opt_str(row, "Payer Name")
    payee_name = _opt_str(row, "Payee Name")
    merchant = _opt_str(row, "Merchant")
    counterparty_name = payer_name or payee_name or merchant
    return TransactionSummary(
        wise_transaction_id=(row.get("TransferWise ID") or "").strip(),
        type=_row_type(row, amount),
        transaction_date=_parse_date(raw_date),
        amount=amount,
        currency=(row.get("Currency") or "").strip(),
        description=_opt_str(row, "Description"),
        payment_reference=_opt_str(row, "Payment Reference"),
        running_balance=_opt_decimal(row, "Running Balance"),
        exchange_from=_opt_str(row, "Exchange From"),
        exchange_to=_opt_str(row, "Exchange To"),
        exchange_rate=_opt_decimal(row, "Exchange Rate"),
        payer_name=payer_name,
        payee_name=payee_name,
        payee_account_number=_opt_str(row, "Payee Account Number"),
        merchant=merchant,
        card_last_four_digits=_opt_str(row, "Card Last Four Digits"),
        card_holder_full_name=_opt_str(row, "Card Holder Full Name"),
        attachment=_opt_str(row, "Attachment"),
        note=_opt_str(row, "Note"),
        total_fees=_opt_decimal(row, "Total fees"),
        exchange_to_amount=_opt_decimal(row, "Exchange To Amount"),
        transaction_details_type=_opt_str(row, "Transaction Details Type"),
        counterparty_name=counterparty_name,
    )


def parse_statement_csv(
    filename: str, settings: Optional[Settings] = None
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

    transactions: List[TransactionSummary] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not (row.get("TransferWise ID") or "").strip():
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
