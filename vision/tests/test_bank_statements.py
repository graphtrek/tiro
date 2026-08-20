"""Bankkivonat PDF UI oldal tesztek (/ui/bank-statements)."""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import vision.auth as vision_auth
from vision.api.main import app
from vision.clients.uploader import UploaderClient

SAMPLE_FILES = [
    {
        "bank": "erste",
        "filename": "HU92116000060000000197860425_20260701_20260731.pdf",
        "from_date": "2026-07-01",
        "to_date": "2026-07-31",
        "size_bytes": 12345,
        "modified_at": "2026-08-19T22:08:05.725694Z",
        "path": "/tmp/erste/HU92116000060000000197860425_20260701_20260731.pdf",
    },
    {
        "bank": "wise",
        "filename": "statement_25546267_HUF_2026-07-01_2026-07-31.pdf",
        "from_date": "2026-07-01",
        "to_date": "2026-07-31",
        "size_bytes": 6789,
        "modified_at": "2026-08-19T22:09:05.725694Z",
        "path": "/tmp/wise/statement_25546267_HUF_2026-07-01_2026-07-31.pdf",
    },
]


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


def _auth_header(
    keypair, role: str | None = None, anonymized: bool | None = None
) -> dict[str, str]:
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
        "aud": "moneypenny",
    }
    if role:
        payload["role"] = role
    if anonymized is not None:
        payload["anonymized"] = anonymized
    token = pyjwt.encode(payload, private_pem, algorithm="RS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_header(keypair) -> dict[str, str]:
    return _auth_header(keypair)


@pytest.fixture
def readonly_auth_header(keypair) -> dict[str, str]:
    return _auth_header(keypair, role="read_only")


@pytest.fixture
def anonymized_auth_header(keypair) -> dict[str, str]:
    return _auth_header(keypair, role="read_only", anonymized=True)


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def test_page_lists_bank_statements(monkeypatch, client, auth_header):
    monkeypatch.setattr(UploaderClient, "list_pdf_statements", lambda self: SAMPLE_FILES)

    response = client.get("/ui/bank-statements", headers=auth_header)

    assert response.status_code == 200
    assert "HU92116000060000000197860425_20260701_20260731.pdf" in response.text
    assert "statement_25546267_HUF_2026-07-01_2026-07-31.pdf" in response.text
    assert "2026-07-01" in response.text
    assert "2026-07-31" in response.text


def test_page_readonly_hides_upload_and_delete(monkeypatch, client, readonly_auth_header):
    monkeypatch.setattr(UploaderClient, "list_pdf_statements", lambda self: SAMPLE_FILES)

    response = client.get("/ui/bank-statements", headers=readonly_auth_header)

    assert response.status_code == 200
    assert 'hx-post="/ui/bank-statements/upload"' not in response.text
    assert "hx-delete=" not in response.text
    # download links stay visible for read-only users
    assert "/download" in response.text


def test_page_anonymized_fakes_filenames_and_hides_download(
    monkeypatch, client, anonymized_auth_header
):
    monkeypatch.setattr(UploaderClient, "list_pdf_statements", lambda self: SAMPLE_FILES)

    response = client.get("/ui/bank-statements", headers=anonymized_auth_header)

    assert response.status_code == 200
    # real filenames (and the IBAN/account they encode) never render
    assert "HU92116000060000000197860425_20260701_20260731.pdf" not in response.text
    assert "statement_25546267_HUF_2026-07-01_2026-07-31.pdf" not in response.text
    # bank + statement period stay real/visible
    assert "erste" in response.text
    assert "wise" in response.text
    assert "2026-07-01" in response.text
    assert "2026-07-31" in response.text
    # no download affordance at all for the anonymized tier
    assert "/download" not in response.text
    assert "bi-download" not in response.text


def test_anonymized_filename_is_deterministic(monkeypatch, client, anonymized_auth_header):
    monkeypatch.setattr(UploaderClient, "list_pdf_statements", lambda self: SAMPLE_FILES)

    first = client.get("/ui/bank-statements", headers=anonymized_auth_header).text
    second = client.get("/ui/bank-statements", headers=anonymized_auth_header).text

    assert first == second


def test_download_blocked_for_anonymized(monkeypatch, client, anonymized_auth_header):
    response = client.get(
        f"/ui/bank-statements/erste/{SAMPLE_FILES[0]['filename']}/download",
        headers=anonymized_auth_header,
    )

    assert response.status_code == 403


def test_upload_success_renders_alert_and_reload_trigger(monkeypatch, client, auth_header):
    upload_result = {
        "filename": "HU92116000060000000197860425_20260701_20260731.pdf",
        "bank": "erste",
        "from_date": "2026-07-01",
        "to_date": "2026-07-31",
        "saved_path": "/tmp/erste/x.pdf",
        "size_bytes": 12345,
        "overwritten": False,
    }
    monkeypatch.setattr(
        UploaderClient, "upload_pdf_statement", lambda self, **kwargs: upload_result
    )

    response = client.post(
        "/ui/bank-statements/upload",
        headers=auth_header,
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    assert "Feltöltve" in response.text
    assert 'hx-get="/ui/bank-statements/table"' in response.text
    assert 'hx-target="#table-container"' in response.text


def test_upload_error_renders_alert(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        UploaderClient,
        "upload_pdf_statement",
        lambda self, **kwargs: {"error": "Nem felismerhető bankkivonat PDF formátum"},
    )

    response = client.post(
        "/ui/bank-statements/upload",
        headers=auth_header,
        files={"file": ("random.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    assert "Feltöltés sikertelen" in response.text


def test_delete_rerenders_table(monkeypatch, client, auth_header):
    monkeypatch.setattr(UploaderClient, "delete_pdf_statement", lambda self, bank, filename: True)
    monkeypatch.setattr(UploaderClient, "list_pdf_statements", lambda self: [])

    response = client.request(
        "DELETE",
        f"/ui/bank-statements/erste/{SAMPLE_FILES[0]['filename']}",
        headers=auth_header,
    )

    assert response.status_code == 200
    assert "bank-statement-table" in response.text
