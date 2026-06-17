from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional


class DownloadRequest(BaseModel):
    """Parameters for a PDF-attachment download job."""
    start_date: str = Field(..., description="Filter start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Filter end date (YYYY-MM-DD)")
    output_dir: Optional[str] = Field(
        None, description="Subdirectory under DOWNLOAD_ROOT_DIR (default: root of DOWNLOAD_ROOT_DIR)"
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("expected YYYY-MM-DD format")
        return v

    @model_validator(mode="after")
    def _validate_date_range(self) -> "DownloadRequest":
        start = datetime.strptime(self.start_date, "%Y-%m-%d")
        end = datetime.strptime(self.end_date, "%Y-%m-%d")
        if end < start:
            raise ValueError("end_date must not be before start_date")
        return self


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
