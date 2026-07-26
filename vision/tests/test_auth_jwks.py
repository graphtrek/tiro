"""JWKS TLS trust store + hibaüzenet tesztek a vision.auth modulhoz.

Nem hívunk valódi hálózatot -- a PyJWKClient bekötését és a
verify_jwt hibaágait mock-oljuk.
"""

from __future__ import annotations

import logging
import ssl

import certifi
import jwt
import pytest

import vision.auth as auth_mod
from vision.config import Settings


@pytest.fixture(autouse=True)
def _reset_jwk_client_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_mod, "_jwk_clients", {})
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

    key = auth_mod._get_signing_key("some.jwt.token", "http://localhost:8007")

    assert key == "dummy-key"
    assert isinstance(captured_kwargs.get("ssl_context"), ssl.SSLContext)


def test_verify_jwt_jwks_connection_error_is_distinguishable_from_invalid_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Egy JWKS lekérési (hálózat/TLS) hiba a logban egyértelműen auth
    infrastruktúra hibaként jelenjen meg, ne keveredjen össze egy tényleg
    érvénytelen access token debug-üzenetével -- mindkettő None-t ad vissza
    (a middleware szerződését megtartva), de a logban meg kell tudni
    különböztetni őket."""

    def fake_get_signing_key(token, auth_service_url):
        raise jwt.PyJWKClientConnectionError(
            'Fail to fetch data from the url, err: "<urlopen error CERTIFICATE_VERIFY_FAILED>"'
        )

    monkeypatch.setattr(auth_mod, "_get_signing_key", fake_get_signing_key)

    with caplog.at_level(logging.ERROR, logger="vision.auth"):
        result = auth_mod.verify_jwt("some.jwt.token", Settings())

    assert result is None
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert "JWKS" in caplog.records[0].message


def test_verify_jwt_genuinely_invalid_token_logged_separately(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Egy tényleg érvénytelen tokennél nem jelenik meg ERROR szintű, JWKS-re
    utaló logüzenet -- ez csak egy alacsonyabb szintű, konkrétan "érvénytelen
    access token"-re utaló bejegyzés."""

    def fake_get_signing_key(token, auth_service_url):
        return "not-a-real-signing-key"

    monkeypatch.setattr(auth_mod, "_get_signing_key", fake_get_signing_key)

    with caplog.at_level(logging.DEBUG, logger="vision.auth"):
        result = auth_mod.verify_jwt("not-a-jwt-at-all", Settings())

    assert result is None
    assert not any(r.levelno == logging.ERROR for r in caplog.records)
    assert any("Érvénytelen access token" in r.message for r in caplog.records)
