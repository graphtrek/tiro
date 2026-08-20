"""storage.py egységtesztek (fájlrendszer műveletek tmp_path alatt)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from uploader.config import Settings
from uploader.storage import (
    delete_file,
    delete_pdf_file,
    get_file_path,
    get_pdf_file_path,
    get_storage_status,
    list_files,
    list_pdf_files,
    save_file,
    save_pdf_file,
)

CSV_BYTES = b"date,amount\n2026-05-01,100\n"
PDF_BYTES = b"%PDF-1.4 fake pdf content"


def test_save_file_creates_bank_subdir_and_result(settings: Settings):
    result = save_file(CSV_BYTES, "a_2026-05-01_2026-05-31.csv", "erste", settings=settings)

    assert result.bank == "erste"
    assert result.filename == "a_2026-05-01_2026-05-31.csv"
    assert result.size_bytes == len(CSV_BYTES)
    assert result.overwritten is False
    assert (
        Path(settings.storage_dir) / "erste" / "a_2026-05-01_2026-05-31.csv"
    ).read_bytes() == CSV_BYTES


def test_save_file_existing_without_overwrite_raises(settings: Settings):
    save_file(CSV_BYTES, "dup.csv", "wise", settings=settings)
    with pytest.raises(FileExistsError):
        save_file(CSV_BYTES, "dup.csv", "wise", settings=settings)


def test_save_file_existing_with_overwrite_replaces(settings: Settings):
    save_file(CSV_BYTES, "dup.csv", "wise", settings=settings)
    result = save_file(b"new,data\n", "dup.csv", "wise", overwrite=True, settings=settings)

    assert result.overwritten is True
    assert (Path(settings.storage_dir) / "wise" / "dup.csv").read_bytes() == b"new,data\n"


def test_list_files_filters_by_bank(settings: Settings):
    save_file(CSV_BYTES, "e1.csv", "erste", settings=settings)
    save_file(CSV_BYTES, "w1.csv", "wise", settings=settings)

    erste_files = list_files(bank="erste", settings=settings)
    assert [f.filename for f in erste_files] == ["e1.csv"]
    assert erste_files[0].bank == "erste"


def test_list_files_all_combines_both_banks(settings: Settings):
    save_file(CSV_BYTES, "e1.csv", "erste", settings=settings)
    save_file(CSV_BYTES, "w1.csv", "wise", settings=settings)

    all_files = list_files(bank="all", settings=settings)
    assert {f.filename for f in all_files} == {"e1.csv", "w1.csv"}


def test_list_files_ignores_non_csv(settings: Settings):
    save_file(CSV_BYTES, "e1.csv", "erste", settings=settings)
    (Path(settings.storage_dir) / "erste" / "notes.txt").write_text("ignore me")

    erste_files = list_files(bank="erste", settings=settings)
    assert [f.filename for f in erste_files] == ["e1.csv"]


def test_get_storage_status_totals(settings: Settings):
    save_file(CSV_BYTES, "e1.csv", "erste", settings=settings)
    save_file(CSV_BYTES, "w1.csv", "wise", settings=settings)
    save_file(CSV_BYTES, "w2.csv", "wise", settings=settings)

    status = get_storage_status(settings=settings)
    assert status.total_files == 3
    assert len(status.banks["erste"]) == 1
    assert len(status.banks["wise"]) == 2
    assert status.storage_dir == settings.storage_dir


def test_delete_file_removes_existing(settings: Settings):
    save_file(CSV_BYTES, "e1.csv", "erste", settings=settings)
    delete_file("erste", "e1.csv", settings=settings)

    assert list_files(bank="erste", settings=settings) == []


def test_delete_file_missing_raises(settings: Settings):
    with pytest.raises(FileNotFoundError):
        delete_file("erste", "missing.csv", settings=settings)


def test_get_file_path_returns_existing(settings: Settings):
    save_file(CSV_BYTES, "e1.csv", "erste", settings=settings)
    path = get_file_path("erste", "e1.csv", settings=settings)

    assert path.read_bytes() == CSV_BYTES


def test_get_file_path_missing_raises(settings: Settings):
    with pytest.raises(FileNotFoundError):
        get_file_path("erste", "missing.csv", settings=settings)


def test_get_file_path_sanitizes_path_traversal(settings: Settings):
    """A '../' próbálkozás nem szökhet ki a bank alkönyvtárból."""
    save_file(CSV_BYTES, "e1.csv", "erste", settings=settings)

    with pytest.raises(FileNotFoundError):
        get_file_path("erste", "../../../etc/passwd", settings=settings)


def test_save_pdf_file_creates_bank_subdir_and_result(settings: Settings):
    result = save_pdf_file(
        PDF_BYTES,
        "HU92116000060000000197860425_20260701_20260731.pdf",
        "erste",
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
        settings=settings,
    )

    assert result.bank == "erste"
    assert result.from_date == date(2026, 7, 1)
    assert result.to_date == date(2026, 7, 31)
    assert result.overwritten is False
    assert (
        Path(settings.pdf_storage_dir)
        / "erste"
        / "HU92116000060000000197860425_20260701_20260731.pdf"
    ).read_bytes() == PDF_BYTES


def test_save_pdf_file_existing_without_overwrite_raises(settings: Settings):
    save_pdf_file(
        PDF_BYTES,
        "dup.pdf",
        "wise",
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
        settings=settings,
    )
    with pytest.raises(FileExistsError):
        save_pdf_file(
            PDF_BYTES,
            "dup.pdf",
            "wise",
            from_date=date(2026, 7, 1),
            to_date=date(2026, 7, 31),
            settings=settings,
        )


def test_list_pdf_files_parses_dates(settings: Settings):
    save_pdf_file(
        PDF_BYTES,
        "HU92116000060000000197860425_20260701_20260731.pdf",
        "erste",
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
        settings=settings,
    )
    save_pdf_file(
        PDF_BYTES,
        "statement_25546267_HUF_2026-07-01_2026-07-31.pdf",
        "wise",
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
        settings=settings,
    )

    files = list_pdf_files(bank="all", settings=settings)
    assert {f.filename for f in files} == {
        "HU92116000060000000197860425_20260701_20260731.pdf",
        "statement_25546267_HUF_2026-07-01_2026-07-31.pdf",
    }
    erste_file = next(f for f in files if f.bank == "erste")
    assert erste_file.from_date == date(2026, 7, 1)
    assert erste_file.to_date == date(2026, 7, 31)


def test_delete_pdf_file_removes_existing(settings: Settings):
    save_pdf_file(
        PDF_BYTES,
        "HU92116000060000000197860425_20260701_20260731.pdf",
        "erste",
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
        settings=settings,
    )
    delete_pdf_file(
        "erste", "HU92116000060000000197860425_20260701_20260731.pdf", settings=settings
    )

    assert list_pdf_files(bank="erste", settings=settings) == []


def test_delete_pdf_file_missing_raises(settings: Settings):
    with pytest.raises(FileNotFoundError):
        delete_pdf_file("erste", "missing.pdf", settings=settings)


def test_get_pdf_file_path_sanitizes_path_traversal(settings: Settings):
    save_pdf_file(
        PDF_BYTES,
        "HU92116000060000000197860425_20260701_20260731.pdf",
        "erste",
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
        settings=settings,
    )

    with pytest.raises(FileNotFoundError):
        get_pdf_file_path("erste", "../../../etc/passwd", settings=settings)
