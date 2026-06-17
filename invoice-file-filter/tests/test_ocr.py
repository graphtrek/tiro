"""Tests for the OCR fallback path in extractor.extract_text() and extract_words_csv()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from invoice_file_filter.ocr import ocr_extract_words, ocr_pdf


class TestOcrPdf:
    def test_returns_tesseract_text(self):
        fake_image = MagicMock()
        with (
            patch("invoice_file_filter.ocr._import_deps") as mock_deps,
        ):
            mock_pytesseract = MagicMock()
            mock_pytesseract.image_to_string.return_value = "Számla\nÁFA: 27 000 Ft"
            mock_convert = MagicMock(return_value=[fake_image])
            mock_deps.return_value = (mock_pytesseract, mock_convert)

            result = ocr_pdf("/fake/invoice.pdf", language="hun+eng")

        assert "Számla" in result
        mock_pytesseract.image_to_string.assert_called_once_with(fake_image, lang="hun+eng")

    def test_multipage_concatenated(self):
        page1, page2 = MagicMock(), MagicMock()
        with patch("invoice_file_filter.ocr._import_deps") as mock_deps:
            mock_pytesseract = MagicMock()
            mock_pytesseract.image_to_string.side_effect = ["Page one text", "Page two text"]
            mock_convert = MagicMock(return_value=[page1, page2])
            mock_deps.return_value = (mock_pytesseract, mock_convert)

            result = ocr_pdf("/fake/multi.pdf")

        assert "Page one text" in result
        assert "Page two text" in result

    def test_missing_deps_returns_empty(self):
        with patch("invoice_file_filter.ocr._import_deps", side_effect=RuntimeError("no deps")):
            result = ocr_pdf("/fake/invoice.pdf")
        assert result == ""

    def test_pdf2image_failure_returns_empty(self):
        with patch("invoice_file_filter.ocr._import_deps") as mock_deps:
            mock_pytesseract = MagicMock()
            mock_convert = MagicMock(side_effect=Exception("poppler not found"))
            mock_deps.return_value = (mock_pytesseract, mock_convert)

            result = ocr_pdf("/fake/invoice.pdf")

        assert result == ""

    def test_tesseract_page_failure_skips_page(self):
        page1, page2 = MagicMock(), MagicMock()
        with patch("invoice_file_filter.ocr._import_deps") as mock_deps:
            mock_pytesseract = MagicMock()
            mock_pytesseract.image_to_string.side_effect = [Exception("tess crash"), "Good page"]
            mock_convert = MagicMock(return_value=[page1, page2])
            mock_deps.return_value = (mock_pytesseract, mock_convert)

            result = ocr_pdf("/fake/invoice.pdf")

        assert "Good page" in result


class TestExtractTextOcrFallback:
    """Verify extract_text() triggers OCR when pdfplumber yields sparse text."""

    def test_ocr_triggered_when_text_sparse(self, tmp_path):
        pdf = tmp_path / "scanned.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        with (
            patch("invoice_file_filter.extractor.pdfplumber") as mock_pdfplumber,
            patch("invoice_file_filter.extractor.get_settings") as mock_settings,
            patch("invoice_file_filter.extractor.ocr_pdf", return_value="OCR: Számla") as mock_ocr,
        ):
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""
            mock_pdfplumber.open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(pages=[mock_page])
            )
            mock_pdfplumber.open.return_value.__exit__ = MagicMock(return_value=False)
            settings = MagicMock()
            settings.ocr_enabled = True
            settings.ocr_min_chars = 50
            settings.ocr_language = "hun+eng"
            mock_settings.return_value = settings

            from invoice_file_filter.extractor import extract_text
            result = extract_text(str(pdf))

        assert result == "OCR: Számla"

    def test_ocr_skipped_when_text_sufficient(self, tmp_path):
        pdf = tmp_path / "digital.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        long_text = "Számla " * 20  # well over 50 chars

        with (
            patch("invoice_file_filter.extractor.pdfplumber") as mock_pdfplumber,
            patch("invoice_file_filter.extractor.get_settings") as mock_settings,
            patch("invoice_file_filter.ocr.ocr_pdf") as mock_ocr,
        ):
            mock_page = MagicMock()
            mock_page.extract_text.return_value = long_text
            mock_pdfplumber.open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(pages=[mock_page])
            )
            mock_pdfplumber.open.return_value.__exit__ = MagicMock(return_value=False)
            settings = MagicMock()
            settings.ocr_enabled = True
            settings.ocr_min_chars = 50
            mock_settings.return_value = settings

            from invoice_file_filter.extractor import extract_text
            result = extract_text(str(pdf))

        mock_ocr.assert_not_called()
        assert long_text in result

    def test_ocr_skipped_when_disabled(self, tmp_path):
        pdf = tmp_path / "scanned_disabled.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        with (
            patch("invoice_file_filter.extractor.pdfplumber") as mock_pdfplumber,
            patch("invoice_file_filter.extractor.get_settings") as mock_settings,
            patch("invoice_file_filter.ocr.ocr_pdf") as mock_ocr,
        ):
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""
            mock_pdfplumber.open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(pages=[mock_page])
            )
            mock_pdfplumber.open.return_value.__exit__ = MagicMock(return_value=False)
            settings = MagicMock()
            settings.ocr_enabled = False
            settings.ocr_min_chars = 50
            mock_settings.return_value = settings

            from invoice_file_filter.extractor import extract_text
            result = extract_text(str(pdf))

        mock_ocr.assert_not_called()
        assert result == ""


class TestOcrExtractWords:
    def _make_tesseract_data(self, words):
        return {
            "text": [w["text"] for w in words],
            "conf": [w.get("conf", 90) for w in words],
            "left": [w.get("left", 10) for w in words],
            "top": [w.get("top", 20) for w in words],
            "width": [w.get("width", 50) for w in words],
            "height": [w.get("height", 15) for w in words],
        }

    def test_returns_word_list(self):
        fake_image = MagicMock()
        data = self._make_tesseract_data([
            {"text": "Számla", "conf": 95},
            {"text": "ÁFA", "conf": 88},
        ])
        with patch("invoice_file_filter.ocr._import_deps") as mock_deps:
            mock_pytesseract = MagicMock()
            mock_pytesseract.Output.DICT = "dict"
            mock_pytesseract.image_to_data.return_value = data
            mock_convert = MagicMock(return_value=[fake_image])
            mock_deps.return_value = (mock_pytesseract, mock_convert)

            result = ocr_extract_words("/fake/invoice.pdf")

        assert "Számla" in result
        assert "ÁFA" in result

    def test_filters_empty_and_neg_conf(self):
        fake_image = MagicMock()
        data = self._make_tesseract_data([
            {"text": "Good", "conf": 80},
            {"text": "", "conf": -1},
            {"text": "   ", "conf": 90},
        ])
        with patch("invoice_file_filter.ocr._import_deps") as mock_deps:
            mock_pytesseract = MagicMock()
            mock_pytesseract.Output.DICT = "dict"
            mock_pytesseract.image_to_data.return_value = data
            mock_convert = MagicMock(return_value=[fake_image])
            mock_deps.return_value = (mock_pytesseract, mock_convert)

            result = ocr_extract_words("/fake/invoice.pdf")

        assert result == ["Good"]

    def test_missing_deps_returns_empty_list(self):
        with patch("invoice_file_filter.ocr._import_deps", side_effect=RuntimeError("no deps")):
            result = ocr_extract_words("/fake/invoice.pdf")
        assert result == []

    def test_multipage_collects_all_words(self):
        p1, p2 = MagicMock(), MagicMock()
        data1 = self._make_tesseract_data([{"text": "Eladó", "conf": 90}])
        data2 = self._make_tesseract_data([{"text": "Vevő", "conf": 90}])
        with patch("invoice_file_filter.ocr._import_deps") as mock_deps:
            mock_pytesseract = MagicMock()
            mock_pytesseract.Output.DICT = "dict"
            mock_pytesseract.image_to_data.side_effect = [data1, data2]
            mock_convert = MagicMock(return_value=[p1, p2])
            mock_deps.return_value = (mock_pytesseract, mock_convert)

            result = ocr_extract_words("/fake/multi.pdf")

        assert "Eladó" in result
        assert "Vevő" in result


class TestExtractWordsCsvOcrFallback:
    def test_output_is_single_column_normalised(self, tmp_path):
        pdf = tmp_path / "digital.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        with (
            patch("invoice_file_filter.extractor.pdfplumber") as mock_pdfplumber,
            patch("invoice_file_filter.extractor.get_settings") as mock_settings,
            patch("invoice_file_filter.extractor.os.path.getmtime", return_value=0.0),
        ):
            mock_page = MagicMock()
            mock_page.extract_words.return_value = [
                {"text": "Számla"},
                {"text": "számla"},   # duplicate after normalisation
                {"text": "ÁFA"},      # 3 chars → passes _MIN_WORD_LEN >= 3
                {"text": "db"},       # 2 chars → filtered out
            ]
            mock_pdfplumber.open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(pages=[mock_page])
            )
            mock_pdfplumber.open.return_value.__exit__ = MagicMock(return_value=False)
            settings = MagicMock()
            settings.ocr_enabled = True
            settings.ocr_language = "hun+eng"
            mock_settings.return_value = settings

            from invoice_file_filter.extractor import clear_words_cache, extract_words_csv
            clear_words_cache()
            result = extract_words_csv(str(pdf))

        lines = result.strip().splitlines()
        assert lines[0] == "word"
        assert "szamla" in lines            # accent stripped, lowercased
        assert lines.count("szamla") == 1   # deduplicated
        assert "afa" in lines               # 3 chars → passes (>= _MIN_WORD_LEN)
        assert "db" not in lines            # 2 chars → filtered

    def test_ocr_fallback_when_no_words(self, tmp_path):
        pdf = tmp_path / "scanned.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        with (
            patch("invoice_file_filter.extractor.pdfplumber") as mock_pdfplumber,
            patch("invoice_file_filter.extractor.get_settings") as mock_settings,
            patch("invoice_file_filter.extractor.os.path.getmtime", return_value=0.0),
            patch("invoice_file_filter.extractor.ocr_extract_words", return_value=["Számla", "Eladó"]) as mock_ocr,
        ):
            mock_page = MagicMock()
            mock_page.extract_words.return_value = []
            mock_pdfplumber.open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(pages=[mock_page])
            )
            mock_pdfplumber.open.return_value.__exit__ = MagicMock(return_value=False)
            settings = MagicMock()
            settings.ocr_enabled = True
            settings.ocr_language = "hun+eng"
            mock_settings.return_value = settings

            from invoice_file_filter.extractor import clear_words_cache, extract_words_csv
            clear_words_cache()
            result = extract_words_csv(str(pdf))

        assert "szamla" in result
        assert "elado" in result
        mock_ocr.assert_called_once()

    def test_no_ocr_when_words_found(self, tmp_path):
        pdf = tmp_path / "digital.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        with (
            patch("invoice_file_filter.extractor.pdfplumber") as mock_pdfplumber,
            patch("invoice_file_filter.extractor.get_settings") as mock_settings,
            patch("invoice_file_filter.extractor.os.path.getmtime", return_value=0.0),
            patch("invoice_file_filter.ocr.ocr_extract_words") as mock_ocr,
        ):
            mock_page = MagicMock()
            mock_page.extract_words.return_value = [{"text": "Számla"}]
            mock_pdfplumber.open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(pages=[mock_page])
            )
            mock_pdfplumber.open.return_value.__exit__ = MagicMock(return_value=False)
            settings = MagicMock()
            settings.ocr_enabled = True
            mock_settings.return_value = settings

            from invoice_file_filter.extractor import clear_words_cache, extract_words_csv
            clear_words_cache()
            result = extract_words_csv(str(pdf))

        mock_ocr.assert_not_called()

    def test_no_ocr_when_disabled(self, tmp_path):
        pdf = tmp_path / "scanned_disabled.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        with (
            patch("invoice_file_filter.extractor.pdfplumber") as mock_pdfplumber,
            patch("invoice_file_filter.extractor.get_settings") as mock_settings,
            patch("invoice_file_filter.extractor.os.path.getmtime", return_value=0.0),
            patch("invoice_file_filter.ocr.ocr_extract_words") as mock_ocr,
        ):
            mock_page = MagicMock()
            mock_page.extract_words.return_value = []
            mock_pdfplumber.open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(pages=[mock_page])
            )
            mock_pdfplumber.open.return_value.__exit__ = MagicMock(return_value=False)
            settings = MagicMock()
            settings.ocr_enabled = False
            mock_settings.return_value = settings

            from invoice_file_filter.extractor import clear_words_cache, extract_words_csv
            clear_words_cache()
            result = extract_words_csv(str(pdf))

        mock_ocr.assert_not_called()
        assert result.strip() == "word"
