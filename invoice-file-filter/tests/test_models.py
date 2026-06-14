"""Tests for the Pydantic models."""

from datetime import datetime

from invoice_file_filter.models import (
    DownloadedFile,
    ExtractRequest,
    ExtractResponse,
    ProcessedFile,
)


class TestProcessedFile:
    def test_fields(self):
        now = datetime(2026, 5, 1, 12, 0)
        meta = ProcessedFile(filename="x.pdf", modified=now)
        assert meta.filename == "x.pdf"
        assert meta.modified == now


class TestExtractRequest:
    def test_defaults(self):
        req = ExtractRequest()
        assert req.download is True
        assert req.start_date is None
        assert req.output_dir is None

    def test_local_mode(self):
        req = ExtractRequest(download=False, output_dir="./pdfs")
        assert req.download is False
        assert req.output_dir == "./pdfs"


class TestExtractResponse:
    def test_defaults(self):
        resp = ExtractResponse()
        assert resp.total_files == 0
        assert resp.invoice_count == 0
        assert resp.files == []


class TestDownloadedFile:
    def test_minimal(self):
        f = DownloadedFile(saved_path="/tmp/x.pdf")
        assert f.filename is None
