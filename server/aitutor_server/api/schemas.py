"""Pydantic v2 contracts for the AI server.

Single source of truth for both the FastAPI request/response shapes and the
JSON schema that documents the grader's per-route score caps. Inference goes to
the Hugging Face Inference Providers router over its OpenAI-compatible API; the
grader's ``structured`` mode is ``"none"`` (see ``providers/config.py``), so that
schema is NOT sent on the wire as a ``response_format`` -- it documents/derives
the caps while a lenient parser carries JSON correctness. Keep these in sync with
the plan and ``providers/grader.py``.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

# --- Common --------------------------------------------------------------

Language = Literal["en", "zh-Hans"]
"""Supported essay languages. Traditional Chinese is out of scope for v1."""

PaperType = Literal["situational", "continuous"]
"""English Paper 1 has both Situational (14 marks) and Continuous (36 marks).
Chinese has only one composition format; this field is ignored when language=='zh-Hans'."""

EditCategory = Literal[
    "grammar", "spelling", "punctuation", "word_choice",
    "sentence_structure", "character_error",
]

CommentCategory = Literal[
    "content", "language", "organization", "vocabulary", "ideas", "praise",
]


class OcrLine(BaseModel):
    """One detected line of handwriting after recognition."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    # bbox: [x_top_left, y_top_left, x_bottom_right, y_bottom_right] in source-image pixels.
    bbox: tuple[int, int, int, int]


# --- /transcribe ---------------------------------------------------------

class TranscribeResponse(BaseModel):
    language: Language
    confidence: float = Field(ge=0.0, le=1.0)
    question_text: str
    essay_text: str
    essay_lines: list[OcrLine] = Field(default_factory=list)


# --- /grade --------------------------------------------------------------

class GradeRequest(BaseModel):
    language: Language
    paper_type: PaperType = "continuous"  # ignored for zh-Hans
    question_text: str
    essay_text: Annotated[str, Field(min_length=1, max_length=8000)]
    student_level: Literal["P5", "P6"] = "P6"


class TrackedEdit(BaseModel):
    """A sentence-level correction the LLM proposes; rendered as a Writer redline."""

    original_span: Annotated[str, Field(min_length=1, max_length=200)]
    """Exact substring of essay_text. Server-side validation drops entries
    whose original_span is not a substring of the submitted essay."""
    occurrence_index: int = Field(default=0, ge=0)
    suggested_replacement: Annotated[str, Field(max_length=200)]
    reason: Annotated[str, Field(max_length=160)]
    category: EditCategory


class RubricComment(BaseModel):
    """A higher-level remark anchored to a span, rendered as a Writer Annotation."""

    span: Annotated[str, Field(min_length=1, max_length=400)]
    occurrence_index: int = Field(default=0, ge=0)
    comment_text: Annotated[str, Field(max_length=600)]
    category: CommentCategory


class RubricScores(BaseModel):
    """PSLE rubric. EN continuous: content/18, language/18 (max_total=36).
    EN situational: content/6, language/8 (max_total=14).
    ZH composition:  content/20, language/20 (max_total=40)."""

    content: float = Field(ge=0)
    language: float = Field(ge=0)
    organization: float | None = None  # not part of the official PSLE rubric; reserved for future
    total: float = Field(ge=0)
    max_total: float = Field(gt=0)
    band: int = Field(ge=1, le=5)

    @field_validator("total")
    @classmethod
    def _total_within_max(cls, v: float, info) -> float:
        max_total = info.data.get("max_total")
        if max_total is not None and v > max_total:
            raise ValueError(f"total {v} exceeds max_total {max_total}")
        return v


class GradeResponse(BaseModel):
    scores: RubricScores
    # Round 1: simple corrections (must change text). Rendered as redlines
    # plus an Annotation per edit whose body is the edit's ``reason`` field.
    tracked_edits: list[TrackedEdit] = Field(default_factory=list, max_length=40)
    # Round 2: score-lifting improvements applied to the v1-corrected essay.
    # Each edit's ``reason`` explains *why* the change would lift the score.
    improvement_edits: list[TrackedEdit] = Field(default_factory=list, max_length=20)
    # Predicted total score after applying ONLY the Round 1 mechanical
    # fixes. Falls between scores.total and target_score. Surfaced in the
    # score-report table so the student sees what the Round 1 fixes
    # actually buy them.
    score_after_v1: float | None = Field(default=None, ge=0)
    # Predicted total score after applying both Round 1 and Round 2 edits.
    # Must be >= 32 and <= max_total. The LLM picks based on what's
    # plausibly achievable.
    target_score: float | None = Field(default=None, ge=0)
    # Free-form remarks unattached to any specific edit. No longer required
    # by the prompt; kept optional for backwards-compat / praise comments.
    comments: list[RubricComment] = Field(default_factory=list, max_length=15)
    overall_feedback: Annotated[str, Field(max_length=1200)]
