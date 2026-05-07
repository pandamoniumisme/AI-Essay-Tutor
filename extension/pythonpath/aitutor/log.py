"""Rotating-file logger for the extension.

LibreOffice swallows stdout/stderr on Windows when launched normally (no
console attached), so a file log is the only way to see what the extension
is doing. Logs land next to the AI server's logs in %APPDATA%\\AIEssayTutor.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_CONFIGURED = False


def _appdata() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "AIEssayTutor"
    return Path.home() / ".config" / "AIEssayTutor"


LOG_FILE = _appdata() / "extension.log"


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
