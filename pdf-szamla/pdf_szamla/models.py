"""Pydantic models for the pdf-szamla microservice."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Extracted invoice metadata (service output) ─────────────────────────────


class InvoiceMetadata(BaseModel):
    """Structured metadata extracted from a single invoice PDF."""

    filename: str
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_tax_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_tax_id: Optional[str] = None
    amount_total: Optional[float] = None
    amount_vat: Optional[float] = None
    currency: Optional[str] = None
    payment_due: Optional[str] = None
    confidence: float = 0.0
    saved_path: Optional[str] = None


# ── Request / response models ───────────────────────────────────────────────


class ExtractRequest(BaseModel):
    """Parameters for an extraction run."""

    start_date: Optional[str] = Field(
        None, description="Filter start date (YYYY-MM-DD); default 30 days ago"
    )
    end_date: Optional[str] = Field(
        None, description="Filter end date (YYYY-MM-DD); default today"
    )
    output_dir: Optional[str] = Field(
        None, description="PDF directory (default: ./downloads)"
    )
    download: bool = Field(
        True,
        description="Download via graphtrek-email first; if False, process existing files in output_dir",
    )


class ExtractResponse(BaseModel):
    """Result of an extraction run."""

    total_files: int = 0
    invoice_count: int = 0
    output_dir: str = ""
    invoices: List[InvoiceMetadata] = Field(default_factory=list)


class ExtractBatchRequest(BaseModel):
    """Batch extraction over one or more local PDF directories."""

    output_dirs: List[str] = Field(
        default_factory=list, description="Directories of PDFs to process"
    )


# ── graphtrek-email job shapes (subset we consume) ──────────────────────────


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DownloadedFile(BaseModel):
    filename: Optional[str] = None
    saved_path: str


class DownloadResult(BaseModel):
    total_emails: int = 0
    total_files: int = 0
    output_dir: str = ""
    files: List[DownloadedFile] = Field(default_factory=list)


class JobInfo(BaseModel):
    """Subset of graphtrek-email's JobInfo that pdf-szamla needs."""

    job_id: str
    status: JobStatus
    result: Optional[DownloadResult] = None
    error: Optional[str] = None
