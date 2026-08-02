"""Configuration for the invoice-core microservice (loaded from ``.env``)."""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_ROOT = _PROJECT_ROOT.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
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

    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), case_sensitive=False, extra="ignore")

    # ── Database (existing .env uses JDBC format) ────────────────────────────
    db_url: str = "jdbc:postgresql://localhost:5432/invoice"
    db_user: str = "invoice"
    db_pwd: str = "invoice"

    @property
    def database_url(self) -> str:
        """Convert the JDBC-style DB_URL from .env into a SQLAlchemy connection string.

        The .env file stores the DB URL in JDBC format (e.g. what a Java tool would
        expect): "jdbc:postgresql://host:port/db". SQLAlchemy instead needs a URL that
        also carries the driver name and credentials, e.g.
        "postgresql+psycopg2://user:pwd@host:port/db". This property does that
        rewrite: drop the leading "jdbc:", then splice in the "+psycopg2" driver
        suffix and "user:pwd@" credentials right after "postgresql://".
        """
        url = self.db_url.removeprefix("jdbc:")
        return url.replace(
            "postgresql://", f"postgresql+psycopg2://{self.db_user}:{self.db_pwd}@", 1
        )

    # ── Downstream services ──────────────────────────────────────────────────
    nav_invoice_url: str = "http://localhost:8002"
    invoice_file_filter_url: str = "http://localhost:8001"
    bank_url: str = "http://localhost:8005"
    sync_timeout: int = 300

    # ── FastAPI server ───────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = Field(8004, validation_alias=AliasChoices("INVOICE_CORE_API_PORT", "API_PORT"))
    log_level: str = "INFO"

    # ── Tax account → label mapping (override via TAX_ACCOUNTS JSON in .env) ─
    # Maps Hungarian tax-authority (NAV) and local-council bank account numbers to
    # a human-readable label, so bank transactions paid to these accounts can be
    # shown in reports as e.g. "NAV ÁFA" (VAT) instead of a raw account number.
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
    # Bank fee/interest transactions don't come with a real counterparty name, so
    # we treat the bank itself as the "supplier" for these transactions and use
    # this mapping to turn the short bank code ("erste", "wise") into a proper
    # display name.
    bank_supplier_names: dict[str, str] = {
        "erste": "Erste Bank Hungary Zrt.",
        "wise": "Wise",
    }


def get_settings() -> Settings:
    """Return a settings instance loaded from the environment."""
    return Settings()


def make_http_session() -> requests.Session:
    """Create a pre-configured requests.Session for internal service clients."""
    from invoice_core.auth import TokenPassthrough  # lazy import (körkörös import ellen)

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    # A beérkező kérés Bearer tokenjét továbbadjuk a hívott szerviznek.
    session.auth = TokenPassthrough()
    return session


def token_hint_for_error(exc: Exception) -> str:
    """Suffix appended to an outbound-call error when it looks like a missing/
    invalid bearer token (401 from the downstream service), telling the CLI
    user how to supply one — see DEF-002 / README's CLI Auth section.

    The CLI has no bearer token of its own (unlike a request coming through
    the API, which forwards the caller's token via `current_token`/
    `TokenPassthrough`); `invoice-core sync`'s `--token` option or the shared
    `MP_SERVICE_TOKEN` env var fill that gap.
    """
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 401:
        return (
            " — supply a bearer token via --token or the MP_SERVICE_TOKEN "
            "env var (see invoice-core/README.md)"
        )
    return ""


def error_detail_from_response(exc: Exception) -> str:
    """Suffix appended to an outbound-call error with the downstream service's
    JSON ``detail`` field, when present — surfaces the *actual* root cause
    instead of just the generic HTTP status line. This matters most for
    chained failures: e.g. nav-invoice/invoice-file-filter/bank each proxy a
    further downstream call and translate any failure there into their own
    502, so without this the sync-log `errors` column only ever shows
    "502 Server Error: Bad Gateway" with no indication of which downstream
    service actually failed or why.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    if not detail:
        return ""
    return f" — upstream detail: {detail}"
