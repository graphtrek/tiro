"""Configuration for the pdf-szamla microservice (loaded from ``.env``)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


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
