"""HTTP client for the invoice-file-filter service (:8001)."""

from __future__ import annotations

import csv
import io
import logging
import time

import requests

from .config import Settings, get_settings, make_http_session, token_hint_for_error

logger = logging.getLogger(__name__)


class PdfClientError(RuntimeError):
    """Raised when invoice-file-filter cannot fulfil a request."""


class PdfClient:
    """Client for invoice-file-filter's extraction and word-search endpoints.

    Fields in each file dict from extract(): filename, path, modified.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.invoice_file_filter_url.rstrip("/")
        self.session = make_http_session()

    def extract(self, start_date: str, end_date: str) -> list[dict]:
        """POST /api/v1/invoices/extract → list of matched file dicts."""
        t0 = time.monotonic()
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/invoices/extract",
                json={"start_date": start_date, "end_date": end_date, "download": True},
                timeout=self.settings.sync_timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise PdfClientError(
                f"Failed to reach invoice-file-filter at {self.base_url}: "
                f"{exc}{token_hint_for_error(exc)}"
            ) from exc
        data = resp.json()
        files = data.get("files", [])
        for f in files:
            f.setdefault("preview_base64", None)
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "POST %s/api/v1/invoices/extract → %d file(s) in %.0fms",
            self.base_url,
            len(files),
            elapsed_ms,
        )
        return files

    def clear_cache(self) -> int:
        """DELETE /api/v1/pdf/words/cache → number of cleared entries (0 on error)."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/api/v1/pdf/words/cache",
                timeout=self.settings.sync_timeout,
            )
            resp.raise_for_status()
            removed = resp.json().get("removed", 0)
            logger.info("invoice-file-filter cache cleared: %d entry(s)", removed)
            return removed
        except requests.RequestException as exc:
            logger.warning("Could not clear invoice-file-filter cache: %s", exc)
            return 0

    def get_words_text(self, pdf_path: str) -> str:
        """POST /api/v1/pdf/words → all words from the PDF joined into one string.

        The response is a single-column CSV (header: word); one normalised word per row.
        Returns an empty string on any error so callers can treat it as a no-match.
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/pdf/words",
                json={"pdf_path": pdf_path},
                timeout=self.settings.sync_timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Could not get words for %s: %s", pdf_path, exc)
            return ""
        reader = csv.reader(io.StringIO(resp.text))
        next(reader, None)  # skip header row
        words = [row[0].replace("\x00", "") for row in reader if row]
        return " ".join(words)
