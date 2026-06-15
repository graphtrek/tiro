"""NAV Online Számla 3.0 REST client.

Builds the common request envelope (header / user / software), posts to the
``/invoiceService/v3`` operation endpoints, and parses the XML response.
"""

import logging
import time
from typing import Any, Iterable, Optional
from xml.sax.saxutils import escape

import requests
from lxml import etree

from nav_invoice import crypto
from nav_invoice.config import Settings

logger = logging.getLogger(__name__)

API_NS = "http://schemas.nav.gov.hu/OSA/3.0/api"
COMMON_NS = "http://schemas.nav.gov.hu/NTCA/1.0/common"


class NavApiError(Exception):
    """Raised when NAV returns a fault or a non-OK funcCode."""

    def __init__(self, message: str, func_code: str = "", error_code: str = ""):
        self.func_code = func_code
        self.error_code = error_code
        super().__init__(message)


def _xml(value: Any) -> str:
    """Escape a value for safe inclusion in XML text."""
    return escape(str(value))


class NavClient:
    """HTTP client for the NAV Online Számla 3.0 REST API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/xml;charset=UTF-8",
                "Accept": "application/xml",
            }
        )

    # ── Envelope construction ───────────────────────────

    def build_request(
        self,
        root_name: str,
        body_xml: str = "",
        *,
        invoices: Optional[Iterable[tuple[str, str]]] = None,
    ) -> str:
        """Build a complete request envelope XML string.

        ``body_xml`` is the operation-specific content placed after the
        ``software`` element. ``invoices`` (operation, base64_data) tuples are
        used only to extend the request signature for manage operations.
        """
        s = self.settings
        request_id = crypto.generate_request_id()
        now = crypto.utc_now()
        timestamp = crypto.format_timestamp(now)
        pwd_hash = crypto.password_hash(s.password)
        signature = crypto.request_signature(request_id, now, s.sign_key, invoices)

        software_xml = "".join(
            f"<{k}>{_xml(v)}</{k}>" for k, v in s.software.items()
        )

        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<{root_name} xmlns="{API_NS}" xmlns:common="{COMMON_NS}">'
            "<common:header>"
            f"<common:requestId>{request_id}</common:requestId>"
            f"<common:timestamp>{timestamp}</common:timestamp>"
            "<common:requestVersion>3.0</common:requestVersion>"
            "<common:headerVersion>1.0</common:headerVersion>"
            "</common:header>"
            "<common:user>"
            f"<common:login>{_xml(s.login)}</common:login>"
            f'<common:passwordHash cryptoType="SHA-512">{pwd_hash}</common:passwordHash>'
            f"<common:taxNumber>{_xml(s.tax_number)}</common:taxNumber>"
            f'<common:requestSignature cryptoType="SHA3-512">{signature}</common:requestSignature>'
            "</common:user>"
            f"<software>{software_xml}</software>"
            f"{body_xml}"
            f"</{root_name}>"
        )

    # ── HTTP ────────────────────────────────────────────

    def post(
        self,
        path: str,
        xml_payload: str,
    ) -> "etree._Element":
        """POST an envelope to ``path`` and return the parsed response root.

        Raises :class:`NavApiError` on HTTP/parse failures or NAV faults.
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        logger.debug("NAV POST %s payload:\n%s", url, xml_payload)

        start = time.perf_counter()
        response = self.session.post(
            url, data=xml_payload.encode("utf-8"), timeout=70
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info("NAV POST %s → %d in %.0fms", path.lstrip("/"), response.status_code, elapsed_ms)
        logger.debug("Response:\n%s", response.text[:4000])

        try:
            root = etree.fromstring(response.content)
        except etree.XMLSyntaxError as exc:
            raise NavApiError(
                f"HTTP {response.status_code}: invalid XML response ({exc})"
            ) from exc

        self._raise_for_fault(root)
        return root

    # ── Response parsing helpers ────────────────────────

    @staticmethod
    def _raise_for_fault(root: "etree._Element") -> None:
        """Inspect the response root and raise on NAV faults / non-OK code."""
        local = etree.QName(root).localname

        if local in ("GeneralExceptionResponse", "TechnicalFault", "GeneralErrorResponse"):
            message = findtext(root, "message") or "Ismeretlen NAV hiba"
            func_code = findtext(root, "funcCode")
            error_code = findtext(root, "errorCode")
            raise NavApiError(message, func_code=func_code, error_code=error_code)

        func_code = findtext(root, "funcCode")
        if func_code and func_code != "OK":
            message = findtext(root, "message") or func_code
            error_code = findtext(root, "errorCode")
            raise NavApiError(message, func_code=func_code, error_code=error_code)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def findtext(root: "etree._Element", local_name: str) -> str:
    """Return the text of the first descendant with the given local name."""
    for el in root.iter():
        if _local(el.tag) == local_name and el.text is not None:
            return el.text.strip()
    return ""


def findall(root: "etree._Element", local_name: str) -> list["etree._Element"]:
    """Return all descendants with the given local name."""
    return [el for el in root.iter() if _local(el.tag) == local_name]


def child_text(element: "etree._Element", local_name: str) -> str:
    """Return the text of the first direct/descendant child by local name."""
    for el in element.iter():
        if el is element:
            continue
        if _local(el.tag) == local_name and el.text is not None:
            return el.text.strip()
    return ""