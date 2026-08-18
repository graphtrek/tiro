"""Login flow, whitelist, refresh és revoke logika."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from auth_service.config import Settings, get_settings
from auth_service.invoice_core_client import InvoiceCoreClient, InvoiceCoreClientError
from auth_service.jwt_service import JWTService, make_pkce_pair, make_state
from auth_service.models import (
    AuthError,
    ForbiddenError,
    JWTClaims,
    NotAllowedError,
    ProviderInfo,
    TokenPair,
    UserInfo,
)
from auth_service.providers import build_providers
from auth_service.providers.base import AuthProvider

logger = logging.getLogger(__name__)


class Denylist:
    """Visszavont refresh token `jti`-k — fájl alapú, nincs DB."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._jtis: set[str] = set()
        if self._path.exists():
            self._jtis = {
                line.strip() for line in self._path.read_text().splitlines() if line.strip()
            }

    def add(self, jti: str) -> None:
        if jti in self._jtis:
            return
        self._jtis.add(jti)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(f"{jti}\n")

    def __contains__(self, jti: str) -> bool:
        return jti in self._jtis

    def __len__(self) -> int:
        return len(self._jtis)


@dataclass
class PendingLogin:
    """Folyamatban lévő OAuth belépés (state → PKCE verifier + next URL)."""

    provider: str
    code_verifier: str
    next_url: str | None
    created_at: float = field(default_factory=time.time)


class AuthService:
    """A belépési folyamat vezérlése a providerek és a JWT szerviz felett."""

    def __init__(
        self,
        settings: Settings | None = None,
        jwt_service: JWTService | None = None,
        providers: dict[str, AuthProvider] | None = None,
        invoice_core_client: InvoiceCoreClient | None = None,
        regenerate_keys: bool = False,
    ):
        self.settings = settings or get_settings()
        self.jwt = jwt_service or JWTService(self.settings, regenerate_keys=regenerate_keys)
        self.providers = providers if providers is not None else build_providers(self.settings)
        self.denylist = Denylist(self.settings.denylist_path)
        self._invoice_core = invoice_core_client or InvoiceCoreClient(self.settings)
        self._pending: dict[str, PendingLogin] = {}

    # -- providerek --------------------------------------------------------

    def provider_infos(self) -> list[ProviderInfo]:
        return [
            ProviderInfo(
                key=p.key,
                label=p.label,
                icon=p.icon,
                login_url=f"/auth/{p.key}/login",
            )
            for p in self.providers.values()
        ]

    def get_provider(self, key: str) -> AuthProvider:
        provider = self.providers.get(key)
        if provider is None:
            raise AuthError(f"Ismeretlen vagy nem engedélyezett provider: {key!r}")
        return provider

    # -- belépés -----------------------------------------------------------

    def start_login(self, provider_key: str, next_url: str | None = None) -> str:
        """OAuth flow indítása → a provider authorize URL-je (state + PKCE)."""
        provider = self.get_provider(provider_key)
        state = make_state()
        verifier, challenge = make_pkce_pair()
        self._cleanup_pending()
        self._pending[state] = PendingLogin(
            provider=provider_key, code_verifier=verifier, next_url=next_url
        )
        return provider.authorize_url(
            state=state,
            code_challenge=challenge,
            redirect_uri=self.settings.oauth_redirect_url,
        )

    def complete_login(
        self, provider_key: str, code: str, state: str
    ) -> tuple[TokenPair, UserInfo, str]:
        """OAuth callback: code → token csere, whitelist, saját JWT kiállítás.

        Visszaadja a token párt, a felhasználót és a belépés utáni redirect URL-t.
        """
        pending = self._pending.pop(state, None)
        if pending is None or pending.provider != provider_key:
            raise AuthError("Érvénytelen vagy lejárt state paraméter (CSRF védelem)")
        if time.time() - pending.created_at > self.settings.login_state_ttl:
            raise AuthError("A belépési kérés lejárt — próbáld újra")

        provider = self.get_provider(provider_key)
        user = provider.exchange_code(
            code=code,
            code_verifier=pending.code_verifier,
            redirect_uri=self.settings.oauth_redirect_url,
        )
        user.role, user.anonymized = self.resolve_access(user.email)

        tokens = self.issue_tokens(user)
        self._save_user(user, tokens.access_token)
        logger.info("Sikeres belépés: %s (%s)", user.email, provider_key)
        return tokens, user, self._safe_next_url(pending.next_url)

    def _save_user(self, user: UserInfo, access_token: str) -> None:
        """Login rekord mentése invoice-core-ban — best-effort, sosem buktatja a belépést."""
        try:
            self._invoice_core.save_user(user, access_token)
        except InvoiceCoreClientError as exc:
            logger.warning(
                "Nem sikerült a felhasználót elmenteni invoice-core-ban: %s (%s)",
                user.email,
                exc,
            )

    def resolve_access(self, email: str) -> tuple[str, bool]:
        """Tiltólista → elutasítás; allowlist → (read_write, valós adat);
        READONLY_EMAILS/DOMAINS → (read_only, valós adat) — megbízható külső
        fiókok; egyébként (bármely hitelesített Google fiók) → (read_only,
        anonimizált adat)."""
        email = email.strip().lower()
        domain = email.rsplit("@", 1)[-1]
        blocked = self.settings.blocked_emails_list
        blocked_domains = self.settings.blocked_domains_list
        if email in blocked or domain in blocked_domains:
            logger.warning("Elutasított belépés (tiltólistán): %s", email)
            raise NotAllowedError(f"A(z) {email} fiókkal nem engedélyezett a belépés")
        allowed = self.settings.allowed_emails_list
        allowed_domains = self.settings.allowed_domains_list
        if email in allowed or domain in allowed_domains:
            return "read_write", False
        readonly = self.settings.readonly_emails_list
        readonly_domains = self.settings.readonly_domains_list
        if email in readonly or domain in readonly_domains:
            return "read_only", False
        return "read_only", True

    def _safe_next_url(self, next_url: str | None) -> str:
        """Open redirect elleni védelem: csak relatív útvonal engedett."""
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return f"{self.settings.vision_url.rstrip('/')}{next_url}"
        return self.settings.vision_url

    def _cleanup_pending(self) -> None:
        deadline = time.time() - self.settings.login_state_ttl
        expired = [s for s, p in self._pending.items() if p.created_at < deadline]
        for state in expired:
            del self._pending[state]

    # -- tokenek -----------------------------------------------------------

    def issue_tokens(self, user: UserInfo) -> TokenPair:
        access = self.jwt.issue_access_token(user)
        refresh, _jti = self.jwt.issue_refresh_token(user)
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=self.settings.access_token_ttl,
        )

    def verify_access_token(self, token: str) -> JWTClaims:
        return self.jwt.decode(token, expected_typ="access")

    def refresh(self, refresh_token: str) -> TokenPair:
        """Refresh flow: érvényes (nem visszavont) refresh token → új access token."""
        claims = self.jwt.decode(refresh_token, expected_typ="refresh")
        if claims.jti and claims.jti in self.denylist:
            raise AuthError("A refresh token vissza lett vonva")
        user = UserInfo(
            sub=claims.sub,
            email=claims.email or "",
            name=claims.name,
            picture=claims.picture,
            provider=claims.provider or "unknown",
            role=claims.role or "read_write",
            anonymized=claims.anonymized if claims.anonymized is not None else False,
        )
        access = self.jwt.issue_access_token(user)
        return TokenPair(
            access_token=access,
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_ttl,
        )

    def revoke_refresh_token(self, refresh_token: str) -> str | None:
        """Logout: a refresh token `jti`-jének visszavonása."""
        try:
            claims = self.jwt.decode(refresh_token, expected_typ="refresh")
        except AuthError:
            return None  # lejárt/érvénytelen token visszavonása no-op
        if claims.jti:
            self.denylist.add(claims.jti)
        return claims.jti

    # -- megszemélyesítés (support impersonation) ---------------------------

    def impersonate(
        self, admin_claims: JWTClaims, target_email: str, access_token: str
    ) -> TokenPair:
        """Admin belép egy másik felhasználóként — rövid élettartamú access token,
        refresh token nélkül (az admin saját refresh cookie-ja érintetlen marad,
        így a `/auth/refresh` automatikusan visszaállítja az admin identitást)."""
        admin_email = (admin_claims.email or "").strip().lower()
        if admin_email not in self.settings.admin_emails_list:
            logger.warning("Elutasított megszemélyesítési kísérlet: %s", admin_email)
            raise ForbiddenError(f"{admin_email} nem admin — megszemélyesítés nem engedélyezett")

        try:
            target = self._invoice_core.find_user_by_email(target_email, access_token)
        except InvoiceCoreClientError as exc:
            raise AuthError(f"invoice-core nem érhető el: {exc}") from exc
        if target is None:
            raise AuthError(f"Nincs ilyen felhasználó: {target_email}")

        admin_user = UserInfo(
            sub=admin_claims.sub,
            email=admin_email,
            name=admin_claims.name,
            picture=admin_claims.picture,
            provider=admin_claims.provider or "unknown",
        )
        access = self.jwt.issue_access_token(target, impersonator=admin_user)
        logger.info("Megszemélyesítés: %s → %s", admin_email, target.email)
        return TokenPair(
            access_token=access, refresh_token=None, expires_in=self.settings.access_token_ttl
        )
