"""Shared fixtures for tests."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def mock_env(tmp_path: Path):
    """Create a temporary .env file for each test."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NAV_USERNAME=testuser\n"
        "NAV_PASSWORD=testpass\n"
        "NAV_LICENSE_KEY=testkey123\n"
        "NAV_CERTIFICATE_PATH=./certs/cert.pem\n"
        "NAV_PRIVATE_KEY_PATH=./certs/key.pem\n"
        "NAV_ENVIRONMENT=test\n"
        "NAV_ENDPOINT_URL=http://test.nav.example.com/navservice/\n"
    )

    # Point to the temp .env
    os.environ["PYDANTIC_SETTINGS_ENV_FILE"] = str(env_file)

    yield env_file