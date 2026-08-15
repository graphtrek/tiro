"""JWT kiállítás és validálás — RS256 kulcspár + JWKS publikáció.

A privát kulcs kizárólag ennél a szerviznél van; a védett mikroszervizek a
`/.well-known/jwks.json` végponton kiadott publikus kulccsal validálnak
lokálisan. A `kid` a publikus kulcs SHA-256 ujjlenyomatából származik, így a
kulcsrotáció támogatott (új kulcs → új `kid`, a JWKS mindkettőt kiadhatja).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from auth_service.config import Settings
from auth_service.models import AuthError, JWTClaims, UserInfo


def generate_keypair(out_dir: str | Path, key_size: int = 2048) -> tuple[Path, Path]:
    """RS256 kulcspár generálása (első beüzemelés: `auth keygen`)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)

    private_path = out / "jwt_private.pem"
    public_path = out / "jwt_public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


class JWTService:
    """Access / refresh token kiállítás, validálás és JWKS."""

    def __init__(self, settings: Settings, regenerate_keys: bool = False):
        self.settings = settings
        private_path = Path(settings.jwt_private_key_path)
        public_path = Path(settings.jwt_public_key_path)
        if regenerate_keys:
            # Friss kulcspár minden szerverindításkor: a régi `kid` eltűnik a
            # JWKS-ből, így minden korábban kiadott access/refresh token
            # érvényesítése elbukik -- újraindítás után mindenkinek újra be
            # kell lépnie (lásd CLAUDE.md "always needs to login").
            generate_keypair(private_path.parent)
        if not private_path.exists() or not public_path.exists():
            raise AuthError(
                f"Hiányzó RS256 kulcspár ({private_path}, {public_path}) — "
                "generáld az `auth keygen` paranccsal."
            )
        self._private_pem = private_path.read_bytes()
        self._public_pem = public_path.read_bytes()
        self.kid = self._compute_kid(self._public_pem)

    @staticmethod
    def _compute_kid(public_pem: bytes) -> str:
        public_key = serialization.load_pem_public_key(public_pem)
        der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(der).hexdigest()[:16]

    # -- kiállítás ---------------------------------------------------------

    def issue_access_token(
        self, user: UserInfo, now: int | None = None, impersonator: UserInfo | None = None
    ) -> str:
        now = now or int(time.time())
        payload = {
            "sub": user.sub,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
            "provider": user.provider,
            "typ": "access",
            "iat": now,
            "exp": now + self.settings.access_token_ttl,
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
        }
        if impersonator is not None:
            payload["impersonator_sub"] = impersonator.sub
            payload["impersonator_email"] = impersonator.email
        return jwt.encode(
            payload, self._private_pem, algorithm="RS256", headers={"kid": self.kid}
        )

    def issue_refresh_token(self, user: UserInfo, now: int | None = None) -> tuple[str, str]:
        """Refresh token + a visszavonáshoz használt `jti`.

        A profil claims (email, name, ...) is bekerülnek, mert DB híján a
        refresh flow-nak ezekből kell az új access tokent kiállítania.
        """
        now = now or int(time.time())
        jti = uuid.uuid4().hex
        payload = {
            "sub": user.sub,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
            "provider": user.provider,
            "jti": jti,
            "typ": "refresh",
            "iat": now,
            "exp": now + self.settings.refresh_token_ttl,
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
        }
        token = jwt.encode(
            payload, self._private_pem, algorithm="RS256", headers={"kid": self.kid}
        )
        return token, jti

    # -- validálás ---------------------------------------------------------

    def decode(self, token: str, expected_typ: str = "access") -> JWTClaims:
        try:
            payload = jwt.decode(
                token,
                self._public_pem,
                algorithms=["RS256"],
                audience=self.settings.jwt_audience,
                issuer=self.settings.jwt_issuer,
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"Érvénytelen token: {exc}") from exc
        if payload.get("typ") != expected_typ:
            raise AuthError(
                f"Nem megfelelő token típus: {payload.get('typ')!r} "
                f"(elvárt: {expected_typ!r})"
            )
        return JWTClaims(**payload)

    # -- JWKS --------------------------------------------------------------

    def jwks(self) -> dict:
        public_key = serialization.load_pem_public_key(self._public_pem)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
        jwk.update({"kid": self.kid, "alg": "RS256", "use": "sig"})
        return {"keys": [jwk]}


def make_state() -> str:
    """CSRF elleni `state` paraméter."""
    return secrets.token_urlsafe(32)


def make_pkce_pair() -> tuple[str, str]:
    """PKCE `code_verifier` + S256 `code_challenge`."""
    import base64

    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge
