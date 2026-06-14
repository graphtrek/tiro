"""Typer CLI a wise-szamla mikroszervizhez."""

from __future__ import annotations

import json as _json
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from wise_szamla.client import WiseApiError, WiseClient
from wise_szamla.config import get_settings
from wise_szamla.models import SyncRequest, TransactionType
from wise_szamla.sync import run_sync

app = typer.Typer(
    help="Wise Banki Mikorszerviz — bankkivonat letöltés.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _main():
    """Wise Banki Mikorszerviz CLI."""


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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Részletes napló"),
):
    """Wise tranzakciók lekérése a megadott időszakra."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

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


@app.command("list")
def list_transactions(
    last: int = typer.Option(
        10, "--last", "-n", help="Utolsó n tranzakció (csak futó API szerveren)"
    ),
):
    """Legutóbbi tranzakciók listázása (API-n keresztül).

      GET /transactions/{wise_transaction_id}
    """
    console.print(
        "[yellow]Megjegyzés:[/yellow] Az előzmény csak az API szerveren él.\n"
        "  POST /sync → tranzakció lista\n"
        "  GET /transactions/{wise_transaction_id}"
    )


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
            console.print(
                f"  ID: {p.get('id')}  "
                f"Típus: {p.get('type')}  "
                f"Név: {p.get('fullName', '')}"
            )
    except WiseApiError as exc:
        console.print(f"[red]✗ Wise API hiba:[/red] {exc}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
