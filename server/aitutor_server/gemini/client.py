"""Gemini client + runtime config.

The web build delegates all inference to Google's Gemini API. Two things are
configurable:

- The API key. Resolved from ``GEMINI_API_KEY`` (or ``GOOGLE_API_KEY``) in the
  environment, falling back to ``gemini_api_key`` in
  ``%APPDATA%\\AIEssayTutor\\config.json``. Never commit it.
- The model IDs. ``AITUTOR_TRANSCRIBE_MODEL`` and ``AITUTOR_GRADE_MODEL``.
  Defaults below are deliberately cost-safe (both ``flash``); bump grading to a
  ``pro`` tier if quality demands it. Verify the exact IDs against Google's
  current model list -- the tier names move.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

from aitutor_server.paths import CONFIG_FILE

log = logging.getLogger(__name__)

# Cost-safe defaults. Override via env without a code change.
DEFAULT_TRANSCRIBE_MODEL = "gemini-2.5-flash"
DEFAULT_GRADE_MODEL = "gemini-2.5-flash"


def transcribe_model() -> str:
    return os.environ.get("AITUTOR_TRANSCRIBE_MODEL", DEFAULT_TRANSCRIBE_MODEL)


def grade_model() -> str:
    return os.environ.get("AITUTOR_GRADE_MODEL", DEFAULT_GRADE_MODEL)


def _api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key.strip()
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        val = cfg.get("gemini_api_key")
        return val.strip() if isinstance(val, str) and val.strip() else None
    except (OSError, json.JSONDecodeError):
        return None


def key_present() -> bool:
    return _api_key() is not None


class MissingApiKey(RuntimeError):
    """Raised when a Gemini call is attempted without a configured API key."""


@lru_cache(maxsize=1)
def get_client():
    """Return a cached ``google.genai.Client``. Raises :class:`MissingApiKey`
    if no key is configured so the API layer can surface a friendly 503."""
    key = _api_key()
    if not key:
        raise MissingApiKey(
            "No Gemini API key. Set GEMINI_API_KEY in the environment or add "
            '{"gemini_api_key": "..."} to %APPDATA%\\AIEssayTutor\\config.json.'
        )
    from google import genai

    log.info("creating Gemini client (transcribe=%s, grade=%s)",
             transcribe_model(), grade_model())
    return genai.Client(api_key=key)
