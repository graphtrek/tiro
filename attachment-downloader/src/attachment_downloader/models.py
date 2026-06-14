from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Any, List

class EmailSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    subject: str
    from_address: str = Field(alias="from")
    date: str
    snippet: str

class EmailDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    subject: str
    from_address: str = Field(alias="from")
    to: str
    date: str
    body: str

class Label(BaseModel):
    id: str
    name: str
    type: Optional[str] = None

class GmailResponse(BaseModel):
    status: str
    id: Optional[str] = None
    message: Optional[str] = None
    data: Optional[Any] = None


# --- PDF download / job models (graphtrek-email Moneypenny service) ---

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DownloadRequest(BaseModel):
    """Parameters for a PDF-attachment download job."""
    start_date: str = Field(..., description="Filter start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Filter end date (YYYY-MM-DD)")
    output_dir: Optional[str] = Field(
        None, description="Target directory (default: ./downloads/)"
    )


class DownloadedFile(BaseModel):
    filename: str
    original_filename: str
    message_id: str
    email_date: str
    size_bytes: int
    saved_path: str


class DownloadResult(BaseModel):
    total_emails: int = 0
    total_files: int = 0
    skipped_files: int = 0
    output_dir: str
    files: List[DownloadedFile] = Field(default_factory=list)


class JobLogEntry(BaseModel):
    timestamp: datetime
    level: str
    message: str


class JobInfo(BaseModel):
    job_id: str
    status: JobStatus
    request: DownloadRequest
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[DownloadResult] = None
    error: Optional[str] = None


class JobLogs(BaseModel):
    job_id: str
    logs: List[JobLogEntry] = Field(default_factory=list)