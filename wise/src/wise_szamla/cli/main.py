"""Typer CLI a wise-szamla mikroszervizhez."""

from __future__ import annotations

import json as _json
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from datetime import date

from wise_szamla.client import WiseApiError, WiseClient
from wise_szamla.config import configure_logging, get_settings
from wise_szamla.csv_import import (
    StatementCsvError,
    list_statement_files,
    parse_statement_csv,
)
from wise_szamla.models import SyncRequest, TransactionType
from wise_szamla.sync import run_sync

app = typer.Typer(
    help="Wise Banki Mikorszerviz — bankkivonat letöltés.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="DEBUG szintű napló"),
):
    """Wise Banki Mikorszerviz CLI."""
    configure_logging("DEBUG" if verbose else get_settings().log_level)


@app.command()
def sync(
    start: Optional[str] = typer.Option(
        None, "--start", help="Szűrés kezdete (YYYY-MM-DD); default 30 napja"
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="Szűrés vége (YYYY-MM-DD); default ma"
    ),
    currency: Optional[str] = typer.Option(
        None, "--currency", help="Pénznem (pl. EUR, GBP, HUF)"
    ),
    as_json: bool = typer.Option(False, "--json", help="JSON kimenet"),
):
    """Wise tranzakciók lekérése a megadott időszakra."""
    request = SyncRequest(start_date=start, end_date=end, currency=currency)
    try:
        result = run_sync(request)
    except WiseApiError as exc:
        console.print(f"[red]✗ Wise API hiba:[/red] {exc}")
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(_json.dumps(result.model_dump(), default=str))
        return

    console.print(
        f"[green]✓[/green] {result.fetched} tranzakció "
        f"({result.start_date}..{result.end_date}, {result.currency})\n"
    )
    if not result.transactions:
        console.print("Nincs tranzakció a megadott időszakban.")
        return

    table = Table(show_lines=False)
    table.add_column("Azonosító", overflow="fold")
    table.add_column("Típus", width=7)
    table.add_column("Dátum", width=12)
    table.add_column("Összeg", justify="right")
    table.add_column("Partner", overflow="fold")

    for txn in result.transactions:
        color = "green" if txn.type == TransactionType.CREDIT else "red"
        table.add_row(
            txn.wise_transaction_id,
            f"[{color}]{txn.type.value}[/{color}]",
            txn.transaction_date.strftime("%Y-%m-%d"),
            f"{txn.amount:,.2f} {txn.currency}",
            txn.counterparty_name or "[dim]–[/dim]",
        )
    console.print(table)


@app.command()
def balances():
    """Elérhető Wise egyenlegek listázása (pénznem és balance ID)."""
    client = WiseClient()
    try:
        items = client.get_balances()
    except WiseApiError as exc:
        console.print(f"[red]✗ Wise API hiba:[/red] {exc}")
        raise typer.Exit(code=1)

    if not items:
        console.print("Nincs egyenleg a profilban.")
        return

    table = Table(show_lines=False)
    table.add_column("Balance ID", justify="right")
    table.add_column("Pénznem", width=8)
    table.add_column("Egyenleg", justify="right")

    for b in items:
        amt = b.get("amount", {})
        table.add_row(
            str(b.get("id", "–")),
            b.get("currency", "–"),
            f"{amt.get('value', 0):,.2f} {amt.get('currency', '')}",
        )
    console.print(table)


@app.command()
def status():
    """Wise API kapcsolat és profilok ellenőrzése."""
    settings = get_settings()
    client = WiseClient(settings)
    try:
        profiles = client.get_profiles()
        env = "sandbox" if settings.wise_sandbox else "live"
        console.print(
            f"[green]✓[/green] Wise API OK ({env}) — {len(profiles)} profil"
        )
        for p in profiles:
            name = (
                p.get("fullName")
                or p.get("businessName")
                or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            )
            console.print(
                f"  ID: {p.get('id')}  Típus: {p.get('type')}  Név: {name}"
            )
    except WiseApiError as exc:
        console.print(f"[red]✗ Wise API hiba:[/red] {exc}")
        raise typer.Exit(code=1)


@app.command()
def statements(
    from_: Optional[str] = typer.Option(
        None, "--from", help="Csak az ettől a dátumtól adatot tartalmazó fájlok (YYYY-MM-DD)"
    ),
    to: Optional[str] = typer.Option(
        None, "--to", help="Csak az eddig a dátumig adatot tartalmazó fájlok (YYYY-MM-DD)"
    ),
    currency: Optional[str] = typer.Option(
        None, "--currency", help="Pénznem szűrő (pl. HUF)"
    ),
):
    """Letöltött kivonat CSV-k listázása a balance-statements mappából."""
    files = list_statement_files(
        from_date=date.fromisoformat(from_) if from_ else None,
        to_date=date.fromisoformat(to) if to else None,
        currency=currency,
    )
    if not files:
        console.print("Nincs a szűrésnek megfelelő kivonat CSV.")
        return

    table = Table(show_lines=False)
    table.add_column("Fájl", overflow="fold")
    table.add_column("Balance ID", justify="right")
    table.add_column("Pénznem", width=8)
    table.add_column("Időszak")
    table.add_column("Méret", justify="right")

    for f in files:
        table.add_row(
            f.filename,
            str(f.balance_id),
            f.currency,
            f"{f.from_date} .. {f.to_date}",
            f"{f.size_bytes:,} B",
        )
    console.print(table)


@app.command(name="import")
def import_csv(
    filename: str = typer.Argument(
        ..., help="Kivonat CSV fájlnév a balance-statements mappában"
    ),
    as_json: bool = typer.Option(False, "--json", help="JSON kimenet"),
):
    """Egy letöltött kivonat CSV beolvasása és tranzakciók megjelenítése."""
    try:
        result = parse_statement_csv(filename)
    except StatementCsvError as exc:
        console.print(f"[red]✗ CSV hiba:[/red] {exc}")
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(_json.dumps(result.model_dump(), default=str))
        return

    console.print(
        f"[green]✓[/green] {result.fetched} tranzakció "
        f"({result.from_date}..{result.to_date}, {result.currency})\n"
    )
    if not result.transactions:
        console.print("Nincs tranzakció a fájlban.")
        return

    table = Table(show_lines=False)
    table.add_column("Azonosító", overflow="fold")
    table.add_column("Típus", width=7)
    table.add_column("Dátum", width=12)
    table.add_column("Összeg", justify="right")
    table.add_column("Partner", overflow="fold")

    for txn in result.transactions:
        color = "green" if txn.type == TransactionType.CREDIT else "red"
        table.add_row(
            txn.wise_transaction_id,
            f"[{color}]{txn.type.value}[/{color}]",
            txn.transaction_date.strftime("%Y-%m-%d"),
            f"{txn.amount:,.2f} {txn.currency}",
            txn.counterparty_name or "[dim]–[/dim]",
        )
    console.print(table)


if __name__ == "__main__":
    app()
