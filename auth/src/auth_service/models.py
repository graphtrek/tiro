"""Adatmodellek az auth mikroszervizhez."""

from __future__ import annotations

from pydantic import BaseModel


class UserInfo(BaseModel):
    """Providertől kapott, ellenőrzött felhasználói adatok."""

    sub: str  # provider-beli user id
    email: str
    name: str | None = None
    picture: str | None = None  # avatar URL
    provider: str  # "google"
    role: str = "read_write"
    anonymized: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str | None = None  # megszemélyesítésnél nincs refresh token
    token_type: str = "bearer"
    expires_in: int  # access token TTL másodpercben


class ProviderInfo(BaseModel):
    key: str  # "google"
    label: str  # "Belépés Google-fiókkal"
    icon: str  # "bi-google"
    login_url: str  # "/auth/google/login"


class JWTClaims(BaseModel):
    """Saját kiállítású JWT dekódolt claims-ei."""

    sub: str
    iat: int
    exp: int
    iss: str
    aud: str
    typ: str  # "access" | "refresh"
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    provider: str | None = None
    role: str | None = None
    anonymized: bool | None = None
    jti: str | None = None  # refresh tokennél, visszavonáshoz
    impersonator_sub: str | None = None  # megszemélyesítésnél: az admin sub-ja
    impersonator_email: str | None = None  # megszemélyesítésnél: az admin e-mailje


class AuthError(Exception):
    """Általános authentikációs hiba (érvénytelen state, token, provider...)."""


class NotAllowedError(AuthError):
    """A felhasználó e-mail címe nincs a whitelisten."""


class ForbiddenError(AuthError):
    """A felhasználó nincs az admin whitelisten (megszemélyesítéshez)."""


class ProviderError(AuthError):
    """A provider (Google) hívása vagy az ID token ellenőrzése sikertelen."""
