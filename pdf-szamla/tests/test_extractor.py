"""Tests for the regex-based metadata extraction."""

from pdf_szamla.extractor import is_invoice, parse_metadata


class TestParseMetadataHungarian:
    def test_core_fields(self, hu_invoice):
        meta = parse_metadata(hu_invoice, filename="2026-05-001_szamla.pdf")
        assert meta.invoice_number == "2026-001"
        assert meta.invoice_date == "2026-05-01"
        assert meta.supplier_tax_id == "12345678-1-01"
        assert meta.customer_tax_id == "87654321-2-02"
        assert meta.payment_due == "2026-05-31"
        assert meta.amount_total == 127000.0
        assert meta.amount_vat == 27000.0
        assert meta.currency == "HUF"

    def test_confidence_full(self, hu_invoice):
        meta = parse_metadata(hu_invoice, filename="szamla.pdf")
        # all four core fields present
        assert meta.confidence == 1.0


class TestAccentInsensitive:
    def test_unaccented_hungarian_parses(self):
        # Accent-stripped text (e.g. from OCR / plain export) must still parse.
        text = (
            "Szamla\nSzamlaszam: 2026-001\nKelt: 2026-05-01\n"
            "Elado adoszama: 12345678-1-01\nFizetesi hatarido: 2026-05-31\n"
            "AFA osszege: 27 000\nVegosszeg: 127 000 Ft\n"
        )
        meta = parse_metadata(text, filename="szamla.pdf")
        assert meta.invoice_number == "2026-001"
        assert meta.amount_total == 127000.0
        assert meta.amount_vat == 27000.0
        assert meta.payment_due == "2026-05-31"
        assert meta.confidence == 1.0


class TestParseMetadataEnglish:
    def test_fields(self, en_invoice):
        meta = parse_metadata(en_invoice, filename="invoice.pdf")
        assert meta.invoice_number == "INV-2026-42"
        assert meta.invoice_date == "2026-05-10"
        assert meta.amount_total == 1234.56
        assert meta.currency == "EUR"

    def test_partial_confidence(self, en_invoice):
        meta = parse_metadata(en_invoice, filename="invoice.pdf")
        # no tax id present -> 3 of 4 core fields
        assert meta.supplier_tax_id is None
        assert meta.confidence == 0.75


class TestIsInvoice:
    def test_keyword_in_text(self, hu_invoice):
        assert is_invoice("random.pdf", hu_invoice) is True

    def test_keyword_in_filename(self):
        assert is_invoice("2026_invoice_42.pdf", "no body text") is True

    def test_non_invoice_rejected(self, non_invoice):
        assert is_invoice("memo.pdf", non_invoice) is False
