"""Regression tests for DEF-002: the invoice-core CLI's sync commands must be
able to supply a bearer token for their outbound calls (nav-invoice,
invoice-file-filter, bank) when AUTH_ENABLED=true, via a `--token` flag or the
shared `MP_SERVICE_TOKEN` env var -- reusing the existing `current_token`
ContextVar / TokenPassthrough mechanism, not a second auth mechanism.
"""

import pytest
import requests

from invoice_core.auth import current_token
from invoice_core.cli.main import _resolve_service_token, _run_sync
from invoice_core.config import token_hint_for_error
from invoice_core.models import SyncMode, SyncResponse
from invoice_core.nav_client import NavClient, NavClientError


@pytest.fixture(autouse=True)
def _reset_current_token():
    """Isolate current_token across tests (it's a process-wide ContextVar)."""
    tok = current_token.set(None)
    yield
    current_token.reset(tok)


def test_resolve_service_token_returns_none_when_neither_flag_nor_env(monkeypatch):
    monkeypatch.delenv("MP_SERVICE_TOKEN", raising=False)

    assert _resolve_service_token(None) is None


def test_resolve_service_token_falls_back_to_env_var(monkeypatch):
    monkeypatch.setenv("MP_SERVICE_TOKEN", "env-token")

    assert _resolve_service_token(None) == "env-token"


def test_resolve_service_token_flag_wins_over_env_var(monkeypatch):
    monkeypatch.setenv("MP_SERVICE_TOKEN", "env-token")

    assert _resolve_service_token("flag-token") == "flag-token"


def _fake_sync_all_capturing_token(captured: list):
    def _fake(request, db):
        captured.append(current_token.get())
        return SyncResponse(start_date=request.start_date or "2026-06-01", end_date="2026-06-30")

    return _fake


def test_run_sync_sets_current_token_from_flag(monkeypatch):
    monkeypatch.delenv("MP_SERVICE_TOKEN", raising=False)
    captured: list = []
    monkeypatch.setattr(
        "invoice_core.cli.main.sync_all", _fake_sync_all_capturing_token(captured)
    )

    _run_sync(SyncMode.nav_only, token="flag-token")

    assert captured == ["flag-token"]


def test_run_sync_sets_current_token_from_env(monkeypatch):
    monkeypatch.setenv("MP_SERVICE_TOKEN", "env-token")
    captured: list = []
    monkeypatch.setattr(
        "invoice_core.cli.main.sync_all", _fake_sync_all_capturing_token(captured)
    )

    _run_sync(SyncMode.nav_only, token=None)

    assert captured == ["env-token"]


def test_run_sync_flag_wins_over_env(monkeypatch):
    monkeypatch.setenv("MP_SERVICE_TOKEN", "env-token")
    captured: list = []
    monkeypatch.setattr(
        "invoice_core.cli.main.sync_all", _fake_sync_all_capturing_token(captured)
    )

    _run_sync(SyncMode.nav_only, token="flag-token")

    assert captured == ["flag-token"]


def test_run_sync_without_any_token_leaves_current_token_unset_and_warns(monkeypatch, caplog):
    monkeypatch.delenv("MP_SERVICE_TOKEN", raising=False)
    captured: list = []
    monkeypatch.setattr(
        "invoice_core.cli.main.sync_all", _fake_sync_all_capturing_token(captured)
    )

    with caplog.at_level("WARNING"):
        _run_sync(SyncMode.nav_only, token=None)

    assert captured == [None]  # clean degrade: no token set, sync_all still runs
    assert any(
        "--token" in rec.message and "MP_SERVICE_TOKEN" in rec.message for rec in caplog.records
    )


def _fake_401_response():
    resp = requests.Response()
    resp.status_code = 401
    return resp


def test_token_hint_for_error_appends_hint_on_401():
    exc = requests.HTTPError("401 Client Error: Unauthorized")
    exc.response = _fake_401_response()

    hint = token_hint_for_error(exc)

    assert "--token" in hint
    assert "MP_SERVICE_TOKEN" in hint


def test_token_hint_for_error_empty_for_non_auth_errors():
    exc = requests.ConnectionError("Connection refused")

    assert token_hint_for_error(exc) == ""


def test_nav_client_error_message_includes_token_hint_on_401(monkeypatch):
    """End-to-end (within the client): a 401 from nav-invoice must surface a
    NavClientError whose message tells the CLI user how to authenticate."""
    from invoice_core.config import Settings

    def _fake_get(self, *args, **kwargs):
        resp = requests.Response()
        resp.status_code = 401
        resp._content = b"Unauthorized"
        return resp

    client = NavClient(Settings(_env_file=None))
    monkeypatch.setattr(client.session, "get", _fake_get.__get__(client.session))

    with pytest.raises(NavClientError) as excinfo:
        client._fetch("2026-06-01", "2026-06-05", "OUTBOUND")

    assert "--token" in str(excinfo.value)
    assert "MP_SERVICE_TOKEN" in str(excinfo.value)
