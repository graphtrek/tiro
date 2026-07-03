"""Erste CSV bankkivonat beolvasása → BankTransaction lista.

Fájljellemzők:
- Kódolás: UTF-16 (BOM automatikusan kezelve)
- Elválasztó: , (vesszős, idézőjeles mezők)
- Összeg: ezres elválasztó = \\xa0 (non-breaking space), negatív = DEBIT
- Egyenleg: "3\\xa0343\\xa0587 HUF" formátum (pénznem kód a végén)
- Dátumformátum: YYYY.MM.DD
- Datetime formátum: YYYY.MM.DD HH:MM:SS
"""

from __future__ import annotations

import csv
import hashlib
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..models import BankTransaction

logger = logging.getLogger(__name__)

_COL_DATE = "Könyvelés dátuma"
_COL_DATETIME = "Tranzakció dátuma és ideje"
_COL_AMOUNT = "Összeg"
_COL_CURRENCY = "Devizanem"
_COL_TXN_ID = "Tranzakcióazonosító"
_COL_PAYMENT_REF = "Közlemény"
_COL_PARTNER_NAME = "Partner név"
_COL_PARTNER_IBAN = "Partner IBAN száma"
_COL_PARTNER_ACCOUNT = "Partner számlaszáma"
_COL_DESCRIPTION = "Könyvelési információk"
_COL_TXN_TYPE = "Tranzakció típusa"
_COL_CATEGORY = "Kategória"
_COL_BALANCE = "Számlaegyenleg"


def _parse_amount(raw: str) -> Decimal:
    """Erste összeg parszolása: \\xa0 ezres elválasztó eltávolítása, majd Decimal."""
    cleaned = raw.strip().replace("\xa0", "").replace(" ", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Hibás összeg: {raw!r}") from exc


def _parse_balance(raw: str) -> Decimal | None:
    """Egyenleg parszolása: '3\\xa0343\\xa0587 HUF' → Decimal."""
    if not raw or not raw.strip():
        return None
    parts = raw.strip().rsplit(" ", 1)
    number_part = parts[0].replace("\xa0", "").replace(" ", "")
    try:
        return Decimal(number_part)
    except InvalidOperation:
        return None


def _parse_date(raw: str) -> date | None:
    if not raw or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y.%m.%d").date()
    except ValueError:
        return None


def _parse_datetime(raw: str) -> datetime | None:
    if not raw or not raw.strip():
        return None
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _opt_str(row: dict, col: str) -> str | None:
    return (row.get(col) or "").strip() or None


def _make_id(row: dict, occurrence: int) -> str:
    """Determinisztikus ID generálás, ha a Tranzakcióazonosító üres (pl. kártyás tranzakció).

    `occurrence` a hányadik előfordulása ennek a (dátum, összeg, leírás) kulcsnak a
    fájlon belül — nem a sor abszolút pozíciója. Ez stabil marad akkor is, ha egy
    későbbi export átfedő (más kezdő/záró dátumú) időszakot tartalmaz és emiatt a
    releváns sor előtt más sorok száma megváltozik.
    """
    raw = f"{row.get(_COL_DATE,'')}{row.get(_COL_AMOUNT,'')}{row.get(_COL_DESCRIPTION,'')}{occurrence}"
    return "ERSTE-" + hashlib.sha1(raw.encode()).hexdigest()[:16].upper()


def parse_erste_csv(path: Path) -> list[BankTransaction]:
    """Beolvas egy Erste CSV fájlt és BankTransaction listát ad vissza."""
    transactions: list[BankTransaction] = []
    dup_occurrences: dict[tuple[str, str, str], int] = {}
    with path.open(encoding="utf-16", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_date = _opt_str(row, _COL_DATE)
            if not raw_date:
                continue
            parsed_date = _parse_date(raw_date)
            if not parsed_date:
                logger.warning("Érvénytelen dátum (%s), sor kihagyva: %s", raw_date, dict(row))
                continue

            raw_amount = (row.get(_COL_AMOUNT) or "").strip()
            if not raw_amount:
                continue
            try:
                amount = _parse_amount(raw_amount)
            except ValueError:
                logger.warning("Érvénytelen összeg: %s", raw_amount)
                continue

            txn_id = _opt_str(row, _COL_TXN_ID)
            if not txn_id:
                key = (raw_date, raw_amount, _opt_str(row, _COL_DESCRIPTION) or "")
                occurrence = dup_occurrences.get(key, 0)
                dup_occurrences[key] = occurrence + 1
                txn_id = _make_id(row, occurrence)
            direction = "CREDIT" if amount >= 0 else "DEBIT"

            transactions.append(
                BankTransaction(
                    bank="erste",
                    transaction_id=txn_id,
                    date=parsed_date,
                    datetime=_parse_datetime(_opt_str(row, _COL_DATETIME) or ""),
                    amount=abs(amount),
                    currency=(_opt_str(row, _COL_CURRENCY) or "HUF"),
                    direction=direction,
                    description=_opt_str(row, _COL_DESCRIPTION),
                    payment_reference=_opt_str(row, _COL_PAYMENT_REF),
                    counterparty_name=_opt_str(row, _COL_PARTNER_NAME),
                    counterparty_account=_opt_str(row, _COL_PARTNER_ACCOUNT),
                    counterparty_iban=_opt_str(row, _COL_PARTNER_IBAN),
                    transaction_type=_opt_str(row, _COL_TXN_TYPE),
                    category=_opt_str(row, _COL_CATEGORY),
                    balance=_parse_balance(_opt_str(row, _COL_BALANCE) or ""),
                    fees=None,
                )
            )

    logger.info("Erste CSV: %s — %d tranzakció", path.name, len(transactions))
    return transactions
