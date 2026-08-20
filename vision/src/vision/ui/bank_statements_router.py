"""Bankkivonat PDF UI routes served by vision (consumes uploader REST API)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from vision.clients.uploader import UploaderClient
from vision.ui.utils import is_anonymized

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui", tags=["bank-statements-ui"])
logger = logging.getLogger(__name__)

_FAKE_WORDS = [
    "kobalt",
    "gyanant",
    "opal",
    "korall",
    "azur",
    "smaragd",
    "borostyan",
    "zafir",
    "rubin",
    "gyongy",
    "kvarc",
    "onix",
    "topaz",
    "malachit",
    "jade",
]


def _uploader_client() -> UploaderClient:
    return UploaderClient()


def _fake_statement_filename(real: str) -> str:
    """Deterministic fake filename — same real filename always maps to the
    same fake one, mirroring invoice-core's `fake_identifier()` scheme, but
    the real bank account/IBAN encoded in the filename never leaves this
    function."""
    _, _, ext = real.rpartition(".")
    digest = hashlib.sha256(f"bank_statement_filename:{real.strip().lower()}".encode()).hexdigest()
    word = _FAKE_WORDS[int(digest[:2], 16) % len(_FAKE_WORDS)]
    suffix = digest[2:8]
    return f"{word}_{suffix}.{ext}" if ext else f"{word}_{suffix}"


def _anonymize_files(files: list[dict]) -> list[dict]:
    return [{**f, "filename": _fake_statement_filename(f["filename"])} for f in files]


@router.get("/bank-statements")
def bank_statements_page(request: Request):
    """Bankkivonat PDF-ek oldala."""
    uc = _uploader_client()
    files = uc.list_pdf_statements() or []
    anonymized = is_anonymized(request)
    if anonymized:
        files = _anonymize_files(files)
    return templates.TemplateResponse(
        request,
        "bank_statements.html",
        {"files": files, "anonymized": anonymized},
    )


@router.post("/bank-statements/upload", response_class=HTMLResponse)
async def do_upload_bank_statement(
    request: Request,
    file: UploadFile = File(...),
    bank: str | None = Form(None),
    overwrite: bool = Form(False),
):
    """HTMX endpoint: PDF bankkivonat feltöltése és eredmény partial visszaadása."""
    uc = _uploader_client()
    data = await file.read()
    result = uc.upload_pdf_statement(
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
            f"({result['bank'].upper()}, {result['from_date']} - {result['to_date']})"
            f"</div>"
            f'<div hx-get="/ui/bank-statements/table" hx-trigger="load" '
            f'hx-target="#table-container" hx-swap="innerHTML"></div>'
        )
    return HTMLResponse(content=html)


@router.get("/bank-statements/table", response_class=HTMLResponse)
def bank_statements_table_partial(request: Request):
    """HTMX partial: tárolt PDF bankkivonatok táblázata."""
    uc = _uploader_client()
    files = uc.list_pdf_statements() or []
    anonymized = is_anonymized(request)
    if anonymized:
        files = _anonymize_files(files)
    return templates.TemplateResponse(
        request,
        "partials/bank_statement_table.html",
        {"files": files, "anonymized": anonymized},
    )


@router.get("/bank-statements/{bank}/{filename}/download")
def download_bank_statement(request: Request, bank: str, filename: str):
    """PDF bankkivonat letöltése az uploader szervizről."""
    if is_anonymized(request):
        raise HTTPException(
            status_code=403,
            detail="Anonimizált nézetben a bankkivonat PDF letöltése nem engedélyezett.",
        )
    uc = _uploader_client()
    url = f"{uc.base_url}/api/v1/pdf/files/{bank}/{filename}/download"

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
        status_code=resp.status_code,
    )


@router.delete("/bank-statements/{bank}/{filename}", response_class=HTMLResponse)
def delete_bank_statement(request: Request, bank: str, filename: str):
    """HTMX endpoint: PDF bankkivonat törlése — a teljes táblázatot rerendereli."""
    uc = _uploader_client()
    uc.delete_pdf_statement(bank=bank, filename=filename)
    files = uc.list_pdf_statements() or []
    anonymized = is_anonymized(request)
    if anonymized:
        files = _anonymize_files(files)
    return templates.TemplateResponse(
        request,
        "partials/bank_statement_table.html",
        {"files": files, "anonymized": anonymized},
    )
