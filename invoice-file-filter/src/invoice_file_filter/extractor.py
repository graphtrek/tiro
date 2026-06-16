"""PDF invoice detection and file listing (pdfplumber for keyword matching)."""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pdfplumber

from .config import get_settings
from .models import ProcessedFile

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = ["invoice", "bill", "szamla", "számla", "számviteli bizonylat"]

# In-memory word cache: path → (mtime, csv_data)
_words_cache: Dict[str, Tuple[float, str]] = {}


def _fold(text: str) -> str:
    """Strip diacritics so accented and unaccented labels match identically."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def get_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF (0 if it cannot be read)."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception as exc:
        logger.warning("Could not read page count from %s: %s", pdf_path, exc)
        return 0


def extract_words_csv(pdf_path: str) -> str:
    """Return all words from a PDF as CSV with columns: page,word,x0,top,x1,bottom.

    Results are cached by file path keyed on mtime; stale entries are evicted automatically.
    """
    try:
        mtime = os.path.getmtime(pdf_path)
    except OSError:
        mtime = 0.0

    cached_mtime, cached_csv = _words_cache.get(pdf_path, (None, None))
    if cached_mtime == mtime and cached_csv is not None:
        logger.debug("words cache hit: %s", pdf_path)
        return cached_csv

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["page", "word", "x0", "top", "x1", "bottom"])
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                for word in page.extract_words():
                    writer.writerow(
                        [page_num, word["text"], word["x0"], word["top"], word["x1"], word["bottom"]]
                    )
    except Exception as exc:
        logger.warning("Could not extract words from %s: %s", pdf_path, exc)
    csv_data = buf.getvalue()
    _words_cache[pdf_path] = (mtime, csv_data)
    return csv_data


def words_cache_info() -> dict:
    """Return stats about the current words cache."""
    return {"entries": len(_words_cache), "paths": list(_words_cache.keys())}


def clear_words_cache() -> int:
    """Evict all entries from the words cache; return the number removed."""
    count = len(_words_cache)
    _words_cache.clear()
    return count


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
    """True if the filename or text contains an invoice keyword (whole-word match).

    Underscores and hyphens are treated as word separators so that filenames
    like ``2026_invoice_42.pdf`` match the keyword ``invoice``.
    """
    kws = [_fold(k).lower() for k in (keywords or DEFAULT_KEYWORDS)]
    raw = _fold(f"{filename}\n{text}").lower()
    haystack = re.sub(r"[_\-]", " ", raw)
    return any(re.search(r"\b" + re.escape(kw) + r"\b", haystack) for kw in kws)


def describe_file(pdf_path: str) -> ProcessedFile:
    """Return the filename, absolute path and modification date of a PDF file."""
    modified = datetime.fromtimestamp(os.path.getmtime(pdf_path))
    return ProcessedFile(
        filename=os.path.basename(pdf_path),
        path=os.path.abspath(pdf_path),
        modified=modified,
    )


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
    paths (e.g. the ``saved_path`` list returned by attachment-downloader).
    """
    kws = list(keywords) if keywords else get_settings().invoice_keywords
    results: List[ProcessedFile] = []
    for pdf_path in _iter_pdf_paths(paths_or_dir):
        filename = os.path.basename(pdf_path)
        page_count = get_page_count(pdf_path)
        text = extract_text(pdf_path)
        if not is_invoice(filename, text, kws):
            logger.info("Skipping non-invoice file: %s", filename)
            continue
        if page_count == 0 or page_count > 2:
            logger.warning("Skipping file (%d pages): %s", page_count, filename)
            continue
        results.append(describe_file(pdf_path))
    return results
