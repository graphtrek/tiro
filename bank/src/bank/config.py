"""Bank mikroszerviz konfiguráció (`.env`-ből töltve)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_ROOT = _PROJECT_ROOT.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_BALANCE_STATEMENTS_DIR = _WORKSPACE_ROOT / "storage" / "bank" / "balance-statements"


def configure_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers and root.level == level:
        return
    _LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    file_handler = logging.FileHandler(_LOG_DIR / "bank.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class Settings(BaseSettings):
    """Bank mikroszerviz beállítások."""

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    balance_statements_dir: str = str(_BALANCE_STATEMENTS_DIR)
    erste_subdir: str = "erste"
    wise_subdir: str = "wise"
    api_host: str = "0.0.0.0"
    api_port: int = 8005
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
