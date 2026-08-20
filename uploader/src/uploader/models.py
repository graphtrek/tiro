"""Uploader adatmodellek."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class UploadResult(BaseModel):
    filename: str
    bank: str
    saved_path: str
    size_bytes: int
    overwritten: bool


class StorageFile(BaseModel):
    bank: str
    filename: str
    size_bytes: int
    modified_at: datetime
    path: str


class StorageStatus(BaseModel):
    storage_dir: str
    banks: dict[str, list[StorageFile]]
    total_files: int


class PdfUploadResult(BaseModel):
    filename: str
    bank: str
    from_date: date
    to_date: date
    saved_path: str
    size_bytes: int
    overwritten: bool


class PdfStatementFile(BaseModel):
    bank: str
    filename: str
    from_date: date
    to_date: date
    size_bytes: int
    modified_at: datetime
    path: str
