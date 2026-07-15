"""JWT validálás a központi auth szerviz (:8007) JWKS kulcsaival.

A tokent kérésenként lokálisan validáljuk — a JWKS publikus kulcsokat a
PyJWKClient tölti le és cache-eli (1 óra TTL, ismeretlen `kid` esetén
újratöltés). Nincs kérésenkénti hálózati hívás az auth szerviz felé.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

import jwt
import requests.auth
from fastapi import Request

from vision.config import Settings

logger = logging.getLogger(__name__)

ACCESS_COOKIE_NAME = "mp_access_token"

# A beérkező kérés Bearer tokenje — a kliens hívások (invoice-core, uploader)
# ezt adják tovább (token passthrough).
current_token: ContextVar[str | None] = ContextVar("current_token", default=None)

_jwk_clients: dict[str, jwt.PyJWKClient] = {}


def _get_signing_key(token: str, auth_service_url: str):
    url = f"{auth_service_url.rstrip('/')}/.well-known/jwks.json"
    client = _jwk_clients.get(url)
    if client is None:
        client = _jwk_clients[url] = jwt.PyJWKClient(
            url, cache_keys=True, lifespan=3600
        )
    return client.get_signing_key_from_jwt(token).key


def extract_token(request: Request) -> str | None:
    """Bearer fejléc vagy HttpOnly cookie — mindkettőt elfogadjuk."""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get(ACCESS_COOKIE_NAME)


def verify_jwt(token: str, settings: Settings) -> dict | None:
    """RS256 aláírás + exp + aud + iss ellenőrzés; hibánál None."""
    try:
        claims = jwt.decode(
            token,
            _get_signing_key(token, settings.auth_service_url),
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        logger.debug("Érvénytelen access token: %s", exc)
        return None
    except Exception as exc:  # pl. a JWKS nem érhető el
        logger.warning("JWT validálás sikertelen (JWKS?): %s", exc)
        return None
    if claims.get("typ") != "access":
        return None
    return claims


class TokenPassthrough(requests.auth.AuthBase):
    """A beérkező kérés Bearer tokenjének továbbadása a hívott szerviznek."""

    def __call__(self, prepared):
        token = current_token.get()
        if token and "Authorization" not in prepared.headers:
            prepared.headers["Authorization"] = f"Bearer {token}"
        return prepared
