"""Shared fixtures for invoice-file-filter tests."""

import pytest

SAMPLE_INVOICE_HU = """
ABC Kft.
Számla
Számlaszám: 2026-001
Kelt: 2026-05-01
Eladó adószáma: 12345678-1-01
Vevő: XYZ Bt.
Vevő adószáma: 87654321-2-02
Fizetési határidő: 2026-05-31
ÁFA összege: 27 000
Végösszeg: 127 000 Ft
"""

SAMPLE_INVOICE_EN = """
ACME Inc.
INVOICE
Invoice No: INV-2026-42
Date: 2026-05-10
Total: 1 234,56
Currency: EUR
"""

SAMPLE_NON_INVOICE = """
Hello,
This is just a regular memo with no billing information whatsoever.
Kind regards.
"""


@pytest.fixture
def hu_invoice() -> str:
    return SAMPLE_INVOICE_HU


@pytest.fixture
def en_invoice() -> str:
    return SAMPLE_INVOICE_EN


@pytest.fixture
def non_invoice() -> str:
    return SAMPLE_NON_INVOICE
