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
from invoice_core.db import Invoice, InvoiceFile, SessionLocal, WiseTransaction
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
    clear_cache: bool = False,
    verbose: bool = False,
) -> SyncResponse:
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1).isoformat()
        end = date(y, m, calendar.monthrange(y, m)[1]).isoformat()

    req = SyncRequest(start_date=start, end_date=end, sync_mode=mode, clear_cache=clear_cache)
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
    table.add_row("Wise files matched", str(result.wise_files_matched))
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
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Clear all downstream caches before syncing"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Full synchronization: NAV + PDF + Wise."""
    result = _run_sync(SyncMode.full, start=start, end=end, clear_cache=clear_cache, verbose=verbose)
    _print_result(result, as_json)


@app.command("sync-nav")
def sync_nav(
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Clear all downstream caches before syncing"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Synchronize NAV invoice data only."""
    result = _run_sync(SyncMode.nav_only, start=start, end=end, clear_cache=clear_cache, verbose=verbose)
    _print_result(result, as_json)


@app.command("sync-pdf")
def sync_pdf(
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Clear all downstream caches before syncing"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Synchronize PDF invoice file index only."""
    result = _run_sync(SyncMode.pdf_only, start=start, end=end, clear_cache=clear_cache, verbose=verbose)
    _print_result(result, as_json)


@app.command("sync-wise")
def sync_wise(
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Clear all downstream caches before syncing"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Synchronize Wise transactions only."""
    result = _run_sync(SyncMode.wise_only, clear_cache=clear_cache, verbose=verbose)
    _print_result(result, as_json)


@app.command("sync-match")
def sync_match(
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Best-match existing Wise transactions to invoice files (no fetching)."""
    result = _run_sync(SyncMode.match_only, verbose=verbose)
    _print_result(result, as_json)


@app.command()
def report(
    month: str = typer.Option(..., "--month", help="Month in YYYY-MM format"),
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Clear all downstream caches before syncing"),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Full sync for a specific month and print a summary report."""
    result = _run_sync(SyncMode.full, month=month, clear_cache=clear_cache, verbose=verbose)
    if as_json:
        console.print_json(_json.dumps(result.model_dump()))
        return
    console.print(f"\n[bold]Monthly report: {month}[/bold]\n")
    _print_result(result, as_json=False)


@app.command()
def link(
    invoice_number: str = typer.Argument(help="Invoice number as stored in NAV (e.g. '87/2026')"),
    filename: str = typer.Argument(help="PDF filename as stored in invoice_file table (e.g. '2026-06-04_0020_GRAPHTREK_szamla.pdf')"),
):
    """Manually link an invoice to a PDF file."""
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter_by(invoice_number=invoice_number).first()
        if not invoice:
            console.print(f"[red]Invoice not found: {invoice_number}[/red]")
            raise typer.Exit(1)
        invoice_file = db.query(InvoiceFile).filter_by(filename=filename).first()
        if not invoice_file:
            console.print(f"[red]InvoiceFile not found: {filename}[/red]")
            console.print("[yellow]Run sync-pdf first to import the file.[/yellow]")
            raise typer.Exit(1)
        invoice.invoice_file_id = invoice_file.id
        db.commit()
        console.print(f"[green]✓ Linked {invoice_number} → {filename}[/green]")
    finally:
        db.close()


@app.command("link-wise")
def link_wise(
    wise_transaction_id: str = typer.Argument(help="Wise transaction id (e.g. 'CARD-3868107236')"),
    filename: str = typer.Argument(help="PDF filename as stored in invoice_file (e.g. '2026-06-02_0017_scaleway-invoice-2026-05.pdf')"),
):
    """Manually link a Wise transaction to a PDF file."""
    db = SessionLocal()
    try:
        txn = db.query(WiseTransaction).filter_by(wise_transaction_id=wise_transaction_id).first()
        if not txn:
            console.print(f"[red]Wise transaction not found: {wise_transaction_id}[/red]")
            raise typer.Exit(1)
        invoice_file = db.query(InvoiceFile).filter_by(filename=filename).first()
        if not invoice_file:
            console.print(f"[red]InvoiceFile not found: {filename}[/red]")
            console.print("[yellow]Run sync-pdf first to import the file.[/yellow]")
            raise typer.Exit(1)
        txn.invoice_file_id = invoice_file.id
        db.commit()
        console.print(f"[green]✓ Linked {wise_transaction_id} → {filename}[/green]")
    finally:
        db.close()


if __name__ == "__main__":
    app()
