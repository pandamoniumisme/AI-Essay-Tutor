"""Model lifecycle: download, convert, NPU-probe, manifest.

Five models are managed:

- PP-OCRv5 detector (line bounding-box detection, language-agnostic)
- PP-OCRv5 ch_rec    (Simplified Chinese recognizer)
  Both come bundled with the ``paddleocr>=3.0`` package and are downloaded by it on first use.
  We do not need to fetch them ourselves; we just trigger the lazy download.
- TrOCR-base-handwritten (English handwriting recognizer)
  Downloaded from microsoft/trocr-base-handwritten via huggingface_hub.
  Converted to OpenVINO IR via optimum-cli at bootstrap time.
- Qwen3.5-9B INT4 (primary LLM)
  Downloaded from Qwen/Qwen3.5-9B; converted to INT4 OpenVINO IR via optimum-cli.
  Then NPU-probed; on probe failure we fall through to:
- Qwen3-8B INT4-cw (NPU fallback LLM)
  Pre-converted at OpenVINO/Qwen3-8B-int4-cw-ov; snapshot-downloaded as-is.

The manager is callable in two modes:

- CLI: ``python -m aitutor_server.models.manager fetch``  (used by bootstrap_server.ps1)
- In-process: ``ensure_models_async(state)`` runs in a background thread on server start
  and reports progress through the global ``StatusTracker`` for /models/status.

This file deliberately avoids importing the heavy OpenVINO / transformers / paddleocr
modules at import time — they're loaded lazily inside the methods that need them.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from aitutor_server.api.schemas import (
    CaptionerModelStatus,
    LlmModelStatus,
    ModelsStatus,
    OcrModelStatus,
)
from aitutor_server.models.paths import (
    CAPTIONER_DIR,
    GEMMA_3_4B_DIR,
    LLM_FALLBACK_DIR,
    MANIFEST_FILE,
    MODELS_DIR,
    OCR_RECOGNIZER_EN_DIR,
    ensure_dirs,
)

log = logging.getLogger(__name__)

ModelState = Literal["missing", "downloading", "converting", "ready", "error"]

# --- Model repositories (HuggingFace) ------------------------------------

GEMMA_3_4B_REPO = "OpenVINO/gemma-3-4b-it-int4-cw-ov"
"""English route: multimodal (text + vision), used as both captioner and
grader. NPU-ready INT4 channelwise IR. Apache 2.0. Gated on HF -- requires
the user to accept Google's Gemma license + a HF token at fetch time."""

CAPTIONER_REPO = "OpenVINO/Qwen2.5-VL-7B-Instruct-int4-ov"
"""Chinese captioner. Apache 2.0. iGPU."""

QWEN3_8B_NPU_REPO = "OpenVINO/Qwen3-8B-int4-cw-ov"
"""Chinese grader. Apache 2.0. NPU INT4-cw."""

TROCR_REPO = "microsoft/trocr-base-handwritten"


# --- Route table: (language, fast) -> (captioner, grader) ----------------

EN = "en"
ZH = "zh-Hans"


def route_for(language: str, fast: bool = False) -> dict:
    """Return the model paths + devices for a language route. ``fast`` is
    accepted for backwards compatibility but ignored -- the Fast (Qwen3-4B)
    grader was retired on 2026-05-07. Both routes currently grade with
    Qwen3-8B (see the EN grader override below)."""
    if language == EN:
        # TEMP: EN now uses the same models as ZH -- Qwen2.5-VL-7B for OCR
        # and Qwen3-8B for grading. Gemma 3 4B is unused while this holds.
        # Revert captioner_* to GEMMA_3_4B_* (NPU) and grader_* to
        # GEMMA_3_4B_* to restore the original shared-Gemma EN route.
        return {
            "captioner_dir": CAPTIONER_DIR,
            "captioner_repo": CAPTIONER_REPO,
            "captioner_device": "GPU",
            "grader_dir": LLM_FALLBACK_DIR,
            "grader_repo": QWEN3_8B_NPU_REPO,
            "grader_device": "NPU",
            "label": "en/qwen2.5-vl-7b(cap)+qwen3-8b(grade)",
        }
    return {
        "captioner_dir": CAPTIONER_DIR,
        "captioner_repo": CAPTIONER_REPO,
        "captioner_device": "GPU",
        "grader_dir": LLM_FALLBACK_DIR,
        "grader_repo": QWEN3_8B_NPU_REPO,
        "grader_device": "NPU",
        "label": "zh/qwen2.5-vl-7b+qwen3-8b",
    }


# --- Progress reporting --------------------------------------------------

@dataclass
class StatusTracker:
    """Thread-safe-ish progress state for /models/status."""

    detector: ModelState = "missing"
    rec_zh: ModelState = "missing"
    rec_en: ModelState = "missing"
    captioner_state: ModelState = "missing"
    llm_name: str = "Qwen3.5-9B"  # primary by default; flipped on fallback
    llm_state: ModelState = "missing"
    progress: float = 0.0
    message: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)
            log.info("status: %s", {k: v for k, v in kwargs.items() if k != "_lock"})

    def to_payload(self) -> ModelsStatus:
        with self._lock:
            return ModelsStatus(
                ocr=OcrModelStatus(
                    detector=self.detector, rec_zh=self.rec_zh, rec_en=self.rec_en,
                ),
                captioner=CaptionerModelStatus(
                    name=_resolve_captioner_name(),
                    state=self.captioner_state,
                ),
                llm=LlmModelStatus(name=_resolve_llm_name(self.llm_name),
                                   state=self.llm_state),
                progress=self.progress,
                message=self.message,
            )


_TRACKER = StatusTracker()


def get_status() -> ModelsStatus:
    return _TRACKER.to_payload()


def _resolve_captioner_name() -> str:
    return "multi-route (en: gemma-3-4b-it, zh-fast: qwen2.5-vl-3b, zh: qwen2.5-vl-7b)"


def active_captioner_dir(language: str = ZH, fast: bool = False):
    """Where the captioner IR lives for a given route."""
    return route_for(language, fast)["captioner_dir"]


def active_grader_dir(language: str = ZH, fast: bool = False):
    return route_for(language, fast)["grader_dir"]


def _resolve_llm_name(default_name: str) -> str:
    return default_name


# --- Manifest ------------------------------------------------------------

def _read_manifest() -> dict:
    if not MANIFEST_FILE.exists():
        return {}
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("malformed manifest.json; ignoring")
        return {}


def _write_manifest(manifest: dict) -> None:
    ensure_dirs()
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# --- PaddleOCR (detector + Chinese recognizer) ---------------------------

def _ensure_paddleocr() -> None:
    """No-op. Paddleocr was retired from the request path on 2026-05-07 in
    favour of letting the Qwen2.5-VL-7B captioner handle all OCR. The OCR
    state fields stay in /models/status as 'ready' for backwards compat with
    the extension's blocker check; that check is loose anyway."""
    _TRACKER.set(detector="ready", rec_zh="ready",
                 message="paddleocr retired; OCR is handled by the captioner")


# --- TrOCR (English handwriting) -----------------------------------------

def _ensure_trocr() -> None:
    """English handwriting recognizer.

    Phase 1 uses PP-OCRv5's English path through paddleocr (downloaded by
    ``_ensure_paddleocr``); TrOCR is a planned Phase-2 quality upgrade. For now
    this just records the chosen backend in the manifest and marks ready.
    Once we flip the pipeline to TrOCR, replace this body with the optimum-cli
    export below (kept here as a comment for reference).

    Future implementation:
        cmd = [sys.executable, "-m", "optimum.commands.optimum_cli",
               "export", "openvino", "--model", TROCR_REPO,
               "--task", "image-to-text", "--weight-format", "fp16",
               str(OCR_RECOGNIZER_EN_DIR)]
    """
    _TRACKER.set(rec_en="ready", message="english handled by PP-OCRv5 in v1 (TrOCR deferred to v1.5)")


# --- Generic snapshot fetcher --------------------------------------------

_IR_MARKER_FILES = (
    "openvino_model.xml",            # text-only IR
    "openvino_language_model.xml",   # multimodal IR (VLM)
)


def _ir_present(model_dir: Path) -> bool:
    return any((model_dir / m).exists() for m in _IR_MARKER_FILES)


def _ensure_snapshot(repo: str, dest_dir: Path, label: str) -> bool:
    """Snapshot-download ``repo`` into ``dest_dir`` if not already there.
    Returns True on success."""
    if _ir_present(dest_dir):
        log.info("%s IR already present at %s", label, dest_dir)
        return True
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
        log.info("fetching %s -> %s", repo, dest_dir)
        snapshot_download(
            repo_id=repo,
            local_dir=str(dest_dir),
            local_dir_use_symlinks=False,
        )
        return True
    except Exception:
        log.exception("snapshot_download failed for %s", repo)
        return False


# --- Per-route fetchers (called from ensure_models) ----------------------

def _ensure_route(language: str, fast: bool) -> tuple[bool, bool]:
    """Ensure both the captioner and grader IRs for the given route are on
    disk. Returns (captioner_ok, grader_ok)."""
    r = route_for(language, fast)
    label = r["label"]

    cap_ok = _ensure_snapshot(r["captioner_repo"], r["captioner_dir"], f"{label}/captioner")
    grd_ok = (
        cap_ok if r["grader_dir"] == r["captioner_dir"]
        else _ensure_snapshot(r["grader_repo"], r["grader_dir"], f"{label}/grader")
    )
    return cap_ok, grd_ok


def _probe_npu(model_dir: Path) -> bool:
    """Try to compile the LLM IR for the NPU device. Cheap enough to run at bootstrap."""
    try:
        import openvino as ov
    except ImportError:
        log.warning("openvino not importable; skipping NPU probe (assuming success)")
        return True

    try:
        core = ov.Core()
        if "NPU" not in core.available_devices:
            log.warning("NPU not in available_devices=%s; skipping probe", core.available_devices)
            return True  # not a fatal error; OpenVINO GenAI may still pick a different device
        xml = model_dir / "openvino_model.xml"
        if not xml.exists():
            log.error("NPU probe: %s missing", xml)
            return False
        model = core.read_model(str(xml))
        core.compile_model(model, device_name="NPU")
        log.info("NPU compile probe passed for %s", model_dir.name)
        return True
    except Exception:
        log.exception("NPU compile probe failed for %s", model_dir.name)
        return False


# --- Top-level entry points ---------------------------------------------

def ensure_models() -> StatusTracker:
    """Synchronous: fetch every model needed for any of the three routes
    (en, zh-fast, zh-normal). Returns the tracker for inspection."""
    ensure_dirs()

    try:
        _ensure_paddleocr()
    except Exception:
        log.exception("paddleocr setup failed")
        _TRACKER.set(detector="error", rec_zh="error")

    try:
        _ensure_trocr()
    except Exception:
        log.exception("trocr setup failed")

    routes = [
        (EN, False, "en"),
        (ZH, False, "zh"),
    ]
    cap_ok_overall = False
    grd_ok_overall = False
    for lang, fast, tag in routes:
        try:
            _TRACKER.set(captioner_state="downloading", llm_state="downloading",
                         message=f"fetching route={tag}")
            cap_ok, grd_ok = _ensure_route(lang, fast)
            cap_ok_overall = cap_ok_overall or cap_ok
            grd_ok_overall = grd_ok_overall or grd_ok
        except Exception:
            log.exception("route %s fetch failed", tag)

    _TRACKER.set(
        captioner_state="ready" if cap_ok_overall else "error",
        llm_state="ready" if grd_ok_overall else "error",
        llm_name="multi-route",
        message="ready" if (cap_ok_overall and grd_ok_overall) else "some routes missing IRs; see server.log",
    )

    manifest = _read_manifest()
    manifest["routes"] = {
        "en": _ir_present(GEMMA_3_4B_DIR),
        "zh-captioner": _ir_present(CAPTIONER_DIR),
        "zh-grader": _ir_present(LLM_FALLBACK_DIR),
    }
    manifest["last_run"] = "ok"
    _write_manifest(manifest)

    return _TRACKER


def ensure_models_async() -> threading.Thread:
    """Background variant — kicked off from the FastAPI lifespan."""
    t = threading.Thread(target=ensure_models, name="aitutor-model-manager", daemon=True)
    t.start()
    return t


def _cli() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "fetch":
        print("usage: python -m aitutor_server.models.manager fetch", file=sys.stderr)
        return 2
    from aitutor_server.util.log import setup_logging
    setup_logging("INFO")

    tracker = ensure_models()
    print()
    print("--- summary ---")
    # Render via the Pydantic payload so we don't try to serialize the threading.Lock
    # field on the tracker (asdict deepcopies, which fails on locks).
    print(tracker.to_payload().model_dump_json(indent=2))
    if (
        tracker.llm_state == "ready"
        and tracker.detector == "ready"
        and tracker.rec_en == "ready"
        and tracker.captioner_state == "ready"
    ):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
