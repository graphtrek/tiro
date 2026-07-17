"""Közös fixture-ök: ideiglenes RS256 kulcspár + fake Google provider."""

from __future__ import annotations

import pytest

from auth_service.config import Settings
from auth_service.invoice_core_client import InvoiceCoreClientError
from auth_service.jwt_service import JWTService, generate_keypair
from auth_service.models import ProviderError, UserInfo


class FakeProvider:
    """A Google provider helyettesítője — nem hív hálózatot."""

    key = "google"
    label = "Belépés Google-fiókkal"
    icon = "bi-google"

    def __init__(self, user: UserInfo | None = None, error: str | None = None):
        self.user = user or UserInfo(
            sub="google-user-1",
            email="imre.tatai@graphtrek.co",
            name="Imre Tatai",
            picture="https://example.com/avatar.png",
            provider="google",
        )
        self.error = error
        self.exchange_calls: list[dict] = []

    def authorize_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        return (
            "https://fake.google.example/authorize"
            f"?state={state}&code_challenge={code_challenge}&redirect_uri={redirect_uri}"
        )

    def exchange_code(self, code: str, code_verifier: str, redirect_uri: str) -> UserInfo:
        self.exchange_calls.append(
            {"code": code, "code_verifier": code_verifier, "redirect_uri": redirect_uri}
        )
        if self.error:
            raise ProviderError(self.error)
        return self.user


class FakeInvoiceCoreClient:
    """invoice-core kliens helyettesítője — nem hív hálózatot."""

    def __init__(self, error: str | None = None):
        self.error = error
        self.save_calls: list[dict] = []

    def save_user(self, user: UserInfo, access_token: str) -> None:
        self.save_calls.append({"user": user, "access_token": access_token})
        if self.error:
            raise InvoiceCoreClientError(self.error)


@pytest.fixture(scope="session")
def keys_dir(tmp_path_factory: pytest.TempPathFactory):
    out = tmp_path_factory.mktemp("keys")
    generate_keypair(out)
    return out


@pytest.fixture
def settings(keys_dir, tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        jwt_private_key_path=str(keys_dir / "jwt_private.pem"),
        jwt_public_key_path=str(keys_dir / "jwt_public.pem"),
        denylist_path=str(tmp_path / "revoked_jti.txt"),
        allowed_emails="imre.tatai@graphtrek.co",
        allowed_domains="graphtrek.co",
        google_client_id="test-client",
        google_client_secret="test-secret",
        vision_url="http://localhost:8009",
    )


@pytest.fixture
def jwt_service(settings) -> JWTService:
    return JWTService(settings)
