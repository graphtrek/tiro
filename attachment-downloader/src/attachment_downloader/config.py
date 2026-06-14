import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def configure_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    file_handler = logging.FileHandler(LOG_DIR / "attachment-downloader.log", encoding="utf-8")
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

# Project root directory (config.py lives at attachment_downloader/config/config.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Google API configuration — attachment-downloader's own OAuth client, independent of any other project
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

DOWNLOAD_ROOT_DIR = BASE_DIR / os.getenv("DOWNLOAD_ROOT_DIR", "downloads")

CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "graphtrek_client_secret_611876331781-ldji0jb23got9n5fk623s0h195q61vt3.apps.googleusercontent.com.json")
TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

# Resolve absolute paths
CREDENTIALS_PATH = BASE_DIR / CREDENTIALS_FILE
TOKEN_PATH = BASE_DIR / TOKEN_FILE

def get_credentials_path() -> str:
    """Returns the absolute path to the credentials file."""
    return str(CREDENTIALS_PATH)

def get_token_path() -> str:
    """Returns the absolute path to the token file."""
    return str(TOKEN_PATH)

def validate_config():
    """Validates that the necessary configuration files exist."""
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(f"Credentials file not found at: {CREDENTIALS_PATH}")