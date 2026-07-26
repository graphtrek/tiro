"""FastAPI app a bank mikroszervizhez."""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from bank.auth import require_auth
from bank.config import configure_logging, get_settings
from bank.models import BankStatement, ConsolidatedStatement, StatementFile
from bank.service import (
    get_bank_statement,
    get_consolidated_statement,
    get_statement_by_filename,
    list_files,
)

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Bank Konszolidált Kivonat Mikroszerviz",
    description=(
        "Erste és Wise CSV bankkivonatok egységes feldolgozása. "
        "Levél szolgáltatás: CSV fájlokat olvas, DB-t nem kezel."
    ),
    version="0.1.0",
    dependencies=[Depends(require_auth)],
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


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/settings")
def settings_info():
    s = get_settings()
    return {
        "balance_statements_dir": s.balance_statements_dir,
        "erste_subdir": s.erste_subdir,
        "wise_subdir": s.wise_subdir,
        "api_port": s.api_port,
        "log_level": s.log_level,
    }


@app.get("/balance-statements", response_model=list[StatementFile])
def list_balance_statements():
    """Elérhető CSV fájlok listája (minden bank)."""
    return list_files(bank="all")


@app.get("/balance-statements/{bank}", response_model=list[StatementFile])
def list_balance_statements_by_bank(bank: str):
    """Adott bank elérhető fájljai (erste / wise)."""
    if bank not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=f"Ismeretlen bank: {bank!r}. Használható: erste, wise",
        )
    return list_files(bank=bank)


@app.get("/balance-statement/all", response_model=ConsolidatedStatement)
def get_consolidated(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    currency: str | None = Query(None),
):
    """Konszolidált kivonat: Erste + Wise tranzakciók együtt."""
    return get_consolidated_statement(from_date=from_, to_date=to, currency=currency)


@app.get("/balance-statement/{bank}/{filename}", response_model=BankStatement)
def get_statement_file(bank: str, filename: str):
    """Konkrét fájl beolvasása."""
    if bank not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=f"Ismeretlen bank: {bank!r}. Használható: erste, wise",
        )
    stmt = get_statement_by_filename(bank=bank, filename=filename)
    if stmt is None:
        raise HTTPException(status_code=404, detail=f"Fájl nem található: {filename}")
    return stmt


@app.get("/balance-statement/{bank}", response_model=BankStatement)
def get_statement(
    bank: str,
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    currency: str | None = Query(None),
):
    """Adott bank tranzakciói. Szűrő nélkül a legfrissebb fájl adatait adja vissza."""
    if bank not in ("erste", "wise"):
        raise HTTPException(
            status_code=400,
            detail=f"Ismeretlen bank: {bank!r}. Használható: erste, wise",
        )
    stmt = get_bank_statement(bank=bank, from_date=from_, to_date=to, currency=currency)
    if stmt is None:
        raise HTTPException(status_code=404, detail=f"Nincs elérhető kivonat: {bank}")
    return stmt


def run_server():
    import uvicorn

    s = get_settings()
    uvicorn.run("bank.api.main:app", host=s.api_host, port=s.api_port, reload=True)


if __name__ == "__main__":
    run_server()
