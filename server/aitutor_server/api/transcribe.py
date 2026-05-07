"""POST /transcribe -- runs OCR + visual captioning over the question + essay images.

This endpoint runs **synchronously** -- the request blocks until the work is
done. It is convenient for curl/Postman testing. The LibreOffice extension
uses the **async** variant in ``api.jobs`` (POST /jobs/transcribe + polling
GET /jobs/{id}) to avoid freezing the LO UI.

Both endpoints share the same worker (``do_transcribe``) so the OCR/caption
behaviour is identical.

OCR backend: Qwen2.5-VL-7B-Instruct. We started out using paddleocr but it
hangs on Lunar Lake CPU; the VLM does both jobs (OCR and picture description)
through a single model, eliminates the paddle/paddlex/oneDNN/PIR stack, and
reuses the captioner pipeline that's already loaded.
"""
from __future__ import annotations

import logging
from typing import Callable, Literal

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from aitutor_server.api.schemas import Language, OcrLine, TranscribeResponse
from aitutor_server.ocr import lang_detect
from aitutor_server.vision import captioner

log = logging.getLogger(__name__)
router = APIRouter()

LangHint = Literal["en", "zh-Hans", "auto"]
ProgressCb = Callable[[str, float], None]


# --- Upload helpers (also used by api.jobs) -----------------------------

def decode_upload(upload: UploadFile, name: str) -> np.ndarray:
    """Read an UploadFile into a BGR numpy array. Raises 400 on decode failure.

    After this returns we no longer need the UploadFile -- the numpy array
    holds the decoded pixels in memory, which is what the worker thread
    consumes."""
    raw = upload.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail=f"{name} is empty")
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail=f"{name} could not be decoded as an image")
    return img


def decode_uploads(uploads: list[UploadFile], name: str) -> list[np.ndarray]:
    if not uploads:
        raise HTTPException(status_code=400, detail=f"at least one {name} is required")
    return [decode_upload(u, f"{name}[{i}]") for i, u in enumerate(uploads)]


# --- Worker (shared between sync /transcribe and async /jobs/transcribe) -

def _noop(_msg: str, _progress: float) -> None:
    pass


def do_transcribe(
    question_imgs: list[np.ndarray],
    essay_imgs: list[np.ndarray],
    language: LangHint,
    on_progress: ProgressCb = _noop,
) -> TranscribeResponse:
    """Run the full transcribe pipeline over already-decoded images using
    Qwen2.5-VL-7B for both OCR and picture description.

    The VLM is loaded once on first call (lazy, ~30-60s cold start on iGPU),
    then reused. Each subsequent inference is ~10-20 seconds per page on the
    226V at 2400px max long edge.

    Phases (with progress fractions):
      0.05  language detect    (zh-Hans only when language='auto')
      0.10  transcribe essay page 1/N
      0.10 + 0.6*(i/N)  transcribe essay page i/N
      0.70  transcribe question (printed text + picture descriptions, one VLM call per page)
      0.95  finalising
    """
    final_lang: Language = _resolve_language(language, essay_imgs, on_progress)

    n_essay = len(essay_imgs)

    def _essay_progress(done: int, total: int) -> None:
        # Map essay pages to 0.10 -> 0.70 of total progress.
        frac = 0.10 + 0.60 * (done / max(total, 1))
        on_progress(f"transcribing essay (page {done}/{total})", frac)

    on_progress(f"transcribing essay page 1/{n_essay}", 0.10)
    essay_text = captioner.transcribe_essay_pages(
        essay_imgs, final_lang, on_page=_essay_progress,
    )

    on_progress("transcribing question + describing pictures", 0.75)
    question_text = captioner.transcribe_question_pages(question_imgs, final_lang)

    on_progress("finalising", 0.95)

    # We no longer have per-line bboxes (VLM doesn't expose them). Synthesize
    # a single OcrLine per non-empty essay line so the response shape stays
    # backwards compatible. Confidence is set to 1.0 as a placeholder -- the
    # user-correction step in Writer is the real safety net.
    essay_lines = [
        OcrLine(text=line, confidence=1.0, bbox=(0, 0, 0, 0))
        for line in essay_text.splitlines()
        if line.strip()
    ]

    return TranscribeResponse(
        language=final_lang,
        confidence=1.0 if essay_lines else 0.0,
        question_text=question_text,
        essay_text=essay_text,
        essay_lines=essay_lines,
    )


def _resolve_language(language: LangHint, essay_imgs: list[np.ndarray],
                      on_progress: ProgressCb) -> Language:
    """If user picked the language explicitly, return it. Otherwise sniff the
    first essay page using a quick zh-Hans transcription pass and inspect the
    Unicode ranges of the result. We only do this for 'auto' -- the LO
    extension always sends an explicit en/zh-Hans, so this path is rarely hit."""
    if language != "auto":
        return language
    on_progress("detecting language", 0.05)
    sample = captioner.transcribe_essay_page(essay_imgs[0], "zh-Hans")
    return lang_detect.detect_language(sample)


# --- Sync endpoint (curl-friendly) --------------------------------------

@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    question_images: list[UploadFile] = File(...),
    essay_images: list[UploadFile] = File(...),
    language: LangHint = Form("auto"),
) -> TranscribeResponse:
    log.info("/transcribe (sync): lang=%s question=%d essay=%d",
             language, len(question_images), len(essay_images))
    question_imgs = decode_uploads(question_images, "question_images")
    essay_imgs = decode_uploads(essay_images, "essay_images")
    return do_transcribe(question_imgs, essay_imgs, language)


# --- Question-text assembly (also used by api.jobs) ---------------------

# NOTE: question_text now comes verbatim from the VLM, which is prompted to
# output two clearly delimited sections (=== Prompt === and === Pictures ===).
# We no longer post-process or reformat it -- the grader sees what the VLM saw.
