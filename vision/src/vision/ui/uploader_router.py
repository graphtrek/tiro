"""Uploader UI routes served by vision (consumes uploader REST API)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from vision.clients.uploader import UploaderClient
from vision.ui.utils import redirect_if_readonly

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui", tags=["uploader-ui"])
logger = logging.getLogger(__name__)


def _uploader_client() -> UploaderClient:
    return UploaderClient()


@router.get("/upload")
def upload_page(request: Request):
    """Feltöltési oldal."""
    if (redirect := redirect_if_readonly(request)) is not None:
        return redirect
    uc = _uploader_client()
    storage = uc.list_files()
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "storage": storage,
        },
    )


@router.post("/upload/do", response_class=HTMLResponse)
async def do_upload(
    request: Request,
    file: UploadFile = File(...),
    bank: str | None = Form(None),
    overwrite: bool = Form(False),
):
    """HTMX endpoint: fájl feltöltése és eredmény partial visszaadása."""
    uc = _uploader_client()
    data = await file.read()
    result = uc.upload_file(
        file_bytes=data,
        filename=file.filename or "",
        bank=bank or None,
        overwrite=overwrite,
    )
    if result is None:
        html = (
            '<div class="alert alert-danger">'
            '<i class="bi bi-x-circle me-2"></i>'
            "Feltöltés sikertelen — az uploader szerviz nem elérhető."
            "</div>"
        )
    elif "error" in result:
        html = (
            '<div class="alert alert-danger">'
            '<i class="bi bi-x-circle me-2"></i>'
            f"Feltöltés sikertelen: {result['error']}"
            "</div>"
        )
    else:
        action = "Felülírva" if result.get("overwritten") else "Feltöltve"
        html = (
            f'<div class="alert alert-success">'
            f'<i class="bi bi-check-circle me-2"></i>'
            f"<strong>{action}:</strong> {result['filename']} "
            f"({result['bank'].upper()}, {result['size_bytes']:,} bájt)"
            f"</div>"
            f'<div hx-get="/ui/upload/files" hx-trigger="load" hx-swap="outerHTML"></div>'
        )
    return HTMLResponse(content=html)


@router.get("/upload/files", response_class=HTMLResponse)
def upload_files_partial(request: Request):
    """HTMX partial: tárolt fájlok táblázata."""
    if (redirect := redirect_if_readonly(request)) is not None:
        return redirect
    uc = _uploader_client()
    storage = uc.list_files()
    return templates.TemplateResponse(
        request,
        "partials/upload_files.html",
        {"storage": storage},
    )


@router.get("/upload/files/{bank}/{filename}/download")
def download_file(request: Request, bank: str, filename: str):
    """Fájl letöltése az uploader szervizről."""
    if (redirect := redirect_if_readonly(request)) is not None:
        return redirect
    uc = _uploader_client()
    url = f"{uc.base_url}/api/v1/files/{bank}/{filename}/download"

    resp = uc.session.get(url, stream=True, timeout=uc.timeout)
    resp.raise_for_status()

    allowed_headers = ("content-disposition", "content-type")
    headers = {k: v for k, v in resp.headers.items() if k.lower() in allowed_headers}

    def generator():
        try:
            yield from resp.iter_content(chunk_size=8192)
        finally:
            resp.close()

    return StreamingResponse(
        generator(),
        headers=headers,
        status_code=resp.status_code
    )


@router.delete("/upload/files/{bank}/{filename}", response_class=HTMLResponse)
def delete_file(request: Request, bank: str, filename: str):
    """HTMX endpoint: fájl törlése."""
    uc = _uploader_client()
    ok = uc.delete_file(bank=bank, filename=filename)
    if not ok:
        return HTMLResponse(
            content=(
                '<tr><td colspan="5"><span class="text-danger">Törlés sikertelen.</span></td></tr>'
            )
        )
    return HTMLResponse(content="")
