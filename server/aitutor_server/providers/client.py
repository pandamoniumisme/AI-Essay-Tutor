"""OpenAI-compatible backend for the online provider (Hugging Face / Qwen3.5-9B).

Vision goes through an inline base64 ``image_url`` part; grading optionally uses
``response_format`` per the provider's ``structured`` mode (currently "none" for
HF — we rely on the prompt + lenient parse/validate). Base URL, key, and model
come from config.py.
"""
from __future__ import annotations

import base64
import logging
from functools import lru_cache

from aitutor_server.providers import config

log = logging.getLogger(__name__)

Image = tuple[bytes, str]  # (raw bytes, mime_type)


@lru_cache(maxsize=4)
def _client(name: str, base_url: str, key: str):
    from openai import OpenAI

    log.info("creating OpenAI-compatible client for provider=%s", name)
    return OpenAI(api_key=key, base_url=base_url)


def _get_client():
    key = config.api_key()
    if not key:
        s = config.settings()
        raise config.MissingApiKey(
            f"No API key for provider '{config.active_name()}'. Set "
            f"{'/'.join(s['key_env'])} (or the matching key in config.json)."
        )
    s = config.settings()
    return _client(config.active_name(), s["base_url"], key)


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
    """Text-only call. When ``json_schema`` is given, constrain output to JSON
    using whichever mechanism the active endpoint supports."""
    kwargs: dict = {}
    if json_schema is not None:
        mode = config.settings()["structured"]
        if mode == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "grade_response", "schema": json_schema},
            }
        elif mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        # mode == "none": don't force a response_format; the prompt + lenient
        # parse/validate handle JSON extraction (broadest provider support).

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
