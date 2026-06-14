import os

from attachment_downloader.config import BASE_DIR

CREDENTIALS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE",
    "graphtrek_client_secret_611876331781-ldji0jb23got9n5fk623s0h195q61vt3.apps.googleusercontent.com.json",
)
TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

CREDENTIALS_PATH = BASE_DIR / CREDENTIALS_FILE
TOKEN_PATH = BASE_DIR / TOKEN_FILE
