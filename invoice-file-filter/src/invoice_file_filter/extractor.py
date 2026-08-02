"""PDF invoice detection and file listing (pdfplumber for keyword matching)."""

from __future__ import annotations

import base64
import csv
import io
import logging
import os
import re
import threading
import time
import unicodedata
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pdfplumber
from pdfminer.pdfexceptions import PDFException

from .config import get_settings
from .models import ProcessedFile

logger = logging.getLogger(__name__)

_MIN_WORD_LEN = 3

# In-memory caches: path → (mtime, cached_at, data)
_words_cache: dict[str, tuple[float, float, str]] = {}
_text_cache: dict[str, tuple[float, float, str]] = {}
_page_count_cache: dict[str, tuple[float, float, int]] = {}

# pypdfium2 (pdfplumber's page.to_image() backend) is not safe to call
# concurrently from multiple threads — process_directory's worker pool can
# segfault the process without this. Text extraction (pdfminer, used by
# extract_text/get_page_count) doesn't touch pdfium and needs no lock.
_pdfium_lock = threading.Lock()

try:
    from .ocr import ocr_extract_words, ocr_pdf
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False


def _fold(text: str) -> str:
    """Strip diacritics so accented and unaccented labels match identically."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def get_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF (0 if it cannot be read)."""
    try:
        mtime = os.path.getmtime(pdf_path)
    except OSError:
        mtime = 0.0

    ttl = get_settings().cache_ttl_seconds
    entry = _page_count_cache.get(pdf_path)
    if entry is not None:
        cached_mtime, cached_at, cached_count = entry
        if cached_mtime == mtime and time.time() - cached_at < ttl:
            logger.debug("page count cache hit: %s", pdf_path)
            return cached_count

    try:
        with pdfplumber.open(pdf_path) as pdf:
            count = len(pdf.pages)
    except (OSError, PDFException) as exc:
        logger.warning("Could not read page count from %s: %s", pdf_path, exc)
        count = 0

    _page_count_cache[pdf_path] = (mtime, time.time(), count)
    return count


def extract_words_csv(pdf_path: str) -> str:
    """Return distinct, normalised words from a PDF as single-column CSV (header: word).

    Words are lower-cased and diacritics are stripped so accented and unaccented
    variants collapse to the same token.  Results are cached by mtime.
    """
    try:
        mtime = os.path.getmtime(pdf_path)
    except OSError:
        mtime = 0.0

    ttl = get_settings().cache_ttl_seconds
    words_entry = _words_cache.get(pdf_path)
    if words_entry is not None:
        cached_mtime, cached_at, cached_csv = words_entry
        if cached_mtime == mtime and time.time() - cached_at < ttl:
            logger.debug("words cache hit: %s", pdf_path)
            return cached_csv

    raw_words: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for word in page.extract_words():
                    raw_words.append(word["text"])
    except (OSError, PDFException) as exc:
        logger.warning("Could not extract words from %s: %s", pdf_path, exc)

    if not raw_words and _OCR_AVAILABLE:
        settings = get_settings()
        if settings.ocr_enabled:
            logger.info("No words from pdfplumber in %s — falling back to OCR", pdf_path)
            raw_words = ocr_extract_words(pdf_path, settings.ocr_language)

    normalised = sorted({_fold(w).lower() for w in raw_words if len(w.strip()) >= _MIN_WORD_LEN})

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["word"])
    for w in normalised:
        writer.writerow([w])

    csv_data = buf.getvalue()
    _words_cache[pdf_path] = (mtime, time.time(), csv_data)
    return csv_data


def words_cache_info() -> dict[str, object]:
    """Return stats about the current words cache."""
    return {"entries": len(_words_cache), "paths": list(_words_cache.keys())}


def clear_words_cache() -> int:
    """Evict all entries from the words cache; return the number removed."""
    count = len(_words_cache)
    _words_cache.clear()
    return count


def extract_text(pdf_path: str) -> str:
    """Return all text from a PDF, falling back to OCR for scanned pages.

    pdfplumber is tried first. If the extracted text is shorter than
    ``settings.ocr_min_chars`` and OCR is enabled, Tesseract is used instead.
    Results are cached by mtime.
    """
    try:
        mtime = os.path.getmtime(pdf_path)
    except OSError:
        mtime = 0.0

    ttl = get_settings().cache_ttl_seconds
    text_entry = _text_cache.get(pdf_path)
    if text_entry is not None:
        cached_mtime, cached_at, cached_text = text_entry
        if cached_mtime == mtime and time.time() - cached_at < ttl:
            logger.debug("text cache hit: %s", pdf_path)
            return cached_text

    try:
        with pdfplumber.open(pdf_path) as pdf:
            parts = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(parts)
    except (OSError, PDFException) as exc:
        logger.warning("Could not extract text from %s: %s", pdf_path, exc)
        text = ""

    settings = get_settings()
    if len(text.strip()) < settings.ocr_min_chars and settings.ocr_enabled and _OCR_AVAILABLE:
        logger.info("Sparse text (%d chars) in %s — trying OCR", len(text.strip()), pdf_path)
        text = ocr_pdf(pdf_path, settings.ocr_language)

    _text_cache[pdf_path] = (mtime, time.time(), text)
    return text


def is_invoice(filename: str, text: str, keywords: Sequence[str] | None = None) -> bool:
    """True if the filename or text contains an invoice keyword (whole-word match).

    Underscores and hyphens are treated as word separators so that filenames
    like ``2026_invoice_42.pdf`` match the keyword ``invoice``.
    """
    kws = [_fold(k).lower() for k in (keywords or get_settings().invoice_keywords)]
    raw = _fold(f"{filename}\n{text}").lower()
    haystack = re.sub(r"[_\-]", " ", raw)
    return any(re.search(r"\b" + re.escape(kw) + r"\b", haystack) for kw in kws)


def describe_file(pdf_path: str) -> ProcessedFile:
    """Return the filename, absolute path, modification date and size of a PDF file."""
    abs_path = os.path.abspath(pdf_path)
    modified = datetime.fromtimestamp(os.path.getmtime(abs_path), tz=UTC).astimezone()
    size = os.path.getsize(abs_path)
    try:
        with pdfplumber.open(abs_path) as pdf:
            if len(pdf.pages) > 0:
                page = pdf.pages[0]
                with _pdfium_lock:
                    img = page.to_image(resolution=72)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                preview_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:  # noqa: BLE001 - best-effort preview: pdf2image/Pillow/pdfplumber failure surfaces are broad (e.g. PopplerNotInstalledError, which is a plain Exception subclass); swallow any failure and return None
        logger.warning("Could not generate preview for %s: %s", abs_path, e)
        preview_base64 = None
    
    if preview_base64:
        logger.info("Preview base64 generated successfully for %s", os.path.basename(abs_path))
    else:
        logger.info("Preview base64 generation failed for %s", os.path.basename(abs_path))
    
    return ProcessedFile(
        filename=os.path.basename(abs_path),
        path=abs_path,
        modified=modified,
        file_size=size,
        preview_base64=preview_base64,
    )


def _iter_pdf_paths(paths_or_dir: str | Path | Sequence[str | Path]) -> list[str]:
    """Normalize input (a directory, a single path, or a list) to PDF paths."""
    if isinstance(paths_or_dir, (str, Path)):
        p = Path(paths_or_dir)
        if p.is_dir():
            return sorted(str(f) for f in p.glob("*.[pP][dD][fF]"))
        return [str(p)] if p.suffix.lower() == ".pdf" else []
    out: list[str] = []
    for item in paths_or_dir:
        out.extend(_iter_pdf_paths(item))
    return out


def _process_one(pdf_path: str, kws: Sequence[str]) -> ProcessedFile | None:
    """Classify and describe a single PDF; ``None`` if it's not a kept invoice."""
    filename = os.path.basename(pdf_path)
    page_count = get_page_count(pdf_path)
    text = extract_text(pdf_path)
    if not is_invoice(filename, text, kws):
        logger.info("Skipping non-invoice file: %s", filename)
        return None
    if page_count == 0 or page_count > 5:
        logger.warning("Skipping file (%d pages): %s", page_count, filename)
        return None
    return describe_file(pdf_path)


def process_directory(
    paths_or_dir: str | Path | Sequence[str | Path],
    keywords: Sequence[str] | None = None,
) -> list[ProcessedFile]:
    """Select invoice PDFs among the given paths/dir and list them.

    ``paths_or_dir`` may be a directory, a single PDF path, or an iterable of
    paths (e.g. the ``saved_path`` list returned by attachment-downloader).

    Per-file work (pdfplumber text extraction, Tesseract OCR fallback,
    preview rendering) is spread across a thread pool — each of those calls
    is subprocess/IO-bound (tesseract, poppler) and releases the GIL while
    waiting, so this cuts wall-clock time roughly by ``extract_workers`` on
    multi-file syncs instead of processing PDFs one at a time.
    """
    kws = list(keywords) if keywords else get_settings().invoice_keywords
    pdf_paths = _iter_pdf_paths(paths_or_dir)
    if not pdf_paths:
        return []
    workers = max(1, get_settings().extract_workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processed = pool.map(lambda pdf_path: _process_one(pdf_path, kws), pdf_paths)
    return [pf for pf in processed if pf is not None]
