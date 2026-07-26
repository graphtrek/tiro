"""storage.py egységtesztek (fájlrendszer műveletek tmp_path alatt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uploader.config import Settings
from uploader.storage import (
    delete_file,
    get_file_path,
    get_storage_status,
    list_files,
    save_file,
)

CSV_BYTES = b"date,amount\n2026-05-01,100\n"


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
