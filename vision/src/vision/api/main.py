"""FastAPI application for the Vision microservice."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from vision.auth import current_token, extract_token, verify_jwt
from vision.config import configure_logging, get_settings
from vision.ui.admin_router import router as admin_ui_router
from vision.ui.controlling_router import router as controlling_ui_router
from vision.ui.invoice_router import router as invoice_ui_router
from vision.ui.router import router as ui_router
from vision.ui.uploader_router import router as uploader_ui_router

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
app.include_router(uploader_ui_router)
app.include_router(controlling_ui_router)
app.include_router(admin_ui_router)


# Token nélkül elérhető végpontok — minden más érvényes JWT-t igényel.
_PUBLIC_PATHS = {"/", "/pitch", "/login", "/logout", "/health", "/favicon.ico"}


def _is_public(path: str) -> bool:
    return path in _PUBLIC_PATHS or path.startswith("/static/")


@app.middleware("http")
async def require_auth(request: Request, call_next):
    settings = get_settings()
    if not settings.auth_enabled or _is_public(request.url.path):
        return await call_next(request)

    token = extract_token(request)
    claims = verify_jwt(token, settings) if token else None
    if claims is None:
        next_url = request.url.path
        if request.url.query:
            next_url = f"{next_url}?{request.url.query}"
        login_url = f"/login?next={quote(next_url, safe='')}"

        # htmx (incl. hx-boost) requests never send an "Accept: text/html" header — they
        # rely on HX-Request instead — so without this check every boosted nav click while
        # unauthenticated silently 401s and htmx (which doesn't swap non-2xx responses)
        # renders nothing, with no error and no redirect visible to the user.
        if request.headers.get("HX-Request") == "true":
            return JSONResponse(
                {"detail": "Érvénytelen vagy hiányzó access token"},
                status_code=401,
                headers={"HX-Redirect": login_url},
            )
        # böngészős oldal → login oldal; API hívás → 401 JSON
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(login_url, status_code=302)
        return JSONResponse({"detail": "Érvénytelen vagy hiányzó access token"}, status_code=401)

    request.state.user = claims
    if claims.get("role") == "read_only" and request.method not in ("GET", "HEAD", "OPTIONS"):
        return JSONResponse(
            {"detail": "Csak olvasási jogosultság — írási művelet nem engedélyezett"},
            status_code=403,
        )
    ctx = current_token.set(token)
    try:
        return await call_next(request)
    finally:
        current_token.reset(ctx)


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
    timestamp = datetime.now(UTC).astimezone().replace(tzinfo=None).isoformat()
    return {"status": "ok", "timestamp": timestamp}
