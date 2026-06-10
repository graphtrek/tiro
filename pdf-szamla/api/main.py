"""FastAPI app for the pdf-szamla microservice."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException

from pdf_szamla.client import GraphtrekEmailError
from pdf_szamla.config import get_settings
from pdf_szamla.extractor import process_directory
from pdf_szamla.models import (
    ExtractBatchRequest,
    ExtractRequest,
    ExtractResponse,
)
from pdf_szamla.service import run_extract

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PDF Számla Feldolgozó",
    description="Downloads invoice PDFs via graphtrek-email and extracts metadata.",
    version="0.1.0",
)

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
        invoices = process_directory(output_dir, settings.invoice_keywords)
        result = ExtractResponse(
            total_files=len(invoices),
            invoice_count=len(invoices),
            output_dir=output_dir,
            invoices=invoices,
        )
        _history.append(result)
        results.append(result)
    return results


@app.get("/api/v1/invoices", response_model=List[ExtractResponse])
def list_processed():
    """Return the in-memory processing history."""
    return _history


def run_server():
    """Start the FastAPI development server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    run_server()
