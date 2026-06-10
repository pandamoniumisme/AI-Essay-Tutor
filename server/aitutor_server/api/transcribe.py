"""POST /api/transcribe -- OCR + picture description via Gemini.

Synchronous: the browser shows a spinner while this runs. Gemini calls take
seconds (not the minutes the local NPU stack did), so there is no async job
queue anymore.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from aitutor_server.api.schemas import TranscribeResponse
from aitutor_server.gemini import client as gemini_client
from aitutor_server.gemini import transcriber

log = logging.getLogger(__name__)
router = APIRouter()

LangHint = Literal["en", "zh-Hans", "auto"]


def _read_upload(upload: UploadFile, name: str) -> tuple[bytes, str]:
    raw = upload.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail=f"{name} is empty")
    return raw, upload.content_type or "image/jpeg"


def _read_uploads(uploads: list[UploadFile], name: str) -> list[tuple[bytes, str]]:
    if not uploads:
        raise HTTPException(status_code=400, detail=f"at least one {name} is required")
    return [_read_upload(u, f"{name}[{i}]") for i, u in enumerate(uploads)]


@router.post("/api/transcribe", response_model=TranscribeResponse)
async def transcribe(
    question_images: list[UploadFile] = File(...),
    essay_images: list[UploadFile] = File(...),
    language: LangHint = Form("zh-Hans"),
) -> TranscribeResponse:
    log.info("/api/transcribe: lang=%s question=%d essay=%d",
             language, len(question_images), len(essay_images))
    q = _read_uploads(question_images, "question_images")
    e = _read_uploads(essay_images, "essay_images")
    try:
        return transcriber.do_transcribe(q, e, language)
    except gemini_client.MissingApiKey as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
