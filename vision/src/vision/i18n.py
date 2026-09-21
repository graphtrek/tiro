"""Minimal request-scoped i18n for the vision UI.

Translations are plain dicts keyed by the Hungarian source string as it
appears in the templates (see ``vision.translations``). No gettext/Babel —
just a context-aware Jinja global (`t`) that reads ``request.state.lang``
fresh on every call, so it stays safe under concurrent requests for
different users/languages sharing the same Jinja ``Environment``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import pass_context

from vision.translations import TRANSLATIONS

if TYPE_CHECKING:
    from fastapi import Request

    from vision.config import Settings

SUPPORTED_LANGS = ("hu", "en")


def _lang_from_accept_header(accept_language: str) -> str | None:
    """Pick the best supported language from an `Accept-Language` header, if any."""
    best_lang: str | None = None
    best_q = 0.0
    for part in accept_language.split(","):
        tag, _, q_part = part.strip().partition(";")
        tag = tag.strip().lower()
        if not tag:
            continue
        q = 1.0
        if q_part.startswith("q="):
            try:
                q = float(q_part[2:])
            except ValueError:
                q = 1.0
        primary = tag.split("-")[0]
        if primary in SUPPORTED_LANGS and q > best_q:
            best_lang, best_q = primary, q
    return best_lang


def resolve_lang(request: Request, settings: Settings) -> str:
    """Resolve the language for this request: cookie > Accept-Language > default."""
    cookie_lang = request.cookies.get("vision_lang")
    if cookie_lang in SUPPORTED_LANGS:
        return cookie_lang

    accept_language = request.headers.get("accept-language", "")
    detected = _lang_from_accept_header(accept_language) if accept_language else None
    if detected:
        return detected

    if settings.default_language in SUPPORTED_LANGS:
        return settings.default_language
    return "hu"


@pass_context
def t(ctx, hu_text: str) -> str:
    """Jinja global: translate a Hungarian source string to the current request's language.

    `hu_text` IS the dictionary key — the Hungarian string as it appears in
    the template. Falls back to the Hungarian original when there's no
    English entry (or the request's language is Hungarian).
    """
    request = ctx.get("request")
    lang = getattr(getattr(request, "state", None), "lang", "hu")
    if lang == "en":
        return TRANSLATIONS.get(hu_text, hu_text)
    return hu_text
