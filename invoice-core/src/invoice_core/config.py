"""Configuration for the invoice-core microservice (loaded from ``.env``)."""

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
    file_handler = logging.FileHandler(_LOG_DIR / "invoice-core.log", encoding="utf-8")
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
    """Invoice Core settings."""

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    # ── Database (existing .env uses JDBC format) ────────────────────────────
    db_url: str = "jdbc:postgresql://localhost:5432/invoice"
    db_user: str = "invoice"
    db_pwd: str = "invoice"

    @property
    def database_url(self) -> str:
        # "jdbc:postgresql://host:port/db" → "postgresql+psycopg2://user:pwd@host:port/db"
        url = self.db_url.removeprefix("jdbc:")
        return url.replace("postgresql://", f"postgresql+psycopg2://{self.db_user}:{self.db_pwd}@", 1)

    # ── Downstream services ──────────────────────────────────────────────────
    nav_invoice_url: str = "http://localhost:8002"
    invoice_file_filter_url: str = "http://localhost:8001"
    bank_url: str = "http://localhost:8005"
    sync_timeout: int = 300

    # ── FastAPI server ───────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8004
    log_level: str = "INFO"

    # ── Tax account → label mapping (override via TAX_ACCOUNTS JSON in .env) ─
    tax_accounts: dict[str, str] = {
        "10032000-01076868-00000000": "NAV ÁFA",
        "10032000-01076301-00000000": "NAV Bírság",
        "10032000-06055950-00000000": "NAV SZJA",
        "10032000-06055912-00000000": "NAV Szochó",
        "10032000-01076019-00000000": "NAV TAO",
        "10032000-06055819-00000000": "NAV TB",
        "12001008-00272513-00100005": "HIPA",
        "12001008-00335345-00100002": "HIPA - Késedelmi",
        "12100011-10639683-00000000": "Iparkamara",
    }

    # ── Bank code → supplier name (used for fee/interest transactions) ───────
    bank_supplier_names: dict[str, str] = {
        "erste": "Erste Bank Hungary Zrt.",
        "wise": "Wise",
    }


def get_settings() -> Settings:
    """Return a settings instance loaded from the environment."""
    return Settings()


def make_http_session() -> requests.Session:
    """Create a pre-configured requests.Session for internal service clients."""
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    return session
