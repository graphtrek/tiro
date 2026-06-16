"""Tesseract OCR fallback for scanned PDFs that yield no selectable text."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _import_deps():
    """Lazy import of OCR dependencies so the service starts even without them."""
    try:
        import pytesseract  # noqa: F401
        from pdf2image import convert_from_path  # noqa: F401
        return pytesseract, convert_from_path
    except ImportError as exc:
        raise RuntimeError(
            "OCR dependencies not installed. Run: uv add pytesseract pdf2image Pillow"
        ) from exc


def ocr_pdf(pdf_path: str, language: str = "hun+eng") -> str:
    """Convert each page of a PDF to an image and run Tesseract OCR.

    Returns the concatenated text from all pages, or an empty string if OCR
    fails (e.g. Tesseract binary not on PATH, corrupt PDF).
    """
    try:
        pytesseract, convert_from_path = _import_deps()
    except RuntimeError as exc:
        logger.warning("OCR unavailable: %s", exc)
        return ""

    try:
        images = convert_from_path(pdf_path)
    except Exception as exc:
        logger.warning("pdf2image failed for %s: %s", pdf_path, exc)
        return ""

    parts: list[str] = []
    for i, img in enumerate(images, start=1):
        try:
            text = pytesseract.image_to_string(img, lang=language)
            parts.append(text)
        except Exception as exc:
            logger.warning("Tesseract failed on page %d of %s: %s", i, pdf_path, exc)

    result = "\n".join(parts)
    logger.debug("OCR extracted %d chars from %s", len(result), pdf_path)
    return result


def ocr_extract_words(pdf_path: str, language: str = "hun+eng") -> list[str]:
    """Extract raw word strings from a scanned PDF via Tesseract.

    Returns a flat list of non-empty words; empty list if OCR is unavailable or fails.
    """
    try:
        pytesseract, convert_from_path = _import_deps()
    except RuntimeError as exc:
        logger.warning("OCR unavailable: %s", exc)
        return []

    try:
        images = convert_from_path(pdf_path)
    except Exception as exc:
        logger.warning("pdf2image failed for %s: %s", pdf_path, exc)
        return []

    words: list[str] = []
    for page_num, img in enumerate(images, start=1):
        try:
            data = pytesseract.image_to_data(
                img, lang=language, output_type=pytesseract.Output.DICT
            )
            for i, text in enumerate(data["text"]):
                if int(data["conf"][i]) == -1 or not text.strip():
                    continue
                words.append(text.strip())
        except Exception as exc:
            logger.warning(
                "Tesseract word extraction failed on page %d of %s: %s", page_num, pdf_path, exc
            )

    logger.debug("OCR extracted %d raw words from %s", len(words), pdf_path)
    return words
