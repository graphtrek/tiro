"""AuthProvider protocol — minden provider ezt implementálja."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from auth_service.models import UserInfo


@runtime_checkable
class AuthProvider(Protocol):
    key: str  # "google"
    label: str  # "Belépés Google-fiókkal"
    icon: str  # "bi-google" (Bootstrap Icons osztály)

    def authorize_url(
        self, state: str, code_challenge: str, redirect_uri: str
    ) -> str: ...

    def exchange_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> UserInfo: ...
