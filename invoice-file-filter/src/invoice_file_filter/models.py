"""Pydantic models for the invoice-file-filter microservice."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ── Processed invoice file (service output) ─────────────────────────────────


class ProcessedFile(BaseModel):
    """A single invoice PDF identified by the service."""

    filename: str
    path: str
    modified: datetime
    file_size: int | None = None


# ── Request / response models ───────────────────────────────────────────────


class ExtractRequest(BaseModel):
    """Parameters for an extraction run."""

    start_date: str | None = Field(
        None, description="Filter start date (YYYY-MM-DD); default 30 days ago"
    )
    end_date: str | None = Field(
        None, description="Filter end date (YYYY-MM-DD); default today"
    )
    output_dir: str | None = Field(
        None, description="PDF directory (default: ../attachment-downloader/downloads)"
    )
    download: bool = Field(
        True,
        description="Download via attachment-downloader first; if False, process existing files in output_dir",
    )


class ExtractResponse(BaseModel):
    """Result of an extraction run."""

    total_files: int = 0
    invoice_count: int = 0
    output_dir: str = ""
    files: list[ProcessedFile] = Field(default_factory=list)


class WordsRequest(BaseModel):
    """Request for word-level CSV extraction from a single PDF."""

    pdf_path: str = Field(..., description="Absolute or relative path to the PDF file")


# ── attachment-downloader response shapes (subset we consume) ─────────────────


class DownloadedFile(BaseModel):
    filename: str | None = None
    saved_path: str


class DownloadResult(BaseModel):
    total_emails: int = 0
    total_files: int = 0
    output_dir: str = ""
    files: list[DownloadedFile] = Field(default_factory=list)
