"""Online provider configuration.

A single online backend: **Hugging Face Inference Providers**, reached over its
OpenAI-compatible router. Default model is Qwen3.5-9B.

Key from ``HF_TOKEN`` (or ``HUGGINGFACE_API_KEY``), falling back to
``hf_token`` in config.json. Model overridable via ``AITUTOR_HF_MODEL`` (e.g.
append ``:cheapest`` or a ``:provider`` suffix to pick routing).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from aitutor_server.paths import CONFIG_FILE


class MissingApiKey(RuntimeError):
    """Raised when the active provider has no API key configured."""


# ``structured`` = how JSON grade output is constrained. HF routes to many
# providers with mixed response_format support, so we force nothing ("none")
# and rely on the prompt + lenient parse/validate.
PROVIDERS: dict[str, dict] = {
    "huggingface": {
        "label": "Hugging Face",
        "base_url": "https://router.huggingface.co/v1",
        "key_env": ("HF_TOKEN", "HUGGINGFACE_API_KEY"),
        "config_key": "hf_token",
        "default_model": "Qwen/Qwen3.5-9B",
        "model_env": "AITUTOR_HF_MODEL",
        "structured": "none",
    },
}


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


def active_name() -> str:
    return "huggingface"


def settings() -> dict:
    return PROVIDERS[active_name()]


def model() -> str:
    _load_dotenv_once()
    s = settings()
    return os.environ.get(s["model_env"], s["default_model"])


def api_key() -> str | None:
    _load_dotenv_once()
    s = settings()
    for env in s["key_env"]:
        v = os.environ.get(env)
        if v and v.strip():
            return v.strip()
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        v = cfg.get(s["config_key"])
        return v.strip() if isinstance(v, str) and v.strip() else None
    except (OSError, json.JSONDecodeError):
        return None


def key_present() -> bool:
    return api_key() is not None


def health() -> dict:
    s = settings()
    return {
        "ok": True,
        "provider": active_name(),
        "provider_label": s["label"],
        "model": model(),
        "key_present": key_present(),
    }
