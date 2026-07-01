"""Bankdetektálás fájlnévből (Erste / Wise)."""

from __future__ import annotations

import re

_ERSTE_PATTERN = re.compile(r".+_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv$", re.IGNORECASE)


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
