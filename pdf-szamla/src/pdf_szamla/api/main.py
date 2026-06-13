"""FastAPI app for the pdf-szamla microservice."""

from __future__ import annotations

import io
import logging
import time
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from pdf_szamla.client import GraphtrekEmailError
from pdf_szamla.config import configure_logging, get_settings
from pdf_szamla.extractor import clear_words_cache, extract_words_csv, process_directory, words_cache_info
from pdf_szamla.models import (
    ExtractBatchRequest,
    ExtractRequest,
    ExtractResponse,
    WordsRequest,
)
from pdf_szamla.service import run_extract

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PDF Számla Feldolgozó",
    description="Downloads invoice PDFs via graphtrek-email and extracts metadata.",
    version="0.1.0",
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


# In-memory processing history (most recent runs).
_history: List[ExtractResponse] = []


@app.get("/health")
def health_check():
    """Service health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/settings")
def get_settings_info():
    """Return the effective configuration."""
    settings = get_settings()
    return {
        "graphtrek_email_url": settings.graphtrek_email_url,
        "output_dir": settings.output_dir,
        "invoice_keywords": settings.invoice_keywords,
        "download_timeout": settings.download_timeout,
        "poll_interval": settings.poll_interval,
    }


@app.post("/api/v1/invoices/extract", response_model=ExtractResponse)
def extract_invoices(request: ExtractRequest):
    """Download (via graphtrek-email) and extract invoice metadata."""
    try:
        result = run_extract(request)
    except GraphtrekEmailError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _history.append(result)
    return result


@app.post("/api/v1/invoices/extract-batch", response_model=List[ExtractResponse])
def extract_invoices_batch(request: ExtractBatchRequest):
    """Extract metadata from one or more local PDF directories (no download)."""
    settings = get_settings()
    results: List[ExtractResponse] = []
    for output_dir in request.output_dirs:
        files = process_directory(output_dir, settings.invoice_keywords)
        result = ExtractResponse(
            total_files=len(files),
            invoice_count=len(files),
            output_dir=output_dir,
            files=files,
        )
        _history.append(result)
        results.append(result)
    return results


@app.post("/api/v1/pdf/words")
def get_pdf_words(request: WordsRequest):
    """Extract all words from a PDF and return them as CSV (page,word,x0,top,x1,bottom)."""
    csv_content = extract_words_csv(request.pdf_path)
    filename = request.pdf_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "words"
    filename = filename.removesuffix(".pdf") + "_words.csv"
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


@app.get("/api/v1/invoices", response_model=List[ExtractResponse])
def list_processed():
    """Return the in-memory processing history."""
    return _history


def run_server():
    """Start the FastAPI development server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "pdf_szamla.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    run_server()
