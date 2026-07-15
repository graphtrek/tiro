"""FastAPI app for the invoice-file-filter microservice."""

from __future__ import annotations

import io
import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from invoice_file_filter.auth import require_auth
from invoice_file_filter.client import AttachmentDownloaderError
from invoice_file_filter.config import configure_logging, get_settings
from invoice_file_filter.extractor import clear_words_cache, extract_words_csv, words_cache_info
from invoice_file_filter.models import (
    ExtractRequest,
    ExtractResponse,
    WordsRequest,
)
from invoice_file_filter.service import run_extract

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PDF Számla Feldolgozó",
    description="Downloads invoice PDFs via attachment-downloader and extracts metadata.",
    version="0.1.0",
    dependencies=[Depends(require_auth)],
)


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    logger.info("%s %s → %d in %.0fms", request.method, path, response.status_code, elapsed_ms)
    return response


@app.get("/health")
def health_check() -> dict[str, str]:
    """Service health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.post("/api/v1/invoices/extract", response_model=ExtractResponse)
def extract_invoices(request: ExtractRequest) -> ExtractResponse:
    """Download (via attachment-downloader) and extract invoice metadata."""
    try:
        result = run_extract(request)
    except AttachmentDownloaderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return result


@app.post("/api/v1/pdf/words")
def get_pdf_words(request: WordsRequest) -> StreamingResponse:
    """Extract distinct normalised words from a PDF and return them as single-column CSV (word)."""
    csv_content = extract_words_csv(request.pdf_path)
    filename = Path(request.pdf_path).stem + "_words.csv"
    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/pdf/words/cache")
def get_words_cache_info():
    """Return stats about the in-memory words cache."""
    return words_cache_info()


@app.delete("/api/v1/pdf/words/cache")
def delete_words_cache():
    """Evict all entries from the in-memory words cache."""
    removed = clear_words_cache()
    return {"removed": removed}


def run_server():
    """Start the FastAPI development server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "invoice_file_filter.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    run_server()
