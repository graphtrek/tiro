"""Typer CLI for the pdf-szamla microservice."""

from __future__ import annotations

import json as _json
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from pdf_szamla.client import GraphtrekEmailError
from pdf_szamla.config import get_settings
from pdf_szamla.models import ExtractRequest
from pdf_szamla.service import run_extract

app = typer.Typer(
    help="PDF Számla Feldolgozó — download and extract invoice metadata.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _main():
    """PDF Számla Feldolgozó CLI."""


@app.command()
def process(
    start: Optional[str] = typer.Option(
        None, "--start", help="Filter start date (YYYY-MM-DD); default 30 days ago"
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="Filter end date (YYYY-MM-DD); default today"
    ),
    output_dir: Optional[str] = typer.Option(
        None, "--output-dir", help="PDF directory (default: ./downloads)"
    ),
    local: bool = typer.Option(
        False,
        "--local/--download",
        help="Process existing PDFs without calling graphtrek-email",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
):
    """Download invoice PDFs (last 30 days by default) and extract metadata."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

    settings = get_settings()
    request = ExtractRequest(
        start_date=start,
        end_date=end,
        output_dir=output_dir,
        download=not local,
    )

    try:
        result = run_extract(request, settings)
    except GraphtrekEmailError as exc:
        console.print(f"[red]✗ graphtrek-email hiba:[/red] {exc}")
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(_json.dumps(result.model_dump()))
        return

    console.print(
        f"[green]✓[/green] {result.invoice_count} számla "
        f"({result.total_files} fájlból) — {result.output_dir}\n"
    )
    if not result.invoices:
        console.print("Nincs számla találat.")
        return

    table = Table(show_lines=False)
    table.add_column("Fájl", overflow="fold")
    table.add_column("Számlaszám")
    table.add_column("Dátum")
    table.add_column("Szállító adószám")
    table.add_column("Összeg", justify="right")
    table.add_column("Pénznem")
    table.add_column("Conf.", justify="right")

    for inv in result.invoices:
        amount = f"{inv.amount_total:,.0f}" if inv.amount_total is not None else "—"
        table.add_row(
            inv.filename,
            inv.invoice_number or "—",
            inv.invoice_date or "—",
            inv.supplier_tax_id or "—",
            amount,
            inv.currency or "—",
            f"{inv.confidence:.2f}",
        )
    console.print(table)


if __name__ == "__main__":
    app()
