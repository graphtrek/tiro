"""Typer CLI for invoice-core."""

from __future__ import annotations

import calendar
import json as _json
import logging
from datetime import date
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from invoice_core.config import configure_logging, get_settings
from invoice_core.db import SessionLocal
from invoice_core.models import SyncMode, SyncRequest, SyncResponse
from invoice_core.service import sync_all

app = typer.Typer(
    help="Invoice Core — master orchestrator for the Moneypenny pipeline.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)


@app.callback()
def _main():
    configure_logging(get_settings().log_level)


def _run_sync(
    mode: SyncMode,
    start: Optional[str] = None,
    end: Optional[str] = None,
    month: Optional[str] = None,
    verbose: bool = False,
) -> SyncResponse:
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1).isoformat()
        end = date(y, m, calendar.monthrange(y, m)[1]).isoformat()

    req = SyncRequest(start_date=start, end_date=end, sync_mode=mode)
    db = SessionLocal()
    try:
        return sync_all(req, db)
    finally:
        db.close()


def _print_result(result: SyncResponse, as_json: bool) -> None:
    if as_json:
        console.print_json(_json.dumps(result.model_dump()))
        return
    table = Table(show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("NAV invoices synced", str(result.nav_invoices_synced))
    table.add_row("PDF files synced", str(result.pdf_files_synced))
    table.add_row("Wise transactions synced", str(result.wise_transactions_synced))
    table.add_row("Period", f"{result.start_date} → {result.end_date}")
    console.print(table)
    for err in result.errors:
        console.print(f"[red]  {err}[/red]")
    if not result.errors:
        console.print("[green]✓ Sync complete[/green]")


@app.command()
def sync(
    start: Optional[str] = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: Optional[str] = typer.Option(None, "--end", help="YYYY-MM-DD"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Full synchronization: NAV + PDF + Wise."""
    result = _run_sync(SyncMode.full, start=start, end=end, verbose=verbose)
    _print_result(result, as_json)


@app.command("sync-nav")
def sync_nav(
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Synchronize NAV invoice data only."""
    result = _run_sync(SyncMode.nav_only, start=start, end=end, verbose=verbose)
    _print_result(result, as_json)


@app.command("sync-pdf")
def sync_pdf(
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Synchronize PDF invoice file index only."""
    result = _run_sync(SyncMode.pdf_only, start=start, end=end, verbose=verbose)
    _print_result(result, as_json)


@app.command("sync-wise")
def sync_wise(
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Synchronize Wise transactions only."""
    result = _run_sync(SyncMode.wise_only, verbose=verbose)
    _print_result(result, as_json)


@app.command()
def report(
    month: str = typer.Option(..., "--month", help="Month in YYYY-MM format"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Full sync for a specific month and print a summary report."""
    result = _run_sync(SyncMode.full, month=month, verbose=verbose)
    if as_json:
        console.print_json(_json.dumps(result.model_dump()))
        return
    console.print(f"\n[bold]Monthly report: {month}[/bold]\n")
    _print_result(result, as_json=False)


if __name__ == "__main__":
    app()
