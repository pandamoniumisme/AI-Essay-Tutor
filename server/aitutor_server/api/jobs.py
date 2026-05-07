"""Async job queue.

Single-user, single-process; in-memory state only. Restarting the server loses
any in-flight jobs (acceptable for this dev install).

Pattern:
    POST /jobs/transcribe   -> {"job_id": "..."}    (returns immediately)
    GET  /jobs/{id}          -> {status, progress, message, result, error}

The client polls /jobs/{id} every few seconds. ``status`` cycles through
``pending`` -> ``running`` -> (``done`` | ``error``); ``result`` is populated
with the full TranscribeResponse on ``done``.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from aitutor_server.api import transcribe as transcribe_api
from aitutor_server.api.grade import do_grade
from aitutor_server.api.schemas import GradeRequest
from aitutor_server.api.transcribe import LangHint, decode_uploads, do_transcribe

log = logging.getLogger(__name__)
router = APIRouter()


JobStatus = Literal["pending", "running", "done", "error"]

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_MAX_RETAINED = 16  # garbage-collect oldest finished jobs once we hit this many

# A single global "is a job running" gate. The ML stack (PaddleOCR + Qwen2.5-VL
# captioner + LLM grader) keeps mutable state inside a single process and
# competes for the GIL during inference; running two jobs concurrently
# deadlocks the model-pipeline locks. We serialise by refusing to start a new
# job while another is in flight. The extension surfaces the resulting 409 to
# the user as a friendly "wait for the current job" message.
_RUNNING_JOB_ID: str | None = None


def _set(job_id: str, **kwargs) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(kwargs)


def _get(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        return dict(_JOBS[job_id]) if job_id in _JOBS else None


def _gc_old_jobs() -> None:
    """Trim _JOBS to the most recent _MAX_RETAINED entries, prioritising
    keep-running and dropping done/error ones first."""
    with _LOCK:
        if len(_JOBS) <= _MAX_RETAINED:
            return
        finished = [
            (j["created"], jid) for jid, j in _JOBS.items()
            if j["status"] in ("done", "error")
        ]
        finished.sort()  # oldest first
        for _, jid in finished[: len(_JOBS) - _MAX_RETAINED]:
            _JOBS.pop(jid, None)


@router.post("/jobs/transcribe")
async def start_transcribe_job(
    question_images: list[UploadFile] = File(...),
    essay_images: list[UploadFile] = File(...),
    language: LangHint = Form("auto"),
) -> dict:
    """Queue a transcribe job. Returns ``{"job_id": "..."}`` immediately;
    the heavy OCR + captioner work happens in a background thread.

    Only one transcribe runs at a time. If another is already in flight, this
    endpoint returns 409 Conflict with the running job's id."""
    global _RUNNING_JOB_ID
    with _LOCK:
        if _RUNNING_JOB_ID is not None:
            existing = _JOBS.get(_RUNNING_JOB_ID)
            log.info("rejected new job: %s already running", _RUNNING_JOB_ID)
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "another transcribe job is in progress; wait or cancel it",
                    "running_job_id": _RUNNING_JOB_ID,
                    "running_job": existing,
                },
            )

    # Read uploads NOW -- the request body is consumed when this returns.
    question_imgs = decode_uploads(question_images, "question_images")
    essay_imgs = decode_uploads(essay_images, "essay_images")

    job_id = secrets.token_hex(8)
    with _LOCK:
        _RUNNING_JOB_ID = job_id
        _JOBS[job_id] = {
            "id": job_id,
            "status": "pending",
            "progress": 0.0,
            "message": "queued",
            "result": None,
            "error": None,
            "created": time.time(),
            "started": None,
            "finished": None,
        }

    log.info("job %s queued (lang=%s, q=%d, e=%d)",
             job_id, language, len(question_imgs), len(essay_imgs))
    threading.Thread(
        target=_run,
        args=(job_id, question_imgs, essay_imgs, language),
        daemon=True,
        name=f"transcribe-{job_id}",
    ).start()

    _gc_old_jobs()
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = _get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found (may have been GC'd)")
    return job


def _run(job_id: str, question_imgs, essay_imgs, language) -> None:
    """Background thread body for /jobs/transcribe."""
    _run_generic(
        job_id,
        lambda progress: do_transcribe(question_imgs, essay_imgs, language, on_progress=progress),
    )


def _run_generic(job_id: str, work) -> None:
    """Common machinery for any background job: status updates, progress
    callback, error handling, releasing the serial-job gate at the end."""
    global _RUNNING_JOB_ID
    _set(job_id, status="running", started=time.time(), message="starting")

    def progress(message: str, fraction: float) -> None:
        _set(job_id, message=message, progress=fraction)
        log.info("job %s: %.0f%% %s", job_id, fraction * 100, message)

    try:
        try:
            response = work(progress)
        except Exception as e:
            log.exception("job %s failed", job_id)
            _set(job_id, status="error", error=str(e),
                 message=f"failed: {e!s}", finished=time.time())
            return

        _set(
            job_id,
            status="done",
            progress=1.0,
            message="done",
            result=response.model_dump() if hasattr(response, "model_dump") else response,
            finished=time.time(),
        )
        log.info("job %s done", job_id)
    finally:
        with _LOCK:
            if _RUNNING_JOB_ID == job_id:
                _RUNNING_JOB_ID = None


# --- /jobs/grade ---------------------------------------------------------

@router.post("/jobs/grade")
async def start_grade_job(req: GradeRequest) -> dict:
    """Queue a grade job. Same serial gate as transcribe -- only one ML job
    runs at a time on this 16 GB system."""
    global _RUNNING_JOB_ID
    with _LOCK:
        if _RUNNING_JOB_ID is not None:
            existing = _JOBS.get(_RUNNING_JOB_ID)
            log.info("rejected grade job: %s already running", _RUNNING_JOB_ID)
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "another job is in progress; wait or cancel it",
                    "running_job_id": _RUNNING_JOB_ID,
                    "running_job": existing,
                },
            )

    job_id = secrets.token_hex(8)
    with _LOCK:
        _RUNNING_JOB_ID = job_id
        _JOBS[job_id] = {
            "id": job_id,
            "kind": "grade",
            "status": "pending",
            "progress": 0.0,
            "message": "queued",
            "result": None,
            "error": None,
            "created": time.time(),
            "started": None,
            "finished": None,
        }

    log.info("job %s queued (kind=grade, lang=%s, paper=%s)",
             job_id, req.language, req.paper_type)
    threading.Thread(
        target=_run_generic,
        args=(job_id, lambda progress: do_grade(req, on_progress=progress)),
        daemon=True,
        name=f"grade-{job_id}",
    ).start()

    _gc_old_jobs()
    return {"job_id": job_id}
