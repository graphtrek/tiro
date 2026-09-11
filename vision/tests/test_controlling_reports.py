"""Controlling > Riportok — hét oszlop rendezése.

A "Hét" / "Projekt hét" cellák `W<n>` szövegként jelennek meg, amit a DataTables
sztringként rendezne (W1, W10, W2, ...). A cellák ezért `data-order` attribútumban
viszik a nyers hetiszámot, hogy a rendezés numerikus legyen.
"""

from __future__ import annotations

import re
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import vision.auth as vision_auth
from vision.api.main import app
from vision.clients.invoice_core import InvoiceCoreClient


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture(autouse=True)
def local_jwks(keypair, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _, public_pem = keypair
    monkeypatch.setattr(vision_auth, "_get_signing_key", lambda token, url: public_pem)


@pytest.fixture
def auth_header(keypair) -> dict[str, str]:
    private_pem, _ = keypair
    now = int(time.time())
    payload = {
        "sub": "google-user-1",
        "email": "imre.tatai@graphtrek.co",
        "name": "Imre Tatai",
        "provider": "google",
        "typ": "access",
        "iat": now,
        "exp": now + 900,
        "iss": "auth-service",
        "aud": "tiro",
    }
    return {"Authorization": f"Bearer {pyjwt.encode(payload, private_pem, algorithm='RS256')}"}


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def _entry(week: int, entry_date: str) -> dict:
    return {
        "entry_date": entry_date,
        "weekday": "hétfő",
        "project_week": week,
        "project_code": "PRJ-1",
        "user_name": "Imre Tatai",
        "customer_name": "Acme Kft.",
        "activity_type_name": "Fejlesztés",
        "participants": "",
        "description": "munka",
        "hours": 8.0,
    }


def _week_row(week: int) -> dict:
    return {
        "project_week": week,
        "week_hours": 8.0,
        "cumulative_hours": 8.0 * week,
        "by_activity_type": {"Fejlesztés": 8.0},
    }


@pytest.fixture(autouse=True)
def reference_data(monkeypatch):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_customers",
        lambda self: [{"id": 1, "name": "Acme Kft."}],
    )
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_projects",
        lambda self: [
            {
                "id": 1,
                "code": "PRJ-1",
                "customer_id": 1,
                "customer_name": "Acme Kft.",
                "usage_hours": 40.0,
                "first_entry_date": "2026-01-05",
                "created_at": "2026-01-01T00:00:00",
            }
        ],
    )
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_users",
        lambda self: [{"id": 1, "email": "imre.tatai@graphtrek.co", "name": "Imre Tatai"}],
    )
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_activity_types",
        lambda self: [{"id": 1, "name": "Fejlesztés", "is_active": True}],
    )
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_timesheet_entries",
        lambda self, **kwargs: [{"user_id": 1}],
    )


# A "W<n>" cellák hetiszáma a data-order attribútumból, megjelenési sorrendben.
_WEEK_CELL = re.compile(r'<td data-order="(\d+)">W(\d+)</td>')


def test_project_detail_week_cells_carry_numeric_sort_key(monkeypatch, client, auth_header):
    weeks = [2, 9, 10, 11]
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_timesheet_report",
        lambda self, report_type, **kwargs: {
            "weeks": [_week_row(w) for w in weeks],
            "entries": [_entry(w, f"2026-0{w // 5 + 1}-0{w % 5 + 1}") for w in weeks],
            "activity_type_names": ["Fejlesztés"],
            "total_hours": 32.0,
        },
    )

    resp = client.get(
        "/ui/controlling/reports?report_type=project&project_id=1&date_range=project_start",
        headers=auth_header,
    )
    assert resp.status_code == 200

    matches = _WEEK_CELL.findall(resp.text)
    # heti összesítő sorok + a "Bejegyzések" tábla sorai
    assert len(matches) == 2 * len(weeks)
    for order, label in matches:
        assert order == label
    assert [int(o) for o, _ in matches[: len(weeks)]] == weeks
    # A "Bejegyzések" tábla is rendezhető kell legyen, nem csak a heti összesítő.
    assert 'new DataTable("#report-detail-table"' in resp.text


def test_entry_list_week_cells_carry_numeric_sort_key(monkeypatch, client, auth_header):
    weeks = [3, 12]
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_timesheet_report",
        lambda self, report_type, **kwargs: {
            "rows": [
                {
                    "key_label": "Imre Tatai",
                    "total_hours": 16.0,
                    "entry_count": 2,
                    "by_activity_type": {"Fejlesztés": 16.0},
                }
            ],
            "entries": [_entry(w, f"2026-0{w // 5 + 1}-0{w % 5 + 1}") for w in weeks],
            "activity_type_names": ["Fejlesztés"],
            "total_hours": 16.0,
        },
    )

    resp = client.get("/ui/controlling/reports?report_type=person", headers=auth_header)
    assert resp.status_code == 200

    matches = _WEEK_CELL.findall(resp.text)
    assert [int(o) for o, _ in matches] == weeks
    for order, label in matches:
        assert order == label


def test_avg_active_week_hours_rounded_to_one_decimal(monkeypatch, client, auth_header):
    """109 óra / 9 aktív hét = 12,111... — a kártya egy tizedesjegyet mutasson."""
    weeks = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_timesheet_report",
        lambda self, report_type, **kwargs: {
            "rows": [],
            "entries": [_entry(w, f"2026-0{w // 5 + 1}-0{w % 5 + 1}") for w in weeks],
            "activity_type_names": ["Fejlesztés"],
            "total_hours": 109.0,
        },
    )

    resp = client.get("/ui/controlling/reports?report_type=person", headers=auth_header)
    assert resp.status_code == 200
    assert "12,1 óra" in resp.text
    assert "12,1111" not in resp.text


def test_week_rows_show_days_next_to_hours(monkeypatch, client, auth_header):
    """A heti összesítő 8 órás munkanapban is megjelenik (13,5 óra = 1,69 nap)."""
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_timesheet_report",
        lambda self, report_type, **kwargs: {
            "weeks": [
                {
                    "project_week": 1,
                    "week_hours": 4.5,
                    "cumulative_hours": 4.5,
                    "by_activity_type": {"Fejlesztés": 4.5},
                },
                {
                    "project_week": 13,
                    "week_hours": 13.5,
                    "cumulative_hours": 18.0,
                    "by_activity_type": {"Fejlesztés": 13.5},
                },
            ],
            "entries": [_entry(1, "2026-01-05")],
            "activity_type_names": ["Fejlesztés"],
            "total_hours": 18.0,
        },
    )

    resp = client.get(
        "/ui/controlling/reports?report_type=project&project_id=1&date_range=project_start",
        headers=auth_header,
    )
    assert resp.status_code == 200
    assert "<th class=\"text-end\">Heti (nap)</th>" in resp.text
    assert "<th class=\"text-end\">Kumulált (nap)</th>" in resp.text
    # 4,5 óra → 0,56 nap; 13,5 óra → 1,69 nap; kumulálva 18 óra → 2,25 nap
    for value in ("0,56", "1,69", "2,25"):
        assert f'<td class="text-end">{value}</td>' in resp.text
    # A hu.json nem hoz "decimal" kulcsot — e nélkül a tizedesvesszős oszlopok
    # szövegként rendeződnének.
    assert 'decimal: ","' in resp.text
