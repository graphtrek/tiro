"""Support impersonation tesztek — admin gating + auth szerviz proxyzás."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import vision.auth as vision_auth
import vision.ui.admin_router as admin_router
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
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_EMAILS", "imre.tatai@graphtrek.co")
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


def test_impersonate_rejects_non_admin(client: TestClient, keypair):
    private_pem, _ = keypair
    token = make_token(private_pem, email="nem.admin@graphtrek.co")
    client.cookies.set("mp_access_token", token)
    response = client.post("/ui/admin/users/impersonate", data={"email": "kozma@graphtrek.co"})
    assert response.status_code == 403


def test_impersonate_success_sets_access_cookie_and_redirects(
    client: TestClient, keypair, monkeypatch
):
    private_pem, _ = keypair
    token = make_token(private_pem)
    client.cookies.set("mp_access_token", token)

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/auth/impersonate")
        assert json == {"email": "kozma@graphtrek.co"}
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"access_token": "new-impersonation-token", "expires_in": 900},
        )

    monkeypatch.setattr(admin_router.requests, "post", fake_post)
    response = client.post("/ui/admin/users/impersonate", data={"email": "kozma@graphtrek.co"})

    assert response.status_code == 302
    assert response.headers["location"] == "/ui/"
    set_cookie = response.headers.get_list("set-cookie")
    assert any("mp_access_token=new-impersonation-token" in c for c in set_cookie)
    # a refresh cookie-hoz nem nyúlunk — az admin saját refresh tokenje érintetlen marad
    assert not any("mp_refresh_token" in c for c in set_cookie)


def test_impersonate_auth_service_unreachable_returns_502(client: TestClient, keypair, monkeypatch):
    private_pem, _ = keypair
    token = make_token(private_pem)
    client.cookies.set("mp_access_token", token)

    import requests

    def fake_post(*args, **kwargs):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(admin_router.requests, "post", fake_post)
    response = client.post("/ui/admin/users/impersonate", data={"email": "kozma@graphtrek.co"})
    assert response.status_code == 502


def test_stop_impersonation_without_refresh_cookie_redirects_to_login(client: TestClient, keypair):
    private_pem, _ = keypair
    # a middleware csak érvényes access tokennel enged tovább — ez a megszemélyesített token
    impersonated_token = make_token(private_pem, sub="target-1", email="kozma@graphtrek.co")
    client.cookies.set("mp_access_token", impersonated_token)
    response = client.get("/stop-impersonation")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_stop_impersonation_restores_admin_access_cookie(client: TestClient, keypair, monkeypatch):
    import vision.ui.router as ui_router

    private_pem, _ = keypair
    impersonated_token = make_token(private_pem, sub="target-1", email="kozma@graphtrek.co")
    client.cookies.set("mp_access_token", impersonated_token)
    client.cookies.set("mp_refresh_token", "admin-refresh-token")

    def fake_post(url, cookies=None, timeout=None):
        assert url.endswith("/auth/refresh")
        assert cookies == {"mp_refresh_token": "admin-refresh-token"}
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"access_token": "admins-own-token", "expires_in": 900},
        )

    monkeypatch.setattr(ui_router.requests, "post", fake_post)
    response = client.get("/stop-impersonation")

    assert response.status_code == 302
    assert response.headers["location"] == "/ui/"
    set_cookie = response.headers.get_list("set-cookie")
    assert any("mp_access_token=admins-own-token" in c for c in set_cookie)
