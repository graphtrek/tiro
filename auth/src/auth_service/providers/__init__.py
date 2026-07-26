"""Auth provider regisztráció.

Új provider felvétele: új modul (pl. ``microsoft.py``) az :class:`AuthProvider`
protocol implementációjával, majd egy sor a ``_REGISTRY``-be. Az aktív
providereket az ``ENABLED_PROVIDERS`` env változó sorolja fel; a login oldal a
``GET /auth/providers`` végpontból automatikusan megjeleníti a gombokat.
"""

from __future__ import annotations

from collections.abc import Callable

from auth_service.config import Settings
from auth_service.providers.base import AuthProvider
from auth_service.providers.google import GoogleProvider

_REGISTRY: dict[str, Callable[[Settings], AuthProvider]] = {
    "google": lambda s: GoogleProvider(
        client_id=s.google_client_id, client_secret=s.google_client_secret
    ),
}


def build_providers(settings: Settings) -> dict[str, AuthProvider]:
    """Az engedélyezett providerek példányosítása kulcs szerint."""
    providers: dict[str, AuthProvider] = {}
    for key in settings.enabled_providers_list:
        factory = _REGISTRY.get(key)
        if factory is None:
            raise ValueError(
                f"Ismeretlen provider az ENABLED_PROVIDERS-ben: {key!r}. "
                f"Elérhető: {', '.join(sorted(_REGISTRY))}"
            )
        providers[key] = factory(settings)
    return providers
