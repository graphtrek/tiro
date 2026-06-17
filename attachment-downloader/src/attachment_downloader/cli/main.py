from typing import Optional

import typer
from attachment_downloader.config import configure_logging, get_settings
from attachment_downloader.providers import get_client
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Attachment Downloader CLI")
console = Console()


@app.callback()
def _main() -> None:
    configure_logging(get_settings().log_level)


@app.command()
def download(
    start: str = typer.Option(..., "--start", help="Filter start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--end", help="Filter end date (YYYY-MM-DD)"),
    output: Optional[str] = typer.Option(None, "--output", help="Subdirectory under DOWNLOAD_ROOT_DIR (default: DOWNLOAD_ROOT_DIR root)"),
    provider: str = typer.Option("gmail", "--provider", help="Email provider (gmail)"),
):
    """Download PDF attachments from an email provider in a date range."""
    colors = {"INFO": "cyan", "WARN": "yellow", "ERROR": "red"}

    def log(level: str, message: str) -> None:
        console.print(f"[{colors.get(level, 'white')}]{level}[/] {message}")

    client = get_client(provider)
    try:
        result = client.download_pdf_attachments(start, end, output, log=log)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise typer.Exit(code=1)

    if not result.files:
        if result.skipped_files:
            console.print(
                f"[yellow]Nothing new — {result.skipped_files} PDF(s) already "
                f"in {result.output_dir}.[/yellow]"
            )
        else:
            console.print("[yellow]No PDF attachments found in this date range.[/yellow]")
        return

    table = Table(title=f"Downloaded PDFs → {result.output_dir}")
    table.add_column("File", style="white")
    table.add_column("Original", style="dim")
    table.add_column("Email date", style="green")
    table.add_column("Size", style="magenta", justify="right")
    for f in result.files:
        table.add_row(f.filename, f.original_filename, f.email_date, f"{f.size_bytes:,} B")
    console.print(table)
    skipped_note = (
        f" ({result.skipped_files} already present, skipped)"
        if result.skipped_files
        else ""
    )
    console.print(
        f"[green]Done. {result.total_files} PDF(s) from {result.total_emails} "
        f"email(s) saved to {result.output_dir}{skipped_note}[/green]"
    )


if __name__ == "__main__":
    app()
