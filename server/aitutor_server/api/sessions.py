"""Session API: create a grading session, then poll it from any device.

Transcription and grading run as background jobs (see ``sessions.py``); these
endpoints create/inspect/edit sessions and kick the jobs. A session shot on a
phone is graded server-side and picked up on a desktop by listing or opening it.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from aitutor_server import sessions

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions")

LangHint = Literal["en", "zh-Hans", "auto"]
PaperType = Literal["situational", "continuous"]
Role = Literal["question", "essay"]


def _read_uploads(uploads: list[UploadFile], name: str) -> list[tuple[bytes, str]]:
    if not uploads:
        raise HTTPException(status_code=400, detail=f"at least one {name} is required")
    out = []
    for i, u in enumerate(uploads):
        raw = u.file.read()
        if not raw:
            raise HTTPException(status_code=400, detail=f"{name}[{i}] is empty")
        out.append((raw, u.content_type or "image/jpeg"))
    return out


def _require(session_id: str) -> dict:
    s = sessions.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    return s


class TranscriptionPatch(BaseModel):
    question_text: str | None = None
    essay_text: str | None = None


@router.post("")
async def create(
    question_images: list[UploadFile] = File(...),
    essay_images: list[UploadFile] = File(...),
    language: LangHint = Form("zh-Hans"),
    paper_type: PaperType = Form("continuous"),
    student_level: Literal["P5", "P6"] = Form("P6"),
) -> dict:
    q = _read_uploads(question_images, "question_images")
    e = _read_uploads(essay_images, "essay_images")
    session_id = sessions.create_session(language, paper_type, student_level, q, e)
    sessions.enqueue_transcribe(session_id)
    return {"id": session_id, "status": sessions.STATUS_TRANSCRIBING}


@router.get("")
async def list_all() -> dict:
    return {"sessions": sessions.list_sessions()}


@router.get("/{session_id}")
async def get(session_id: str) -> dict:
    return _require(session_id)


@router.patch("/{session_id}")
async def patch(session_id: str, body: TranscriptionPatch) -> dict:
    s = _require(session_id)
    if s["status"] in (sessions.STATUS_TRANSCRIBING, sessions.STATUS_GRADING):
        raise HTTPException(status_code=409, detail="a job is running on this session")
    sessions.update_transcription(
        session_id,
        body.question_text if body.question_text is not None else s["question_text"],
        body.essay_text if body.essay_text is not None else s["essay_text"],
    )
    return _require(session_id)


@router.post("/{session_id}/grade")
async def grade(session_id: str) -> dict:
    s = _require(session_id)
    if s["status"] in (sessions.STATUS_TRANSCRIBING, sessions.STATUS_GRADING):
        raise HTTPException(status_code=409, detail="a job is already running on this session")
    if not (s["essay_text"] or "").strip():
        raise HTTPException(status_code=400, detail="nothing to grade — the essay text is empty")
    sessions.enqueue_grade(session_id)
    return {"id": session_id, "status": sessions.STATUS_GRADING}


@router.post("/{session_id}/retranscribe")
async def retranscribe(session_id: str) -> dict:
    s = _require(session_id)
    if s["status"] in (sessions.STATUS_TRANSCRIBING, sessions.STATUS_GRADING):
        raise HTTPException(status_code=409, detail="a job is already running on this session")
    sessions.enqueue_transcribe(session_id)
    return {"id": session_id, "status": sessions.STATUS_TRANSCRIBING}


@router.delete("/{session_id}")
async def delete(session_id: str) -> dict:
    if not sessions.delete_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": session_id}


@router.get("/{session_id}/images/{role}/{idx}")
async def image(session_id: str, role: Role, idx: int) -> Response:
    img = sessions.image_bytes(session_id, role, idx)
    if img is None:
        raise HTTPException(status_code=404, detail="image not found")
    data, mime = img
    return Response(content=data, media_type=mime)
