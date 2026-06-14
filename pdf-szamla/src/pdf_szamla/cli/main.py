"""Typer CLI for the pdf-szamla microservice."""

from __future__ import annotations

import json as _json
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from pdf_szamla.client import AttachmentDownloaderError
from pdf_szamla.config import get_settings
from pdf_szamla.extractor import clear_words_cache, extract_words_csv, words_cache_info
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
        None, "--output-dir", help="PDF directory (default: ../attachment-downloader/downloads)"
    ),
    local: bool = typer.Option(
        False,
        "--local/--download",
        help="Process existing PDFs without calling attachment-downloader",
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
    except AttachmentDownloaderError as exc:
        console.print(f"[red]✗ attachment-downloader hiba:[/red] {exc}")
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(_json.dumps(result.model_dump()))
        return

    console.print(
        f"[green]✓[/green] {result.invoice_count} számla "
        f"({result.total_files} fájlból) — {result.output_dir}\n"
    )
    if not result.files:
        console.print("Nincs számla találat.")
        return

    table = Table(show_lines=False)
    table.add_column("Fájl", overflow="fold")
    table.add_column("Módosítva")

    for f in result.files:
        table.add_row(f.filename, f.modified.strftime("%Y-%m-%d %H:%M"))
    console.print(table)


@app.command()
def words(
    pdf_path: str = typer.Argument(..., help="Path to the PDF file"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Write CSV to this file instead of stdout"
    ),
):
    """Extract all words from a PDF and output them as CSV (page,word,x0,top,x1,bottom)."""
    csv_content = extract_words_csv(pdf_path)
    if output:
        from pathlib import Path
        Path(output).write_text(csv_content, encoding="utf-8")
        console.print(f"[green]✓[/green] Words written to {output}")
    else:
        console.print(csv_content, end="")


@app.command("cache-info")
def cache_info(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show stats about the in-process words cache."""
    info = words_cache_info()
    if as_json:
        console.print_json(_json.dumps(info))
        return
    console.print(f"[bold]Entries:[/bold] {info['entries']}")
    for path in info["paths"]:
        console.print(f"  {path}")


@app.command("cache-clear")
def cache_clear():
    """Evict all entries from the in-process words cache."""
    removed = clear_words_cache()
    console.print(f"[green]✓[/green] {removed} bejegyzés törölve a gyorsítótárból.")


if __name__ == "__main__":
    app()
