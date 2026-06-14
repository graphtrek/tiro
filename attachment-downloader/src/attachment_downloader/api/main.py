import asyncio
import logging
import time

from fastapi import FastAPI, HTTPException, Request
from attachment_downloader.client import GmailClient
from attachment_downloader.config import configure_logging
from attachment_downloader.models import CacheInfo, DownloadRequest, DownloadResult

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Attachment Downloader API")
client = GmailClient()


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


@app.get("/api/v1/cache", response_model=CacheInfo)
async def get_cache_info():
    """Return cache hit/miss stats and number of cached entries."""
    return CacheInfo(**client._cache.stats)


@app.delete("/api/v1/cache", status_code=204)
async def clear_cache():
    """Evict all cached download results."""
    client._cache.clear()


@app.post("/api/v1/jobs", response_model=DownloadResult)
async def create_download_job(request: DownloadRequest):
    """Download PDF attachments synchronously; returns the result when done."""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: client.download_pdf_attachments(
                start_date=request.start_date,
                end_date=request.end_date,
                output_dir=request.output_dir,
            ),
        )
    except Exception as e:
        logger.exception("download_pdf_attachments failed")
        raise HTTPException(status_code=500, detail=str(e))
