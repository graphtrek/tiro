"""GoogleProvider JWKS TLS trust store + hibaüzenet tesztek.

Nem hívunk valódi hálózatot -- a PyJWKClient bekötését és a hibaágakat
mock-oljuk.
"""

from __future__ import annotations

import ssl
from unittest.mock import MagicMock

import certifi
import jwt
import pytest

from auth_service.models import ProviderError
from auth_service.providers.google import GoogleProvider, build_jwks_ssl_context


def test_build_jwks_ssl_context_uses_certifi_cafile(monkeypatch: pytest.MonkeyPatch):
    """A JWKS SSLContext-nek a certifi bundle-t kell használnia, ne a rendszer
    CA store-ot -- ez a python.org-os macOS / csupasz konténer TLS hibájának
    a javítása (PyJWKClient alapból urllib.request-tel, rendszer CA store-ral
    dolgozna)."""
    captured = {}
    real_create_default_context = ssl.create_default_context

    def fake_create_default_context(*, cafile=None, **kwargs):
        captured["cafile"] = cafile
        return real_create_default_context(cafile=cafile, **kwargs)

    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)

    context = build_jwks_ssl_context()

    assert captured["cafile"] == certifi.where()
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_google_provider_wires_ssl_context_into_pyjwkclient(monkeypatch: pytest.MonkeyPatch):
    """A GoogleProvider a certifi-alapú SSLContext-et adja át a PyJWKClientnek,
    nem hagyja a beépített (rendszer CA store-ra támaszkodó) alapértelmezésen."""
    captured_kwargs = {}
    real_init = jwt.PyJWKClient.__init__

    def fake_init(self, uri, **kwargs):
        captured_kwargs.update(kwargs)
        real_init(self, uri, **kwargs)

    monkeypatch.setattr(jwt.PyJWKClient, "__init__", fake_init)

    GoogleProvider(client_id="cid", client_secret="secret")

    assert isinstance(captured_kwargs.get("ssl_context"), ssl.SSLContext)


def test_verify_id_token_jwks_connection_error_is_distinct_from_invalid_token():
    """Egy JWKS lekérési (hálózat/TLS) hiba ne 'Érvénytelen Google ID token'
    üzenettel bukjon -- külön, egyértelmű hibaüzenetet kell kapnia."""
    provider = GoogleProvider(client_id="cid", client_secret="secret")
    provider._jwk_client = MagicMock()
    provider._jwk_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError(
        'Fail to fetch data from the url, err: "<urlopen error CERTIFICATE_VERIFY_FAILED>"'
    )

    with pytest.raises(ProviderError, match="JWKS kulcsok nem érhetők el") as excinfo:
        provider._verify_id_token("fake.jwt.token")

    assert "Érvénytelen Google ID token" not in str(excinfo.value)


def test_verify_id_token_genuinely_invalid_token_keeps_original_message():
    """Egy tényleg érvénytelen aláírás/token esetén marad a régi, konkrét
    hibaüzenet -- ne keveredjen a JWKS-hiba ágával."""
    provider = GoogleProvider(client_id="cid", client_secret="secret")
    provider._jwk_client = MagicMock()
    provider._jwk_client.get_signing_key_from_jwt.side_effect = jwt.exceptions.DecodeError(
        "Invalid header string"
    )

    with pytest.raises(ProviderError, match="Érvénytelen Google ID token"):
        provider._verify_id_token("fake.jwt.token")
