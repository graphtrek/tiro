"""PDF invoice detection and file listing (pdfplumber for keyword matching)."""

from __future__ import annotations

import logging
import os
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

import pdfplumber

from .config import get_settings
from .models import ProcessedFile

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = ["invoice", "bill", "szamla", "számla"]


def _fold(text: str) -> str:
    """Strip diacritics so accented and unaccented labels match identically."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def extract_text(pdf_path: str) -> str:
    """Return all text from a PDF (empty string if it cannot be read)."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            parts = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(parts)
    except Exception as exc:  # corrupt/locked/scanned PDF
        logger.warning("Could not extract text from %s: %s", pdf_path, exc)
        return ""


def is_invoice(filename: str, text: str, keywords: Optional[Sequence[str]] = None) -> bool:
    """True if the filename or text contains an invoice keyword."""
    kws = [_fold(k).lower() for k in (keywords or DEFAULT_KEYWORDS)]
    haystack = _fold(f"{filename}\n{text}").lower()
    return any(kw in haystack for kw in kws)


def describe_file(pdf_path: str) -> ProcessedFile:
    """Return the original filename and modification date of a PDF file."""
    modified = datetime.fromtimestamp(os.path.getmtime(pdf_path))
    return ProcessedFile(filename=os.path.basename(pdf_path), modified=modified)


def _iter_pdf_paths(paths_or_dir) -> List[str]:
    """Normalize input (a directory, a single path, or a list) to PDF paths."""
    if isinstance(paths_or_dir, (str, Path)):
        p = Path(paths_or_dir)
        if p.is_dir():
            return sorted(str(f) for f in p.glob("*.pdf"))
        return [str(p)] if p.suffix.lower() == ".pdf" else []
    out: List[str] = []
    for item in paths_or_dir:
        out.extend(_iter_pdf_paths(item))
    return out


def process_directory(
    paths_or_dir, keywords: Optional[Sequence[str]] = None
) -> List[ProcessedFile]:
    """Select invoice PDFs among the given paths/dir and list them.

    ``paths_or_dir`` may be a directory, a single PDF path, or an iterable of
    paths (e.g. the ``saved_path`` list returned by graphtrek-email).
    """
    kws = list(keywords) if keywords else get_settings().invoice_keywords
    results: List[ProcessedFile] = []
    for pdf_path in _iter_pdf_paths(paths_or_dir):
        text = extract_text(pdf_path)
        filename = os.path.basename(pdf_path)
        if not is_invoice(filename, text, kws):
            logger.info("Skipping non-invoice file: %s", filename)
            continue
        results.append(describe_file(pdf_path))
    return results
