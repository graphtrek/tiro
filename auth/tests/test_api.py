"""FastAPI végpont tesztek (TestClient, fake providerrel)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from auth_service.api import main as api_main
from auth_service.models import UserInfo
from auth_service.service import AuthService
from tests.conftest import FakeInvoiceCoreClient, FakeProvider


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(settings, jwt_service, provider):
    service = AuthService(
        settings=settings,
        jwt_service=jwt_service,
        providers={"google": provider},
        invoice_core_client=FakeInvoiceCoreClient(),
    )
    api_main.app.dependency_overrides[api_main.get_service] = lambda: service
    with TestClient(api_main.app, follow_redirects=False) as test_client:
        yield test_client
    api_main.app.dependency_overrides.clear()


def _do_login(client: TestClient) -> None:
    """Teljes belépési flow: login redirect → callback → cookie-k."""
    login = client.get("/auth/google/login", params={"next": "/ui/dashboard"})
    assert login.status_code == 302
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

    callback = client.get("/auth/google/callback", params={"code": "c", "state": state})
    assert callback.status_code == 302
    assert callback.headers["location"] == "http://localhost:8009/ui/dashboard"


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_jwks(client: TestClient):
    response = client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    keys = response.json()["keys"]
    assert keys and keys[0]["kty"] == "RSA" and keys[0]["kid"]


def test_providers(client: TestClient):
    response = client.get("/auth/providers")
    assert response.status_code == 200
    assert response.json() == [
        {
            "key": "google",
            "label": "Belépés Google-fiókkal",
            "icon": "bi-google",
            "login_url": "/auth/google/login",
        }
    ]


def test_login_redirects_to_provider(client: TestClient):
    response = client.get("/auth/google/login")
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://fake.google.example/authorize")
    query = parse_qs(urlparse(location).query)
    assert query["state"][0] and query["code_challenge"][0]


def test_login_unknown_provider_404(client: TestClient):
    assert client.get("/auth/microsoft/login").status_code == 404


def test_full_login_flow_sets_cookies(client: TestClient):
    _do_login(client)
    assert client.cookies.get("mp_access_token")
    assert client.cookies.get("mp_refresh_token")


def test_callback_invalid_state_redirects_to_login_error(client: TestClient):
    response = client.get("/auth/google/callback", params={"code": "c", "state": "rossz"})
    assert response.status_code == 302
    assert response.headers["location"].startswith("http://localhost:8009/login?error=")


def test_callback_provider_error_redirects_to_login_error(client: TestClient):
    response = client.get("/auth/google/callback", params={"error": "access_denied"})
    assert response.status_code == 302
    assert "/login?error=" in response.headers["location"]


def test_callback_blocked_email_redirects_with_error(
    client: TestClient, settings, provider: FakeProvider
):
    settings.blocked_emails = "idegen@gmail.com"
    provider.user = UserInfo(sub="x", email="idegen@gmail.com", provider="google")
    login = client.get("/auth/google/login")
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    response = client.get("/auth/google/callback", params={"code": "c", "state": state})
    assert response.status_code == 302
    assert "/login?error=" in response.headers["location"]
    assert not client.cookies.get("mp_access_token")


def test_callback_open_readonly_login_succeeds_for_unlisted_email(
    client: TestClient, provider: FakeProvider
):
    """Bármely más hitelesített Google fiók mostantól belép (anonimizált read_only)."""
    provider.user = UserInfo(sub="x", email="idegen@gmail.com", provider="google")
    login = client.get("/auth/google/login")
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    response = client.get("/auth/google/callback", params={"code": "c", "state": state})
    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:8009"
    assert client.cookies.get("mp_access_token")


def test_me_with_cookie(client: TestClient):
    _do_login(client)
    response = client.get("/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "imre.tatai@graphtrek.co"
    assert body["provider"] == "google"


def test_me_with_bearer_header(client: TestClient, settings, jwt_service, provider):
    token = jwt_service.issue_access_token(provider.user)
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_me_without_token_401(client: TestClient):
    assert client.get("/auth/me").status_code == 401


def test_settings_protected(client: TestClient):
    assert client.get("/settings").status_code == 401
    _do_login(client)
    response = client.get("/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["jwt_issuer"] == "auth-service"
    assert "google_client_secret" not in str(body)
    assert "test-secret" not in str(body)


def test_refresh_with_cookie(client: TestClient):
    _do_login(client)
    response = client.post("/auth/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["token_type"] == "bearer"


def test_refresh_without_token_401(client: TestClient):
    assert client.post("/auth/refresh").status_code == 401


def test_verify_endpoint(client: TestClient, jwt_service, provider):
    token = jwt_service.issue_access_token(provider.user)
    active = client.post("/auth/verify", json={"token": token}).json()
    assert active["active"] is True
    assert active["claims"]["email"] == provider.user.email

    inactive = client.post("/auth/verify", json={"token": "rossz.token.abc"}).json()
    assert inactive["active"] is False


def test_logout_revokes_refresh_token(client: TestClient):
    _do_login(client)
    refresh_token = client.cookies.get("mp_refresh_token")

    response = client.post("/auth/logout")
    assert response.status_code == 200

    # a visszavont refresh tokennel már nem lehet új access tokent kérni
    retry = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert retry.status_code == 401
