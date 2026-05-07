"""Logging setup. Writes to a rotating file in %APPDATA%\\AIEssayTutor\\server.log
plus stderr (visible only when the server is started in a console — the auto-spawn path
hides its console via CREATE_NO_WINDOW)."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from aitutor_server.models.paths import LOG_FILE, ensure_dirs

_CONFIGURED = False


def setup_logging(level: str | int | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    ensure_dirs()

    if level is None:
        level = os.environ.get("AITUTOR_LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = level.upper()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)

    # Quiet down chatty libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)

    _CONFIGURED = True
