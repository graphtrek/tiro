"""HTTP client for uploader REST API (:8006)."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from vision.config import Settings, get_settings, make_http_session

logger = logging.getLogger(__name__)


class UploaderClient:
    """Client for uploader endpoints."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.uploader_url.rstrip("/")
        self.timeout = self.settings.request_timeout
        self.session = make_http_session()

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        bank: str | None = None,
        overwrite: bool = False,
    ) -> dict | None:
        try:
            data: dict = {"overwrite": str(overwrite).lower()}
            if bank:
                data["bank"] = bank
            resp = self.session.post(
                f"{self.base_url}/api/v1/upload",
                files={"file": (filename, file_bytes, "text/csv")},
                data=data,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            detail = None
            if exc.response is not None:
                try:
                    detail = exc.response.json().get("detail")
                except ValueError:
                    pass
            logger.warning("uploader POST /api/v1/upload failed: %s", detail or exc)
            return {"error": detail or str(exc)}
        except requests.RequestException as exc:
            logger.warning("uploader POST /api/v1/upload failed: %s", exc)
            return None

    def list_files(self) -> dict | None:
        try:
            resp = self.session.get(
                f"{self.base_url}/api/v1/files",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("uploader GET /api/v1/files failed: %s", exc)
            return None

    def delete_file(self, bank: str, filename: str) -> bool:
        try:
            resp = self.session.delete(
                f"{self.base_url}/api/v1/files/{bank}/{filename}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.warning(
                "uploader DELETE /api/v1/files/%s/%s failed: %s", bank, filename, exc
            )
            return False
