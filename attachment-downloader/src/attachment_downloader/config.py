import logging
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_ROOT = _BASE_DIR.parent
_LOG_DIR = _BASE_DIR / "logs"
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
    file_handler = logging.FileHandler(_LOG_DIR / "attachment-downloader.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), case_sensitive=False, extra="ignore")

    google_credentials_file: str = "credentials.json"
    google_token_file: str = "token.json"
    cache_ttl_seconds: int = 3600
    download_root_dir: str = "downloads"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(
        8000,
        validation_alias=AliasChoices("ATTACHMENT_DOWNLOADER_API_PORT", "API_PORT"),
    )

    @property
    def credentials_path(self) -> Path:
        return _BASE_DIR / self.google_credentials_file

    @property
    def token_path(self) -> Path:
        return _BASE_DIR / self.google_token_file

    @property
    def download_root(self) -> Path:
        return _BASE_DIR / self.download_root_dir


def get_settings() -> Settings:
    return Settings()
