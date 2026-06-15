"""Bejelentkezés (Authentication) — ``tokenExchange`` operation.

The NAV Online Számla 3.0 API has no persistent session. ``tokenExchange``
returns an encrypted exchange token used by ``manageInvoice``; it doubles as
the canonical way to verify that the technical user credentials are valid.
"""

import logging
from typing import Optional

from nav_invoice import crypto
from nav_invoice.client import NavClient, NavApiError, findtext
from nav_invoice.config import Settings, get_settings

logger = logging.getLogger(__name__)


def request_token(settings: Optional[Settings] = None) -> dict:
    """Call ``tokenExchange`` and return the decrypted token + validity.

    Returns a dict: ``{"token": str, "valid_from": str, "valid_to": str}``.
    Raises :class:`NavApiError` on failure.
    """
    if settings is None:
        settings = get_settings()

    client = NavClient(settings)
    payload = client.build_request("TokenExchangeRequest")
    root = client.post("/tokenExchange", payload)

    encoded = findtext(root, "encodedExchangeToken")
    if not encoded:
        raise NavApiError("A NAV nem adott vissza tokent (encodedExchangeToken).")

    token = crypto.decrypt_exchange_token(encoded, settings.exchange_key)

    return {
        "token": token,
        "valid_from": findtext(root, "tokenValidityFrom"),
        "valid_to": findtext(root, "tokenValidityTo"),
    }


def login(settings: Optional[Settings] = None) -> dict:
    """Verify NAV authentication via ``tokenExchange``.

    Returns a dict with ``success`` and either ``session_id`` (the token) or
    ``error``.
    """
    if settings is None:
        settings = get_settings()

    try:
        result = request_token(settings)
    except NavApiError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:  # network / crypto errors
        logger.warning("Login failed: %s", exc)
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "session_id": result["token"],
        "valid_from": result["valid_from"],
        "valid_to": result["valid_to"],
        "message": "Bejelentkezés sikeres",
    }


def check_connection(settings: Optional[Settings] = None) -> bool:
    """Quick health-check against the NAV endpoint."""
    return login(settings).get("success", False)