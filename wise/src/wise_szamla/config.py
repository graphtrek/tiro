"""Wise Banki Mikorszerviz konfiguráció (`.env`-ből töltve)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def configure_logging(log_level: str = "INFO") -> None:
    _LOG_DIR.mkdir(exist_ok=True)
    level = getattr(logging, log_level.upper(), logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    file_handler = logging.FileHandler(_LOG_DIR / "wise.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class Settings(BaseSettings):
    """Wise Banki Mikorszerviz beállítások."""

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    # ── Wise API ────────────────────────────────────────────────
    wise_api_key: str = ""
    wise_profile_id: int = 0
    wise_account_currency: str = "EUR"
    wise_sandbox: bool = False

    # ── szamla-db orchestrátor ──────────────────────────────────
    szamla_db_url: str = "http://localhost:8003"

    # ── FastAPI szerver ─────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8004
    log_level: str = "INFO"

    # ── HTTP kliens ─────────────────────────────────────────────
    request_timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0


def get_settings() -> Settings:
    """Visszaadja a környezetből betöltött beállítások példányát."""
    return Settings()
