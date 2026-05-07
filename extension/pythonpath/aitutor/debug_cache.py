"""On-disk cache of the latest LLM outputs, used by the dialog's "Debug" mode.

Every successful transcribe and grade response is written here. When the
user re-runs Compo Tutor with the Debug checkbox ticked, whichever cached
outputs exist short-circuit the corresponding LLM call so the developer
can iterate on downstream code (e.g. ``writer_ops``) without paying the
30-90 s VLM warm-up + grader inference each time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from aitutor.log import get_logger

log = get_logger(__name__)


def _appdata() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "AIEssayTutor"
    return Path.home() / ".config" / "AIEssayTutor"


DEBUG_DIR: Path = _appdata() / "debug"
TRANSCRIBE_FILE: Path = DEBUG_DIR / "last_transcribe.json"
GRADE_FILE: Path = DEBUG_DIR / "last_grade.json"


def save_transcribe(body: dict) -> None:
    _save(TRANSCRIBE_FILE, body)


def save_grade(body: dict) -> None:
    _save(GRADE_FILE, body)


def load_transcribe() -> dict | None:
    return _load(TRANSCRIBE_FILE)


def load_grade() -> dict | None:
    return _load(GRADE_FILE)


def _save(path: Path, body: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(body, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("debug cache: saved %s (%d bytes)", path.name, path.stat().st_size)
    except Exception:
        log.exception("debug cache: failed to save %s", path)


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("debug cache: failed to read %s; ignoring", path)
        return None
