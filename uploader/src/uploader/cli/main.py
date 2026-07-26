"""Typer CLI az uploader mikroszervizhez."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from uploader.config import configure_logging, get_settings
from uploader.detector import detect_bank
from uploader.storage import delete_file, get_storage_status, list_files, save_file

app = typer.Typer(
    help="Uploader — Erste és Wise CSV bankkivonatok feltöltése a storage mappába.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="DEBUG szintű napló"),
):
    configure_logging("DEBUG" if verbose else get_settings().log_level)


@app.command()
def status():
    """Storage mappa és fájlok összesítése."""
    s = get_settings()
    status = get_storage_status(s)
    console.print(f"[bold]Storage könyvtár:[/bold] {status.storage_dir}")
    for bank, files in status.banks.items():
        console.print(f"\n[bold]{bank.upper()}[/bold] — {len(files)} fájl")
        for f in files:
            console.print(
                f"  {f.filename}  ({f.size_bytes:,} bájt, "
                f"{f.modified_at.strftime('%Y-%m-%d %H:%M')})"
            )
    if status.total_files == 0:
        console.print("\n[yellow]Nincs elérhető CSV fájl.[/yellow]")
    else:
        console.print(f"\n[green]Összesen: {status.total_files} fájl[/green]")


@app.command(name="list")
def list_cmd(
    bank: Annotated[str, typer.Option("--bank", help="erste | wise | all")] = "all",
):
    """Elérhető fájlok listázása."""
    if bank not in ("erste", "wise", "all"):
        console.print(f"[red]Ismeretlen bank: {bank!r}. Használható: erste, wise, all[/red]")
        raise typer.Exit(code=1)

    files = list_files(bank=bank)
    if not files:
        console.print("Nincs elérhető CSV fájl.")
        return

    table = Table(show_lines=False)
    table.add_column("Bank", width=6)
    table.add_column("Fájlnév", overflow="fold")
    table.add_column("Méret", justify="right")
    table.add_column("Módosítva", width=17)

    for f in files:
        table.add_row(
            f.bank,
            f.filename,
            f"{f.size_bytes:,} B",
            f.modified_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@app.command()
def upload(
    file: Annotated[Path, typer.Argument(help="Feltöltendő CSV fájl elérési útja")],
    bank: str | None = typer.Option(
        None, "--bank", help="erste | wise (auto-detektálás ha nincs megadva)"
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Létező fájl felülírása"),
):
    """CSV fájl feltöltése a storage mappába."""
    if not file.exists():
        console.print(f"[red]✗ Fájl nem található: {file}[/red]")
        raise typer.Exit(code=1)

    if file.suffix.lower() != ".csv":
        console.print(f"[red]✗ Csak CSV fájl fogadható el: {file.name}[/red]")
        raise typer.Exit(code=1)

    s = get_settings()
    max_bytes = s.max_file_size_mb * 1024 * 1024
    data = file.read_bytes()

    if len(data) > max_bytes:
        console.print(
            f"[red]✗ A fájl mérete meghaladja a maximumot ({s.max_file_size_mb} MB).[/red]"
        )
        raise typer.Exit(code=1)

    detected = bank or detect_bank(file.name)
    if detected not in ("erste", "wise"):
        console.print(
            f"[red]✗ Nem felismerhető bankkivonat formátum: {file.name!r}[/red]\n"
            "  Erste: <számlaszám>_YYYY-MM-DD_YYYY-MM-DD.csv\n"
            "  Wise:  statement_<id>_<currency>_YYYY-MM-DD_YYYY-MM-DD.csv"
        )
        raise typer.Exit(code=1)

    try:
        result = save_file(
            data=data,
            filename=file.name,
            bank=detected,
            overwrite=overwrite,
            settings=s,
        )
    except FileExistsError as exc:
        console.print(f"[red]✗ {exc}[/red]\n  Használd a --overwrite kapcsolót a felülíráshoz.")
        raise typer.Exit(code=1) from exc

    action = "[yellow]Felülírva[/yellow]" if result.overwritten else "[green]Feltöltve[/green]"
    console.print(
        f"{action}: [bold]{result.filename}[/bold] → {result.bank.upper()} "
        f"({result.size_bytes:,} bájt)\n  {result.saved_path}"
    )


@app.command()
def delete(
    bank: Annotated[str, typer.Argument(help="erste | wise")],
    filename: Annotated[str, typer.Argument(help="Törlendő fájl neve")],
):
    """Fájl törlése a storage mappából."""
    if bank not in ("erste", "wise"):
        console.print(f"[red]Ismeretlen bank: {bank!r}. Használható: erste, wise[/red]")
        raise typer.Exit(code=1)

    try:
        delete_file(bank=bank, filename=filename)
        console.print(f"[green]✓ Törölve:[/green] {bank}/{filename}")
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
