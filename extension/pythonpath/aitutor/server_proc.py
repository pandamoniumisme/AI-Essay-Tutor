"""Auto-spawn the AI server subprocess if it isn't already running.

The extension calls :func:`ensure_server` before any HTTP call. If the
``port.txt`` file is stale (server was killed) we start a new one and wait
for /healthz to respond, up to 60 seconds. The server's bootstrap_server.ps1
must have been run beforehand to create the venv.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from aitutor import client
from aitutor.log import get_logger

log = get_logger(__name__)


CREATE_NO_WINDOW = 0x08000000  # subprocess flag: hide the console on Windows


def _localappdata() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AIEssayTutor"
    return Path.home() / ".local" / "share" / "AIEssayTutor"


VENV_PYTHON: Path = _localappdata() / "venv" / "Scripts" / "python.exe"


class ServerNotInstalled(RuntimeError):
    """Raised when the AI server venv is missing -- user must run bootstrap."""


class ServerStartupTimeout(RuntimeError):
    """Raised when /healthz does not respond within the launch budget."""


def ensure_server(timeout: float = 60.0) -> str:
    """Make sure the server is running. Returns its base URL (e.g. ``http://127.0.0.1:8765``).

    If the server is already alive (port file exists and /healthz responds),
    returns immediately. Otherwise launches it via the venv's python.exe.
    """
    if _alive():
        url = client.base_url()
        log.info("server already alive at %s", url)
        return url

    if not VENV_PYTHON.exists():
        raise ServerNotInstalled(
            f"AI server venv missing at {VENV_PYTHON}.\n"
            "Run scripts\\bootstrap_server.ps1 from the AI Essay Tutor repo first."
        )

    # Stale port file means the previous server crashed; remove it.
    client.PORT_FILE.unlink(missing_ok=True)

    log.info("spawning server: %s -m aitutor_server.main", VENV_PYTHON)
    subprocess.Popen(
        [str(VENV_PYTHON), "-m", "aitutor_server.main"],
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(_localappdata()),
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _alive():
            url = client.base_url()
            log.info("server up at %s", url)
            return url
        time.sleep(0.5)

    raise ServerStartupTimeout(
        f"Server did not respond on /healthz within {timeout}s.\n"
        f"Check %APPDATA%\\AIEssayTutor\\server.log for the failure."
    )


def _alive() -> bool:
    return client.healthz(timeout=0.7) is not None
