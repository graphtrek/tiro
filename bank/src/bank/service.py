"""Bank mikroszerviz - fájlfelfedezés, szűrés, konszolidáció."""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from .config import Settings, get_settings
from .models import BankStatement, BankTransaction, ConsolidatedStatement, StatementFile
from .parsers.erste import parse_erste_csv
from .parsers.wise import parse_wise_csv

logger = logging.getLogger(__name__)

# Erste: <számlaszám>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv
_ERSTE_RE = re.compile(
    r"^(?P<account_id>.+)_(?P<from>\d{4}-\d{2}-\d{2})_(?P<to>\d{4}-\d{2}-\d{2})\.csv$"
)

# Wise: statement_<balanceId>_<currency>_<YYYY-MM-DD>_<YYYY-MM-DD>.csv
_WISE_RE = re.compile(
    r"^statement_(?P<account_id>\d+)_(?P<currency>[A-Za-z]{3})_"
    r"(?P<from>\d{4}-\d{2}-\d{2})_(?P<to>\d{4}-\d{2}-\d{2})\.csv$"
)


def _erste_dir(settings: Settings) -> Path:
    return Path(settings.balance_statements_dir) / settings.erste_subdir


def _wise_dir(settings: Settings) -> Path:
    return Path(settings.balance_statements_dir) / settings.wise_subdir


def _parse_erste_filename(path: Path) -> StatementFile | None:
    m = _ERSTE_RE.match(path.name)
    if not m:
        return None
    return StatementFile(
        bank="erste",
        filename=path.name,
        account_id=m.group("account_id"),
        currency=None,
        from_date=date.fromisoformat(m.group("from")),
        to_date=date.fromisoformat(m.group("to")),
        path=str(path),
    )


def _parse_wise_filename(path: Path) -> StatementFile | None:
    m = _WISE_RE.match(path.name)
    if not m:
        return None
    return StatementFile(
        bank="wise",
        filename=path.name,
        account_id=m.group("account_id"),
        currency=m.group("currency").upper(),
        from_date=date.fromisoformat(m.group("from")),
        to_date=date.fromisoformat(m.group("to")),
        path=str(path),
    )


def list_files(
    bank: str = "all",
    from_date: date | None = None,
    to_date: date | None = None,
    currency: str | None = None,
    settings: Settings | None = None,
) -> list[StatementFile]:
    """Listázza az elérhető CSV fájlokat, opcionális szűréssel.

    Átfedés-logika: egy fájl illeszkedik, ha a fájl időszaka átfed a kért intervallummal.
    """
    settings = settings or get_settings()
    results: list[StatementFile] = []
    want_currency = currency.upper() if currency else None

    def _filter(sf: StatementFile) -> bool:
        if want_currency and sf.currency and sf.currency != want_currency:
            return False
        if from_date and sf.to_date < from_date:
            return False
        return not (to_date and sf.from_date > to_date)

    if bank in ("erste", "all"):
        erste_dir = _erste_dir(settings)
        if erste_dir.is_dir():
            for path in sorted(erste_dir.glob("*.csv")):
                sf = _parse_erste_filename(path)
                if sf and _filter(sf):
                    results.append(sf)
        else:
            logger.warning("Erste mappa nem létezik: %s", erste_dir)

    if bank in ("wise", "all"):
        wise_dir = _wise_dir(settings)
        if wise_dir.is_dir():
            for path in sorted(wise_dir.glob("*.csv")):
                sf = _parse_wise_filename(path)
                if sf and _filter(sf):
                    results.append(sf)
        else:
            logger.warning("Wise mappa nem létezik: %s", wise_dir)

    results.sort(key=lambda f: (f.from_date, f.bank), reverse=True)
    return results


def _latest_file(files: list[StatementFile]) -> StatementFile | None:
    if not files:
        return None
    return max(files, key=lambda f: f.to_date)


def _filter_by_date(
    transactions: list[BankTransaction],
    from_date: date | None,
    to_date: date | None,
) -> list[BankTransaction]:
    result = transactions
    if from_date:
        result = [t for t in result if t.date >= from_date]
    if to_date:
        result = [t for t in result if t.date <= to_date]
    return result


def read_statement(
    sf: StatementFile,
    from_date: date | None = None,
    to_date: date | None = None,
) -> BankStatement:
    """Beolvas egy StatementFile-t és BankStatement-et ad vissza."""
    path = Path(sf.path)
    if sf.bank == "erste":
        transactions = parse_erste_csv(path)
    elif sf.bank == "wise":
        transactions = parse_wise_csv(path)
    else:
        raise ValueError(f"Ismeretlen bank: {sf.bank!r}")

    transactions = _filter_by_date(transactions, from_date, to_date)
    transactions.sort(key=lambda t: t.date, reverse=True)

    return BankStatement(
        bank=sf.bank,
        filename=sf.filename,
        account_id=sf.account_id,
        currency=sf.currency,
        from_date=sf.from_date,
        to_date=sf.to_date,
        fetched=len(transactions),
        transactions=transactions,
    )


def get_bank_statement(
    bank: str,
    from_date: date | None = None,
    to_date: date | None = None,
    currency: str | None = None,
    settings: Settings | None = None,
) -> BankStatement | None:
    """Visszaadja a legfrissebb (vagy szűrt) bankkivonatot adott bankhoz.

    Szűrő nélkül: a legfrissebb fájl adatait adja vissza.
    Szűrővel: szűri a tranzakciókat dátum szerint.
    """
    files = list_files(bank=bank, currency=currency, settings=settings)
    if not files:
        return None
    sf = _latest_file(files)
    if sf is None:
        return None
    return read_statement(sf, from_date=from_date, to_date=to_date)


def get_statement_by_filename(
    bank: str,
    filename: str,
    settings: Settings | None = None,
) -> BankStatement | None:
    """Beolvas egy konkrét CSV fájlt név szerint."""
    settings = settings or get_settings()
    if bank == "erste":
        path = _erste_dir(settings) / filename
        sf = _parse_erste_filename(path)
    elif bank == "wise":
        path = _wise_dir(settings) / filename
        sf = _parse_wise_filename(path)
    else:
        return None

    if sf is None or not path.is_file():
        return None
    return read_statement(sf)


def get_consolidated_statement(
    from_date: date | None = None,
    to_date: date | None = None,
    currency: str | None = None,
    settings: Settings | None = None,
) -> ConsolidatedStatement:
    """Konszolidált kivonat: Erste + Wise tranzakciók együtt, dátum szerint csökkenő sorrendben."""
    all_transactions: list[BankTransaction] = []
    banks_present: list[str] = []

    for bank in ("erste", "wise"):
        stmt = get_bank_statement(
            bank=bank,
            from_date=from_date,
            to_date=to_date,
            currency=currency,
            settings=settings,
        )
        if stmt:
            all_transactions.extend(stmt.transactions)
            if bank not in banks_present:
                banks_present.append(bank)

    from datetime import time as _time
    all_transactions.sort(
        key=lambda t: (t.date, t.datetime.time() if t.datetime else _time.min),
        reverse=True,
    )

    actual_from = min((t.date for t in all_transactions), default=from_date)
    actual_to = max((t.date for t in all_transactions), default=to_date)

    return ConsolidatedStatement(
        from_date=actual_from,
        to_date=actual_to,
        banks=banks_present,
        total=len(all_transactions),
        transactions=all_transactions,
    )
