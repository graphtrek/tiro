"""Typer CLI a bank mikroszervizhez."""

from __future__ import annotations

import json as _json
from datetime import date
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bank.config import configure_logging, get_settings
from bank.models import BankTransaction
from bank.service import (
    get_bank_statement,
    get_consolidated_statement,
    get_statement_by_filename,
    list_files,
)

app = typer.Typer(
    help="Bank Konszolidált Kivonat Mikroszerviz — Erste és Wise CSV feldolgozás.",
    no_args_is_help=True,
)
console = Console()


def _print_transaction_table(transactions: list[BankTransaction]) -> None:
    table = Table(show_lines=False)
    table.add_column("Bank", width=6)
    table.add_column("Azonosító", overflow="fold")
    table.add_column("Dir", width=7)
    table.add_column("Dátum", width=12)
    table.add_column("Összeg", justify="right")
    table.add_column("Partner", overflow="fold")
    table.add_column("Közlemény", overflow="fold")
    for txn in transactions:
        color = "green" if txn.direction == "CREDIT" else "red"
        table.add_row(
            txn.bank,
            txn.transaction_id,
            f"[{color}]{txn.direction}[/{color}]",
            str(txn.date),
            f"{txn.amount:,.2f} {txn.currency}",
            txn.counterparty_name or "[dim]–[/dim]",  # noqa: RUF001 - intentional Hungarian dash
            txn.payment_reference or "[dim]–[/dim]",  # noqa: RUF001 - intentional Hungarian dash
        )
    console.print(table)


@app.callback()
def _main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="DEBUG szintű napló"),
):
    configure_logging("DEBUG" if verbose else get_settings().log_level)


@app.command()
def status():
    """CSV mappák és fájlok összesítése."""
    settings = get_settings()
    console.print(f"[bold]Balance statements könyvtár:[/bold] {settings.balance_statements_dir}")
    for bank in ("erste", "wise"):
        files = list_files(bank=bank, settings=settings)
        console.print(f"\n[bold]{bank.upper()}[/bold] — {len(files)} fájl")
        for f in files:
            console.print(f"  {f.filename}  ({f.from_date} .. {f.to_date})")
    if not list_files(bank="all", settings=settings):
        console.print("\n[yellow]Nincs elérhető kivonat CSV.[/yellow]")


@app.command(name="list")
def list_cmd(
    bank: Annotated[str, typer.Option("--bank", help="erste | wise | all")] = "all",
):
    """Elérhető CSV fájlok listázása."""
    if bank not in ("erste", "wise", "all"):
        console.print(f"[red]Ismeretlen bank: {bank!r}. Használható: erste, wise, all[/red]")
        raise typer.Exit(code=1)

    files = list_files(bank=bank)
    if not files:
        console.print("Nincs elérhető kivonat CSV.")
        return

    table = Table(show_lines=False)
    table.add_column("Bank", width=6)
    table.add_column("Fájl", overflow="fold")
    table.add_column("Számlaszám / ID", overflow="fold")
    table.add_column("Pénznem", width=8)
    table.add_column("Időszak")

    for f in files:
        table.add_row(
            f.bank,
            f.filename,
            f.account_id,
            f.currency or "–",  # noqa: RUF001 - intentional Hungarian dash
            f"{f.from_date} .. {f.to_date}",
        )
    console.print(table)


@app.command(name="import")
def import_csv(
    filename: Annotated[
        str,
        typer.Argument(
            help="CSV fájlnév (pl. statement_25546267_HUF_2026-01-01_2026-06-17.csv)"
        ),
    ],
    as_json: bool = typer.Option(False, "--json", help="JSON kimenet"),
):
    """Egy CSV fájl beolvasása és tranzakciók megjelenítése."""
    bank = "wise" if filename.startswith("statement_") else "erste"

    stmt = get_statement_by_filename(bank=bank, filename=filename)
    if stmt is None:
        console.print(f"[red]✗ Fájl nem található: {filename}[/red]")
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(_json.dumps(stmt.model_dump(), default=str))
        return

    console.print(
        f"[green]✓[/green] {stmt.fetched} tranzakció "
        f"({stmt.from_date} .. {stmt.to_date}) — [dim]{stmt.filename}[/dim]\n"
    )
    if not stmt.transactions:
        console.print("Nincs tranzakció a fájlban.")
        return
    _print_transaction_table(stmt.transactions)


@app.command()
def statements(
    bank: Annotated[str, typer.Option("--bank", help="erste | wise | all")] = "all",
    from_: str | None = typer.Option(None, "--from", help="Szűrés kezdete (YYYY-MM-DD)"),
    to: str | None = typer.Option(None, "--to", help="Szűrés vége (YYYY-MM-DD)"),
    currency: str | None = typer.Option(None, "--currency", help="Pénznem szűrő (pl. HUF)"),
    as_json: bool = typer.Option(False, "--json", help="JSON kimenet"),
):
    """Bankkivonatok lekérdezése (legfrissebb fájl, opcionális szűréssel)."""
    if bank not in ("erste", "wise", "all"):
        console.print(f"[red]Ismeretlen bank: {bank!r}. Használható: erste, wise, all[/red]")
        raise typer.Exit(code=1)

    from_date = date.fromisoformat(from_) if from_ else None
    to_date = date.fromisoformat(to) if to else None

    if bank == "all":
        result = get_consolidated_statement(
            from_date=from_date, to_date=to_date, currency=currency
        )
        if as_json:
            console.print_json(_json.dumps(result.model_dump(), default=str))
            return
        console.print(
            f"[green]✓[/green] {result.total} tranzakció "
            f"({result.from_date} .. {result.to_date}) — bankok: {', '.join(result.banks)}\n"
        )
        if not result.transactions:
            console.print("Nincs tranzakció.")
            return
        _print_transaction_table(result.transactions)
    else:
        stmt = get_bank_statement(
            bank=bank, from_date=from_date, to_date=to_date, currency=currency
        )
        if stmt is None:
            console.print(f"[red]✗ Nincs elérhető kivonat: {bank}[/red]")
            raise typer.Exit(code=1)
        if as_json:
            console.print_json(_json.dumps(stmt.model_dump(), default=str))
            return
        console.print(
            f"[green]✓[/green] {stmt.fetched} tranzakció "
            f"({stmt.from_date} .. {stmt.to_date}) — [dim]{stmt.filename}[/dim]\n"
        )
        if not stmt.transactions:
            console.print("Nincs tranzakció.")
            return
        _print_transaction_table(stmt.transactions)


if __name__ == "__main__":
    app()
