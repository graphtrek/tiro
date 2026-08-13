"""InvoiceCoreClient error-surfacing -- regression coverage for DEF-015.

FastAPI's default pydantic validation-error body is
`{"detail": [{"loc": ..., "msg": ..., "type": ...}]}` -- a *list*, not a
string. `_write_json()` used to hand that list straight through as the
`error` value, which the caller (adok_save_estimate) then passed to
`urllib.parse.quote()` for the error-redirect URL; `quote()` only accepts
str/bytes, so a validation failure (e.g. a negative "Becsult bevetel")
crashed instead of producing a visible error banner. `_format_error_detail`
flattens that list into one readable string.
"""

from __future__ import annotations

import json as json_lib
from urllib.parse import quote

import pytest
import requests

from vision.clients.invoice_core import (
    InvoiceCoreClient,
    _format_error_detail,
    _translate_tax_estimate_error,
)


def _http_error_with_detail(detail) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = 422
    resp._content = json_lib.dumps({"detail": detail}).encode()
    return requests.HTTPError(response=resp)


@pytest.mark.parametrize(
    "detail,expected",
    [
        (
            [
                {
                    "loc": ["body", "months", 0, "gross_revenue"],
                    "msg": "Input should be greater than or equal to 0",
                    "type": "greater_than_equal",
                }
            ],
            "Input should be greater than or equal to 0",
        ),
        (
            [
                {"msg": "first error"},
                {"msg": "second error"},
            ],
            "first error; second error",
        ),
        ("plain string detail", "plain string detail"),
        (None, None),
        ([], None),
    ],
)
def test_format_error_detail(detail, expected):
    assert _format_error_detail(detail) == expected


def test_translate_tax_estimate_error_maps_negative_revenue_to_hungarian():
    assert (
        _translate_tax_estimate_error("Input should be greater than or equal to 0")
        == "A becsült bevétel nem lehet negatív szám."
    )


def test_translate_tax_estimate_error_falls_back_for_unknown_detail():
    assert (
        _translate_tax_estimate_error("some other backend detail")
        == "Érvénytelen érték a becsült bevétel mezőben."
    )


def test_save_tax_estimate_overrides_formats_pydantic_validation_list(monkeypatch):
    """A 422 from PUT /api/v1/reports/tax-estimate/overrides (e.g. a negative
    gross_revenue tripping the backend's `Field(ge=0)`) must surface as a
    plain, quote()-able, Hungarian string -- not the raw pydantic error list
    and not pydantic's raw English wording (DEF-015 follow-up)."""
    client = InvoiceCoreClient()

    def fake_request(method, url, json=None, headers=None, timeout=None):
        raise _http_error_with_detail(
            [
                {
                    "type": "greater_than_equal",
                    "loc": ["body", "months", 0, "gross_revenue"],
                    "msg": "Input should be greater than or equal to 0",
                    "input": -500.0,
                }
            ]
        )

    monkeypatch.setattr(client.session, "request", fake_request)

    result = client.save_tax_estimate_overrides(2026, [{"month": 8, "gross_revenue": -500.0}])

    assert result == {"error": "A becsült bevétel nem lehet negatív szám."}
    # Must not raise -- this is exactly what the adok/estimate route does with
    # the error before redirecting, and a list value used to blow up here.
    quote(result["error"])


def test_save_tax_estimate_overrides_falls_back_for_unknown_detail(monkeypatch):
    """Any other backend detail on this save path still gets a Hungarian
    message, without inventing a general-purpose translation layer."""
    client = InvoiceCoreClient()

    def fake_request(method, url, json=None, headers=None, timeout=None):
        raise _http_error_with_detail("some other backend detail")

    monkeypatch.setattr(client.session, "request", fake_request)

    result = client.save_tax_estimate_overrides(2026, [{"month": 8, "gross_revenue": 100.0}])

    assert result == {"error": "Érvénytelen érték a becsült bevétel mezőben."}


def test_save_tax_estimate_overrides_network_failure_keeps_generic_hungarian_fallback(
    monkeypatch,
):
    """When invoice-core is unreachable (no HTTP response at all), the
    generic Hungarian fallback message must not be run through the
    tax-estimate translator."""
    client = InvoiceCoreClient()

    def fake_request(method, url, json=None, headers=None, timeout=None):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(client.session, "request", fake_request)

    result = client.save_tax_estimate_overrides(2026, [{"month": 8, "gross_revenue": 100.0}])

    assert result == {"error": "A szolgáltatás jelenleg nem érhető el"}
