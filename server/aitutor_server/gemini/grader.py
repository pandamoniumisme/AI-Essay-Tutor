"""LLM grader via Gemini structured output.

Replaces the OpenVINO Qwen3-8B grader. Generation is delegated to Gemini with
a JSON ``response_schema``; the *validation* half (lenient parse, drop
hallucinated/no-op spans, clamp scores, compute the v1-corrected essay for
improvement-edit validation) is ported verbatim from the retired
``llm/grader.py`` -- that logic is model-independent and still earns its keep
(Gemini can still propose a span that isn't in the essay).

The grader prompts (with the Singapore-vocabulary allowlists) live in
``gemini/prompts/grader_{en,zh}.md`` and are passed as the system instruction.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from aitutor_server.api.schemas import (
    EditCategory,
    GradeRequest,
    GradeResponse,
    RubricComment,
    RubricScores,
    TrackedEdit,
)
from aitutor_server.gemini import client as gemini_client

log = logging.getLogger(__name__)


# --- Public API ----------------------------------------------------------

def grade(req: GradeRequest) -> GradeResponse:
    system = _system_prompt(req)
    user = _user_prompt(req)
    schema = _grade_response_json_schema(req)
    log.info("grading: lang=%s paper=%s essay_len=%d question_len=%d",
             req.language, req.paper_type, len(req.essay_text), len(req.question_text))

    raw = _generate_structured(system, user, schema)
    log.info("grading: got %d chars of LLM output", len(raw))
    return _parse_and_validate(raw, req)


# --- Prompt construction -------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _read_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _system_prompt(req: GradeRequest) -> str:
    return _read_prompt("grader_zh.md" if req.language == "zh-Hans" else "grader_en.md")


def _user_prompt(req: GradeRequest) -> str:
    if req.language == "zh-Hans":
        return (
            f"题目：\n{req.question_text}\n\n"
            f"学生作文：\n{req.essay_text}\n\n"
            f"请按照评分细则评分，并按指定的 JSON 格式输出。"
        )
    paper = "Continuous Writing (36 marks)" if req.paper_type == "continuous" \
            else "Situational Writing (14 marks)"
    return (
        f"Paper: PSLE English Paper 1 - {paper}\n\n"
        f"Question:\n{req.question_text}\n\n"
        f"Student's essay:\n{req.essay_text}\n\n"
        f"Mark this essay against the rubric. Output JSON only."
    )


# --- JSON schema (Gemini responseSchema subset) --------------------------

def _grade_response_json_schema(req: GradeRequest) -> dict:
    """Build the schema handed to Gemini's ``response_schema``. Gemini accepts
    a constrained OpenAPI subset, so we omit ``additionalProperties``/``const``/
    ``default`` (unsupported) and pin ``max_total`` via minimum==maximum. The
    per-paper sub-mark caps are still expressed with minimum/maximum."""
    if req.language == "zh-Hans":
        content_max, language_max, total_max = 20, 20, 40
    elif req.paper_type == "situational":
        content_max, language_max, total_max = 6, 8, 14
    else:
        content_max, language_max, total_max = 18, 18, 36

    # Round 1 (tracked_edits) is MECHANICAL fixes only -- typos, punctuation,
    # spelling. Grammar / structure / word-choice rewrites belong in Round 2.
    tracked_edit_item_schema = {
        "type": "object",
        "required": ["original_span", "suggested_replacement", "reason", "category"],
        "properties": {
            "original_span":         {"type": "string", "minLength": 1, "maxLength": 200},
            "occurrence_index":      {"type": "integer", "minimum": 0},
            "suggested_replacement": {"type": "string", "minLength": 1, "maxLength": 200},
            "reason":                {"type": "string", "minLength": 1, "maxLength": 160},
            "category":              {"type": "string", "enum": ["spelling", "punctuation", "character_error"]},
        },
    }

    improvement_edit_item_schema = {
        "type": "object",
        "required": ["original_span", "suggested_replacement", "reason", "category"],
        "properties": {
            "original_span":         {"type": "string", "minLength": 1, "maxLength": 200},
            "occurrence_index":      {"type": "integer", "minimum": 0},
            "suggested_replacement": {"type": "string", "minLength": 1, "maxLength": 200},
            "reason":                {"type": "string", "minLength": 1, "maxLength": 160},
            "category":              {"type": "string", "enum": list(EditCategory.__args__)},
        },
    }

    target_floor = min(32, total_max)
    return {
        "type": "object",
        "required": ["scores", "tracked_edits", "improvement_edits",
                     "score_after_v1", "target_score", "overall_feedback"],
        "properties": {
            "scores": {
                "type": "object",
                "required": ["content", "language", "total", "max_total", "band"],
                "properties": {
                    "content":   {"type": "number", "minimum": 0, "maximum": content_max},
                    "language":  {"type": "number", "minimum": 0, "maximum": language_max},
                    "organization": {"type": "number", "nullable": True},
                    "total":     {"type": "number", "minimum": 0, "maximum": total_max},
                    "max_total": {"type": "number", "minimum": total_max, "maximum": total_max},
                    "band":      {"type": "integer", "minimum": 1, "maximum": 5},
                },
            },
            "tracked_edits":     {"type": "array", "maxItems": 30, "items": tracked_edit_item_schema},
            "improvement_edits": {"type": "array", "maxItems": 15, "items": improvement_edit_item_schema},
            "score_after_v1": {"type": "number", "minimum": 0, "maximum": total_max},
            "target_score":   {"type": "number", "minimum": min(target_floor, total_max), "maximum": total_max},
            "overall_feedback": {"type": "string", "maxLength": 1200},
        },
    }


# --- Generation ----------------------------------------------------------

def _generate_structured(system: str, user: str, schema: dict) -> str:
    from google.genai import types

    client = gemini_client.get_client()
    cfg = types.GenerateContentConfig(
        system_instruction=system.strip(),
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=schema,
    )
    log.info("grader generating (model=%s)", gemini_client.grade_model())
    resp = client.models.generate_content(
        model=gemini_client.grade_model(),
        contents=user.strip(),
        config=cfg,
    )
    raw = (resp.text or "").strip()
    log.info("grader raw output (%d chars), first 600:\n%s", len(raw), raw[:600])
    return raw


# --- Output validation (ported verbatim from llm/grader.py) --------------

def _parse_json_lenient(raw: str) -> dict:
    """Try increasingly forgiving repairs before giving up. With Gemini's
    structured output this is almost always a no-op, but it's cheap insurance
    against the occasional code-fence / trailing-prose / truncation."""
    candidates: list[str] = [raw]

    fenced = raw.strip()
    if fenced.startswith("```"):
        fenced = re.sub(r"^```[a-zA-Z]*\n?", "", fenced)
        fenced = re.sub(r"\n?```\s*$", "", fenced)
        candidates.append(fenced)

    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last > first:
        sliced = raw[first : last + 1]
        candidates.append(sliced)
        no_trailing = re.sub(r",\s*([}\]])", r"\1", sliced)
        if no_trailing != sliced:
            candidates.append(no_trailing)

    last_err: Exception | None = None
    for i, candidate in enumerate(candidates):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            last_err = e
            log.debug("lenient parse attempt %d failed: %s", i, e)

    repaired = _close_open_brackets(raw)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            last_err = e
            log.debug("bracket-close repair also failed: %s", e)

    log.error("LLM JSON unparseable after repairs; raw output (first 800):\n%s", raw[:800])
    raise ValueError(f"grader produced invalid JSON: {last_err}") from last_err


def _close_open_brackets(raw: str) -> str | None:
    """If the model was truncated, walk the prefix and append the closing
    punctuation needed to balance the structure. Best-effort."""
    first = raw.find("{")
    if first == -1:
        return None
    s = raw[first:]
    in_string = False
    escape = False
    stack: list[str] = []
    last_safe = -1
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
                last_safe = i
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            last_safe = i
        elif ch in ",":
            last_safe = i
    if last_safe == -1:
        return None
    truncated = s[: last_safe + 1].rstrip().rstrip(",")
    return truncated + "".join(reversed(stack))


def _parse_and_validate(raw: str, req: GradeRequest) -> GradeResponse:
    """Parse the LLM JSON, drop hallucinated tracked-edit spans, clamp scores."""
    data = _parse_json_lenient(raw)

    edits_in = data.get("tracked_edits") or []
    edits_kept: list[TrackedEdit] = []
    edits_dropped_hallucinated = 0
    edits_dropped_noop = 0
    edits_dropped_invalid = 0
    for e in edits_in:
        span = e.get("original_span", "")
        replacement = e.get("suggested_replacement", "")
        if not span or span not in req.essay_text:
            edits_dropped_hallucinated += 1
            continue
        if replacement == span:
            edits_dropped_noop += 1
            continue
        try:
            edits_kept.append(TrackedEdit(**e))
        except Exception:
            edits_dropped_invalid += 1
    if edits_dropped_hallucinated or edits_dropped_noop or edits_dropped_invalid:
        log.warning(
            "tracked_edits: kept %d, dropped %d hallucinated, %d no-op, %d invalid (of %d)",
            len(edits_kept), edits_dropped_hallucinated, edits_dropped_noop,
            edits_dropped_invalid, len(edits_in),
        )

    v1_corrected_text = _apply_edits_to_text(
        req.essay_text, [e.model_dump() for e in edits_kept],
    )
    imp_in = data.get("improvement_edits") or []
    imp_kept: list[TrackedEdit] = []
    imp_dropped_hallucinated = 0
    imp_dropped_noop = 0
    imp_dropped_invalid = 0
    for e in imp_in:
        span = e.get("original_span", "")
        replacement = e.get("suggested_replacement", "")
        if not span or span not in v1_corrected_text:
            imp_dropped_hallucinated += 1
            continue
        if replacement == span:
            imp_dropped_noop += 1
            continue
        try:
            imp_kept.append(TrackedEdit(**e))
        except Exception:
            imp_dropped_invalid += 1
    if imp_dropped_hallucinated or imp_dropped_noop or imp_dropped_invalid:
        log.warning(
            "improvement_edits: kept %d, dropped %d hallucinated, %d no-op, %d invalid (of %d)",
            len(imp_kept), imp_dropped_hallucinated, imp_dropped_noop,
            imp_dropped_invalid, len(imp_in),
        )

    comments_in = data.get("comments") or []
    comments_kept: list[RubricComment] = []
    comments_dropped = 0
    for c in comments_in:
        span = c.get("span", "")
        if span and span in req.essay_text:
            try:
                comments_kept.append(RubricComment(**c))
            except Exception:
                comments_dropped += 1
        else:
            comments_dropped += 1
    if comments_dropped:
        log.warning("dropped %d/%d hallucinated/invalid comments", comments_dropped, len(comments_in))

    scores_in = data.get("scores") or {}
    if req.language == "zh-Hans":
        max_total_expected = 40
    elif req.paper_type == "situational":
        max_total_expected = 14
    else:
        max_total_expected = 36

    if not scores_in.get("max_total"):
        scores_in["max_total"] = max_total_expected
    total = float(scores_in.get("total", 0))
    if total > max_total_expected:
        log.warning("LLM returned total=%.1f > max_total=%d; clamping", total, max_total_expected)
        scores_in["total"] = max_total_expected

    scores = RubricScores(**scores_in)

    target_score = data.get("target_score")
    if target_score is not None:
        floor = min(32.0, float(max_total_expected))
        target_score = max(float(target_score), floor, float(scores.total))
        target_score = min(target_score, float(max_total_expected))

    score_after_v1 = data.get("score_after_v1")
    if score_after_v1 is not None:
        upper = target_score if target_score is not None else float(max_total_expected)
        score_after_v1 = max(float(score_after_v1), float(scores.total))
        score_after_v1 = min(score_after_v1, float(upper))

    return GradeResponse(
        scores=scores,
        tracked_edits=edits_kept,
        improvement_edits=imp_kept,
        score_after_v1=score_after_v1,
        target_score=target_score,
        comments=comments_kept,
        overall_feedback=str(data.get("overall_feedback", "")).strip(),
    )


def _apply_edits_to_text(text: str, edits: list[dict]) -> str:
    """Apply tracked_edits to ``text`` in-Python (first occurrence per edit) to
    compute the v1-corrected essay for improvement-edit span validation."""
    out = text
    for e in edits:
        span = e.get("original_span", "")
        replacement = e.get("suggested_replacement", "")
        if span and replacement and span != replacement and span in out:
            out = out.replace(span, replacement, 1)
    return out
