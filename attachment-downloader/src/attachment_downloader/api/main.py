import logging
import time

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from typing import List, Optional
from attachment_downloader.client import GmailClient
from attachment_downloader.config import configure_logging
from attachment_downloader.models import (
    EmailSummary,
    EmailDetail,
    Label,
    GmailResponse,
    DownloadRequest,
    JobInfo,
    JobLogs,
)
from attachment_downloader.jobs import job_manager

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


@app.get("/emails", response_model=List[EmailSummary])
async def list_emails(q: str = Query("in:inbox", description="Gmail search query"), max_results: int = Query(10, le=50)):
    try:
        return client.list_emails(query=q, max_results=max_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/emails/{email_id}", response_model=EmailDetail)
async def read_email(email_id: str):
    try:
        return client.read_email(email_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/emails/send", response_model=GmailResponse)
async def send_email(to: str, subject: str, body: str, cc: Optional[str] = None, bcc: Optional[str] = None):
    try:
        email_id = client.send_email(to=to, subject=subject, body=body, cc=cc or "", bcc=bcc or "")
        return GmailResponse(status="success", id=email_id)
    except Exception as e:
        return GmailResponse(status="error", message=str(e))

@app.post("/emails/{email_id}/reply", response_model=GmailResponse)
async def reply_to_email(email_id: str, body: str):
    try:
        email_id_sent = client.reply_to_email(email_id, body)
        return GmailResponse(status="success", id=email_id_sent)
    except Exception as e:
        return GmailResponse(status="error", message=str(e))

@app.post("/emails/{email_id}/trash", response_model=GmailResponse)
async def trash_email(email_id: str):
    try:
        client.trash_email(email_id)
        return GmailResponse(status="success")
    except Exception as e:
        return GmailResponse(status="error", message=str(e))

@app.post("/emails/{email_id}/read", response_model=GmailResponse)
async def mark_as_read(email_id: str):
    try:
        client.mark_as_read(email_id)
        return GmailResponse(status="success")
    except Exception as e:
        return GmailResponse(status="error", message=str(e))

@app.post("/emails/{email_id}/unread", response_model=GmailResponse)
async def mark_as_unread(email_id: str):
    try:
        client.mark_as_unread(email_id)
        return GmailResponse(status="success")
    except Exception as e:
        return GmailResponse(status="error", message=str(e))

@app.get("/labels", response_model=List[Label])
async def list_labels():
    try:
        return client.list_labels()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- PDF download jobs (graphtrek-email Moneypenny service) ---

@app.post("/api/v1/jobs", response_model=JobInfo, status_code=202)
async def create_download_job(request: DownloadRequest, background_tasks: BackgroundTasks):
    """Start a PDF-attachment download job; returns the job descriptor."""
    info = job_manager.create_job(request)
    background_tasks.add_task(job_manager.run_job, info.job_id, client)
    return info


@app.get("/api/v1/jobs/{job_id}", response_model=JobInfo)
async def get_download_job(job_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@app.get("/api/v1/jobs/{job_id}/logs", response_model=JobLogs)
async def get_download_job_logs(job_id: str):
    logs = job_manager.get_logs(job_id)
    if logs is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return logs
