"""OCR orchestration.

Phase-1 implementation: paddleocr 3.x for both English and Simplified Chinese.
PaddleOCR's ``predict()`` returns line-level results with text, confidence, and
polygon coordinates — we flatten those into ``OcrLine`` instances.

Phase-2 plan: split into detector-only paddleocr → per-line crops →
TrOCR-base-handwritten for English (better on PSLE-level cursive). Hooks for
that exist in ``models/manager.py::_ensure_trocr``; the structure here is
backend-pluggable so swapping in TrOCR is a localized change.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import cv2
import numpy as np

from aitutor_server.api.schemas import Language, OcrLine
from aitutor_server.ocr import preprocess

log = logging.getLogger(__name__)


# --- Lazy paddleocr instances (one per language) -------------------------

_PADDLE_LOCK = threading.Lock()
_PADDLE_INSTANCES: dict[str, Any] = {}


def _get_paddle(lang: Language) -> Any:
    """Return a process-singleton paddleocr OCR instance for the given language.

    Lazy import — paddleocr is heavy and we don't want to pay the import cost
    just to start the FastAPI server. We pin ``ocr_version='PP-OCRv5'`` and pick
    ``lang='ch'`` for Simplified Chinese (PaddleOCR's ``ch`` model is multilingual
    and handles Chinese + ASCII English in mixed essays) or ``lang='en'`` for
    English-only essays.
    """
    key = "ch" if lang == "zh-Hans" else "en"
    with _PADDLE_LOCK:
        if key not in _PADDLE_INSTANCES:
            from paddleocr import PaddleOCR

            log.info("loading PP-OCRv5 (lang=%s)...", key)
            # enable_mkldnn=False avoids paddlepaddle 3.x's PIR/oneDNN incompat.
            # cpu_threads=2 keeps paddle from spawning a giant internal pool
            # that fights with our uvicorn worker for cores and locks.
            # use_doc_orientation_classify / use_doc_unwarping disable the optional
            # doc-preprocessor inference (PP-LCNet doc-ori + UVDoc unwarping)
            # which would add ~5-15s per image. Handwritten student essays
            # come in upright already; not worth the extra inference cost.
            _PADDLE_INSTANCES[key] = PaddleOCR(
                use_textline_orientation=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                lang=key,
                ocr_version="PP-OCRv5",
                enable_mkldnn=False,
                cpu_threads=2,
            )
        return _PADDLE_INSTANCES[key]


# --- Public ---------------------------------------------------------------

ESSAY_MIN_CONFIDENCE = 0.30
"""Don't filter handwriting too aggressively -- low-confidence OCR is
intentionally surfaced so the user can correct it in Writer before grading."""

QUESTION_MIN_CONFIDENCE = 0.60
"""Question images may contain illustrations (PSLE 看图作文 picture composition).
PaddleOCR's detector occasionally finds text-shaped contours inside line drawings;
those produce low-confidence garbage. Drop them before the question text reaches
the LLM, since the user does NOT review/correct the question transcription."""


def transcribe_essay(bgr: np.ndarray, language: Language) -> list[OcrLine]:
    """Preprocess + OCR a handwritten essay photo. Returns ordered top-to-bottom lines."""
    norm = preprocess.normalize_essay(bgr)
    lines = _run_paddleocr(norm, language)
    return [L for L in lines if L.confidence >= ESSAY_MIN_CONFIDENCE]


def transcribe_essays(bgrs: list[np.ndarray], language: Language) -> list[OcrLine]:
    """OCR multiple essay pages, concatenating lines in page order.

    PSLE essays often span 2-3 pages on lined paper. We do not de-duplicate or
    try to merge spillover sentences across page boundaries -- the transcript
    is presented to the user for review/correction in Writer before grading,
    so any concatenation artifacts are easy to fix manually.
    """
    out: list[OcrLine] = []
    for img in bgrs:
        out.extend(transcribe_essay(img, language))
    return out


def transcribe_question(bgr: np.ndarray, language: Language) -> list[OcrLine]:
    """Preprocess + OCR a printed question photo. Filters low-confidence noise that
    typically comes from illustration regions in PSLE picture-composition questions."""
    norm = preprocess.normalize_question(bgr)
    lines = _run_paddleocr(norm, language)
    return [L for L in lines if L.confidence >= QUESTION_MIN_CONFIDENCE]


def transcribe_questions(bgrs: list[np.ndarray], language: Language) -> list[OcrLine]:
    """OCR multiple question pages, concatenating lines in page order."""
    out: list[OcrLine] = []
    for img in bgrs:
        out.extend(transcribe_question(img, language))
    return out


# --- Implementation -------------------------------------------------------

def _run_paddleocr(img: np.ndarray, language: Language) -> list[OcrLine]:
    """Run PP-OCRv5 over a single preprocessed image and return ``OcrLine`` items
    sorted top-to-bottom (then left-to-right within similar y-bands)."""
    if img.ndim == 2:
        # paddleocr expects 3-channel BGR
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    ocr = _get_paddle(language)
    raw = ocr.predict(img)
    if not raw:
        return []

    # paddleocr 3.x returns either a list of result objects or a list-of-lists
    # depending on version. Normalize: walk the structure and pull (poly, text, score).
    flat = _flatten_paddle_result(raw)

    lines: list[OcrLine] = []
    for poly, text, score in flat:
        if not text:
            continue
        bbox = _poly_to_aabb(poly)
        lines.append(OcrLine(text=text, confidence=float(score), bbox=bbox))

    lines.sort(key=lambda L: (L.bbox[1] // 20, L.bbox[0]))  # 20-px y-band tolerance
    return lines


def _flatten_paddle_result(raw: Any) -> list[tuple[list[list[float]], str, float]]:
    """Tolerate paddleocr's two output shapes:

    - 2.x style:  [[ [poly, (text, score)], ... ]]
    - 3.x style:  [{"rec_polys":..., "rec_texts":..., "rec_scores":...}]
    """
    out: list[tuple[list[list[float]], str, float]] = []
    if not raw:
        return out

    first = raw[0] if isinstance(raw, list) else raw
    if isinstance(first, dict) and "rec_texts" in first:
        # 3.x dict style
        polys = first.get("rec_polys") or first.get("dt_polys") or []
        texts = first.get("rec_texts") or []
        scores = first.get("rec_scores") or []
        for poly, text, score in zip(polys, texts, scores, strict=False):
            poly_list = poly.tolist() if hasattr(poly, "tolist") else list(poly)
            out.append((poly_list, text, float(score)))
        return out

    # 2.x list-of-lists style
    page = raw[0] if (isinstance(raw, list) and raw and isinstance(raw[0], list)) else raw
    for entry in page or []:
        try:
            poly, (text, score) = entry
            out.append((poly, text, float(score)))
        except (TypeError, ValueError):
            log.debug("skipping unparseable paddleocr entry: %r", entry)
    return out


def _poly_to_aabb(poly: list[list[float]]) -> tuple[int, int, int, int]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))


def lines_to_text(lines: list[OcrLine]) -> str:
    """Join lines with newlines for the ``essay_text`` field."""
    return "\n".join(L.text for L in lines)


def average_confidence(lines: list[OcrLine]) -> float:
    if not lines:
        return 0.0
    return sum(L.confidence for L in lines) / len(lines)
