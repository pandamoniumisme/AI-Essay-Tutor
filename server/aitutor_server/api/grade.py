"""POST /api/grade -- run the grader over the supplied text."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from aitutor_server.api.schemas import GradeRequest, GradeResponse
from aitutor_server.providers import config, grader

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/grade", response_model=GradeResponse)
async def grade(req: GradeRequest) -> GradeResponse:
    log.info("/api/grade: lang=%s paper=%s essay_chars=%d",
             req.language, req.paper_type, len(req.essay_text))
    try:
        return grader.grade(req)
    except config.MissingApiKey as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
