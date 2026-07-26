"""JWT validálás a központi auth szerviz (:8007) JWKS kulcsaival.

Projektenként bemásolt modul (nincs közös package a workspace-ben) — a mintát
a moneypenny/auth-service-spec.md írja le. A tokent kérésenként lokálisan
validáljuk: a JWKS publikus kulcsokat a PyJWKClient tölti le és cache-eli
(1 óra TTL, ismeretlen `kid` esetén újratöltés), így nincs kérésenkénti
hálózati hívás az auth szerviz felé.

Használat (app szintű dependency, a publikus útvonalakat a PUBLIC_PATHS adja):

    from fastapi import Depends
    from <pkg>.auth import require_auth

    app = FastAPI(..., dependencies=[Depends(require_auth)])
"""

from __future__ import annotations

import logging
import ssl
from pathlib import Path

import certifi
import jwt
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _WORKSPACE_ROOT / ".env"

ACCESS_COOKIE_NAME = "mp_access_token"
PUBLIC_PATHS = {"/health"}


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), case_sensitive=False, extra="ignore")

    # This is the one service where AUTH_ENABLED differs from the shared
    # default (it's a leaf service hit by `invoice-core sync` without a user
    # token), so it needs its own override key in the shared root .env.
    auth_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("ATTACHMENT_DOWNLOADER_AUTH_ENABLED", "AUTH_ENABLED"),
    )
    auth_service_url: str = "http://localhost:8007"
    jwt_audience: str = "moneypenny"
    jwt_issuer: str = "auth-service"


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


_settings: AuthSettings | None = None
_jwk_client: jwt.PyJWKClient | None = None


def get_auth_settings() -> AuthSettings:
    global _settings
    if _settings is None:
        _settings = AuthSettings()
    return _settings


def _get_signing_key(token: str):
    global _jwk_client
    if _jwk_client is None:
        url = f"{get_auth_settings().auth_service_url.rstrip('/')}/.well-known/jwks.json"
        _jwk_client = jwt.PyJWKClient(
            url, cache_keys=True, lifespan=3600, ssl_context=_build_ssl_context()
        )
    return _jwk_client.get_signing_key_from_jwt(token).key


def verify_jwt(token: str) -> dict:
    """RS256 aláírás + exp + aud + iss ellenőrzés → claims; hibánál HTTPException."""
    settings = get_auth_settings()
    try:
        claims = jwt.decode(
            token,
            _get_signing_key(token),
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWKClientConnectionError as exc:
        # A JWKS lekérés hálózati/TLS hibája nem azonos egy érvénytelen access
        # tokennel -- ne keverjük össze a hibaüzenetben (ez okozta a
        # "Fail to fetch data from the url" TLS hibák "Érvénytelen access
        # token"-ként való megjelenését).
        logger.error("JWKS lekérés sikertelen (hálózat/TLS, fut az auth szerviz?): %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Az auth szerviz JWKS végpontja nem érhető el (hálózat/TLS hiba)",
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Érvénytelen access token: {exc}") from exc
    except Exception as exc:  # a JWKS nem érhető el egyéb okból
        logger.error("JWT validálás sikertelen (fut az auth szerviz?): %s", exc)
        raise HTTPException(status_code=503, detail="Az auth szerviz nem érhető el") from exc
    if claims.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Nem access token")
    return claims


security = HTTPBearer(auto_error=False)


async def require_auth(request: Request) -> dict | None:
    """App szintű dependency: érvényes JWT kell (Bearer fejléc vagy cookie)."""
    settings = get_auth_settings()
    if not settings.auth_enabled or request.url.path in PUBLIC_PATHS:
        return None
    credentials: HTTPAuthorizationCredentials | None = await security(request)
    token = credentials.credentials if credentials else request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Hiányzó access token")
    claims = verify_jwt(token)
    request.state.user = claims
    return claims
