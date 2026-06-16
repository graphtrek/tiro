"""HTTP client for the invoice-file-filter service (:8001)."""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


class PdfClientError(RuntimeError):
    """Raised when invoice-file-filter cannot fulfil a request."""


class PdfClient:
    """Client for invoice-file-filter's extraction endpoint.

    POSTs to POST /api/v1/invoices/extract and returns the list of matched files.
    Fields in each file dict: filename, path, modified.

    Note: /api/v1/invoices/search does not exist on invoice-file-filter.
    Matching against NAV invoice numbers is done locally in service.py
    by checking whether invoice_number appears in filename.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.invoice_file_filter_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

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
                f"Failed to reach invoice-file-filter at {self.base_url}: {exc}"
            ) from exc
        data = resp.json()
        files = data.get("files", [])
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "POST %s/api/v1/invoices/extract → %d file(s) in %.0fms",
            self.base_url, len(files), elapsed_ms,
        )
        return files
