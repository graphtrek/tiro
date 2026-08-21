"""Vacation Planner page -- Controlling > Szabadság.

Covers the `/ui/controlling/vacation` list page and the create/update/delete
routes that forward to invoice-core's `/api/v1/vacation-requests` resource,
mirroring the Timesheet feature's page-shell + HX-Redirect-on-success pattern.
"""

from __future__ import annotations

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
    token = pyjwt.encode(payload, private_pem, algorithm="RS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def current_user(monkeypatch):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_users",
        lambda self: [{"id": 1, "email": "imre.tatai@graphtrek.co", "name": "Imre Tatai"}],
    )


def test_vacation_page_lists_rows_and_marks_ownership(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_vacation_requests",
        lambda self, user_id=None: [
            {
                "id": 10,
                "user_id": 1,
                "user_name": "Imre Tatai",
                "kind": "vacation",
                "start_date": "2026-08-20",
                "end_date": "2026-08-24",
                "note": None,
            },
            {
                "id": 11,
                "user_id": 2,
                "user_name": "Other User",
                "kind": "out_of_office",
                "start_date": "2026-08-25",
                "end_date": "2026-08-25",
                "note": "Orvosnál",
            },
        ],
    )

    response = client.get(
        "/ui/controlling/vacation", headers={**auth_header, "Accept": "text/html"}
    )

    assert response.status_code == 200
    assert "Szabadság" in response.text
    assert "Nem elérhető" in response.text
    assert "Orvosnál" in response.text
    # Own row (id 10) gets edit/delete controls; the other user's row (id 11) does not.
    assert 'data-bs-target="#editVacationModal10"' in response.text
    assert 'data-bs-target="#editVacationModal11"' not in response.text
    assert "/ui/controlling/vacation/10" in response.text
    assert "/ui/controlling/vacation/11" not in response.text


def test_vacation_page_without_resolvable_user_shows_error(monkeypatch, client, auth_header):
    monkeypatch.setattr(InvoiceCoreClient, "get_users", lambda self: [])
    monkeypatch.setattr(InvoiceCoreClient, "get_vacation_requests", lambda self, user_id=None: [])

    response = client.get(
        "/ui/controlling/vacation", headers={**auth_header, "Accept": "text/html"}
    )

    assert response.status_code == 200
    assert "Felhasználó azonosítása sikertelen" in response.text


def test_create_vacation_request_forwards_payload_and_redirects(monkeypatch, client, auth_header):
    captured = {}

    def fake_create(self, user_id, kind, start_date, end_date, note):
        captured.update(
            user_id=user_id, kind=kind, start_date=start_date, end_date=end_date, note=note
        )
        return {"id": 99, "user_id": user_id, "kind": kind}

    monkeypatch.setattr(InvoiceCoreClient, "create_vacation_request", fake_create)

    response = client.post(
        "/ui/controlling/vacation",
        data={
            "kind": "vacation",
            "start_date": "2026-09-01",
            "end_date": "2026-09-05",
            "note": "Nyaralás",
        },
        headers=auth_header,
    )

    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/ui/controlling/vacation"
    assert captured == {
        "user_id": 1,
        "kind": "vacation",
        "start_date": "2026-09-01",
        "end_date": "2026-09-05",
        "note": "Nyaralás",
    }


def test_create_vacation_request_error_rerenders_inline_alert(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "create_vacation_request",
        lambda self, user_id, kind, start_date, end_date, note: {
            "error": "A záró dátum nem lehet korábbi, mint a kezdő dátum"
        },
    )

    response = client.post(
        "/ui/controlling/vacation",
        data={
            "kind": "vacation",
            "start_date": "2026-09-05",
            "end_date": "2026-09-01",
            "note": "",
        },
        headers=auth_header,
    )

    assert response.status_code == 200
    assert "HX-Redirect" not in response.headers
    assert "korábbi" in response.text


def test_update_vacation_request_scoped_to_owner(monkeypatch, client, auth_header):
    captured = {}

    def fake_update(self, request_id, user_id, kind, start_date, end_date, note):
        captured.update(
            request_id=request_id,
            user_id=user_id,
            kind=kind,
            start_date=start_date,
            end_date=end_date,
            note=note,
        )
        return {"id": request_id}

    monkeypatch.setattr(InvoiceCoreClient, "update_vacation_request", fake_update)

    response = client.post(
        "/ui/controlling/vacation/10",
        data={
            "kind": "note",
            "start_date": "2026-09-10",
            "end_date": "2026-09-10",
            "note": "Frissítve",
        },
        headers=auth_header,
    )

    assert response.status_code == 204
    assert captured["request_id"] == 10
    assert captured["user_id"] == 1
    assert captured["kind"] == "note"


def test_delete_vacation_request_scoped_to_owner_and_redirects(monkeypatch, client, auth_header):
    captured = {}

    def fake_delete(self, request_id, user_id):
        captured.update(request_id=request_id, user_id=user_id)
        return {"status": "deleted"}

    monkeypatch.setattr(InvoiceCoreClient, "delete_vacation_request", fake_delete)

    response = client.delete("/ui/controlling/vacation/10", headers=auth_header)

    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/ui/controlling/vacation"
    assert captured == {"request_id": 10, "user_id": 1}


def test_delete_vacation_request_not_owned_shows_error(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "delete_vacation_request",
        lambda self, request_id, user_id: {"error": "Nem található bejegyzés"},
    )
    monkeypatch.setattr(InvoiceCoreClient, "get_vacation_requests", lambda self, user_id=None: [])

    response = client.delete("/ui/controlling/vacation/999", headers=auth_header)

    assert response.status_code == 200
    assert "Nem található bejegyzés" in response.text
