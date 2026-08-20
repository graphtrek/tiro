"""FastAPI app az uploader mikroszervizhez."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from uploader.auth import require_auth
from uploader.config import configure_logging, get_settings
from uploader.detector import detect_bank, parse_pdf_statement
from uploader.models import (
    PdfStatementFile,
    PdfUploadResult,
    StorageFile,
    StorageStatus,
    UploadResult,
)
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

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Uploader - Bankkivonat Feltöltő Mikroszerviz",
    description=(
        "Erste és Wise CSV bankkivonatok feltöltése a bank szerviz "
        "balance-statements/ tároló mappájába."
    ),
    version="0.1.0",
    dependencies=[Depends(require_auth)],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    logger.info("%s %s → %d in %.0fms", request.method, path, response.status_code, elapsed_ms)
    return response


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/settings")
def settings_info():
    s = get_settings()
    return {
        "storage_dir": s.storage_dir,
        "erste_subdir": s.erste_subdir,
        "wise_subdir": s.wise_subdir,
        "max_file_size_mb": s.max_file_size_mb,
        "api_port": s.api_port,
        "log_level": s.log_level,
    }


@app.get("/api/v1/files", response_model=StorageStatus)
def list_all_files():
    """Tárolt fájlok listája (minden bank)."""
    return get_storage_status()


@app.get("/api/v1/files/{bank}", response_model=list[StorageFile])
def list_bank_files(bank: str):
    """Adott bank fájljai (erste / wise)."""
    if bank not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=f"Ismeretlen bank: {bank!r}. Használható: erste, wise",
        )
    return list_files(bank=bank)


@app.post("/api/v1/upload", response_model=UploadResult)
async def upload_file(
    file: Annotated[UploadFile, File(description="CSV fájl")],
    bank: Annotated[str | None, Form()] = None,
    overwrite: Annotated[bool, Form()] = False,
):
    """CSV bankkivonat feltöltése."""
    s = get_settings()

    if not file.filename:
        raise HTTPException(status_code=400, detail="Hiányzó fájlnév.")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Csak CSV fájl fogadható el.")

    max_bytes = s.max_file_size_mb * 1024 * 1024
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"A fájl mérete meghaladja a maximumot ({s.max_file_size_mb} MB).",
        )

    detected = bank or detect_bank(file.filename)
    if detected not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Nem felismerhető bankkivonat formátum: {file.filename!r}. "
                "Erste: <számlaszám>_YYYY-MM-DD_YYYY-MM-DD.csv, "
                "Wise: statement_<id>_<currency>_YYYY-MM-DD_YYYY-MM-DD.csv"
            ),
        )

    try:
        return save_file(
            data=data,
            filename=file.filename,
            bank=detected,
            overwrite=overwrite,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/files/{bank}/{filename}/download")
def download_file(bank: str, filename: str):
    """Fájl letöltése."""
    if bank not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=f"Ismeretlen bank: {bank!r}. Használható: erste, wise",
        )
    try:
        path = get_file_path(bank=bank, filename=filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name, media_type="text/csv")


@app.delete("/api/v1/files/{bank}/{filename}", status_code=204)
def delete_bank_file(bank: str, filename: str):
    """Fájl törlése."""
    if bank not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=f"Ismeretlen bank: {bank!r}. Használható: erste, wise",
        )
    try:
        delete_file(bank=bank, filename=filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/pdf/files", response_model=list[PdfStatementFile])
def list_all_pdf_files():
    """Tárolt PDF bankkivonatok listája (minden bank)."""
    return list_pdf_files()


@app.post("/api/v1/pdf/upload", response_model=PdfUploadResult)
async def upload_pdf_file(
    file: Annotated[UploadFile, File(description="PDF fájl")],
    bank: Annotated[str | None, Form()] = None,
    overwrite: Annotated[bool, Form()] = False,
):
    """PDF bankkivonat feltöltése."""
    s = get_settings()

    if not file.filename:
        raise HTTPException(status_code=400, detail="Hiányzó fájlnév.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Csak PDF fájl fogadható el.")

    max_bytes = s.max_file_size_mb * 1024 * 1024
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"A fájl mérete meghaladja a maximumot ({s.max_file_size_mb} MB).",
        )

    parsed = parse_pdf_statement(file.filename)
    if parsed is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Nem felismerhető bankkivonat PDF formátum: {file.filename!r}. "
                "Erste: <számlaszám>_YYYYMMDD_YYYYMMDD.pdf, "
                "Wise: statement_<id>_<currency>_YYYY-MM-DD_YYYY-MM-DD.pdf"
            ),
        )
    detected_bank, from_date, to_date = parsed
    detected = bank or detected_bank

    try:
        return save_pdf_file(
            data=data,
            filename=file.filename,
            bank=detected,
            from_date=from_date,
            to_date=to_date,
            overwrite=overwrite,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/pdf/files/{bank}/{filename}/download")
def download_pdf_file(bank: str, filename: str):
    """PDF fájl letöltése."""
    if bank not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=f"Ismeretlen bank: {bank!r}. Használható: erste, wise",
        )
    try:
        path = get_pdf_file_path(bank=bank, filename=filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name, media_type="application/pdf")


@app.delete("/api/v1/pdf/files/{bank}/{filename}", status_code=204)
def delete_pdf_bank_file(bank: str, filename: str):
    """PDF fájl törlése."""
    if bank not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=f"Ismeretlen bank: {bank!r}. Használható: erste, wise",
        )
    try:
        delete_pdf_file(bank=bank, filename=filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def run_server():
    import uvicorn

    s = get_settings()
    uvicorn.run("uploader.api.main:app", host=s.api_host, port=s.api_port, reload=True)


if __name__ == "__main__":
    run_server()
