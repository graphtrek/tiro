from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class DownloadRequest(BaseModel):
    """Parameters for a PDF-attachment download job."""

    start_date: str = Field(..., description="Filter start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Filter end date (YYYY-MM-DD)")
    output_dir: str | None = Field(
        None,
        description="Subdirectory under DOWNLOAD_ROOT_DIR (default: root of DOWNLOAD_ROOT_DIR)",
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")  # noqa: DTZ007 - calendar date, not a timestamp
        except ValueError as e:
            raise ValueError("expected YYYY-MM-DD format") from e
        return v

    @model_validator(mode="after")
    def _validate_date_range(self) -> "DownloadRequest":
        start = datetime.strptime(self.start_date, "%Y-%m-%d")  # noqa: DTZ007 - calendar date
        end = datetime.strptime(self.end_date, "%Y-%m-%d")  # noqa: DTZ007 - calendar date
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
    files: list[DownloadedFile] = Field(default_factory=list)


class CacheInfo(BaseModel):
    entries: int
    hits: int
    misses: int
