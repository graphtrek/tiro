"""FastAPI app az uploader mikroszervizhez."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from uploader.auth import require_auth
from uploader.config import configure_logging, get_settings
from uploader.detector import detect_bank
from uploader.models import StorageFile, StorageStatus, UploadResult
from uploader.storage import (
    delete_file,
    get_file_path,
    get_storage_status,
    list_files,
    save_file,
)

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Uploader – Bankkivonat Feltöltő Mikroszerviz",
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
    logger.info(
        "%s %s → %d in %.0fms", request.method, path, response.status_code, elapsed_ms
    )
    return response


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


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
        raise HTTPException(status_code=400, detail=str(exc))


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
        raise HTTPException(status_code=404, detail=str(exc))
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
        raise HTTPException(status_code=404, detail=str(exc))


def run_server():
    import uvicorn

    s = get_settings()
    uvicorn.run("uploader.api.main:app", host=s.api_host, port=s.api_port, reload=True)


if __name__ == "__main__":
    run_server()
