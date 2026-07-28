"""Auth mikroszerviz konfiguráció (`.env`-ből töltve)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_ROOT = _PROJECT_ROOT.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_KEYS_DIR = _PROJECT_ROOT / "keys"
_ENV_FILE = _WORKSPACE_ROOT / ".env"


def configure_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers and root.level == level:
        return
    _LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    file_handler = logging.FileHandler(_LOG_DIR / "auth.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class Settings(BaseSettings):
    """Auth mikroszerviz beállítások."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), case_sensitive=False, extra="ignore"
    )

    # Google OAuth (Google Cloud Console → OAuth 2.0 Client ID, Web application)
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_url: str = "http://localhost:8007/auth/google/callback"

    # JWT (RS256 kulcspár — `auth keygen` generálja)
    jwt_private_key_path: str = str(_KEYS_DIR / "jwt_private.pem")
    jwt_public_key_path: str = str(_KEYS_DIR / "jwt_public.pem")
    access_token_ttl: int = 900  # 15 perc
    refresh_token_ttl: int = 2_592_000  # 30 nap
    jwt_audience: str = "moneypenny"
    jwt_issuer: str = "auth-service"

    # Jogosultság — csak whitelistelt e-mail / domain léphet be
    allowed_emails: str = ""  # vesszővel elválasztva
    allowed_domains: str = ""  # vesszővel elválasztva

    # Admin — ezek az e-mailek indíthatnak megszemélyesítést (POST /auth/impersonate)
    admin_emails: str = ""  # vesszővel elválasztva

    # Providerek
    enabled_providers: str = "google"

    # Cookie-k (localhost fejlesztésnél nincs HTTPS → secure kikapcsolva)
    cookie_secure: bool = False
    access_cookie_name: str = "mp_access_token"
    refresh_cookie_name: str = "mp_refresh_token"

    # Refresh token visszavonás — fájl alapú denylist (nincs DB)
    denylist_path: str = str(_KEYS_DIR / "revoked_jti.txt")

    # OAuth state / PKCE bejegyzések élettartama másodpercben
    login_state_ttl: int = 600

    # Szerver
    vision_url: str = "http://localhost:8009"  # login utáni default redirect
    api_host: str = "0.0.0.0"
    api_port: int = Field(
        8007, validation_alias=AliasChoices("AUTH_API_PORT", "API_PORT")
    )
    log_level: str = "INFO"

    # invoice-core — login rekord mentése (best-effort, POST /api/v1/users)
    invoice_core_url: str = "http://localhost:8004"

    @property
    def allowed_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()]

    @property
    def allowed_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_domains.split(",") if d.strip()]

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def enabled_providers_list(self) -> list[str]:
        return [p.strip().lower() for p in self.enabled_providers.split(",") if p.strip()]


def get_settings() -> Settings:
    return Settings()
