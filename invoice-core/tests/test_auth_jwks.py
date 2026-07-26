"""JWKS TLS trust store + hibaüzenet tesztek a invoice_core.auth modulhoz.

Nem hívunk valódi hálózatot -- a PyJWKClient bekötését és a
verify_jwt hibaágait mock-oljuk.
"""

from __future__ import annotations

import ssl

import certifi
import jwt
import pytest
from fastapi import HTTPException

import invoice_core.auth as auth_mod


@pytest.fixture(autouse=True)
def _reset_jwk_client_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_mod, "_jwk_client", None)
    monkeypatch.setattr(auth_mod, "_settings", None)
    yield


def test_build_ssl_context_uses_certifi_cafile(monkeypatch: pytest.MonkeyPatch):
    """A JWKS SSLContext-nek a certifi bundle-t kell használnia, ne a rendszer
    CA store-ot -- ez javítja a python.org-os macOS / csupasz konténer TLS
    hibáját (PyJWKClient alapból urllib.request-tel, rendszer CA store-ral
    dolgozna)."""
    captured = {}
    real_create_default_context = ssl.create_default_context

    def fake_create_default_context(*, cafile=None, **kwargs):
        captured["cafile"] = cafile
        return real_create_default_context(cafile=cafile, **kwargs)

    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)

    context = auth_mod._build_ssl_context()

    assert captured["cafile"] == certifi.where()
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_get_signing_key_passes_ssl_context_to_pyjwkclient(monkeypatch: pytest.MonkeyPatch):
    """A _get_signing_key a certifi-alapú SSLContext-et adja át a
    PyJWKClientnek, nem hagyja a beépített (rendszer CA store-ra támaszkodó)
    alapértelmezésen."""
    captured_kwargs = {}

    class FakeSigningKey:
        key = "dummy-key"

    class FakePyJWKClient:
        def __init__(self, uri, **kwargs):
            captured_kwargs.update(kwargs)

        def get_signing_key_from_jwt(self, token):
            return FakeSigningKey()

    monkeypatch.setattr(auth_mod.jwt, "PyJWKClient", FakePyJWKClient)

    key = auth_mod._get_signing_key("some.jwt.token")

    assert key == "dummy-key"
    assert isinstance(captured_kwargs.get("ssl_context"), ssl.SSLContext)


def test_verify_jwt_jwks_connection_error_is_503_not_misreported_as_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
):
    """Egy JWKS lekérési (hálózat/TLS) hiba ne 'Érvénytelen access token'
    üzenettel bukjon 401-gyel -- külön, 503-as, egyértelmű hibaüzenetet kell
    kapnia."""

    def fake_get_signing_key(token):
        raise jwt.PyJWKClientConnectionError(
            'Fail to fetch data from the url, err: "<urlopen error CERTIFICATE_VERIFY_FAILED>"'
        )

    monkeypatch.setattr(auth_mod, "_get_signing_key", fake_get_signing_key)

    with pytest.raises(HTTPException) as excinfo:
        auth_mod.verify_jwt("some.jwt.token")

    assert excinfo.value.status_code == 503
    assert "JWKS" in excinfo.value.detail
    assert "Érvénytelen access token" not in excinfo.value.detail


def test_verify_jwt_genuinely_invalid_token_still_401(monkeypatch: pytest.MonkeyPatch):
    """Egy tényleg érvénytelen tokennél a régi, konkrét 401 hibaüzenet marad."""

    def fake_get_signing_key(token):
        return "not-a-real-signing-key"

    monkeypatch.setattr(auth_mod, "_get_signing_key", fake_get_signing_key)

    with pytest.raises(HTTPException) as excinfo:
        auth_mod.verify_jwt("not-a-jwt-at-all")

    assert excinfo.value.status_code == 401
    assert "Érvénytelen access token" in excinfo.value.detail
