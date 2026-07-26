"""CLI-level regression test for DEF-012: when sync_all rejects a concurrent
sync (SyncInProgressError), the CLI must print a clear message and exit
non-zero -- never hang, never exit 0 as if nothing happened.
"""

from __future__ import annotations

from typer.testing import CliRunner

from invoice_core.cli.main import app
from invoice_core.service import SYNC_IN_PROGRESS_MESSAGE, SyncInProgressError

runner = CliRunner()


def test_cli_sync_exits_non_zero_with_clear_message_when_a_sync_is_in_progress(monkeypatch):
    def _raise(*args, **kwargs):
        raise SyncInProgressError(SYNC_IN_PROGRESS_MESSAGE)

    monkeypatch.setattr("invoice_core.cli.main.sync_all", _raise)

    result = runner.invoke(app, ["sync"])

    assert result.exit_code != 0
    assert "folyamatban" in result.output.lower()
