"""Configuration for the pdf-szamla microservice (loaded from ``.env``)."""

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
    file_handler = logging.FileHandler(_LOG_DIR / "pdf-szamla.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(stream_handler)
        root.addHandler(file_handler)
    else:
        root.handlers.clear()
        root.addHandler(stream_handler)
        root.addHandler(file_handler)


class Settings(BaseSettings):
    """PDF Számla Feldolgozó settings."""

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    # ── graphtrek-email (download) service ──────────────────
    graphtrek_email_url: str = "http://localhost:8000"

    # ── PDF source / extraction ─────────────────────────────
    output_dir: str = "../graphtrek-gmail/downloads"
    invoice_keywords: list[str] = ["invoice", "bill", "szamla", "számla"]

    # ── Download job polling (seconds) ──────────────────────
    download_timeout: int = 120
    poll_interval: float = 2.0

    # ── FastAPI server ──────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Return a settings instance loaded from the environment."""
    return Settings()
