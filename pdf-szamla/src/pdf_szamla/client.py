"""HTTP client for the graphtrek-email PDF download service."""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import requests

from .config import Settings, get_settings
from .models import JobInfo, JobStatus

logger = logging.getLogger(__name__)


class GraphtrekEmailError(RuntimeError):
    """Raised when the graphtrek-email service cannot fulfil a request."""


class GraphtrekEmailClient:
    """Thin client over graphtrek-email's async jobs API.

    Drives ``POST /api/v1/jobs`` then polls ``GET /api/v1/jobs/{job_id}`` until
    the download job reaches a terminal state, returning the saved PDF paths.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.graphtrek_email_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def start_download(
        self, start_date: str, end_date: str, output_dir: Optional[str] = None
    ) -> str:
        """Create a download job and return its ``job_id``."""
        payload = {"start_date": start_date, "end_date": end_date}
        if output_dir:
            payload["output_dir"] = output_dir
        t0 = time.monotonic()
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/jobs", json=payload, timeout=30
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise GraphtrekEmailError(
                f"Failed to start download job at {self.base_url}: {exc}"
            ) from exc
        job_id = resp.json().get("job_id")
        if not job_id:
            raise GraphtrekEmailError("graphtrek-email did not return a job_id")
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "POST %s/api/v1/jobs → job_id=%s in %.0fms",
            self.base_url, job_id, elapsed_ms,
        )
        return job_id

    def get_job(self, job_id: str) -> JobInfo:
        """Fetch and parse a job's current state."""
        try:
            resp = self.session.get(
                f"{self.base_url}/api/v1/jobs/{job_id}", timeout=30
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise GraphtrekEmailError(f"Failed to query job {job_id}: {exc}") from exc
        return JobInfo.model_validate(resp.json())

    def wait_for_completion(self, job_id: str) -> List[str]:
        """Poll ``job_id`` until terminal; return the saved PDF paths.

        Raises :class:`GraphtrekEmailError` on failure or timeout.
        """
        t0 = time.monotonic()
        deadline = t0 + self.settings.download_timeout
        while True:
            job = self.get_job(job_id)
            if job.status == JobStatus.COMPLETED:
                files = job.result.files if job.result else []
                paths = [f.saved_path for f in files]
                elapsed_ms = (time.monotonic() - t0) * 1000
                logger.info(
                    "Download job %s completed: %d file(s) in %.0fms",
                    job_id, len(paths), elapsed_ms,
                )
                return paths
            if job.status == JobStatus.FAILED:
                raise GraphtrekEmailError(
                    f"Download job {job_id} failed: {job.error or 'unknown error'}"
                )
            if time.monotonic() >= deadline:
                raise GraphtrekEmailError(
                    f"Download job {job_id} did not finish within "
                    f"{self.settings.download_timeout}s (last status: {job.status.value})"
                )
            time.sleep(self.settings.poll_interval)

    def download(
        self, start_date: str, end_date: str, output_dir: Optional[str] = None
    ) -> List[str]:
        """Start a download job and block until it finishes; return PDF paths."""
        job_id = self.start_download(start_date, end_date, output_dir)
        return self.wait_for_completion(job_id)
