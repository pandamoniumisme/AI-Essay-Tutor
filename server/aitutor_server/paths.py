"""Filesystem paths for the app.

Inference runs against a local Ollama server, so there is no model tree to
download. We keep a data dir for the log file, the optional ``config.json``,
and the persisted sessions (SQLite + per-session image folders) that let a
graded essay be picked up from another device on the tailnet.

The data dir is ``$AITUTOR_DATA_DIR`` when set (the systemd service points this
at a stable spot), else ``$APPDATA/AIEssayTutor`` on Windows, else
``~/.local/share/AIEssayTutor``.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "AIEssayTutor"


def _data_dir() -> Path:
    override = os.environ.get("AITUTOR_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


APPDATA_DIR: Path = _data_dir()

LOG_FILE: Path = APPDATA_DIR / "server.log"
CONFIG_FILE: Path = APPDATA_DIR / "config.json"
SESSIONS_DIR: Path = APPDATA_DIR / "sessions"
SESSIONS_DB: Path = APPDATA_DIR / "sessions.db"


def ensure_dirs() -> None:
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
