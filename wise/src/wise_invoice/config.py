"""Wise Banki Mikorszerviz konfiguráció (`.env`-ből töltve)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_ROOT = _PROJECT_ROOT.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_BALANCE_STATEMENTS_DIR = _PROJECT_ROOT / "balance-statements"
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
    file_handler = logging.FileHandler(_LOG_DIR / "wise.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class Settings(BaseSettings):
    """Wise Banki Mikorszerviz beállítások."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), case_sensitive=False, extra="ignore"
    )

    # ── Wise API ────────────────────────────────────────────────
    wise_api_key: str = ""
    wise_profile_id: int = 0
    wise_account_currency: str = "EUR"
    wise_sandbox: bool = False

    # ── FastAPI szerver ─────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = Field(
        8003, validation_alias=AliasChoices("WISE_API_PORT", "API_PORT")
    )
    log_level: str = "INFO"

    # ── SCA (Strong Customer Authentication) ────────────────────
    # Path to PEM private key registered in Wise API settings.
    # Required for statement downloads (balance-statements endpoint).
    wise_sca_private_key_path: str = ""

    # ── CSV import ──────────────────────────────────────────────
    # Mappa a Wise webfelületről kézzel letöltött kivonat CSV-knek.
    # Fájlnév-séma: statement_<balanceId>_<currency>_<from>_<to>.csv
    balance_statements_dir: str = str(_BALANCE_STATEMENTS_DIR)

    # ── HTTP kliens ─────────────────────────────────────────────
    # This is the one service where REQUEST_TIMEOUT differs from the shared
    # default (SCA balance-statement downloads are slow), hence its own key.
    request_timeout: int = Field(
        30, validation_alias=AliasChoices("WISE_REQUEST_TIMEOUT", "REQUEST_TIMEOUT")
    )
    max_retries: int = 3
    retry_delay: float = 1.0


def get_settings() -> Settings:
    """Visszaadja a környezetből betöltött beállítások példányát."""
    return Settings()
