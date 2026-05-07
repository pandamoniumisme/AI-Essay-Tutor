"""POST /grade -- run the LLM grader synchronously over the supplied text.

The async variant lives in api/jobs.py (POST /jobs/grade + GET /jobs/{id}).
Both share the same worker (``do_grade``) so behaviour is identical.
"""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter

from aitutor_server.api.schemas import GradeRequest, GradeResponse
from aitutor_server.llm import grader

log = logging.getLogger(__name__)
router = APIRouter()


ProgressCb = Callable[[str, float], None]


def _noop(_msg: str, _progress: float) -> None:
    pass


def do_grade(req: GradeRequest, on_progress: ProgressCb = _noop) -> GradeResponse:
    """Run the grader. on_progress fires at phase boundaries for the async caller."""
    on_progress("loading grader", 0.10)
    # First call to grader.grade() triggers lazy load (~30-60s on first ever
    # use, fast on subsequent uses). The grader.unload() of the captioner
    # happens inside grader._get_pipeline.
    on_progress("grading essay", 0.30)
    response = grader.grade(req)
    on_progress("validating output", 0.95)
    return response


@router.post("/grade", response_model=GradeResponse)
async def grade(req: GradeRequest) -> GradeResponse:
    log.info("/grade (sync): lang=%s paper=%s essay_chars=%d",
             req.language, req.paper_type, len(req.essay_text))
    return do_grade(req)
