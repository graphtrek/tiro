"""Shared Jinja2Templates instance for every UI router.

Centralized so the `t()` i18n global only needs registering once.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from vision.i18n import t

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["t"] = t
