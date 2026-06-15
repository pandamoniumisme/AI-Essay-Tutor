"""Filesystem paths for the local web app.

Small-config only -- the web build no longer downloads multi-GB model IRs, so
the old ``%LOCALAPPDATA%\\AIEssayTutor\\models`` tree is gone. We keep a roaming
config dir for the log file and the optional ``config.json`` that can hold the
Gemini API key.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "AIEssayTutor"


def _appdata() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


APPDATA_DIR: Path = _appdata()

LOG_FILE: Path = APPDATA_DIR / "server.log"
CONFIG_FILE: Path = APPDATA_DIR / "config.json"


def ensure_dirs() -> None:
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
