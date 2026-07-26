"""Auth middleware tesztek — publikus vs. védett útvonalak."""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import vision.auth as vision_auth
from vision.api.main import app


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
    """A JWKS letöltés helyett a lokális tesztkulcsot használjuk."""
    # a .env-ben kikapcsolt auth-ot a tesztekhez visszakapcsoljuk
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _, public_pem = keypair
    monkeypatch.setattr(vision_auth, "_get_signing_key", lambda token, url: public_pem)


def make_token(private_pem: bytes, **overrides) -> str:
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
    payload.update(overrides)
    return pyjwt.encode(payload, private_pem, algorithm="RS256")


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def test_public_pages_open_without_token(client: TestClient):
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/login").status_code == 200


def test_protected_page_redirects_browser_to_login(client: TestClient):
    response = client.get("/ui/invoices", headers={"Accept": "text/html"})
    assert response.status_code == 302
    assert response.headers["location"] == "/login?next=%2Fui%2Finvoices"


def test_protected_page_keeps_query_in_next(client: TestClient):
    response = client.get(
        "/ui/invoices", params={"direction": "INBOUND"}, headers={"Accept": "text/html"}
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login?next=%2Fui%2Finvoices%3Fdirection%3DINBOUND"


def test_protected_api_call_returns_401_json(client: TestClient):
    response = client.get("/ui/invoices", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert "token" in response.json()["detail"]


def test_valid_bearer_token_passes(client: TestClient, keypair):
    private_pem, _ = keypair
    token = make_token(private_pem)
    response = client.get(
        "/ui/invoices",
        headers={"Authorization": f"Bearer {token}", "Accept": "text/html"},
    )
    # átjut a middleware-en (az oldal maga üres invoice-core adatokkal renderel)
    assert response.status_code == 200


def test_valid_cookie_passes(client: TestClient, keypair):
    private_pem, _ = keypair
    client.cookies.set("mp_access_token", make_token(private_pem))
    response = client.get("/ui/invoices", headers={"Accept": "text/html"})
    assert response.status_code == 200


def test_expired_token_redirects(client: TestClient, keypair):
    private_pem, _ = keypair
    old = int(time.time()) - 3600
    token = make_token(private_pem, iat=old, exp=old + 900)
    response = client.get(
        "/ui/invoices",
        headers={"Authorization": f"Bearer {token}", "Accept": "text/html"},
    )
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login?next=")


def test_refresh_token_not_accepted(client: TestClient, keypair):
    private_pem, _ = keypair
    token = make_token(private_pem, typ="refresh")
    response = client.get("/ui/invoices", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_wrong_audience_rejected(client: TestClient, keypair):
    private_pem, _ = keypair
    token = make_token(private_pem, aud="masik-rendszer")
    response = client.get("/ui/invoices", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_logout_clears_cookies(client: TestClient, keypair):
    private_pem, _ = keypair
    client.cookies.set("mp_access_token", make_token(private_pem))
    response = client.get("/logout")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    set_cookie = response.headers.get_list("set-cookie")
    assert any("mp_access_token" in c for c in set_cookie)
