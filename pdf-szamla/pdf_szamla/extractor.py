"""PDF text extraction and invoice-metadata parsing (pdfplumber + regex)."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Sequence

import pdfplumber

from .config import get_settings
from .models import InvoiceMetadata

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = ["invoice", "szamla", "számla"]

# All label regexes run against accent-folded text (see _fold), so the Hungarian
# labels below are written without diacritics and match both accented invoices
# and accent-stripped ones (common in OCR / plain-text exports).

# Hungarian tax id: 12345678-1-01
TAX_ID_RE = re.compile(r"\b(\d{8}-\d-\d{2})\b")
# ISO-ish dates: 2026-05-01 / 2026.05.01 / 2026/05/01
DATE_RE = re.compile(r"\b(\d{4})[.\-/](\d{2})[.\-/](\d{2})\b")
# Invoice number, e.g. "Számlaszám: 2026-001", "Invoice No: INV-12"
INVOICE_NO_RE = re.compile(
    r"(?:szamla\s*sorszama|szamlaszam|invoice\s*(?:number|no\.?|#))\s*[:#]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9/\-]{2,})",
    re.IGNORECASE,
)
# Amount near a label. Captures Hungarian/space/comma grouped numbers.
NUMBER = r"([0-9][0-9.\s ]*[0-9](?:,[0-9]{1,2})?)"
TOTAL_RE = re.compile(
    r"(?:vegosszeg|osszesen|fizetendo|brutto|grand\s*total|total\s*due|total)"
    r"[^0-9]{0,12}?" + NUMBER,
    re.IGNORECASE,
)
VAT_RE = re.compile(
    r"(?:afa|vat)(?:\s*(?:osszege|amount))?[^0-9]{0,8}?" + NUMBER, re.IGNORECASE
)
DUE_RE = re.compile(
    r"(?:fizetesi\s*hatarido|payment\s*due|due\s*date)\s*[:]?\s*"
    r"(\d{4}[.\-/]\d{2}[.\-/]\d{2})",
    re.IGNORECASE,
)
CURRENCY_RE = re.compile(r"\b(HUF|EUR|USD|GBP)\b|(Ft)\b", re.IGNORECASE)


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


def _normalize_date(match: re.Match) -> str:
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _parse_amount(raw: str) -> Optional[float]:
    """Parse a Hungarian/European grouped number like '1 234 567,89'."""
    cleaned = raw.strip().replace(" ", "").replace(" ", "")
    # Strip thousands separators (space/dot), treat comma as decimal.
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_metadata(text: str, filename: str, saved_path: Optional[str] = None) -> InvoiceMetadata:
    """Parse invoice metadata out of raw PDF text and score confidence."""
    # Label matching is accent-insensitive; captured values (numbers, dates, tax
    # ids, currency) are ASCII, so reading them from the folded text is safe.
    text = _fold(text)
    invoice_number = None
    m = INVOICE_NO_RE.search(text)
    if m:
        invoice_number = m.group(1).strip()

    invoice_date = None
    dm = DATE_RE.search(text)
    if dm:
        invoice_date = _normalize_date(dm)

    payment_due = None
    due = DUE_RE.search(text)
    if due:
        d = DATE_RE.search(due.group(1))
        payment_due = _normalize_date(d) if d else due.group(1)

    tax_ids = TAX_ID_RE.findall(text)
    supplier_tax_id = tax_ids[0] if len(tax_ids) >= 1 else None
    customer_tax_id = tax_ids[1] if len(tax_ids) >= 2 else None

    amount_total = None
    tm = TOTAL_RE.search(text)
    if tm:
        amount_total = _parse_amount(tm.group(1))

    amount_vat = None
    vm = VAT_RE.search(text)
    if vm:
        amount_vat = _parse_amount(vm.group(1))

    currency = None
    cm = CURRENCY_RE.search(text)
    if cm:
        token = (cm.group(1) or cm.group(2) or "").upper()
        currency = "HUF" if token == "FT" else token or None

    # Confidence: weighted fraction of the four core fields found.
    core = [invoice_number, invoice_date, supplier_tax_id, amount_total]
    confidence = round(sum(1 for f in core if f is not None) / len(core), 2)

    return InvoiceMetadata(
        filename=filename,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        supplier_tax_id=supplier_tax_id,
        customer_tax_id=customer_tax_id,
        amount_total=amount_total,
        amount_vat=amount_vat,
        currency=currency,
        payment_due=payment_due,
        confidence=confidence,
        saved_path=saved_path,
    )


def extract_metadata(pdf_path: str) -> InvoiceMetadata:
    """Extract metadata from a single PDF file."""
    text = extract_text(pdf_path)
    return parse_metadata(text, filename=os.path.basename(pdf_path), saved_path=pdf_path)


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
) -> List[InvoiceMetadata]:
    """Select invoice PDFs among the given paths/dir and extract metadata.

    ``paths_or_dir`` may be a directory, a single PDF path, or an iterable of
    paths (e.g. the ``saved_path`` list returned by graphtrek-email).
    """
    kws = list(keywords) if keywords else get_settings().invoice_keywords
    results: List[InvoiceMetadata] = []
    for pdf_path in _iter_pdf_paths(paths_or_dir):
        text = extract_text(pdf_path)
        filename = os.path.basename(pdf_path)
        if not is_invoice(filename, text, kws):
            logger.info("Skipping non-invoice file: %s", filename)
            continue
        results.append(parse_metadata(text, filename=filename, saved_path=pdf_path))
    return results
