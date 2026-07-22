"""Configuration for the invoice-file-filter microservice (loaded from ``.env``)."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_ROOT = _PROJECT_ROOT.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_PID = os.getpid()
_SRC_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _WORKSPACE_ROOT / ".env"


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
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "invoice-file-filter.log",
        encoding="utf-8",
        maxBytes=10_485_760,  # 10 MB
        backupCount=3,
    )
    file_handler.setFormatter(fmt)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class Settings(BaseSettings):
    """PDF Számla Feldolgozó settings."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), case_sensitive=False, extra="ignore"
    )

    # ── attachment-downloader (download) service ─────────────
    attachment_downloader_url: str = "http://localhost:8000"

    # ── PDF source / extraction ─────────────────────────────
    output_dir: str = "../attachment-downloader/downloads"
    invoice_keywords: list[str] = ["invoice", "bill", "szamla", "számla", "számviteli bizonylat"]

    # ── OCR fallback (Tesseract) ─────────────────────────────
    ocr_enabled: bool = True
    ocr_language: str = "hun+eng"
    ocr_min_chars: int = 50  # pdfplumber chars below this → try OCR

    # ── In-process PDF cache TTL (seconds) ──────────────────
    cache_ttl_seconds: int = 3600

    # ── Download timeout (seconds) ───────────────────────────
    download_timeout: int = 120

    # ── FastAPI server ──────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = Field(
        8001,
        validation_alias=AliasChoices("INVOICE_FILE_FILTER_API_PORT", "API_PORT"),
    )
    # This is the one service where LOG_LEVEL differs from the shared default
    # (DEBUG, for OCR/extraction troubleshooting), hence its own override key.
    log_level: str = Field(
        "INFO",
        validation_alias=AliasChoices("INVOICE_FILE_FILTER_LOG_LEVEL", "LOG_LEVEL"),
    )


def get_settings() -> Settings:
    """Return a settings instance loaded from the environment."""
    return Settings()
