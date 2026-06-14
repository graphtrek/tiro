"""In-memory job manager for asynchronous PDF download jobs.

Jobs are tracked in-process (suitable for a single FastAPI worker). Each job
runs ``GmailClient.download_pdf_attachments`` and streams log lines that the
REST API exposes via ``GET /api/v1/jobs/{job_id}/logs``.
"""

import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from attachment_downloader.models import (
    DownloadRequest,
    JobInfo,
    JobLogEntry,
    JobLogs,
    JobStatus,
)


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, JobInfo] = {}
        self._logs: Dict[str, List[JobLogEntry]] = {}
        self._lock = threading.Lock()

    def create_job(self, request: DownloadRequest) -> JobInfo:
        job_id = uuid.uuid4().hex
        info = JobInfo(
            job_id=job_id,
            status=JobStatus.PENDING,
            request=request,
            created_at=datetime.now(),
        )
        with self._lock:
            self._jobs[job_id] = info
            self._logs[job_id] = []
        return info

    def get_job(self, job_id: str) -> Optional[JobInfo]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_logs(self, job_id: str) -> Optional[JobLogs]:
        with self._lock:
            if job_id not in self._jobs:
                return None
            return JobLogs(job_id=job_id, logs=list(self._logs[job_id]))

    def log(self, job_id: str, level: str, message: str) -> None:
        entry = JobLogEntry(timestamp=datetime.now(), level=level, message=message)
        with self._lock:
            self._logs.setdefault(job_id, []).append(entry)

    def run_job(self, job_id: str, client) -> None:
        """Execute a download job. Intended to run as a background task."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()
        req = job.request
        self.log(
            job_id,
            "INFO",
            f"Starting download {req.start_date} .. {req.end_date}",
        )
        try:
            result = client.download_pdf_attachments(
                start_date=req.start_date,
                end_date=req.end_date,
                output_dir=req.output_dir,
                log=lambda level, message: self.log(job_id, level, message),
            )
            job.result = result
            job.status = JobStatus.COMPLETED
            self.log(
                job_id,
                "INFO",
                f"Completed: {result.total_files} PDF(s) saved to {result.output_dir}",
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure to the job
            job.status = JobStatus.FAILED
            job.error = str(exc)
            self.log(job_id, "ERROR", str(exc))
        finally:
            job.finished_at = datetime.now()


# Module-level singleton shared by the FastAPI app.
job_manager = JobManager()
