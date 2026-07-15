"""HTTP client for the attachment-downloader PDF download service."""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from .config import Settings, get_settings
from .models import DownloadResult

logger = logging.getLogger(__name__)


class AttachmentDownloaderError(RuntimeError):
    """Raised when the attachment-downloader service cannot fulfil a request."""


class AttachmentDownloaderClient:
    """Thin client over attachment-downloader's synchronous jobs API.

    POSTs to ``/api/v1/jobs`` and receives a ``DownloadResult`` immediately.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.attachment_downloader_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        # A beérkező kérés Bearer tokenjét továbbadjuk az attachment-downloadernek.
        from invoice_file_filter.auth import TokenPassthrough

        self.session.auth = TokenPassthrough()

    def download(self, start_date: str, end_date: str) -> DownloadResult:
        """POST a download job and return the full result (files + output_dir)."""
        t0 = time.monotonic()
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/jobs",
                json={"start_date": start_date, "end_date": end_date},
                timeout=self.settings.download_timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise AttachmentDownloaderError(
                f"Failed to reach attachment-downloader at {self.base_url}: {exc}"
            ) from exc
        result = DownloadResult.model_validate(resp.json())
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "POST %s/api/v1/jobs → %d file(s) in %.0fms",
            self.base_url, len(result.files), elapsed_ms,
        )
        return result
