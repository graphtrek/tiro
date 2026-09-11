"""Bankkivonat (PDF + CSV) UI routes served by vision (consumes uploader REST API)."""

from __future__ import annotations

import hashlib
import logging
import re
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


# Erste: <számlaszám>_YYYY-MM-DD_YYYY-MM-DD.csv
# Wise:  statement_<id>_<CCY>_YYYY-MM-DD_YYYY-MM-DD.csv
_CSV_PERIOD = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$", re.IGNORECASE)


def _csv_period(filename: str) -> tuple[str, str]:
    """Kivonat időszak a CSV fájlnévből — a PDF-eknél az uploader adja vissza,
    a CSV listánál viszont csak a fájlnév hordozza."""
    match = _CSV_PERIOD.search(filename.strip())
    return match.groups() if match else ("", "")


def _csv_statements(uc: UploaderClient) -> list[dict]:
    """Feltöltött CSV bankkivonatok a PDF listával azonos alakra hozva."""
    storage = uc.list_files() or {}
    files: list[dict] = []
    for bank, bank_files in (storage.get("banks") or {}).items():
        for f in bank_files:
            from_date, to_date = _csv_period(f["filename"])
            files.append(
                {
                    "kind": "csv",
                    "bank": bank,
                    "filename": f["filename"],
                    "from_date": from_date,
                    "to_date": to_date,
                    "size_bytes": f["size_bytes"],
                    "modified_at": f["modified_at"],
                }
            )
    return files


def _all_statements(uc: UploaderClient) -> list[dict]:
    """PDF és CSV bankkivonatok egy listában, egy táblázathoz."""
    pdfs = [{**f, "kind": "pdf"} for f in (uc.list_pdf_statements() or [])]
    return pdfs + _csv_statements(uc)


def _proxy_download(uc: UploaderClient, url: str) -> StreamingResponse:
    """Az uploader szerviz letöltés válaszának streamelése a böngészőnek."""
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


def _table_response(request: Request, uc: UploaderClient):
    files = _all_statements(uc)
    anonymized = is_anonymized(request)
    if anonymized:
        files = _anonymize_files(files)
    return templates.TemplateResponse(
        request,
        "partials/bank_statement_table.html",
        {"files": files, "anonymized": anonymized},
    )


@router.get("/bank-statements")
def bank_statements_page(request: Request):
    """Bankkivonatok oldala — feltöltött PDF és CSV kivonatok."""
    uc = _uploader_client()
    files = _all_statements(uc)
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
    """HTMX partial: tárolt PDF és CSV bankkivonatok táblázata."""
    return _table_response(request, _uploader_client())


@router.get("/bank-statements/csv/{bank}/{filename}/download")
def download_csv_bank_statement(request: Request, bank: str, filename: str):
    """Feltöltött CSV bankkivonat letöltése az uploader szervizről."""
    if is_anonymized(request):
        raise HTTPException(
            status_code=403,
            detail="Anonimizált nézetben a bankkivonat CSV letöltése nem engedélyezett.",
        )
    uc = _uploader_client()
    return _proxy_download(uc, f"{uc.base_url}/api/v1/files/{bank}/{filename}/download")


@router.delete("/bank-statements/csv/{bank}/{filename}", response_class=HTMLResponse)
def delete_csv_bank_statement(request: Request, bank: str, filename: str):
    """HTMX endpoint: CSV bankkivonat törlése — a teljes táblázatot rerendereli."""
    uc = _uploader_client()
    uc.delete_file(bank=bank, filename=filename)
    return _table_response(request, uc)


@router.get("/bank-statements/{bank}/{filename}/download")
def download_bank_statement(request: Request, bank: str, filename: str):
    """PDF bankkivonat letöltése az uploader szervizről."""
    if is_anonymized(request):
        raise HTTPException(
            status_code=403,
            detail="Anonimizált nézetben a bankkivonat PDF letöltése nem engedélyezett.",
        )
    uc = _uploader_client()
    return _proxy_download(uc, f"{uc.base_url}/api/v1/pdf/files/{bank}/{filename}/download")


@router.delete("/bank-statements/{bank}/{filename}", response_class=HTMLResponse)
def delete_bank_statement(request: Request, bank: str, filename: str):
    """HTMX endpoint: PDF bankkivonat törlése — a teljes táblázatot rerendereli."""
    uc = _uploader_client()
    uc.delete_pdf_statement(bank=bank, filename=filename)
    return _table_response(request, uc)
