"""FastAPI app a wise-szamla mikroszervizhez."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException, Request

from wise_szamla.client import WiseApiError, WiseClient
from wise_szamla.config import configure_logging, get_settings
from wise_szamla.models import SyncHistoryEntry, SyncRequest, SyncResponse, TransactionSummary
from wise_szamla.sync import run_sync

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Wise Banki Mikorszerviz",
    description=(
        "Wise bankkivonatok letöltése és szinkronizálás a szamla-db rendszerrel. "
        "Önálló belépési pont: POST /api/v1/sync"
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
        "szamla_db_url": s.szamla_db_url,
        "api_port": s.api_port,
        "max_retries": s.max_retries,
    }


# ── Szinkronizálás ────────────────────────────────────────────────────────────


@app.post("/api/v1/sync", response_model=SyncResponse)
def sync_transactions(request: SyncRequest):
    """Wise tranzakciók letöltése és szinkronizálása a szamla-db-be.

    Ha a ``start_date`` / ``end_date`` nincs megadva, az utolsó 30 napot dolgozza fel.
    A ``currency`` default értéke a ``WISE_ACCOUNT_CURRENCY`` env változó.
    """
    try:
        result = run_sync(request)
    except WiseApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _sync_history.append(result)
    return result


@app.get("/api/v1/sync/history", response_model=List[SyncHistoryEntry])
def sync_history():
    """Visszaadja a szinkronizálási futások előzményeit (in-memory)."""
    return [
        SyncHistoryEntry(
            start_date=r.start_date,
            end_date=r.end_date,
            currency=r.currency,
            fetched=r.fetched,
            synced=r.synced,
            skipped=r.skipped,
            errors=r.errors,
        )
        for r in _sync_history
    ]


# ── Tranzakció lekérdezés ─────────────────────────────────────────────────────


@app.get("/api/v1/transactions/{reference_number}", response_model=TransactionSummary)
def get_transaction(reference_number: str):
    """Lekérdezi egy szinkronizált tranzakció részleteit referenciaszám alapján."""
    for run in reversed(_sync_history):
        for txn in run.transactions:
            if txn.reference_number == reference_number:
                return txn
    raise HTTPException(
        status_code=404,
        detail=f"Tranzakció nem található: {reference_number}",
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
    """Fejlesztői szerver indítása."""
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
