"""Bankdetektálás fájlnévből (Erste / Wise)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

_ERSTE_PATTERN = re.compile(r".+_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv$", re.IGNORECASE)

# PDF kivonatok elnevezési mintái:
# Erste:  <IBAN>_<YYYYMMDD>_<YYYYMMDD>.pdf   (kötőjel nélküli dátumok)
# Wise:   statement_<id>_<CCY>_<YYYY-MM-DD>_<YYYY-MM-DD>.pdf (a 'statement_' prefix dönt)
_ERSTE_PDF_PATTERN = re.compile(r".+_(\d{8})_(\d{8})\.pdf$", re.IGNORECASE)
_WISE_PDF_PATTERN = re.compile(
    r"statement_.+_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.pdf$", re.IGNORECASE
)


def detect_bank(filename: str) -> str | None:
    """Visszaadja a bank nevét ('erste' | 'wise') vagy None-t, ha nem felismerhető.

    Prioritás:
    1. 'statement_' kezdetű → Wise
    2. dátum-mintájú végű és nem statement_ → Erste
    3. egyéb → None
    """
    name = filename.strip()
    if name.lower().startswith("statement_"):
        return "wise"
    if _ERSTE_PATTERN.match(name):
        return "erste"
    return None


def parse_pdf_statement(filename: str) -> tuple[str, date, date] | None:
    """Bank + kivonat időszak (from, to) kiolvasása egy PDF kivonat fájlnevéből.

    Visszaadja (bank, from_date, to_date)-t, vagy None-t, ha a fájlnév egyik
    ismert mintára sem illeszkedik.
    """
    name = filename.strip()
    wise_match = _WISE_PDF_PATTERN.match(name)
    if wise_match:
        from_str, to_str = wise_match.groups()
        return (
            "wise",
            datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=UTC).date(),
            datetime.strptime(to_str, "%Y-%m-%d").replace(tzinfo=UTC).date(),
        )
    erste_match = _ERSTE_PDF_PATTERN.match(name)
    if erste_match:
        from_str, to_str = erste_match.groups()
        return (
            "erste",
            datetime.strptime(from_str, "%Y%m%d").replace(tzinfo=UTC).date(),
            datetime.strptime(to_str, "%Y%m%d").replace(tzinfo=UTC).date(),
        )
    return None
