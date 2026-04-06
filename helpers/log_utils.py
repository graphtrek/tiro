"""Shared logging helper — appends structured entries to ai.log.

Designed to be imported by dynamically generated programs as well as the main
application.  The log file path is always resolved relative to the project root
(the directory containing this helpers/ package), so it works regardless of the
current working directory.

Usage:
    from helpers.log_utils import log_to_file

    log_to_file("my-program", "INFO", "Started processing request")
    log_to_file("my-program", "ERROR", f"Something went wrong: {e}")
"""

import os
import threading
from datetime import datetime, timezone

_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_FILE = os.path.join(_ROOT, "ai.log")
_lock     = threading.Lock()


def log_to_file(source: str, level: str, message: str) -> None:
    """Append a single log line to ai.log.

    Args:
        source:  Short identifier for the caller, e.g. the program name.
        level:   Severity string, e.g. "INFO", "WARNING", "ERROR".
        message: Free-form log message (newlines are replaced with spaces).
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level.upper()}] [{source}] {message.replace(chr(10), ' ')}\n"
    with _lock:
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
