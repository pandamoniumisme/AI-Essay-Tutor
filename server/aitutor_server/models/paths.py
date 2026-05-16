"""Filesystem paths used by the AI server.

Convention follows Windows %APPDATA% / %LOCALAPPDATA% semantics:
- APPDATA (roaming):       small config, port file, pid file, logs.
- LOCALAPPDATA (local):    venv, model cache (multi-GB).
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


def _local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


APPDATA_DIR: Path = _appdata()
LOCAL_DIR: Path = _local_appdata()

PORT_FILE: Path = APPDATA_DIR / "port.txt"
PID_FILE: Path = APPDATA_DIR / "server.pid"
LOG_FILE: Path = APPDATA_DIR / "server.log"
CONFIG_FILE: Path = APPDATA_DIR / "config.json"

VENV_DIR: Path = LOCAL_DIR / "venv"
MODELS_DIR: Path = LOCAL_DIR / "models"
MANIFEST_FILE: Path = MODELS_DIR / "manifest.json"

OCR_DETECTOR_DIR: Path = MODELS_DIR / "ppocrv5_det"
OCR_RECOGNIZER_ZH_DIR: Path = MODELS_DIR / "ppocrv5_rec_ch"
OCR_RECOGNIZER_EN_DIR: Path = MODELS_DIR / "trocr_base_handwritten"

# --- Model dirs by route (language + fast flag) -------------------------
# English (both OCR + grader): Gemma 3 4B-IT, multimodal, NPU.
GEMMA_3_4B_DIR: Path = MODELS_DIR / "gemma_3_4b_it_int4_cw_ov"

# Chinese captioner -- ALWAYS Qwen2.5-VL-7B on iGPU, regardless of the
# Fast checkbox. The previous Qwen2.5-VL-3B-NPU experiment was retired
# 2026-05-07: NPU's VLM MAX_PROMPT_LEN cap forced bigger compile buffers,
# the smaller weights didn't OCR primary-school handwriting reliably, and
# the 7B path on iGPU is already validated.
CAPTIONER_DIR: Path = MODELS_DIR / "qwen2_5_vl_7b_int4_ov"

# Chinese grader: Qwen3-8B, NPU INT4-cw. The earlier Qwen3-4B "Fast" path
# was retired 2026-05-07 -- it produced visibly worse PSLE feedback than the
# 8B and the dialog stopped offering a way to opt into it.
LLM_FALLBACK_DIR: Path = MODELS_DIR / "qwen3_8b_int4_cw"

# Legacy/unused. Kept so the manager doesn't recreate it on every run.
LLM_PRIMARY_DIR: Path = MODELS_DIR / "qwen3_5_9b_int4"


def ensure_dirs() -> None:
    """Create the small-config and model-cache directories if missing."""
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
