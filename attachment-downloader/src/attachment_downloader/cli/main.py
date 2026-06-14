import typer
from typing import Optional
from attachment_downloader.client import GmailClient
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Graphtrek Gmail CLI")
console = Console()
client = GmailClient()

@app.command()
def list(
    query: str = typer.Option("in:inbox", help="Gmail search query"),
    max_results: int = typer.Option(10, help="Maximum number of messages to return")
):
    """List emails from Gmail."""
    try:
        emails = client.list_emails(query=query, max_results=max_results)
        if not emails:
            console.print("[yellow]No emails found.[/yellow]")
            return

        table = Table(title=f"Emails (query: {query})")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("From", style="magenta")
        table.add_column("Subject", style="white")
        table.add_column("Date", style="green")
        table.add_column("Snippet", style="dim")

        for email in emails:
            table.add_row(
                email.id,
                email.from_address,
                email.subject,
                email.date,
                email.snippet,
            )
        console.print(table)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")

@app.command()
def read(email_id: str):
    """Read the full content of an email."""
    try:
        email = client.read_email(email_id)
        console.print(f"\n[bold cyan]Subject:[/bold cyan] {email.subject}")
        console.print(f"[bold magenta]From:[/bold magenta] {email.from_address}")
        console.print(f"[bold green]To:[/bold green] {email.to}")
        console.print(f"[bold yellow]Date:[/bold yellow] {email.date}")
        console.print("\n" + "="*50 + "\n")
        console.print(email.body)
        console.print("\n" + "="*50)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")

@app.command()
def send(
    to: str = typer.Argument(..., help="Recipient address"),
    subject: str = typer.Argument(..., help="Email subject"),
    body: str = typer.Argument(..., help="Email body"),
    cc: Optional[str] = typer.Option(None, help="CC address(es)"),
    bcc: Optional[str] = typer.Option(None, help="BCC address(es)"),
):
    """Send a new email."""
    try:
        email_id = client.send_email(to=to, subject=subject, body=body, cc=cc or "", bcc=bcc or "")
        console.print(f"[green]Successfully sent email. ID: {email_id}[/green]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")

@app.command()
def reply(email_id: str, body: str):
    """Reply to an existing email."""
    try:
        email_id_sent = client.reply_to_email(email_id, body)
        console.print(f"[green]Successfully replied. ID: {email_id_sent}[/green]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")

@app.command()
def trash(email_id: str):
    """Move an email to the trash."""
    try:
        client.trash_email(email_id)
        console.print(f"[yellow]Email {email_id} moved to trash.[/yellow]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")

@app.command()
def mark_read(email_id: str):
    """Mark an email as read."""
    try:
        client.mark_as_read(email_id)
        console.print(f"[green]Email {email_id} marked as read.[/green]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")

@app.command()
def mark_unread(email_id: str):
    """Mark an email as unread."""
    try:
        client.mark_as_unread(email_id)
        console.print(f"[green]Email {email_id} marked as unread.[/green]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")

@app.command()
def download(
    start: str = typer.Option(..., "--start", help="Filter start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--end", help="Filter end date (YYYY-MM-DD)"),
    output: str = typer.Option("./downloads/", "--output", help="Output directory"),
):
    """Download PDF attachments from Gmail in a date range."""
    colors = {"INFO": "cyan", "WARN": "yellow", "ERROR": "red"}

    def log(level: str, message: str) -> None:
        console.print(f"[{colors.get(level, 'white')}]{level}[/] {message}")

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