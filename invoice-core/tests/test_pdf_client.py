"""Tests for PdfClient — verifies CSV parsing matches the single-column word format."""

from __future__ import annotations

from unittest.mock import MagicMock

from invoice_core.pdf_client import PdfClient


def _make_client():
    settings = MagicMock()
    settings.invoice_file_filter_url = "http://localhost:8001"
    settings.sync_timeout = 30
    client = PdfClient(settings=settings)
    return client


class TestGetWordsText:
    def _mock_response(self, csv_text: str, status: int = 200):
        resp = MagicMock()
        resp.status_code = status
        resp.text = csv_text
        resp.raise_for_status = MagicMock()
        return resp

    def test_parses_single_column_csv(self):
        csv_body = "word\r\ngraphtrek\r\nszamla\r\nvevo\r\n"
        client = _make_client()
        client.session.post = MagicMock(return_value=self._mock_response(csv_body))

        result = client.get_words_text("/downloads/invoice.pdf")

        assert "graphtrek" in result
        assert "szamla" in result
        assert "vevo" in result

    def test_header_row_excluded(self):
        csv_body = "word\r\nszamla\r\n"
        client = _make_client()
        client.session.post = MagicMock(return_value=self._mock_response(csv_body))

        result = client.get_words_text("/downloads/invoice.pdf")

        assert result == "szamla"

    def test_empty_response_returns_empty_string(self):
        csv_body = "word\r\n"
        client = _make_client()
        client.session.post = MagicMock(return_value=self._mock_response(csv_body))

        result = client.get_words_text("/downloads/invoice.pdf")

        assert result == ""

    def test_request_error_returns_empty_string(self):
        import requests

        client = _make_client()
        client.session.post = MagicMock(side_effect=requests.RequestException("timeout"))

        result = client.get_words_text("/downloads/invoice.pdf")

        assert result == ""
