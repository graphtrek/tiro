"""Tests for invoice detection and file listing."""

from datetime import datetime

import pytest

from invoice_file_filter.extractor import describe_file, is_invoice


class TestIsInvoice:
    def test_keyword_in_text(self, hu_invoice):
        assert is_invoice("random.pdf", hu_invoice) is True

    def test_keyword_in_filename(self):
        assert is_invoice("2026_invoice_42.pdf", "no body text") is True

    def test_accounting_document_accepted(self, accounting_document):
        assert is_invoice("biz.pdf", accounting_document) is True

    def test_non_invoice_rejected(self, non_invoice):
        assert is_invoice("memo.pdf", non_invoice) is False


class TestDescribeFile:
    def test_filename_and_modified(self, tmp_path):
        pdf = tmp_path / "2026-05-001_szamla.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        meta = describe_file(str(pdf))
        assert meta.filename == "2026-05-001_szamla.pdf"
        assert meta.path == str(pdf.resolve())
        assert isinstance(meta.modified, datetime)
        assert meta.modified.timestamp() == pytest.approx(pdf.stat().st_mtime)
