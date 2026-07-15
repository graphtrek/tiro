"""Google OAuth 2.0 / OpenID Connect provider (authorization code + PKCE)."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx
import jwt

from auth_service.models import ProviderError, UserInfo

logger = logging.getLogger(__name__)

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
VALID_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleProvider:
    key = "google"
    label = "Belépés Google-fiókkal"
    icon = "bi-google"

    def __init__(self, client_id: str, client_secret: str, timeout: int = 10):
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        # A Google JWKS kulcsait a PyJWKClient cache-eli (TTL-lel).
        self._jwk_client = jwt.PyJWKClient(JWKS_URI, cache_keys=True)

    def authorize_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    def exchange_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> UserInfo:
        try:
            response = httpx.post(
                TOKEN_ENDPOINT,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": redirect_uri,
                    "code_verifier": code_verifier,
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Google token endpoint nem érhető el: {exc}") from exc
        if response.status_code != 200:
            logger.warning("Google token csere hiba: %s %s", response.status_code, response.text)
            raise ProviderError(f"Google token csere sikertelen ({response.status_code})")

        id_token = response.json().get("id_token")
        if not id_token:
            raise ProviderError("A Google válaszából hiányzik az id_token")
        return self._verify_id_token(id_token)

    def _verify_id_token(self, id_token: str) -> UserInfo:
        """ID token ellenőrzés: aláírás (Google JWKS), `aud`, `iss`, `exp`, `email_verified`."""
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
            )
        except jwt.PyJWTError as exc:
            raise ProviderError(f"Érvénytelen Google ID token: {exc}") from exc

        if claims.get("iss") not in VALID_ISSUERS:
            raise ProviderError(f"Érvénytelen issuer a Google ID tokenben: {claims.get('iss')!r}")
        if not claims.get("email_verified"):
            raise ProviderError("A Google-fiók e-mail címe nincs megerősítve")

        return UserInfo(
            sub=claims["sub"],
            email=claims["email"],
            name=claims.get("name"),
            picture=claims.get("picture"),
            provider=self.key,
        )
