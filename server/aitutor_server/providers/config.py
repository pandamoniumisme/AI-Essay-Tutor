"""Inference backend configuration.

A single backend: the **local Ollama server** on the AI box, reached over its
OpenAI-compatible ``/v1`` API. Default model is ``gemma4:26b`` (multimodal: it
does both the OCR/picture-description and the rubric grading). Nothing leaves
the machine — that is the whole point of this build.

Config (all optional; the defaults assume the app runs on the same box as
Ollama):

- ``AITUTOR_OLLAMA_URL`` / ``OLLAMA_BASE_URL`` — OpenAI-compatible base URL
  (default ``http://127.0.0.1:11434/v1``).
- ``AITUTOR_MODEL`` — model tag (default ``gemma4:26b``).

Ollama needs no API key; the OpenAI SDK still wants a non-empty string, so we
pass a placeholder.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "gemma4:26b"
PLACEHOLDER_KEY = "ollama"  # Ollama ignores it; the OpenAI SDK requires non-empty.


def _load_dotenv_once() -> None:
    """Load .env from the working dir into the environment (no override)."""
    if getattr(_load_dotenv_once, "_done", False):
        return
    _load_dotenv_once._done = True  # type: ignore[attr-defined]
    path = Path.cwd() / ".env"
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


def base_url() -> str:
    _load_dotenv_once()
    return (os.environ.get("AITUTOR_OLLAMA_URL")
            or os.environ.get("OLLAMA_BASE_URL")
            or DEFAULT_BASE_URL).rstrip("/")


def model() -> str:
    _load_dotenv_once()
    return os.environ.get("AITUTOR_MODEL", DEFAULT_MODEL)


def api_key() -> str:
    return PLACEHOLDER_KEY


def reachable() -> bool:
    """Quick liveness probe against the OpenAI-compatible ``/models`` endpoint."""
    try:
        with urllib.request.urlopen(f"{base_url()}/models", timeout=2) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def health() -> dict:
    return {
        "ok": True,
        "backend": "ollama",
        "base_url": base_url(),
        "model": model(),
        "reachable": reachable(),
    }
