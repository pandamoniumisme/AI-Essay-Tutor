"""OpenAI-compatible client for the local Ollama backend (gemma4:26b).

Vision goes through an inline base64 ``image_url`` part; grading asks for a JSON
object via ``response_format`` (Ollama honours ``{"type": "json_object"}``) and
the grader still runs its lenient parse/validate afterwards. Base URL and model
come from config.py.
"""
from __future__ import annotations

import base64
import logging
from functools import lru_cache

from aitutor_server.providers import config

log = logging.getLogger(__name__)

Image = tuple[bytes, str]  # (raw bytes, mime_type)

# Local CPU inference of a 26B model can take a while; don't time out mid-grade.
_TIMEOUT_S = 600


@lru_cache(maxsize=4)
def _client(base_url: str, key: str):
    from openai import OpenAI

    log.info("creating OpenAI-compatible client for base_url=%s", base_url)
    return OpenAI(api_key=key, base_url=base_url, timeout=_TIMEOUT_S)


def _get_client():
    return _client(config.base_url(), config.api_key())


def generate_vision(prompt: str, image: Image, max_tokens: int = 1500) -> str:
    """One multimodal call: a single image + prompt, deterministic."""
    data, mime = image
    b64 = base64.b64encode(data).decode("ascii")
    resp = _get_client().chat.completions.create(
        model=config.model(),
        temperature=0.0,
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return (resp.choices[0].message.content or "").strip()


def generate_text(system: str, user: str, json_schema: dict | None = None,
                  max_tokens: int = 1800) -> str:
    """Text-only call. When ``json_schema`` is given, ask the backend for a JSON
    object (the grader's lenient parser is still the safety net)."""
    kwargs: dict = {}
    if json_schema is not None:
        kwargs["response_format"] = {"type": "json_object"}

    resp = _get_client().chat.completions.create(
        model=config.model(),
        temperature=0.0,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **kwargs,
    )
    return (resp.choices[0].message.content or "").strip()
