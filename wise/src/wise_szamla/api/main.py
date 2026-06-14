"""FastAPI app a wise-szamla mikroszervizhez."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException, Request

from wise_szamla.client import WiseApiError, WiseClient
from wise_szamla.config import configure_logging, get_settings
from wise_szamla.models import SyncRequest, SyncResponse, TransactionSummary
from wise_szamla.sync import run_sync

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Wise Banki Mikorszerviz",
    description=(
        "Wise bankkivonatok letöltése és visszaadása strukturált formában. "
        "Levél szolgáltatás: csak Wise API-t hív, DB-t nem kezel."
    ),
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
    logger.info(
        "%s %s → %d in %.0fms", request.method, path, response.status_code, elapsed_ms
    )
    return response


_sync_history: List[SyncResponse] = []


# ── Állapot és konfiguráció ───────────────────────────────────────────────────


@app.get("/health")
def health():
    """Szolgáltatás állapotellenőrző végpont."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/settings")
def settings_info():
    """Visszaadja az aktív konfigurációt (API kulcs nélkül)."""
    s = get_settings()
    return {
        "wise_profile_id": s.wise_profile_id,
        "wise_account_currency": s.wise_account_currency,
        "wise_sandbox": s.wise_sandbox,
        "api_port": s.api_port,
        "max_retries": s.max_retries,
    }


# ── Szinkronizálás ────────────────────────────────────────────────────────────


@app.post("/sync", response_model=SyncResponse)
def sync_transactions(request: SyncRequest):
    """Wise tranzakciók lekérése a megadott időszakra.

    Ha a ``start_date`` / ``end_date`` nincs megadva, az utolsó 30 napot adja vissza.
    A ``currency`` default értéke a ``WISE_ACCOUNT_CURRENCY`` env változó.
    """
    try:
        result = run_sync(request)
    except WiseApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _sync_history.append(result)
    return result


# ── Tranzakció lekérdezés ─────────────────────────────────────────────────────


@app.get("/transactions/{wise_transaction_id}", response_model=TransactionSummary)
def get_transaction(wise_transaction_id: str):
    """Lekérdezi egy tranzakció részleteit azonosító alapján."""
    for run in reversed(_sync_history):
        for txn in run.transactions:
            if txn.wise_transaction_id == wise_transaction_id:
                return txn
    raise HTTPException(
        status_code=404,
        detail=f"Tranzakció nem található: {wise_transaction_id}",
    )


# ── Wise API kapcsolat ellenőrzés ─────────────────────────────────────────────


@app.get("/api/v1/profiles")
def get_profiles():
    """Visszaadja a Wise profillistát (API kapcsolat teszteléshez)."""
    try:
        return WiseClient().get_profiles()
    except WiseApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


def run_server():
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "wise_szamla.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    run_server()
