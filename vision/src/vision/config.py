"""Configuration for the vision microservice (loaded from ``.env``)."""

from __future__ import annotations

import logging
from pathlib import Path

import requests
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
    file_handler = logging.FileHandler(_LOG_DIR / "vision.log", encoding="utf-8")
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class Settings(BaseSettings):
    """Vision service settings."""

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    # Upstream services
    invoice_core_url: str = "http://localhost:8004"
    uploader_url: str = "http://localhost:8006"
    srcprofit_url: str = "https://srcprofit2.graphtrek.co"
    srcprofit_user: str = "admin"
    srcprofit_password: str = ""
    request_timeout: int = 10

    # FastAPI server
    api_host: str = "0.0.0.0"
    api_port: int = 8009
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()


def make_http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    return session
