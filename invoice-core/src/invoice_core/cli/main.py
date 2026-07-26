"""Typer CLI for invoice-core."""

from __future__ import annotations

import calendar
import json as _json
import logging
import os
from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from invoice_core.auth import current_token
from invoice_core.config import configure_logging, get_settings
from invoice_core.db import BankTransaction, Invoice, InvoiceFile, SessionLocal
from invoice_core.models import SyncMode, SyncRequest, SyncResponse
from invoice_core.service import SyncInProgressError, sync_all
from invoice_core.services.dividend_service import calculate_dividend
from invoice_core.timeutil import today

app = typer.Typer(
    help="Invoice Core — master orchestrator for the Moneypenny pipeline.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)

# Shared typer.Option definitions reused across several `sync*`/`report` commands
# below, so the flag names/help text only need to be defined once.
_AS_JSON_OPTION = typer.Option(False, "--json")
_VERBOSE_OPTION = typer.Option(False, "--verbose", "-v")
_CLEAR_CACHE_OPTION = typer.Option(
    False, "--clear-cache", help="Clear all downstream caches before syncing"
)
_TOKEN_OPTION = typer.Option(
    None,
    "--token",
    help=(
        "Bearer token forwarded to nav-invoice/invoice-file-filter/bank "
        "(falls back to the MP_SERVICE_TOKEN env var; required when "
        "AUTH_ENABLED=true, see DEF-002)"
    ),
)


@app.callback()
def _main():
    configure_logging(get_settings().log_level)


def _resolve_service_token(token: str | None) -> str | None:
    """--token wins over the shared MP_SERVICE_TOKEN env var; both optional.

    The CLI process has no bearer token of its own the way an API request
    does (whose token `require_auth` captures and forwards downstream via
    `current_token`/`TokenPassthrough`) — this is the CLI's equivalent way to
    supply one when AUTH_ENABLED=true (see DEF-002).
    """
    return token or os.environ.get("MP_SERVICE_TOKEN") or None


def _run_sync(
    mode: SyncMode,
    start: str | None = None,
    end: str | None = None,
    month: str | None = None,
    clear_cache: bool = False,
    verbose: bool = False,
    token: str | None = None,
) -> SyncResponse:
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    resolved_token = _resolve_service_token(token)
    if resolved_token:
        current_token.set(resolved_token)
    else:
        logger.warning(
            "No bearer token supplied for this CLI sync — downstream calls will "
            "get a clean 401 if AUTH_ENABLED=true. Pass --token or set the "
            "MP_SERVICE_TOKEN env var to authenticate them."
        )

    if month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1).isoformat()
        end = date(y, m, calendar.monthrange(y, m)[1]).isoformat()

    req = SyncRequest(start_date=start, end_date=end, sync_mode=mode, clear_cache=clear_cache)
    db = SessionLocal()
    try:
        return sync_all(req, db)
    except SyncInProgressError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
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
    table.add_row("Bank transactions synced", str(result.bank_transactions_synced))
    table.add_row("Bank files matched", str(result.bank_files_matched))
    table.add_row("Period", f"{result.start_date} → {result.end_date}")
    console.print(table)
    for err in result.errors:
        console.print(f"[red]  {err}[/red]")
    for warn in result.warnings:
        console.print(f"[yellow]  {warn}[/yellow]")
    if not result.errors and not result.warnings:
        console.print("[green]✓ Sync complete[/green]")


@app.command()
def sync(
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    clear_cache: bool = _CLEAR_CACHE_OPTION,
    as_json: bool = _AS_JSON_OPTION,
    verbose: bool = _VERBOSE_OPTION,
    token: str | None = _TOKEN_OPTION,
):
    """Full synchronization: NAV + PDF + Bank."""
    result = _run_sync(
        SyncMode.full, start=start, end=end, clear_cache=clear_cache, verbose=verbose, token=token
    )
    _print_result(result, as_json)


@app.command("sync-nav")
def sync_nav(
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    clear_cache: bool = _CLEAR_CACHE_OPTION,
    as_json: bool = _AS_JSON_OPTION,
    verbose: bool = _VERBOSE_OPTION,
    token: str | None = _TOKEN_OPTION,
):
    """Synchronize NAV invoice data only."""
    result = _run_sync(
        SyncMode.nav_only,
        start=start,
        end=end,
        clear_cache=clear_cache,
        verbose=verbose,
        token=token,
    )
    _print_result(result, as_json)


@app.command("sync-pdf")
def sync_pdf(
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    clear_cache: bool = _CLEAR_CACHE_OPTION,
    as_json: bool = _AS_JSON_OPTION,
    verbose: bool = _VERBOSE_OPTION,
    token: str | None = _TOKEN_OPTION,
):
    """Synchronize PDF invoice file index only."""
    result = _run_sync(
        SyncMode.pdf_only,
        start=start,
        end=end,
        clear_cache=clear_cache,
        verbose=verbose,
        token=token,
    )
    _print_result(result, as_json)


@app.command("sync-bank")
def sync_bank(
    clear_cache: bool = _CLEAR_CACHE_OPTION,
    as_json: bool = _AS_JSON_OPTION,
    verbose: bool = _VERBOSE_OPTION,
    token: str | None = _TOKEN_OPTION,
):
    """Synchronize bank transactions only (Erste + Wise CSV via bank service)."""
    result = _run_sync(SyncMode.bank_only, clear_cache=clear_cache, verbose=verbose, token=token)
    _print_result(result, as_json)


@app.command("sync-match")
def sync_match(
    as_json: bool = _AS_JSON_OPTION,
    verbose: bool = _VERBOSE_OPTION,
    token: str | None = _TOKEN_OPTION,
):
    """Best-match existing bank transactions to invoice files (no fetching)."""
    result = _run_sync(SyncMode.match_only, verbose=verbose, token=token)
    _print_result(result, as_json)


@app.command()
def report(
    month: str = typer.Option(..., "--month", help="Month in YYYY-MM format"),
    clear_cache: bool = _CLEAR_CACHE_OPTION,
    as_json: bool = _AS_JSON_OPTION,
    verbose: bool = _VERBOSE_OPTION,
    token: str | None = _TOKEN_OPTION,
):
    """Full sync for a specific month and print a summary report."""
    result = _run_sync(
        SyncMode.full, month=month, clear_cache=clear_cache, verbose=verbose, token=token
    )
    if not as_json:
        console.print(f"\n[bold]Monthly report: {month}[/bold]\n")
    _print_result(result, as_json)


@app.command()
def dividend(
    year: int | None = typer.Option(None, "--year", help="Year (default: current year)"),
    # Passed into calculate_dividend()'s `tao_rate` parameter, not a separate
    # KIVA calculation — see the docstring below for why.
    kiva_rate: float = typer.Option(0.10, "--kiva-rate", help="KIVA tax rate"),
    hipa_rate: float = typer.Option(
        0.02, "--hipa-rate", help="HIPA (helyi iparűzési adó) tax rate"
    ),
):
    """Calculate estimated dividend advance (osztalékelőleg) for the given year.

    `kiva_rate` overrides the corporate-tax-rate assumption used internally
    (`calculate_dividend`'s `tao_rate`, normally 9% TAO): a Hungarian company
    pays either TAO or KIVA, never both, so this lets a KIVA-taxed company
    plug in their own flat rate instead of the TAO default.
    """
    effective_year = year or today().year
    db = SessionLocal()
    try:
        report = calculate_dividend(db, effective_year, kiva_rate, hipa_rate=hipa_rate)
    finally:
        db.close()

    console.print(f"\n[bold]Osztalékszámítás — {effective_year}[/bold]\n")

    summary = Table(show_header=False, show_lines=False, box=None)
    summary.add_column("Tétel", style="bold")
    summary.add_column("Összeg", justify="right")
    summary.add_row(
        "Bevétel (kimenő számlák nettó)", f"{report.revenue:>18,.0f} HUF".replace(",", " ")
    )
    summary.add_row(
        "Kiadás (bejövő számlák nettó)", f"{report.expenses:>18,.0f} HUF".replace(",", " ")
    )
    summary.add_row("─" * 30, "─" * 22)
    summary.add_row("Bruttó nyereség", f"{report.gross_profit:>18,.0f} HUF".replace(",", " "))
    # `report.tao_rate`/`tao_tax` hold whatever rate was passed in above (the
    # --kiva-rate value), labeled "KIVA" here since that's what the CLI user
    # actually asked to compute with.
    summary.add_row(
        f"KIVA ({int(report.tao_rate * 100)}%)", f"{report.tao_tax:>18,.0f} HUF".replace(",", " ")
    )
    summary.add_row(
        f"HIPA ({int(report.hipa_rate * 100)}%)", f"{report.hipa_tax:>18,.0f} HUF".replace(",", " ")
    )
    summary.add_row("─" * 30, "─" * 22)
    summary.add_row(
        "[green]Nettó nyereség (kivehető osztalékelőleg)[/green]",
        f"[green]{report.net_profit:>18,.0f} HUF[/green]".replace(",", " "),
    )
    console.print(summary)

    console.print(f"\n  Kimenő számlák száma: {report.invoice_count_out}")
    console.print(f"  Bejövő számlák száma: {report.invoice_count_in}")

    if report.monthly:
        console.print("\n[bold]Havi bontás[/bold]\n")
        monthly = Table(show_lines=False)
        monthly.add_column("Hónap")
        monthly.add_column("Bevétel", justify="right")
        monthly.add_column("Kiadás", justify="right")
        monthly.add_column("Nyereség", justify="right")
        for row in report.monthly:
            color = "green" if row.gross_profit >= 0 else "red"
            monthly.add_row(
                row.month,
                f"{row.revenue:,.0f}".replace(",", " "),
                f"{row.expenses:,.0f}".replace(",", " "),
                f"[{color}]{row.gross_profit:,.0f}[/{color}]".replace(",", " "),
            )
        console.print(monthly)


def _link_entity_to_file(db, entity, entity_label: str, entity_display: str, filename: str) -> None:
    """Shared body of `link`/`link-bank`: find the file, point *entity* at it, commit, print.

    *entity* is the already-looked-up Invoice or BankTransaction row (or None
    if the caller's lookup found nothing) — this helper only knows it has an
    `invoice_file_id` column to set, not which specific table it came from.
    """
    if not entity:
        console.print(f"[red]{entity_label} not found: {entity_display}[/red]")
        raise typer.Exit(1)
    invoice_file = db.query(InvoiceFile).filter(InvoiceFile.filename.ilike(filename)).first()
    if not invoice_file:
        console.print(f"[red]InvoiceFile not found: {filename}[/red]")
        console.print("[yellow]Run sync-pdf first to import the file.[/yellow]")
        raise typer.Exit(1)
    entity.invoice_file_id = invoice_file.id
    db.commit()
    console.print(f"[green]✓ Linked {entity_display} → {filename}[/green]")


@app.command()
def link(
    invoice_number: str = typer.Argument(help="Invoice number as stored in NAV (e.g. '87/2026')"),
    filename: str = typer.Argument(
        help="PDF filename as stored in invoice_file table "
        "(e.g. '2026-06-04_0020_GRAPHTREK_szamla.pdf')"
    ),
):
    """Manually link an invoice to a PDF file."""
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter_by(invoice_number=invoice_number).first()
        _link_entity_to_file(db, invoice, "Invoice", invoice_number, filename)
    finally:
        db.close()


@app.command("link-bank")
def link_bank(
    transaction_id: str = typer.Argument(
        help="Bank transaction id (e.g. 'F0HO10062026036547' or 'CARD-3868107236')"
    ),
    filename: str = typer.Argument(
        help="PDF filename as stored in invoice_file "
        "(e.g. '2026-06-02_0017_scaleway-invoice-2026-05.pdf')"
    ),
):
    """Manually link a bank transaction to a PDF file."""
    db = SessionLocal()
    try:
        txn = db.query(BankTransaction).filter_by(transaction_id=transaction_id).first()
        _link_entity_to_file(db, txn, "Bank transaction", transaction_id, filename)
    finally:
        db.close()


if __name__ == "__main__":
    app()
