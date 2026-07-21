"""FastAPI végpont tesztek (TestClient, izolált tmp_path storage-dzsal)."""

from __future__ import annotations

import io

import httpx
from fastapi.testclient import TestClient

ERSTE_FILENAME = "12345678-12345678_2026-05-01_2026-05-31.csv"
WISE_FILENAME = "statement_123_EUR_2026-05-01_2026-05-31.csv"
CSV_BYTES = b"date,amount\n2026-05-01,100\n"


def _upload(client: TestClient, filename: str, **form) -> httpx.Response:
    return client.post(
        "/api/v1/upload",
        files={"file": (filename, io.BytesIO(CSV_BYTES), "text/csv")},
        data=form,
    )


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_settings_info(client: TestClient):
    response = client.get("/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["erste_subdir"] == "erste"
    assert body["wise_subdir"] == "wise"


def test_list_all_files_empty(client: TestClient):
    response = client.get("/api/v1/files")
    assert response.status_code == 200
    assert response.json()["total_files"] == 0


def test_list_bank_files_invalid_bank_400(client: TestClient):
    response = client.get("/api/v1/files/unknown")
    assert response.status_code == 400


def test_upload_rejects_non_csv(client: TestClient):
    response = _upload(client, "invoice.pdf")
    assert response.status_code == 400


def test_upload_rejects_unrecognized_filename(client: TestClient):
    response = _upload(client, "random.csv")
    assert response.status_code == 400


def test_upload_auto_detects_erste_and_lists(client: TestClient):
    response = _upload(client, ERSTE_FILENAME)
    assert response.status_code == 200
    body = response.json()
    assert body["bank"] == "erste"
    assert body["overwritten"] is False

    listing = client.get("/api/v1/files/erste").json()
    assert [f["filename"] for f in listing] == [ERSTE_FILENAME]


def test_upload_auto_detects_wise(client: TestClient):
    response = _upload(client, WISE_FILENAME)
    assert response.status_code == 200
    assert response.json()["bank"] == "wise"


def test_upload_explicit_bank_overrides_detection(client: TestClient):
    response = _upload(client, "random.csv", bank="erste")
    assert response.status_code == 200
    assert response.json()["bank"] == "erste"


def test_upload_duplicate_without_overwrite_400(client: TestClient):
    _upload(client, ERSTE_FILENAME)
    response = _upload(client, ERSTE_FILENAME)
    assert response.status_code == 400


def test_upload_duplicate_with_overwrite_succeeds(client: TestClient):
    _upload(client, ERSTE_FILENAME)
    response = _upload(client, ERSTE_FILENAME, overwrite="true")
    assert response.status_code == 200
    assert response.json()["overwritten"] is True


def test_download_uploaded_file(client: TestClient):
    _upload(client, ERSTE_FILENAME)
    response = client.get(f"/api/v1/files/erste/{ERSTE_FILENAME}/download")
    assert response.status_code == 200
    assert response.content == CSV_BYTES


def test_download_missing_file_404(client: TestClient):
    response = client.get("/api/v1/files/erste/missing.csv/download")
    assert response.status_code == 404


def test_download_invalid_bank_400(client: TestClient):
    response = client.get("/api/v1/files/unknown/f.csv/download")
    assert response.status_code == 400


def test_delete_uploaded_file(client: TestClient):
    _upload(client, ERSTE_FILENAME)
    response = client.delete(f"/api/v1/files/erste/{ERSTE_FILENAME}")
    assert response.status_code == 204

    listing = client.get("/api/v1/files/erste").json()
    assert listing == []


def test_delete_missing_file_404(client: TestClient):
    response = client.delete("/api/v1/files/erste/missing.csv")
    assert response.status_code == 404


def test_protected_endpoint_requires_auth(unauthenticated_client: TestClient):
    response = unauthenticated_client.get("/api/v1/files")
    assert response.status_code == 401


def test_health_is_public_without_auth(unauthenticated_client: TestClient):
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200
