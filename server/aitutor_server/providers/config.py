"""Online provider configuration.

Two interchangeable online backends, both reached over an OpenAI-compatible
endpoint (so a single client implementation serves both):

  - gemini    : Google Gemini (default gemini-3.5-flash)
  - dashscope : Alibaba Cloud Model Studio / Qwen (default qwen3.5-flash)

Select with AITUTOR_PROVIDER=gemini|dashscope (default gemini). Keys come from
the provider's env var(s), falling back to config.json. Model ids are
overridable per provider without a code change.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from aitutor_server.paths import CONFIG_FILE


class MissingApiKey(RuntimeError):
    """Raised when the active provider has no API key configured."""


# name -> settings. ``structured`` is how this endpoint enforces JSON output:
# Gemini's OpenAI layer supports json_schema; Qwen uses json_object.
PROVIDERS: dict[str, dict] = {
    "gemini": {
        "label": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "config_key": "gemini_api_key",
        "default_model": "gemini-3.5-flash",
        "model_env": "AITUTOR_GEMINI_MODEL",
        "structured": "json_schema",
    },
    "dashscope": {
        "label": "Alibaba Cloud (Qwen)",
        # Singapore (international) region. Use dashscope.aliyuncs.com for Beijing.
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "key_env": ("DASHSCOPE_API_KEY",),
        "config_key": "dashscope_api_key",
        "default_model": "qwen3.5-flash",
        "model_env": "AITUTOR_DASHSCOPE_MODEL",
        "structured": "json_object",
    },
}


def _load_dotenv_once() -> None:
    """Load .env from the working dir into the environment (no override). Keeps
    the 'put keys in .env and run' path working with no extra dependency."""
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
    _load_dotenv_once()
    name = os.environ.get("AITUTOR_PROVIDER", "gemini").lower()
    return name if name in PROVIDERS else "gemini"


def settings() -> dict:
    return PROVIDERS[active_name()]


def model() -> str:
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
