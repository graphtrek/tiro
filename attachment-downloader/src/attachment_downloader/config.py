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