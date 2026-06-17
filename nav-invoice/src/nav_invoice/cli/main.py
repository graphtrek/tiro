"""CLI entry point for NAV Online Számla."""

import json
import logging
from datetime import date, timedelta
from typing import Optional

import click

from nav_invoice import cache as _cache
from nav_invoice.auth import login as nav_login, check_connection
from nav_invoice.client import NavApiError
from nav_invoice.config import get_settings
from nav_invoice.models import DigestQueryParams, InvoiceDirection, SubmitInvoiceRequest
from nav_invoice.query import query_invoice_data, query_invoice_digest
from nav_invoice.reporting import submit_invoice

logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output.")
def main(verbose: bool) -> None:
    """NAV Online Számla CLI tool."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)


# ── login command ─────────────────────────────────────

@main.command()
def login():
    """Test authentication with NAV (Bejelentkezés)."""
    settings = get_settings()

    click.echo(f"Connecting to {settings.endpoint}...")
    result = nav_login(settings)

    if result.get("success"):
        click.echo(click.style("✓ Bejelentkezés sikeres!", fg="green"))
        token = result.get("session_id", "")
        if token:
            click.echo(f"  Token: {token[:24]}…")
        if result.get("valid_to"):
            click.echo(f"  Érvényes: {result.get('valid_from')} → {result.get('valid_to')}")
    else:
        click.echo(click.style(f"✗ Hiba: {result.get('error')}", fg="red"))


# ── list command ─────────────────────────────────────

@main.command()
@click.option("--from", "from_date", type=str, default=None, help="Start date (YYYY-MM-DD).")
@click.option("--to", "to_date", type=str, default=None, help="End date (YYYY-MM-DD).")
@click.option(
    "--direction",
    type=click.Choice(["OUTBOUND", "INBOUND"]),
    default="OUTBOUND",
    help="OUTBOUND (kiállított) vagy INBOUND (befogadott).",
)
@click.option("--page", type=int, default=1, help="Lapozás (1-től).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def list(
    from_date: Optional[str],
    to_date: Optional[str],
    direction: str,
    page: int,
    as_json: bool,
) -> None:
    """List invoices from NAV (queryInvoiceDigest)."""
    settings = get_settings()

    from_obj = date.fromisoformat(from_date) if from_date else date.today() - timedelta(days=30)
    to_obj = date.fromisoformat(to_date) if to_date else date.today()

    params = DigestQueryParams(
        from_date=from_obj,
        to_date=to_obj,
        direction=InvoiceDirection(direction),
        page=page,
    )

    try:
        invoices = query_invoice_digest(params, settings)
    except NavApiError as exc:
        click.echo(click.style(f"✗ Hiba: {exc}", fg="red"))
        raise SystemExit(1)

    if as_json:
        data = [inv.model_dump() for inv in invoices]
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return

    if not invoices:
        click.echo("Nincs találat.")
        return

    click.echo(f"{len(invoices)} számla találva:\n")
    for inv in invoices:
        partner = inv.customer_name or inv.customer_tax_number or inv.supplier_name
        gross = inv.invoice_net_amount or 0.0
        click.echo(
            f"  {inv.invoice_number:20s} | {inv.invoice_issue_date} | "
            f"{inv.invoice_operation:6s} | {gross:>12,.0f} | {partner}"
        )


# ── show command ─────────────────────────────────────

@main.command()
@click.argument("szamlaszam")
@click.option(
    "--direction",
    type=click.Choice(["OUTBOUND", "INBOUND"]),
    default="OUTBOUND",
)
def show(szamlaszam: str, direction: str) -> None:
    """Show a single invoice's decoded XML (queryInvoiceData)."""
    settings = get_settings()

    try:
        invoice_xml = query_invoice_data(
            szamlaszam, InvoiceDirection(direction), settings=settings
        )
    except NavApiError as exc:
        click.echo(click.style(f"✗ Hiba: {exc}", fg="red"))
        raise SystemExit(1)

    if not invoice_xml:
        click.echo(click.style(f"Számla nem található: {szamlaszam}", fg="red"))
        raise SystemExit(1)

    click.echo(invoice_xml)


# ── report command ───────────────────────────────────

@main.command()
@click.option("--json", "input_json", type=str, default=None, help="Invoice data as JSON string.")
def report(input_json: Optional[str]) -> None:
    """Submit an invoice to NAV (Adatszolgáltatás)."""
    settings = get_settings()

    if not input_json:
        click.echo("Még nem implementált — használd a --json opciót.")
        return

    try:
        data = json.loads(input_json)
        request = SubmitInvoiceRequest(**data)
    except (json.JSONDecodeError, ValueError) as exc:
        click.echo(click.style(f"✗ Érvénytelen bemeneti adat: {exc}", fg="red"))
        raise SystemExit(1)

    result = submit_invoice(request, settings)

    if result.success:
        click.echo(click.style("✓ Adatszolgáltatás sikeres!", fg="green"))
        if result.submission_id:
            click.echo(f"  Submission ID: {result.submission_id}")
    else:
        click.echo(click.style(f"✗ Hiba: {result.message}", fg="red"))
        raise SystemExit(1)


# ── cache-clear command ──────────────────────────────

@main.command("cache-clear")
def cache_clear() -> None:
    """Clear the in-memory query cache."""
    cleared = _cache.clear()
    click.echo(f"Cache törölve: {cleared} bejegyzés eltávolítva.")


if __name__ == "__main__":
    main()