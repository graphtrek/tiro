"""Cryptographic helpers for the NAV Online Számla 3.0 REST API.

All hashes are returned as UPPERCASE hexadecimal strings, matching the format
NAV expects (see interface spec §1.5 "A requestSignature számítása").
"""

import base64
import hashlib
import logging
import secrets
import string
from collections.abc import Iterable
from datetime import UTC, datetime

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


# ── Hashing ─────────────────────────────────────────────

def sha512_hex(data: str) -> str:
    """SHA-512 of ``data`` as uppercase hex."""
    return hashlib.sha512(data.encode("utf-8")).hexdigest().upper()


def sha3_512_hex(data: str) -> str:
    """SHA3-512 of ``data`` as uppercase hex."""
    return hashlib.sha3_512(data.encode("utf-8")).hexdigest().upper()


def password_hash(password: str) -> str:
    """Return the ``passwordHash`` value (SHA-512, uppercase hex)."""
    return sha512_hex(password)


# ── Timestamp / request id ──────────────────────────────

def utc_now() -> datetime:
    """Current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def format_timestamp(dt: datetime) -> str:
    """Header timestamp: ``YYYY-MM-DDTHH:MM:SS.mmmZ`` in UTC."""
    dt = dt.astimezone(UTC)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def signature_timestamp(dt: datetime) -> str:
    """Signature timestamp: ``YYYYMMDDHHMMSS`` in UTC (no millis)."""
    return dt.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def generate_request_id() -> str:
    """Generate a unique requestId matching ``[+a-zA-Z0-9_]{1,30}``.

    Uses a 30-char string of uppercase letters/digits starting with a letter.
    """
    alphabet = string.ascii_uppercase + string.digits
    first = secrets.choice(string.ascii_uppercase)
    rest = "".join(secrets.choice(alphabet) for _ in range(29))
    return first + rest


# ── Request signature ───────────────────────────────────

def request_signature(
    request_id: str,
    dt: datetime,
    sign_key: str,
    invoices: Iterable[tuple[str, str]] | None = None,
) -> str:
    """Compute the ``requestSignature`` value (SHA3-512, uppercase hex).

    Base string = requestId + signatureTimestamp + signKey.

    For ``manageInvoice`` / ``manageAnnulment`` requests, ``invoices`` is an
    iterable of ``(operation, base64_data)`` tuples; for each one the hash
    ``SHA3-512(operation + base64_data)`` is appended to the base string before
    the final hash is taken.
    """
    base = request_id + signature_timestamp(dt) + sign_key

    if invoices:
        for operation, b64_data in invoices:
            base += sha3_512_hex(operation + b64_data)

    return sha3_512_hex(base)


# ── Exchange token decryption ───────────────────────────

def decrypt_exchange_token(encoded_token: str, exchange_key: str) -> str:
    """Decrypt the ``encodedExchangeToken`` from a tokenExchange response.

    The token is base64-encoded AES-128-ECB ciphertext (PKCS7 padded),
    encrypted with the 16-character exchange key.
    """
    key_bytes = exchange_key.encode("utf-8")
    if len(key_bytes) != 16:
        raise ValueError(
            f"Exchange key must be 16 bytes (AES-128), got {len(key_bytes)}."
        )

    ciphertext = base64.b64decode(encoded_token)

    decryptor = Cipher(algorithms.AES(key_bytes), modes.ECB()).decryptor()
    decrypted = decryptor.update(ciphertext) + decryptor.finalize()

    # Strip PKCS7 padding.
    pad_len = decrypted[-1]
    if 1 <= pad_len <= 16:
        decrypted = decrypted[:-pad_len]

    return decrypted.decode("utf-8")