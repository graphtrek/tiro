"""JWT validálás a központi auth szerviz (:8007) JWKS kulcsaival.

A tokent kérésenként lokálisan validáljuk — a JWKS publikus kulcsokat a
PyJWKClient tölti le és cache-eli (1 óra TTL, ismeretlen `kid` esetén
újratöltés). Nincs kérésenkénti hálózati hívás az auth szerviz felé.
"""

from __future__ import annotations

import logging
import ssl
from contextvars import ContextVar

import certifi
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


def _build_ssl_context() -> ssl.SSLContext:
    """Certifi-alapú TLS trust store a JWKS lekéréshez (ne a rendszer CA store).

    A PyJWKClient a urllib.request modult használja a JWKS letöltéséhez, ami a
    rendszer CA store-jára támaszkodik -- ez pl. egy python.org-os macOS
    telepítésen vagy egy csupasz konténerben üres/hiányos lehet, és a JWKS
    lekérést hamis "invalid token" hibaként buktatja. A többi HTTP hívás
    (requests/httpx) certifi-t bundle-el; itt explicit certifi-alapú
    SSLContext-tel ugyanazt a megbízható store-ot használjuk.
    """
    return ssl.create_default_context(cafile=certifi.where())


def _get_signing_key(token: str, auth_service_url: str):
    url = f"{auth_service_url.rstrip('/')}/.well-known/jwks.json"
    client = _jwk_clients.get(url)
    if client is None:
        client = _jwk_clients[url] = jwt.PyJWKClient(
            url, cache_keys=True, lifespan=3600, ssl_context=_build_ssl_context()
        )
    return client.get_signing_key_from_jwt(token).key


def extract_token(request: Request) -> str | None:
    """Bearer fejléc vagy HttpOnly cookie — mindkettőt elfogadjuk."""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get(ACCESS_COOKIE_NAME)


def verify_jwt(token: str, settings: Settings) -> dict | None:
    """RS256 aláírás + exp + aud + iss ellenőrzés; hibánál None.

    A middleware szerződése (böngészőnek redirect a /login-ra, API hívásnak
    401 JSON) minden hiba esetén None-t vár -- de a JWKS lekérés hálózati/TLS
    hibáját NEM keverjük össze egy ténylegesen érvénytelen access tokennel a
    logban: az előbbi szerver oldali (auth infrastruktúra) hiba, nem a
    felhasználó munkamenetének hibája.
    """
    try:
        claims = jwt.decode(
            token,
            _get_signing_key(token, settings.auth_service_url),
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWKClientConnectionError as exc:
        # A JWKS lekérés hálózati/TLS hibája nem azonos egy érvénytelen access
        # tokennel -- ne keverjük össze a logban (ez okozta a "Fail to fetch
        # data from the url" TLS hibák néma "nincs bejelentkezve"-ként való
        # megjelenését).
        logger.error("JWKS lekérés sikertelen (hálózat/TLS, fut az auth szerviz?): %s", exc)
        return None
    except jwt.PyJWTError as exc:
        logger.debug("Érvénytelen access token: %s", exc)
        return None
    except (OSError, TypeError, ValueError) as exc:  # pl. a JWKS nem érhető el egyéb okból
        logger.error("JWT validálás sikertelen (fut az auth szerviz?): %s", exc)
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
