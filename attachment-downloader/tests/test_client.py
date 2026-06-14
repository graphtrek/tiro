import base64
from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch
from attachment_downloader.providers.gmail.client import GmailClient


@pytest.fixture
def gmail_client():
    with patch('attachment_downloader.providers.gmail.client.build') as mock_build:
        client = GmailClient()
        client._get_service = MagicMock()
        yield client


def test_download_pdf_attachments(gmail_client, tmp_path):
    mock_service = MagicMock()
    gmail_client._get_service.return_value = mock_service

    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg1"}]
    }

    internal_ms = int(datetime(2026, 5, 12).timestamp() * 1000)
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg1",
        "internalDate": str(internal_ms),
        "payload": {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": ""}},
                {
                    "mimeType": "application/pdf",
                    "filename": "invoice 2026.pdf",
                    "body": {"attachmentId": "att1"},
                },
            ],
        },
    }

    pdf_bytes = b"%PDF-1.4 hello"
    mock_service.users().messages().attachments().get().execute.return_value = {
        "data": base64.urlsafe_b64encode(pdf_bytes).decode()
    }

    result = gmail_client.download_pdf_attachments(
        "2026-05-01", "2026-05-31", output_dir=str(tmp_path)
    )

    assert result.total_emails == 1
    assert result.total_files == 1
    f = result.files[0]
    assert f.filename == "2026-05-12_0001_invoice_2026.pdf"
    assert f.original_filename == "invoice 2026.pdf"
    assert f.size_bytes == len(pdf_bytes)
    saved = tmp_path / f.filename
    assert saved.exists()
    assert saved.read_bytes() == pdf_bytes


def test_download_counter_resumes_per_year(gmail_client, tmp_path):
    # A file from an earlier run already used counter 0042 for 2026.
    (tmp_path / "2026-03-01_0042_old.pdf").write_bytes(b"%PDF old")
    # An unrelated year must not influence 2026's counter.
    (tmp_path / "2025-12-31_0099_other.pdf").write_bytes(b"%PDF other")

    mock_service = MagicMock()
    gmail_client._get_service.return_value = mock_service
    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg1"}]
    }
    internal_ms = int(datetime(2026, 5, 12).timestamp() * 1000)
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg1",
        "internalDate": str(internal_ms),
        "payload": {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "application/pdf",
                    "filename": "invoice 2026.pdf",
                    "body": {"attachmentId": "att1"},
                },
            ],
        },
    }
    mock_service.users().messages().attachments().get().execute.return_value = {
        "data": base64.urlsafe_b64encode(b"%PDF-1.4 hello").decode()
    }

    result = gmail_client.download_pdf_attachments(
        "2026-05-01", "2026-05-31", output_dir=str(tmp_path)
    )

    # Resumes from 0042 → next is 0043, not 0001.
    assert result.files[0].filename == "2026-05-12_0043_invoice_2026.pdf"


def test_download_skips_already_present_file(gmail_client, tmp_path):
    # Same email date + (sanitized) original name already on disk under an
    # earlier counter — must be skipped without fetching the attachment.
    (tmp_path / "2026-05-12_0007_invoice_2026.pdf").write_bytes(b"%PDF old")

    mock_service = MagicMock()
    gmail_client._get_service.return_value = mock_service
    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg1"}]
    }
    internal_ms = int(datetime(2026, 5, 12).timestamp() * 1000)
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg1",
        "internalDate": str(internal_ms),
        "payload": {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "application/pdf",
                    "filename": "invoice 2026.pdf",
                    "body": {"attachmentId": "att1"},
                },
            ],
        },
    }
    attachments_get = mock_service.users().messages().attachments().get

    result = gmail_client.download_pdf_attachments(
        "2026-05-01", "2026-05-31", output_dir=str(tmp_path)
    )

    assert result.total_files == 0
    assert result.skipped_files == 1
    attachments_get.assert_not_called()


def test_download_rejects_bad_date(gmail_client, tmp_path):
    with pytest.raises(ValueError):
        gmail_client.download_pdf_attachments("not-a-date", "2026-05-31", str(tmp_path))
