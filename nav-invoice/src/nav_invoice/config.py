"""Configuration settings loaded from environment variables.

Maps the NAV Online Számla 3.0 *technikai felhasználó* (technical user)
credentials and software registration data into a single ``Settings`` object.
"""

import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = _PROJECT_ROOT / "logs"
_ENV_FILE = _PROJECT_ROOT / ".env"
_SRC_DIR = Path(__file__).resolve().parent.parent


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            record.relpath = Path(record.pathname).relative_to(_SRC_DIR)
        except ValueError:
            record.relpath = Path(record.pathname).name
        return super().format(record)


def configure_logging(level: str = "INFO") -> None:
    LOG_DIR.mkdir(exist_ok=True)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    fmt = _Formatter(
        "%(asctime)s %(levelname)-8s %(relpath)s:%(lineno)d %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    if root.handlers:
        return

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    file_handler = logging.FileHandler(LOG_DIR / "nav-invoice.log", encoding="utf-8")
    file_handler.setFormatter(fmt)

    root.setLevel(numeric_level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class Settings(BaseSettings):
    """NAV Online Számla 3.0 settings."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), case_sensitive=False, extra="ignore"
    )

    # ── Technical user credentials ──────────────────────
    # Field names mirror the legacy .env keys; the properties below expose them
    # under the names used by the NAV API specification.
    username: str = "your_username"        # NAV "login" (technikai felhasználó)
    password: str = "your_password"        # plain password (hashed at request time)
    license_key: str = "your_sign_key"     # XML aláírókulcs  -> signKey
    csere_key: str = "your_exchange_key"   # XML cserekulcs   -> exchangeKey
    tax_number: str = "00000000"           # 8-digit adószám törzsszám

    # ── Software registration (required in every request) ─
    software_id: str = "HU00000000NAVSZAML0"
    software_name: str = "nav-invoice-python"
    software_operation: str = "LOCAL_SOFTWARE"  # or "ONLINE_SERVICE"
    software_main_version: str = "0.1.0"
    software_dev_name: str = "nav-invoice"
    software_dev_contact: str = "dev@example.com"
    software_dev_country_code: str = "HU"
    software_dev_tax_number: str = ""

    # Legacy certificate paths (unused by the v3 REST API, kept for compat).
    certificate_path: str = "./certs/cert.pem"
    private_key_path: str = "./certs/key.pem"

    # ── Environment / endpoint ──────────────────────────
    environment: str = "test"  # "test" or "production"
    endpoint_url: str = ""     # optional full base URL override

    # ── FastAPI server ──────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    log_level: str = "INFO"
    cache_ttl_seconds: int = 3600

    # ── Derived credential accessors (NAV spec names) ───
    @property
    def login(self) -> str:
        return self.username

    @property
    def sign_key(self) -> str:
        return self.license_key

    @property
    def exchange_key(self) -> str:
        return self.csere_key

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def base_url(self) -> str:
        """Return the ``/invoiceService/v3`` base URL for the environment."""
        if self.endpoint_url and "invoiceService" in self.endpoint_url:
            return self.endpoint_url.rstrip("/")

        host = (
            "https://api.onlineszamla.nav.gov.hu"
            if self.is_production
            else "https://api-test.onlineszamla.nav.gov.hu"
        )
        return f"{host}/invoiceService/v3"

    # Backwards-compatible alias used by older code/tests.
    @property
    def endpoint(self) -> str:
        return self.base_url

    @property
    def software(self) -> dict[str, str]:
        """Software block as an ordered dict (XSD element order)."""
        return {
            "softwareId": self.software_id,
            "softwareName": self.software_name,
            "softwareOperation": self.software_operation,
            "softwareMainVersion": self.software_main_version,
            "softwareDevName": self.software_dev_name,
            "softwareDevContact": self.software_dev_contact,
            "softwareDevCountryCode": self.software_dev_country_code,
            "softwareDevTaxNumber": self.software_dev_tax_number or self.tax_number,
        }


def get_settings() -> Settings:
    """Return a settings instance loaded from the environment."""
    return Settings()