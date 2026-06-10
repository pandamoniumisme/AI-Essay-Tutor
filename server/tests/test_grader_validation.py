"""Unit tests for the model-independent grader validation logic.

No network / no Gemini -- these exercise the JSON parsing, span filtering, and
score clamping that run on whatever the model returns.
"""
from __future__ import annotations

import json

from aitutor_server.api.schemas import GradeRequest
from aitutor_server.providers import grader


def _req(essay: str, language: str = "zh-Hans", paper: str = "continuous") -> GradeRequest:
    return GradeRequest(
        language=language, paper_type=paper,
        question_text="题目", essay_text=essay, student_level="P6",
    )


def test_schema_caps_by_route():
    zh = grader._grade_response_json_schema(_req("作文", "zh-Hans"))
    assert zh["properties"]["scores"]["properties"]["content"]["maximum"] == 20
    assert zh["properties"]["scores"]["properties"]["max_total"]["minimum"] == 40

    en_cont = grader._grade_response_json_schema(_req("essay", "en", "continuous"))
    assert en_cont["properties"]["scores"]["properties"]["content"]["maximum"] == 18

    en_sit = grader._grade_response_json_schema(_req("essay", "en", "situational"))
    assert en_sit["properties"]["scores"]["properties"]["language"]["maximum"] == 8
    # target_score floor is clamped to max_total when max_total < 32.
    assert en_sit["properties"]["target_score"]["minimum"] == 14


def test_drops_hallucinated_and_noop_edits():
    essay = "小明去学校。他很开心。"
    raw = json.dumps({
        "scores": {"content": 12, "language": 13, "total": 25, "max_total": 40, "band": 3},
        "tracked_edits": [
            {"original_span": "学校", "suggested_replacement": "學校",
             "reason": "繁体", "category": "character_error"},
            {"original_span": "不存在的句子", "suggested_replacement": "x",
             "reason": "幻觉", "category": "spelling"},       # hallucinated -> dropped
            {"original_span": "他很开心", "suggested_replacement": "他很开心",
             "reason": "noop", "category": "punctuation"},     # no-op -> dropped
        ],
        "improvement_edits": [],
        "score_after_v1": 26,
        "target_score": 33,
        "overall_feedback": "不错",
    })
    out = grader._parse_and_validate(raw, _req(essay))
    assert len(out.tracked_edits) == 1
    assert out.tracked_edits[0].original_span == "学校"


def test_clamps_total_and_target():
    essay = "essay text here"
    raw = json.dumps({
        "scores": {"content": 18, "language": 18, "total": 99, "max_total": 36, "band": 5},
        "tracked_edits": [], "improvement_edits": [],
        "score_after_v1": 50, "target_score": 50,
        "overall_feedback": "good",
    })
    out = grader._parse_and_validate(raw, _req(essay, "en", "continuous"))
    assert out.scores.total == 36
    assert out.target_score <= 36
    assert out.score_after_v1 <= out.target_score


def test_lenient_parse_strips_code_fence():
    raw = "```json\n{\"a\": 1}\n```"
    assert grader._parse_json_lenient(raw) == {"a": 1}


def test_close_open_brackets_repairs_truncation():
    # Truncated mid-array after a complete value -- the repair cuts at the last
    # safe comma/closer and balances the open brackets.
    raw = '{"total": 25, "edits": [1, 2,'
    repaired = grader._close_open_brackets(raw)
    assert repaired is not None
    parsed = json.loads(repaired)
    assert parsed["total"] == 25
    assert parsed["edits"] == [1, 2]
