"""FastAPI app a wise-szamla mikroszervizhez."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import List, Optional, Union

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse

from wise_szamla.client import WiseApiError, WiseClient
from wise_szamla.config import configure_logging, get_settings
from wise_szamla.csv_import import (
    StatementCsvError,
    list_statement_files,
    parse_statement_csv,
    resolve_statement_path,
)
from wise_szamla.models import (
    StatementFile,
    StatementImport,
    SyncRequest,
    SyncResponse,
    TransactionSummary,
)
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


# ── Kivonat CSV-k (kézi letöltés a Wise webfelületről) ────────────────────────


@app.get(
    "/balance-statements",
    response_model=Union[StatementImport, List[StatementFile]],
)
def list_balance_statements(
    from_: Optional[date] = Query(
        None, alias="from", description="Csak az ettől a dátumtól adatot tartalmazó fájlok"
    ),
    to: Optional[date] = Query(
        None, description="Csak az eddig a dátumig adatot tartalmazó fájlok"
    ),
    currency: Optional[str] = Query(None, description="Pénznem szűrő, pl. HUF"),
):
    """Kivonat CSV-k a mappából.

    - **Szűrő nélkül** (default): a legfrissebb (today-hez legközelebbi) kivonat
      beolvasott tranzakcióit adja vissza JSON-ban (:class:`StatementImport`).
    - **Szűrővel** (``from`` / ``to`` / ``currency``): a megfelelő fájlok
      metaadat-listáját adja vissza.

    Példa: ``GET /balance-statements?from=2026-05-19&currency=HUF``
    """
    if from_ is None and to is None and currency is None:
        files = list_statement_files()
        if not files:
            raise HTTPException(status_code=404, detail="Nincs elérhető kivonat CSV.")
        # A legfrissebb = a legnagyobb to_date-tel (today-hez legközelebbi vége).
        latest = max(files, key=lambda f: f.to_date)
        try:
            return parse_statement_csv(latest.filename)
        except StatementCsvError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return list_statement_files(from_date=from_, to_date=to, currency=currency)


@app.get("/balance-statements/{filename}", response_model=StatementImport)
def import_balance_statement(
    filename: str,
    csv: bool = Query(
        False, description="Az eredeti CSV fájlt adja vissza a JSON helyett"
    ),
):
    """Beolvas egy kivonat CSV-t és visszaadja a tranzakciókat (default JSON).

    A dátumok formázva: ``transaction_date`` = ``yyyy-mm-dd hh:mm:ss``,
    ``date`` = ``yyyy-mm-dd``. A ``?csv=true`` paraméterrel az eredeti CSV
    fájl tölthető le.
    """
    try:
        if csv:
            path = resolve_statement_path(filename)
            return FileResponse(path, media_type="text/csv", filename=filename)
        return parse_statement_csv(filename)
    except StatementCsvError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Wise API kapcsolat ellenőrzés ─────────────────────────────────────────────


@app.get("/profiles")
def get_profiles():
    """Visszaadja a Wise profillistát (API kapcsolat teszteléshez)."""
    try:
        return WiseClient().get_profiles()
    except WiseApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/balances")
def get_balances():
    """Visszaadja a profil STANDARD egyenlegeit (pénznem és balance ID)."""
    try:
        return WiseClient().get_balances()
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
