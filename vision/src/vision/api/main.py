"""FastAPI application for the Vision microservice."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from vision.config import configure_logging, get_settings
from vision.ui.invoice_router import router as invoice_ui_router
from vision.ui.router import router as ui_router

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(
    title="Vision",
    description="Ownership aggregator dashboard — invoice-core + SrcProfit.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
app.include_router(ui_router)
app.include_router(invoice_ui_router)


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
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


