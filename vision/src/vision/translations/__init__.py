"""English translations for the vision UI, split by feature area so
independent editing passes never collide on the same file.

Each area module exposes ``TRANSLATIONS: dict[str, str]`` mapping the
Hungarian source string (as it appears verbatim in a template's ``t(...)``
call) to its English translation. This module merges them all into one
lookup dict used by ``vision.i18n.t``.
"""

from __future__ import annotations

from vision.translations import (
    admin,
    bank_statements,
    common,
    controlling,
    dashboard,
    invoices,
    uploader,
)

TRANSLATIONS: dict[str, str] = {}
for _mod in (common, invoices, bank_statements, controlling, admin, uploader, dashboard):
    TRANSLATIONS.update(_mod.TRANSLATIONS)
