"""detector.py egységtesztek (bank felismerés fájlnévből)."""

from __future__ import annotations

import pytest

from uploader.detector import detect_bank


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("statement_123_EUR_2026-05-01_2026-05-31.csv", "wise"),
        ("STATEMENT_123_EUR_2026-05-01_2026-05-31.csv", "wise"),
        ("12345678-12345678_2026-05-01_2026-05-31.csv", "erste"),
        ("random.csv", None),
        ("invoice.pdf", None),
        ("statement_no_dates.csv", "wise"),
    ],
)
def test_detect_bank(filename: str, expected: str | None):
    assert detect_bank(filename) == expected


def test_detect_bank_strips_whitespace():
    assert detect_bank("  statement_1_EUR_2026-05-01_2026-05-31.csv  ") == "wise"


def test_detect_bank_statement_prefix_wins_over_erste_pattern():
    # a dátum-minta önmagában Erste-t jelezne, de a 'statement_' prefix elsőbbséget élvez
    assert detect_bank("statement_2026-05-01_2026-05-31.csv") == "wise"
