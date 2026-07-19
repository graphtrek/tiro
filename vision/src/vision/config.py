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

    # Auth — minden /ui/* oldal JWT-vel védett (teszthez kikapcsolható)
    auth_enabled: bool = True
    jwt_audience: str = "moneypenny"
    jwt_issuer: str = "auth-service"

    # Upstream services
    auth_service_url: str = "http://localhost:8007"
    # Browser-reachable auth URL (login links, silent-refresh fetch). Falls back to
    # auth_service_url — only needs overriding when that's a Docker-internal hostname
    # the browser can't resolve (e.g. auth_service_url=http://auth:8007).
    auth_public_url: str = ""
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

    @property
    def auth_public_url_or_default(self) -> str:
        return self.auth_public_url or self.auth_service_url


def get_settings() -> Settings:
    return Settings()


def make_http_session() -> requests.Session:
    from vision.auth import TokenPassthrough  # lazy import (körkörös import ellen)

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    # A beérkező kérés Bearer tokenjét továbbadjuk a hívott szerviznek
    # (per-request `auth=` — pl. srcprofit basic auth — felülírja ezt).
    session.auth = TokenPassthrough()
    return session
