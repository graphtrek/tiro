"""Configuration for the invoice-file-filter microservice (loaded from ``.env``)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_SRC_DIR = Path(__file__).resolve().parent.parent


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            record.relpath = Path(record.pathname).relative_to(_SRC_DIR)
        except ValueError:
            record.relpath = Path(record.pathname).name
        return super().format(record)


def configure_logging(log_level: str = "INFO") -> None:
    _LOG_DIR.mkdir(exist_ok=True)
    level = getattr(logging, log_level.upper(), logging.INFO)
    fmt = _Formatter(
        "%(asctime)s %(levelname)-8s %(relpath)s:%(lineno)d %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    file_handler = logging.FileHandler(_LOG_DIR / "invoice-file-filter.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)

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

    # ── attachment-downloader (download) service ─────────────
    attachment_downloader_url: str = "http://localhost:8000"

    # ── PDF source / extraction ─────────────────────────────
    output_dir: str = "../attachment-downloader/downloads"
    invoice_keywords: list[str] = ["invoice", "bill", "szamla", "számla"]

    # ── Download timeout (seconds) ───────────────────────────
    download_timeout: int = 120

    # ── FastAPI server ──────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Return a settings instance loaded from the environment."""
    return Settings()
