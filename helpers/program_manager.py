"""Lifecycle management for dynamically generated FastAPI programs."""

import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

GENERATED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "generated_programs",
)
BASE_PORT = 8600
MAX_PROGRAMS = 100


# ── Internal helpers ──────────────────────────────────────────────────────────


def _used_ports() -> set:
    used: set = set()
    root = Path(GENERATED_DIR)
    if not root.exists():
        return used
    for prog_dir in root.iterdir():
        manifest_path = prog_dir / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path) as fh:
                    manifest = json.load(fh)
                port = manifest.get("port")
                if port:
                    used.add(port)
            except (json.JSONDecodeError, OSError):
                pass
    return used


def _allocate_port() -> int:
    used = _used_ports()
    for port in range(BASE_PORT, BASE_PORT + MAX_PROGRAMS):
        if port not in used:
            return port
    raise RuntimeError("No available ports in range 8600-8700")


def _slugify(name: str) -> str:
    """Convert a program name to a safe directory-name component."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:40] or "program"


def _find_prog_dir(program_id: str) -> Optional[Path]:
    """Locate a program directory by its ID using glob (name may vary)."""
    root = Path(GENERATED_DIR)
    if not root.exists():
        return None
    matches = list(root.glob(f"*-{program_id}"))
    if matches:
        return matches[0]
    # Fallback: legacy dirs named by ID only
    legacy = root / program_id
    if legacy.exists():
        return legacy
    return None


def _save_manifest(prog_dir: Path, manifest: dict) -> None:
    (prog_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _refresh_status(manifest: dict, prog_dir: Path) -> dict:
    """Check whether the stored PID is still alive and update status in-place."""
    pid = manifest.get("pid")
    if pid:
        try:
            os.kill(pid, 0)  # signal 0 = existence check
            manifest["status"] = "running"
        except (ProcessLookupError, PermissionError):
            manifest["status"] = "stopped"
            manifest["pid"] = None
            _save_manifest(prog_dir, manifest)
    else:
        manifest["status"] = "stopped"
    return manifest


# ── Public API ────────────────────────────────────────────────────────────────


def create_program(
    name: str,
    description: str,
    code: str,
    mode: str = "service",
) -> dict:
    """Persist a generated program to disk and return its manifest."""
    program_id = uuid.uuid4().hex[:8]
    port = _allocate_port()

    dir_name = f"{_slugify(name)}-{program_id}"
    prog_dir = Path(GENERATED_DIR) / dir_name
    prog_dir.mkdir(parents=True, exist_ok=True)

    (prog_dir / "main.py").write_text(code)

    manifest = {
        "id": program_id,
        "name": name,
        "description": description,
        "port": port,
        "mode": mode,
        "status": "stopped",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pid": None,
    }
    _save_manifest(prog_dir, manifest)
    return manifest


def list_programs() -> list:
    programs = []
    root = Path(GENERATED_DIR)
    if not root.exists():
        return programs
    for prog_dir in sorted(root.iterdir()):
        manifest_path = prog_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            with open(manifest_path) as fh:
                manifest = json.load(fh)
            _refresh_status(manifest, prog_dir)
            programs.append(manifest)
        except (json.JSONDecodeError, OSError):
            pass
    return programs


def get_program(program_id: str) -> Optional[dict]:
    prog_dir = _find_prog_dir(program_id)
    if not prog_dir:
        return None
    manifest_path = prog_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    _refresh_status(manifest, prog_dir)
    return manifest


def start_program(program_id: str) -> dict:
    prog_dir = _find_prog_dir(program_id)
    manifest_path = prog_dir / "manifest.json" if prog_dir else None
    if not prog_dir or not manifest_path.exists():
        raise FileNotFoundError(f"Program {program_id} not found")

    with open(manifest_path) as fh:
        manifest = json.load(fh)

    # Already running?
    pid = manifest.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            manifest["status"] = "running"
            return manifest
        except (ProcessLookupError, PermissionError):
            pass

    port = manifest["port"]
    log_path = prog_dir / "output.log"

    # Inject the project root into PYTHONPATH so generated programs can import
    # helpers.drive_utils, helpers.gmail_utils, etc.
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_project_root}:{existing}" if existing else _project_root

    proc = subprocess.Popen(
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(port)],
        cwd=str(prog_dir),
        stdout=open(log_path, "w"),
        stderr=subprocess.STDOUT,
        env=env,
    )

    manifest["pid"] = proc.pid
    manifest["status"] = "running"
    _save_manifest(prog_dir, manifest)
    return manifest


def stop_program(program_id: str) -> dict:
    prog_dir = _find_prog_dir(program_id)
    manifest_path = prog_dir / "manifest.json" if prog_dir else None
    if not prog_dir or not manifest_path.exists():
        raise FileNotFoundError(f"Program {program_id} not found")

    with open(manifest_path) as fh:
        manifest = json.load(fh)

    pid = manifest.get("pid")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    manifest["pid"] = None
    manifest["status"] = "stopped"
    _save_manifest(prog_dir, manifest)
    return manifest


def delete_program(program_id: str) -> None:
    prog_dir = _find_prog_dir(program_id)
    if not prog_dir:
        raise FileNotFoundError(f"Program {program_id} not found")

    # Stop cleanly before removing files
    manifest_path = prog_dir / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path) as fh:
                manifest = json.load(fh)
            pid = manifest.get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
        except (json.JSONDecodeError, OSError):
            pass

    shutil.rmtree(prog_dir)


def get_logs(program_id: str, lines: int = 100) -> str:
    prog_dir = _find_prog_dir(program_id)
    if not prog_dir:
        return ""
    log_path = prog_dir / "output.log"
    if not log_path.exists():
        return ""
    with open(log_path) as fh:
        all_lines = fh.readlines()
    return "".join(all_lines[-lines:])


def update_code(program_id: str, code: str) -> None:
    prog_dir = _find_prog_dir(program_id)
    if not prog_dir:
        raise FileNotFoundError(f"Program {program_id} not found")
    (prog_dir / "main.py").write_text(code)
