"""LLM grader.

Loads Qwen3-8B-Instruct INT4 OpenVINO IR onto the NPU and runs PSLE-rubric
grading with structured JSON output. The captioner (Qwen2.5-VL-7B on iGPU)
is unloaded before the grader loads, since both don't fit on the 226V's
16 GB simultaneously.

Phases per request:
  - lazy-load Qwen3-8B on NPU (one-time cold start ~30-60s, then warm)
  - build the language-appropriate prompt (en or zh-Hans)
  - run constrained generation with the GradeResponse JSON schema
  - parse + validate (drop hallucinated tracked-edit spans, clamp total)

The JSON schema is enforced via openvino_genai.StructuredOutputConfig with
its xgrammar backend (OpenVINO 2025.4+). XGrammar guarantees the output
parses as valid JSON matching the schema; we still run the result through
Pydantic to validate semantics (total <= max_total etc.) and through our own
span-existence check.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from aitutor_server.api.schemas import (
    EditCategory,
    GradeRequest,
    GradeResponse,
    RubricComment,
    RubricScores,
    TrackedEdit,
)
from aitutor_server.models.paths import LLM_FALLBACK_DIR

log = logging.getLogger(__name__)

_PIPELINE_LOCK = threading.Lock()
_PIPELINE: Any | None = None

# Hard cap so a runaway model doesn't burn all day. ~1500 tokens is enough for
# 30 tracked edits + 10 comments + scores + a 1200-char feedback paragraph.
_MAX_NEW_TOKENS = 1800


# --- Public API ----------------------------------------------------------

def grade(req: GradeRequest) -> GradeResponse:
    """Grade an essay against the PSLE rubric using Qwen3-8B-Instruct on NPU.
    The captioner (Qwen2.5-VL-7B on iGPU) is unloaded by ``_get_pipeline``
    before the grader loads."""
    prompt = _build_prompt(req)
    schema = _grade_response_json_schema(req)
    log.info("grading: lang=%s paper=%s essay_len=%d question_len=%d",
             req.language, req.paper_type, len(req.essay_text), len(req.question_text))

    pipeline = _get_pipeline()
    raw = _generate_structured(pipeline, prompt, schema)

    log.info("grading: got %d chars of LLM output", len(raw))
    return _parse_and_validate(raw, req)


def active_model_name() -> str:
    return "Qwen3-8B-Instruct"


def unload() -> None:
    """Free the grader from RAM (rarely needed -- the grader is the last
    model to load in a typical session)."""
    global _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is not None:
            log.info("unloading grader")
            _PIPELINE = None


# --- Pipeline lifecycle --------------------------------------------------

def _get_pipeline() -> Any:
    """Lazy-load the Qwen3-8B INT4 IR on the NPU. Unloads the captioner
    first to keep peak RAM under 16 GB."""
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is not None:
            return _PIPELINE

        if not (LLM_FALLBACK_DIR / "openvino_model.xml").exists():
            raise FileNotFoundError(
                f"grader IR missing at {LLM_FALLBACK_DIR}; run "
                "scripts/bootstrap_server.ps1 to fetch it"
            )

        # Free the captioner BEFORE we load the grader -- otherwise we may OOM
        # on a 16 GB system. Lazy import avoids a circular dep at module-load.
        try:
            from aitutor_server.vision import captioner
            captioner.unload()
        except Exception:
            log.exception("failed to unload captioner (continuing anyway)")

        import openvino_genai

        log.info("loading grader IR from %s on NPU...", LLM_FALLBACK_DIR)
        # NPU's stateful LLM pipeline pre-allocates two fixed-size buffers at
        # compile time:
        #   MAX_PROMPT_LEN   -- input budget. Must cover system prompt +
        #                       question + essay + chat-template overhead.
        #   MIN_RESPONSE_LEN -- output budget. *This is what max_new_tokens
        #                       cannot exceed at runtime.* If unset, recent
        #                       openvino-genai builds default it to ~128-256
        #                       tokens, which silently truncates the grader
        #                       JSON mid-string with no error -- the symptom
        #                       was an output that ended in the middle of a
        #                       "reason" field at ~150 tokens.
        # Both must be ints (string values trip a type-check error).
        _PIPELINE = openvino_genai.LLMPipeline(
            str(LLM_FALLBACK_DIR), "NPU",
            MAX_PROMPT_LEN=4096,
            MIN_RESPONSE_LEN=2048,
        )
        log.info("grader ready (NPU MAX_PROMPT_LEN=4096, MIN_RESPONSE_LEN=2048)")
        return _PIPELINE


# --- Prompt construction -------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _read_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _build_prompt(req: GradeRequest) -> str:
    if req.language == "zh-Hans":
        system = _read_prompt("grader_zh.md")
        user = (
            f"题目：\n{req.question_text}\n\n"
            f"学生作文：\n{req.essay_text}\n\n"
            f"请按照评分细则评分，并按指定的 JSON 格式输出。"
        )
    else:
        paper = "Continuous Writing (36 marks)" if req.paper_type == "continuous" \
                else "Situational Writing (14 marks)"
        system = _read_prompt("grader_en.md")
        user = (
            f"Paper: PSLE English Paper 1 - {paper}\n\n"
            f"Question:\n{req.question_text}\n\n"
            f"Student's essay:\n{req.essay_text}\n\n"
            f"Mark this essay against the rubric. Output JSON only."
        )

    # Qwen3 chat template: a short system block followed by the user turn.
    # OpenVINO GenAI's LLMPipeline doesn't auto-apply a chat template; we
    # build the turn boundaries explicitly. enable_thinking=False is enforced
    # by NOT including the <think> trigger.
    return (
        "<|im_start|>system\n" + system.strip() + "<|im_end|>\n"
        "<|im_start|>user\n" + user.strip() + "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


# --- JSON schema ---------------------------------------------------------

def _grade_response_json_schema(req: GradeRequest) -> dict:
    """Build the JSON schema we hand to xgrammar. Sub-mark caps depend on the
    paper -- EN continuous has content/18 + language/18, EN situational
    content/6 + language/8, ZH composition content/20 + language/20."""
    if req.language == "zh-Hans":
        content_max, language_max, total_max = 20, 20, 40
    elif req.paper_type == "situational":
        content_max, language_max, total_max = 6, 8, 14
    else:
        content_max, language_max, total_max = 18, 18, 36

    edit_item_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["original_span", "suggested_replacement", "reason", "category"],
        "properties": {
            "original_span":         {"type": "string", "minLength": 1, "maxLength": 200},
            "occurrence_index":      {"type": "integer", "minimum": 0, "default": 0},
            "suggested_replacement": {"type": "string", "minLength": 1, "maxLength": 200},
            "reason":                {"type": "string", "minLength": 1, "maxLength": 160},
            "category":              {"enum": list(EditCategory.__args__)},
        },
    }

    # Floor for target_score. Cap at total_max so EN-situational (max 14)
    # doesn't get an unreachable target.
    target_floor = min(30, total_max)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["scores", "tracked_edits", "improvement_edits",
                     "target_score", "overall_feedback"],
        "properties": {
            "scores": {
                "type": "object",
                "additionalProperties": False,
                "required": ["content", "language", "total", "max_total", "band"],
                "properties": {
                    "content":   {"type": "number", "minimum": 0, "maximum": content_max},
                    "language":  {"type": "number", "minimum": 0, "maximum": language_max},
                    "organization": {"type": ["number", "null"]},
                    "total":     {"type": "number", "minimum": 0, "maximum": total_max},
                    "max_total": {"type": "number", "const": total_max},
                    "band":      {"type": "integer", "minimum": 1, "maximum": 5},
                },
            },
            "tracked_edits":     {"type": "array", "maxItems": 30, "items": edit_item_schema},
            "improvement_edits": {"type": "array", "maxItems": 15, "items": edit_item_schema},
            "target_score": {
                "type": "number",
                "minimum": min(target_floor, total_max),
                "maximum": total_max,
            },
            "overall_feedback": {"type": "string", "maxLength": 1200},
        },
    }


# --- Generation ----------------------------------------------------------

def _generate_structured(pipeline: Any, prompt: str, schema: dict) -> str:
    """Run constrained generation. Falls back to free generation if the
    installed OpenVINO GenAI version doesn't support StructuredOutputConfig
    (we then rely on the prompt to coax JSON and best-effort parse)."""
    import openvino_genai

    cfg = openvino_genai.GenerationConfig()
    cfg.max_new_tokens = _MAX_NEW_TOKENS
    cfg.do_sample = False
    cfg.temperature = 0.0

    structured_applied = False
    structured = getattr(openvino_genai, "StructuredOutputConfig", None)
    if structured is not None:
        try:
            cfg.structured_output_config = structured(json_schema=json.dumps(schema))
            structured_applied = True
        except Exception:
            log.exception("StructuredOutputConfig setup failed; falling back to free generation")
    log.info("grader generating (structured_output=%s, max_new_tokens=%d)",
             structured_applied, _MAX_NEW_TOKENS)

    result = pipeline.generate(prompt, generation_config=cfg)
    raw = str(result).strip()
    log.info("grader raw output (%d chars), first 600:\n%s", len(raw), raw[:600])
    if len(raw) > 600:
        log.info("grader raw output, last 200:\n%s", raw[-200:])
    return raw


# --- Output validation ---------------------------------------------------


def _parse_json_lenient(raw: str) -> dict:
    """Try increasingly forgiving repairs before giving up.

    Common Qwen3-8B failure modes when xgrammar isn't constraining (e.g. NPU
    pipelines that don't yet support structured output):
      * Output wrapped in ```json ... ``` code fences.
      * Trailing prose after the closing ``}`` ("Here is the JSON: { ... }.")
      * Trailing commas before ``}`` or ``]``.
      * Truncated mid-string when ``max_new_tokens`` is exceeded.
    """
    candidates: list[str] = []

    # 1. Verbatim
    candidates.append(raw)

    # 2. Strip common code fences
    fenced = raw.strip()
    if fenced.startswith("```"):
        fenced = re.sub(r"^```[a-zA-Z]*\n?", "", fenced)
        fenced = re.sub(r"\n?```\s*$", "", fenced)
        candidates.append(fenced)

    # 3. Slice from first '{' to last '}' (drops surrounding prose).
    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last > first:
        sliced = raw[first : last + 1]
        candidates.append(sliced)
        # 4. Strip trailing commas (common LLM tic).
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

    # 5. Last resort: try to truncate mid-tail and close brackets.
    repaired = _close_open_brackets(raw)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            last_err = e
            log.debug("bracket-close repair also failed: %s", e)

    log.error("LLM JSON unparseable after repairs; raw output (first 800):\n%s",
              raw[:800])
    raise ValueError(f"grader produced invalid JSON: {last_err}") from last_err


def _close_open_brackets(raw: str) -> str | None:
    """If the model was truncated, walk the prefix and append the
    closing punctuation needed to balance the structure. Best-effort.
    Returns None if we can't find a sensible cut point."""
    first = raw.find("{")
    if first == -1:
        return None
    s = raw[first:]
    # Cut at the last balanced position we can identify -- find the last
    # comma or closer outside of a string.
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

    # Drop tracked_edits that:
    #   - have an ``original_span`` that isn't a substring of the essay
    #     (LLM hallucination; would produce phantom redlines)
    #   - have ``suggested_replacement == original_span`` (no-op edit; the
    #     model dumped a "could add detail" suggestion here instead of
    #     putting it in ``comments``)
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

    # improvement_edits: validated against the *v1-corrected* essay (after
    # tracked_edits would be applied). The LLM was instructed to author them
    # against the original essay; spans that overlap a tracked_edit may now
    # be missing from v1-corrected text and will be silently dropped.
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

    # Comments are now optional. Validate any that the LLM still emitted.
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
        log.warning("dropped %d/%d hallucinated/invalid comments",
                    comments_dropped, len(comments_in))

    scores_in = data.get("scores") or {}
    # Clamp + repair scores. If max_total is missing/wrong, set from the schema-side
    # defaults; if total > max_total, clamp.
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
        log.warning("LLM returned total=%.1f > max_total=%d; clamping",
                    total, max_total_expected)
        scores_in["total"] = max_total_expected

    scores = RubricScores(**scores_in)

    target_score = data.get("target_score")
    if target_score is not None:
        floor = min(30.0, float(max_total_expected))
        target_score = max(float(target_score), floor, float(scores.total))
        target_score = min(target_score, float(max_total_expected))

    return GradeResponse(
        scores=scores,
        tracked_edits=edits_kept,
        improvement_edits=imp_kept,
        target_score=target_score,
        comments=comments_kept,
        overall_feedback=str(data.get("overall_feedback", "")).strip(),
    )


def _apply_edits_to_text(text: str, edits: list[dict]) -> str:
    """Apply tracked_edits to ``text`` in-Python. Used to compute the
    v1-corrected essay so we can validate improvement_edits' spans against
    it. Replaces only the FIRST matching occurrence per edit, matching the
    UNO-side ``findAll().getByIndex(0)`` apply behaviour."""
    out = text
    for e in edits:
        span = e.get("original_span", "")
        replacement = e.get("suggested_replacement", "")
        if span and replacement and span != replacement and span in out:
            out = out.replace(span, replacement, 1)
    return out
