"""Manage a local Headroom proxy that compresses the CLI's LLM traffic.

Headroom (https://headroom-docs.vercel.app/docs/quickstart) is a standalone HTTP
proxy: point an OpenAI-compatible client at it and every request is compressed
before being forwarded upstream. This module starts that proxy on demand, points
it at whichever provider the active model uses, and stops the process on exit.

It's on by default; configure it through the environment (typically the .env
loaded by cli.py). Set HEADROOM=0 to turn it off:

    HEADROOM=0                 disable proxy routing (default: enabled)
    HEADROOM_HOST=127.0.0.1    host to bind (default 127.0.0.1)
    HEADROOM_PORT=8787         port to bind (default 8787)
    HEADROOM_MODE=token        optimization strategy: `token` (max token savings)
                               or `cache` (maximise provider cache hit rate)

The CLI drives a single ProxyManager: `ensure(spec)` before each agent build (it
(re)starts the proxy so its upstream matches the model's provider), and `stop()`
on exit. `resolve_model()` in main.py checks `proxy_base_url()` to route the model
through the proxy only while it's actually running.

Only providers with a routable upstream go through the proxy (local / deepseek /
openrouter); anything else runs direct. A proxy we didn't start (already listening
on the port) is reused but never stopped by us.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# Set by a ProxyManager once the proxy is confirmed healthy; read by resolve_model.
# None means "route direct" (proxy off, unsupported provider, or start failed).
_ACTIVE_BASE_URL: str | None = None
_ACTIVE_SPEC: str | None = None


class HeadroomError(RuntimeError):
    """The proxy could not be started or did not become healthy."""


def _headroom_launcher() -> list[str]:
    """The command prefix that runs the headroom CLI.

    Prefer the `headroom` console script when it's on PATH (e.g. inside the uv
    venv); otherwise fall back to invoking its entry point through the current
    interpreter, so it works even when the script dir isn't exported. Raises
    HeadroomError with an install hint when neither is available.
    """
    exe = shutil.which("headroom")
    if exe:
        return [exe]
    if importlib.util.find_spec("headroom") is not None:
        return [sys.executable, "-c", "import sys; from headroom.cli import main; sys.exit(main())"]
    raise HeadroomError(
        "the `headroom` command was not found. Install it with:\n"
        '  uv add "headroom-ai[proxy]"   (or)   pip install "headroom-ai[proxy]"'
    )


def proxy_enabled() -> bool:
    """True unless HEADROOM is explicitly set to a falsey value.

    Routing is on by default; disable it with HEADROOM=0 (or false/no/off).
    """
    val = os.environ.get("HEADROOM")
    if val is None:
        return True
    return val.strip().lower() not in {"0", "false", "no", "off"}


def proxy_host() -> str:
    return os.environ.get("HEADROOM_HOST", "127.0.0.1").strip() or "127.0.0.1"


def proxy_port() -> int:
    raw = os.environ.get("HEADROOM_PORT", "8787").strip()
    try:
        return int(raw)
    except ValueError:
        return 8787


def proxy_mode() -> str:
    """Headroom's optimization strategy: `token` (default) or `cache`."""
    mode = os.environ.get("HEADROOM_MODE", "token").strip().lower()
    return mode if mode in {"token", "cache"} else "token"


def _client_host() -> str:
    """The host a local client should dial. 0.0.0.0 means "all interfaces" to the
    server, but a client must connect to a concrete address."""
    host = proxy_host()
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def _base_url() -> str:
    """OpenAI-compatible endpoint the client points at."""
    return f"http://{_client_host()}:{proxy_port()}/v1"


def proxy_base_url() -> str | None:
    """The proxy's OpenAI base URL while it's active, else None (route direct)."""
    return _ACTIVE_BASE_URL


def _local_upstream() -> str:
    """LOCAL_LLM_URL with a trailing /v1 removed — the proxy re-appends the path
    itself when forwarding (it POSTs to `{upstream}/v1/chat/completions`)."""
    url = os.environ.get("LOCAL_LLM_URL", "http://localhost:1234/v1").strip()
    if url.endswith("/v1"):
        return url[: -len("/v1")]
    return url.rstrip("/")


# Provider prefix -> how to route it: the env the proxy needs to reach the upstream
# and the API key the client sends (which the proxy forwards on). deepseek and
# openrouter are OpenAI-compatible, so all three route through the same
# OPENAI_TARGET_API_URL passthrough. Providers absent here can't be routed and
# run direct.
def _provider_config(spec: str) -> dict | None:
    if spec.startswith("local:"):
        return {
            "prefix": "local:",
            "env": {"OPENAI_TARGET_API_URL": _local_upstream()},
            "api_key": "local",
        }
    if spec.startswith("deepseek:"):
        return {
            "prefix": "deepseek:",
            "env": {"OPENAI_TARGET_API_URL": "https://api.deepseek.com"},
            "api_key": os.environ.get("DEEPSEEK_API_KEY", "none"),
        }
    if spec.startswith("openrouter:"):
        return {
            "prefix": "openrouter:",
            "env": {"OPENAI_TARGET_API_URL": "https://openrouter.ai/api"},
            "api_key": os.environ.get("OPENROUTER_API_KEY", "none"),
        }
    return None


def proxy_api_key_for(spec: str) -> str | None:
    """The key the client should send for `spec` (the proxy forwards it upstream)."""
    cfg = _provider_config(spec)
    return cfg["api_key"] if cfg else None


@dataclass
class ProxyStatus:
    """Outcome of ensure(): whether traffic is now routed, and why/how."""

    active: bool
    external: bool = False  # reusing a proxy we didn't start
    reason: str = ""


class ProxyManager:
    """Owns at most one `headroom proxy` subprocess and the module's active state.

    ensure(spec) makes the proxy ready for a model's provider (starting or
    restarting as needed); stop() tears down only a process we launched.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None  # the process we own, if any
        self._provider: str | None = None           # prefix the running proxy serves
        self._external = False                       # reusing someone else's proxy

    def ensure(self, spec: str) -> ProxyStatus:
        """Route `spec` through the proxy. Returns the resulting status.

        Raises HeadroomError if starting our own proxy fails; callers decide
        whether to surface it and keep running direct.
        """
        global _ACTIVE_BASE_URL, _ACTIVE_SPEC

        cfg = _provider_config(spec)
        if cfg is None:
            # No routable upstream for this provider — fall back to a direct run.
            self.stop()
            _ACTIVE_BASE_URL = None
            _ACTIVE_SPEC = None
            return ProxyStatus(
                active=False,
                reason=f"{spec} has no Headroom upstream — running without the proxy",
            )

        prefix = cfg["prefix"]

        # Already serving this provider from a process we own and it's healthy.
        if self._proc is not None and self._provider == prefix and self._healthy():
            _ACTIVE_BASE_URL, _ACTIVE_SPEC = _base_url(), spec
            return ProxyStatus(active=True)

        # A proxy is already listening that we didn't start: reuse, never manage it.
        if self._proc is None and self._healthy():
            self._external = True
            self._provider = prefix
            _ACTIVE_BASE_URL, _ACTIVE_SPEC = _base_url(), spec
            return ProxyStatus(
                active=True,
                external=True,
                reason=(
                    "reusing a Headroom proxy already on "
                    f"{_client_host()}:{proxy_port()} — its upstream may not match {prefix[:-1]}"
                ),
            )

        # (Re)start our own proxy with this provider's upstream.
        self._stop_owned()
        self._spawn(cfg)
        if not self._wait_healthy():
            self._stop_owned()
            _ACTIVE_BASE_URL = None
            _ACTIVE_SPEC = None
            raise HeadroomError(
                f"the proxy did not become healthy on {_client_host()}:{proxy_port()}"
            )
        self._provider = prefix
        self._external = False
        _ACTIVE_BASE_URL, _ACTIVE_SPEC = _base_url(), spec
        return ProxyStatus(active=True)

    def stop(self) -> None:
        """Stop the proxy we started (a reused external one is left running)."""
        global _ACTIVE_BASE_URL, _ACTIVE_SPEC
        self._stop_owned()
        self._external = False
        self._provider = None
        _ACTIVE_BASE_URL = None
        _ACTIVE_SPEC = None

    def _spawn(self, cfg: dict) -> None:
        env = os.environ.copy()
        env.update(cfg["env"])
        cmd = [
            *_headroom_launcher(),
            "proxy",
            "--host",
            proxy_host(),
            "--port",
            str(proxy_port()),
            "--mode",
            proxy_mode(),
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # shield it from the CLI's Ctrl-C
            )
        except FileNotFoundError as exc:
            raise HeadroomError(
                "the `headroom` command was not found. Install it with:\n"
                '  uv add "headroom-ai[proxy]"   (or)   pip install "headroom-ai[proxy]"'
            ) from exc

    def _stop_owned(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        if proc.poll() is not None:  # already exited
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def _healthy(self) -> bool:
        """True when GET /health returns 200 on the configured host:port."""
        url = f"http://{_client_host()}:{proxy_port()}/health"
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310 - localhost only
                return resp.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _wait_healthy(self, timeout: float = 30.0) -> bool:
        """Poll /health until healthy or `timeout` seconds elapse."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                return False  # process died while starting
            if self._healthy():
                return True
            time.sleep(0.3)
        return False
