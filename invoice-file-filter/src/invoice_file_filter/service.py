"""Orchestration shared by the API and CLI: download (optional) + extract."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Optional

from .client import AttachmentDownloaderClient
from .config import Settings, get_settings
from .extractor import process_directory
from .models import ExtractRequest, ExtractResponse

logger = logging.getLogger(__name__)


def _default_dates(start: Optional[str], end: Optional[str]) -> tuple[str, str]:
    """Default to the last 30 days when dates are omitted."""
    end_obj = date.fromisoformat(end) if end else date.today()
    start_obj = date.fromisoformat(start) if start else end_obj - timedelta(days=30)
    return start_obj.isoformat(), end_obj.isoformat()


def run_extract(
    request: ExtractRequest, settings: Optional[Settings] = None
) -> ExtractResponse:
    """Run an extraction: optionally download via attachment-downloader, then parse.

    When ``request.download`` is True (default) the last-30-days window is used
    unless explicit dates are given. When False, PDFs already present in
    ``output_dir`` are processed directly.
    """
    settings = settings or get_settings()
    output_dir = request.output_dir or settings.output_dir
    t0 = time.monotonic()

    if request.download:
        start, end = _default_dates(request.start_date, request.end_date)
        logger.info("Downloading PDFs %s .. %s via attachment-downloader", start, end)
        client = AttachmentDownloaderClient(settings)
        paths = client.download(start, end, output_dir)
        source: object = paths if paths else output_dir
    else:
        logger.info("Processing existing PDFs in %s", output_dir)
        source = output_dir

    files = process_directory(source, settings.invoice_keywords)
    total_files = len(paths) if request.download else _count_pdfs(output_dir)
    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(
        "Extraction complete: %d invoice(s) from %d file(s) in %.0fms",
        len(files), total_files, elapsed_ms,
    )
    return ExtractResponse(
        total_files=total_files,
        invoice_count=len(files),
        output_dir=output_dir,
        files=files,
    )


def _count_pdfs(output_dir: str) -> int:
    from pathlib import Path

    p = Path(output_dir)
    return len(list(p.glob("*.pdf"))) if p.is_dir() else 0
