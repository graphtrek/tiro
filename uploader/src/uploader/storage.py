"""Fájlrendszer műveletek: mentés, lista, törlés."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from uploader.config import Settings, get_settings
from uploader.detector import parse_pdf_statement
from uploader.models import (
    PdfStatementFile,
    PdfUploadResult,
    StorageFile,
    StorageStatus,
    UploadResult,
)

logger = logging.getLogger(__name__)


def _bank_dir(bank: str, settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    subdir = s.erste_subdir if bank == "erste" else s.wise_subdir
    d = Path(s.storage_dir) / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pdf_bank_dir(bank: str, settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    subdir = s.erste_subdir if bank == "erste" else s.wise_subdir
    d = Path(s.pdf_storage_dir) / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_file(
    data: bytes,
    filename: str,
    bank: str,
    overwrite: bool = False,
    settings: Settings | None = None,
) -> UploadResult:
    s = settings or get_settings()
    dest_dir = _bank_dir(bank, s)
    dest = dest_dir / filename
    overwritten = dest.exists()

    if overwritten and not overwrite:
        raise FileExistsError(f"A fájl már létezik: {filename}")

    dest.write_bytes(data)
    logger.info("Mentve: %s (%d bájt, overwrite=%s)", dest, len(data), overwritten)

    return UploadResult(
        filename=filename,
        bank=bank,
        saved_path=str(dest),
        size_bytes=len(data),
        overwritten=overwritten,
    )


def list_files(bank: str = "all", settings: Settings | None = None) -> list[StorageFile]:
    s = settings or get_settings()
    banks = ["erste", "wise"] if bank == "all" else [bank]
    result: list[StorageFile] = []
    for b in banks:
        d = _bank_dir(b, s)
        for path in sorted(d.glob("*.csv")):
            stat = path.stat()
            result.append(
                StorageFile(
                    bank=b,
                    filename=path.name,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    path=str(path),
                )
            )
    return result


def get_storage_status(settings: Settings | None = None) -> StorageStatus:
    s = settings or get_settings()
    banks: dict[str, list[StorageFile]] = {
        "erste": list_files("erste", s),
        "wise": list_files("wise", s),
    }
    total = sum(len(v) for v in banks.values())
    return StorageStatus(
        storage_dir=s.storage_dir,
        banks=banks,
        total_files=total,
    )


def delete_file(bank: str, filename: str, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    dest = _bank_dir(bank, s) / filename
    if not dest.exists():
        raise FileNotFoundError(f"Fájl nem található: {filename}")
    dest.unlink()
    logger.info("Törölve: %s", dest)


def get_file_path(bank: str, filename: str, settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    safe_name = Path(filename).name
    dest = _bank_dir(bank, s) / safe_name
    if not dest.exists():
        raise FileNotFoundError(f"Fájl nem található: {filename}")
    return dest


def save_pdf_file(
    data: bytes,
    filename: str,
    bank: str,
    from_date,
    to_date,
    overwrite: bool = False,
    settings: Settings | None = None,
) -> PdfUploadResult:
    s = settings or get_settings()
    dest_dir = _pdf_bank_dir(bank, s)
    dest = dest_dir / filename
    overwritten = dest.exists()

    if overwritten and not overwrite:
        raise FileExistsError(f"A fájl már létezik: {filename}")

    dest.write_bytes(data)
    logger.info("PDF mentve: %s (%d bájt, overwrite=%s)", dest, len(data), overwritten)

    return PdfUploadResult(
        filename=filename,
        bank=bank,
        from_date=from_date,
        to_date=to_date,
        saved_path=str(dest),
        size_bytes=len(data),
        overwritten=overwritten,
    )


def list_pdf_files(bank: str = "all", settings: Settings | None = None) -> list[PdfStatementFile]:
    s = settings or get_settings()
    banks = ["erste", "wise"] if bank == "all" else [bank]
    result: list[PdfStatementFile] = []
    for b in banks:
        d = _pdf_bank_dir(b, s)
        for path in sorted(d.glob("*.pdf")):
            parsed = parse_pdf_statement(path.name)
            if parsed is None:
                continue
            _, from_date, to_date = parsed
            stat = path.stat()
            result.append(
                PdfStatementFile(
                    bank=b,
                    filename=path.name,
                    from_date=from_date,
                    to_date=to_date,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    path=str(path),
                )
            )
    return result


def delete_pdf_file(bank: str, filename: str, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    dest = _pdf_bank_dir(bank, s) / filename
    if not dest.exists():
        raise FileNotFoundError(f"Fájl nem található: {filename}")
    dest.unlink()
    logger.info("PDF törölve: %s", dest)


def get_pdf_file_path(bank: str, filename: str, settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    safe_name = Path(filename).name
    dest = _pdf_bank_dir(bank, s) / safe_name
    if not dest.exists():
        raise FileNotFoundError(f"Fájl nem található: {filename}")
    return dest
