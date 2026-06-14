from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional


class DownloadRequest(BaseModel):
    """Parameters for a PDF-attachment download job."""
    start_date: str = Field(..., description="Filter start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Filter end date (YYYY-MM-DD)")
    output_dir: Optional[str] = Field(
        None, description="Subdirectory under DOWNLOAD_ROOT_DIR (default: root of DOWNLOAD_ROOT_DIR)"
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


class CacheInfo(BaseModel):
    entries: int
    hits: int
    misses: int
