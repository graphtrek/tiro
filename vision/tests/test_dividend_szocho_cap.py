"""Dividend page shows the annual szocho cap invoice-core now reports.

The cap line is rendered from `szocho_cap`/`szocho_base`, which older
invoice-core builds don't return -- the page must still render without them.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import vision.auth as vision_auth
from vision.api.main import app
from vision.clients.invoice_core import InvoiceCoreClient

REPORT = {
    "year": 2026,
    "revenue": 100_000_000.0,
    "expenses": 10_000_000.0,
    "gross_profit": 90_000_000.0,
    "tao_rate": 0.09,
    "tao_tax": 8_100_000.0,
    "hipa_rate": 0.02,
    "hipa_tax": 2_000_000.0,
    "net_profit": 79_900_000.0,
    "szja_rate": 0.15,
    "szja_tax": 11_985_000.0,
    "szocho_rate": 0.13,
    "szocho_cap": 7_747_200.0,
    "szocho_base": 7_747_200.0,
    "szocho_tax": 1_007_136.0,
    "net_dividend_without_szocho": 67_915_000.0,
    "net_dividend_with_szocho": 66_907_864.0,
    "invoice_count_out": 10,
    "invoice_count_in": 5,
    "monthly": [],
}


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture(autouse=True)
def local_jwks(keypair, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _, public_pem = keypair
    monkeypatch.setattr(vision_auth, "_get_signing_key", lambda token, url: public_pem)


@pytest.fixture
def auth_header(keypair) -> dict[str, str]:
    private_pem, _ = keypair
    now = int(time.time())
    token = pyjwt.encode(
        {
            "sub": "google-user-1",
            "email": "imre.tatai@graphtrek.co",
            "name": "Imre Tatai",
            "provider": "google",
            "typ": "access",
            "iat": now,
            "exp": now + 900,
            "iss": "auth-service",
            "aud": "tiro",
        },
        private_pem,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def test_page_shows_the_cap(monkeypatch, client, auth_header):
    monkeypatch.setattr(InvoiceCoreClient, "get_dividend_report", lambda self, year: REPORT)

    response = client.get("/ui/dividend", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert "éves plafon" in response.text
    assert "7 747 200" in response.text


def test_page_renders_without_cap_fields(monkeypatch, client, auth_header):
    legacy = {k: v for k, v in REPORT.items() if k not in ("szocho_cap", "szocho_base")}
    monkeypatch.setattr(InvoiceCoreClient, "get_dividend_report", lambda self, year: legacy)

    response = client.get("/ui/dividend", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert "éves plafon" not in response.text
