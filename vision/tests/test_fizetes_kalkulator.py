"""Fizetes kalkulator page -- savable wage/dividend calculator inputs.

Covers the "fizetes-kalkulator should be able to save (in the database)"
feature: the page must seed its net-wage/revenue inputs from the state saved
via invoice-core's `/api/v1/fizetes-kalkulator`, and the new
`POST /ui/fizetes-kalkulator` route must forward the edited values back to
invoice-core and redirect (303, redirect-after-POST) so a reload proves the
round trip.
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
    payload = {
        "sub": "google-user-1",
        "email": "imre.tatai@graphtrek.co",
        "name": "Imre Tatai",
        "provider": "google",
        "typ": "access",
        "iat": now,
        "exp": now + 900,
        "iss": "auth-service",
        "aud": "moneypenny",
    }
    token = pyjwt.encode(payload, private_pem, algorithm="RS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def test_page_seeds_inputs_from_saved_state(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_fizetes_kalkulator",
        lambda self: {"net_wage": 1_200_000.0, "revenue": 8_500_000.0, "revenue_touched": True},
    )

    response = client.get("/ui/fizetes-kalkulator", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert 'name="net_wage" value="1200000"' in response.text
    assert 'name="revenue" value="8500000"' in response.text
    assert 'id="fc-revenue-touched" value="true"' in response.text


def test_page_falls_back_to_defaults_when_never_saved(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_fizetes_kalkulator",
        lambda self: {"net_wage": 1_000_000.0, "revenue": 0.0, "revenue_touched": False},
    )

    response = client.get("/ui/fizetes-kalkulator", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert 'name="net_wage" value="1000000"' in response.text
    assert 'id="fc-revenue-touched" value="false"' in response.text


def test_save_forwards_payload_and_redirects(monkeypatch, client, auth_header):
    captured = {}

    def fake_save(self, net_wage, revenue, revenue_touched):
        captured["net_wage"] = net_wage
        captured["revenue"] = revenue
        captured["revenue_touched"] = revenue_touched
        return {"net_wage": net_wage, "revenue": revenue, "revenue_touched": revenue_touched}

    monkeypatch.setattr(InvoiceCoreClient, "save_fizetes_kalkulator", fake_save)

    response = client.post(
        "/ui/fizetes-kalkulator",
        data={"net_wage": "1300000", "revenue": "9000000", "revenue_touched": "true"},
        headers=auth_header,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ui/fizetes-kalkulator?saved=1"
    assert captured == {"net_wage": 1300000.0, "revenue": 9000000.0, "revenue_touched": True}


def test_save_client_error_redirects_with_error(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "save_fizetes_kalkulator",
        lambda self, net_wage, revenue, revenue_touched: {
            "error": "Nem sikerult menteni a kalkulator adatait"
        },
    )

    response = client.post(
        "/ui/fizetes-kalkulator",
        data={"net_wage": "1300000", "revenue": "9000000", "revenue_touched": "false"},
        headers=auth_header,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/ui/fizetes-kalkulator?error=")
    assert "menteni" in response.headers["location"]


def test_page_shows_success_banner(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_fizetes_kalkulator",
        lambda self: {"net_wage": 1_000_000.0, "revenue": 0.0, "revenue_touched": False},
    )

    response = client.get(
        "/ui/fizetes-kalkulator?saved=1", headers={**auth_header, "Accept": "text/html"}
    )

    assert response.status_code == 200
    assert "alert-success" in response.text
    assert "Kalkulátor adatai mentve" in response.text


def test_page_shows_error_banner(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_fizetes_kalkulator",
        lambda self: {"net_wage": 1_000_000.0, "revenue": 0.0, "revenue_touched": False},
    )

    response = client.get(
        "/ui/fizetes-kalkulator?error=Nem+sikerult+menteni",
        headers={**auth_header, "Accept": "text/html"},
    )

    assert response.status_code == 200
    assert "alert-danger" in response.text
    assert "Nem sikerult menteni" in response.text
