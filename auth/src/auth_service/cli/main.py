"""Typer CLI az auth mikroszervizhez (script neve: `auth`)."""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from auth_service.config import configure_logging, get_settings
from auth_service.jwt_service import JWTService, generate_keypair
from auth_service.models import AuthError
from auth_service.service import AuthService, Denylist

app = typer.Typer(
    help="Auth - Központi Authentication Mikroszerviz (Google OAuth 2.0 + JWT).",
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
    """Konfiguráció + kulcsok + providerek állapota."""
    settings = get_settings()
    private_ok = Path(settings.jwt_private_key_path).exists()
    public_ok = Path(settings.jwt_public_key_path).exists()

    console.print("[bold]Kulcsok[/bold]")
    console.print(f"  privát:   {settings.jwt_private_key_path}  "
                  f"{'[green]✓[/green]' if private_ok else '[red]✗ hiányzik[/red]'}")
    console.print(f"  publikus: {settings.jwt_public_key_path}  "
                  f"{'[green]✓[/green]' if public_ok else '[red]✗ hiányzik[/red]'}")
    if private_ok and public_ok:
        jwt_service = JWTService(settings)
        console.print(f"  kid:      {jwt_service.kid}")
    else:
        console.print("  [yellow]Futtasd: auth keygen[/yellow]")

    console.print("\n[bold]JWT[/bold]")
    console.print(f"  issuer: {settings.jwt_issuer} · audience: {settings.jwt_audience}")
    console.print(f"  access TTL: {settings.access_token_ttl}s · "
                  f"refresh TTL: {settings.refresh_token_ttl}s")

    console.print("\n[bold]Google OAuth[/bold]")
    client_ok = bool(settings.google_client_id and settings.google_client_secret)
    client_state = (
        "[green]✓ konfigurálva[/green]"
        if client_ok
        else "[red]✗ hiányzó GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET[/red]"
    )
    console.print(f"  client: {client_state}")
    console.print(f"  redirect: {settings.oauth_redirect_url}")

    console.print("\n[bold]Whitelist[/bold]")
    console.print(
        f"  e-mailek: {', '.join(settings.allowed_emails_list) or '[dim]–[/dim]'}"  # noqa: RUF001
    )
    console.print(
        f"  domainek: {', '.join(settings.allowed_domains_list) or '[dim]–[/dim]'}"  # noqa: RUF001
    )

    denylist = Denylist(settings.denylist_path)
    console.print(f"\n[bold]Visszavont refresh tokenek:[/bold] {len(denylist)}")
    console.print(f"[bold]Providerek:[/bold] {', '.join(settings.enabled_providers_list)}")


@app.command()
def keygen(
    out: Annotated[str, typer.Option("--out", help="Cél könyvtár")] = "keys",
    force: bool = typer.Option(False, "--force", help="Meglévő kulcsok felülírása"),
):
    """RS256 kulcspár generálása (első beüzemelés)."""
    out_dir = Path(out)
    private_path = out_dir / "jwt_private.pem"
    if private_path.exists() and not force:
        console.print(
            f"[red]✗ Már létezik: {private_path} — használd a --force opciót a felülíráshoz.[/red]"
        )
        console.print(
            "[yellow]Figyelem: új kulcs után minden kiadott token érvénytelenné válik![/yellow]"
        )
        raise typer.Exit(code=1)
    private_path, public_path = generate_keypair(out_dir)
    console.print(f"[green]✓[/green] Privát kulcs:   {private_path}")
    console.print(f"[green]✓[/green] Publikus kulcs: {public_path}")


@app.command()
def verify(token: Annotated[str, typer.Argument(help="JWT (access vagy refresh)")]):
    """JWT dekódolás + validálás (debug)."""
    settings = get_settings()
    jwt_service = JWTService(settings)
    for typ in ("access", "refresh"):
        try:
            claims = jwt_service.decode(token, expected_typ=typ)
        except AuthError as exc:
            last_error = exc
            continue
        console.print(f"[green]✓ Érvényes {typ} token[/green]")
        console.print_json(_json.dumps(claims.model_dump()))
        return
    console.print(f"[red]✗ Érvénytelen token: {last_error}[/red]")
    raise typer.Exit(code=1)


@app.command()
def revoke(jti: Annotated[str, typer.Argument(help="A refresh token jti claim-je")]):
    """Refresh token visszavonása jti alapján."""
    settings = get_settings()
    denylist = Denylist(settings.denylist_path)
    if jti in denylist:
        console.print(f"[yellow]Már vissza van vonva: {jti}[/yellow]")
        return
    denylist.add(jti)
    console.print(f"[green]✓ Visszavonva: {jti}[/green] ({settings.denylist_path})")


@app.command()
def providers():
    """Engedélyezett providerek listája."""
    service = AuthService()
    table = Table(show_lines=False)
    table.add_column("Kulcs", width=12)
    table.add_column("Címke")
    table.add_column("Ikon", width=12)
    table.add_column("Login URL")
    for info in service.provider_infos():
        table.add_row(info.key, info.label, info.icon, info.login_url)
    console.print(table)


if __name__ == "__main__":
    app()
