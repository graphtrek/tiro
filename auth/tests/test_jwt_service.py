"""JWT kiállítás / validálás / JWKS tesztek."""

from __future__ import annotations

import time

import pytest

from auth_service.jwt_service import JWTService, make_pkce_pair, make_state
from auth_service.models import AuthError, UserInfo

USER = UserInfo(
    sub="google-user-1",
    email="imre.tatai@graphtrek.co",
    name="Imre Tatai",
    picture=None,
    provider="google",
)


def test_access_token_roundtrip(jwt_service: JWTService):
    token = jwt_service.issue_access_token(USER)
    claims = jwt_service.decode(token, expected_typ="access")
    assert claims.sub == "google-user-1"
    assert claims.email == "imre.tatai@graphtrek.co"
    assert claims.provider == "google"
    assert claims.iss == "auth-service"
    assert claims.aud == "moneypenny"
    assert claims.exp - claims.iat == jwt_service.settings.access_token_ttl


def test_access_token_roundtrip_carries_role(jwt_service: JWTService):
    readonly_user = USER.model_copy(update={"role": "read_only"})
    token = jwt_service.issue_access_token(readonly_user)
    claims = jwt_service.decode(token, expected_typ="access")
    assert claims.role == "read_only"


def test_refresh_token_has_jti_and_profile(jwt_service: JWTService):
    token, jti = jwt_service.issue_refresh_token(USER)
    claims = jwt_service.decode(token, expected_typ="refresh")
    assert claims.jti == jti
    assert claims.email == USER.email
    assert claims.exp - claims.iat == jwt_service.settings.refresh_token_ttl


def test_typ_mismatch_rejected(jwt_service: JWTService):
    access = jwt_service.issue_access_token(USER)
    with pytest.raises(AuthError, match="token típus"):
        jwt_service.decode(access, expected_typ="refresh")


def test_expired_token_rejected(jwt_service: JWTService):
    old = int(time.time()) - jwt_service.settings.access_token_ttl - 60
    token = jwt_service.issue_access_token(USER, now=old)
    with pytest.raises(AuthError, match="Érvénytelen token"):
        jwt_service.decode(token)


def test_tampered_token_rejected(jwt_service: JWTService):
    token = jwt_service.issue_access_token(USER)
    header, payload, sig = token.split(".")
    with pytest.raises(AuthError):
        jwt_service.decode(f"{header}.{payload}.{sig[:-4]}AAAA")


def test_wrong_audience_rejected(jwt_service: JWTService, settings):
    other = settings.model_copy(update={"jwt_audience": "masik-rendszer"})
    token = JWTService(other).issue_access_token(USER)
    with pytest.raises(AuthError):
        jwt_service.decode(token)


def test_jwks_structure(jwt_service: JWTService):
    jwks = jwt_service.jwks()
    assert len(jwks["keys"]) == 1
    key = jwks["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert key["kid"] == jwt_service.kid
    assert "n" in key and "e" in key


def test_kid_in_token_header(jwt_service: JWTService):
    import jwt as pyjwt

    token = jwt_service.issue_access_token(USER)
    header = pyjwt.get_unverified_header(token)
    assert header["kid"] == jwt_service.kid


def test_state_and_pkce_helpers():
    assert make_state() != make_state()
    verifier, challenge = make_pkce_pair()
    assert len(verifier) >= 43
    assert challenge and "=" not in challenge


def test_regenerate_keys_invalidates_previous_tokens(settings):
    """Egy szerverindítás (regenerate_keys=True) rotálja a kulcspárt és a `kid`-et,
    így minden korábban kiadott tokent érvényteleníti — kényszerített újra-belépés."""
    before = JWTService(settings)
    token = before.issue_access_token(USER)

    after = JWTService(settings, regenerate_keys=True)

    assert after.kid != before.kid
    with pytest.raises(AuthError):
        after.decode(token, expected_typ="access")
    # a régi instancia még mindig érvényesíti a saját maga által kiadott tokent
    assert before.decode(token, expected_typ="access").sub == USER.sub
