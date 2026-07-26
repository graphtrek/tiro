"""Sync pipeline e2e tests against the real running invoice-core (+ its downstream services).

`test_full_sync_end_to_end` is slow (real Gmail/OCR/NAV/bank calls, can take minutes) and
requires real external credentials to be configured in the shared .env; mark-deselect it with
`-m "not slow"` for a fast run.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
_INVOICE_CORE_DIR = _WORKSPACE_ROOT / "invoice-core"

SYNC_DATE_RANGE = {"start_date": "2026-06-01", "end_date": "2026-06-30"}


@pytest.mark.slow
def test_full_sync_end_to_end(base_urls, api_session):
    """POST /api/v1/sync runs all four pipeline stages and completes without manual intervention.

    errors may be non-empty if external creds are missing (that's the "degrades cleanly" case
    covered by test_sync_stage_cli_degrades_cleanly_without_a_token below) — what matters here is
    that the call completes (no 500, no hang) and returns the expected shape.
    """
    resp = api_session.post(
        f"{base_urls['invoice_core']}/api/v1/sync", json=SYNC_DATE_RANGE, timeout=600
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "start_date",
        "end_date",
        "nav_invoices_synced",
        "pdf_files_synced",
        "bank_transactions_synced",
        "bank_files_matched",
        "errors",
    ):
        assert key in body, f"missing {key} in {body}"

    # A sync_log row must have been written for this run.
    logs = api_session.get(f"{base_urls['invoice_core']}/api/v1/sync/logs", timeout=10).json()
    assert logs, "expected at least one sync_log row"
    assert logs[0]["mode"] == "full"


@pytest.mark.parametrize("stage_cmd", ["sync-nav", "sync-pdf", "sync-bank"])
def test_sync_stage_cli_degrades_cleanly_without_a_token(stage_cmd):
    """The invoice-core CLI has no bearer token to attach to its downstream calls (no browser
    session to pass through). With AUTH_ENABLED=true service-wide (this workspace's current
    config), every downstream call the CLI makes gets a 401 from that service — the requirement
    is that the CLI stage still degrades cleanly (clear per-stage error, exit 0, a sync_log row
    written), not that it 500s or hangs.
    """
    cmd = ["uv", "run", "invoice-core", stage_cmd]
    if stage_cmd != "sync-bank":
        cmd += ["--start", "2026-06-01", "--end", "2026-06-30"]
    result = subprocess.run(
        cmd,
        cwd=_INVOICE_CORE_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"{stage_cmd} exited {result.returncode}:\n{result.stderr}"
    assert "Traceback" not in result.stderr, result.stderr


def test_sync_match_cli_runs_without_a_token():
    """sync-match only touches the local DB (no downstream HTTP call), so it should succeed
    outright even with no token at all.
    """
    result = subprocess.run(
        ["uv", "run", "invoice-core", "sync-match"],
        cwd=_INVOICE_CORE_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"sync-match exited {result.returncode}:\n{result.stderr}"


@pytest.mark.slow
def test_sync_stage_endpoints_return_200_and_log(base_urls, api_session):
    """Each stage HTTP endpoint returns 200 with an errors list, and logs a sync_log row —
    exercised here with a valid token (so, unlike the CLI test above, these calls do real work
    against the live downstream services via token passthrough).
    """
    for stage in ("nav", "pdf", "bank", "match"):
        resp = api_session.post(
            f"{base_urls['invoice_core']}/api/v1/sync/{stage}",
            json=SYNC_DATE_RANGE,
            timeout=280,
        )
        assert resp.status_code == 200, f"stage {stage}: {resp.status_code} {resp.text}"
        assert "errors" in resp.json()

    logs = api_session.get(f"{base_urls['invoice_core']}/api/v1/sync/logs", timeout=10).json()
    assert len(logs) >= 4
