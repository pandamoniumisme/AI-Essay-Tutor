"""Transcription: OCR + picture description via Gemini multimodal.

Replaces the OpenVINO Qwen2.5-VL captioner. Same public shape as before
(``do_transcribe(...) -> TranscribeResponse``) so the API layer is unchanged.

Images arrive as ``(bytes, mime_type)`` tuples -- we hand them straight to
Gemini as inline parts; no OpenCV decode is needed. Each essay/question page is
one ``generate_content`` call so progress stays granular.

The prompts are ported verbatim from the retired ``vision/captioner.py`` so the
question output keeps its two-section (``=== Prompt === / === Pictures ===``)
shape the grader already expects.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from aitutor_server import lang_detect
from aitutor_server.api.schemas import Language, OcrLine, TranscribeResponse
from aitutor_server.gemini import client as gemini_client

log = logging.getLogger(__name__)

ProgressCb = Callable[[str, float], None]
Image = tuple[bytes, str]  # (raw bytes, mime_type)


def _noop(_msg: str, _progress: float) -> None:
    pass


# --- Prompts (ported verbatim from the OpenVINO captioner) ---------------

_QUESTION_PROMPT_EN = """\
You are looking at a PSLE Primary 6 English Continuous Writing question prompt.
The page contains some combination of: printed instructions, a question or
topic statement, and 3-4 illustrated picture stimuli the student must use in
their composition.

Output two clearly delimited sections:

=== Prompt ===
Verbatim transcription of ALL printed text on the page (instructions,
question, any captions). Preserve the original line structure as much as
possible. Do NOT paraphrase. If the page has no printed text, write "(none)".

=== Pictures ===
For each illustrated panel, in order:
- Identify the setting (where it takes place).
- Identify the main characters and any relevant objects.
- Describe what is happening in clear, specific terms.
- Note any text, signs, or labels visible inside the illustration itself.
Output as a numbered list, one short paragraph per panel. If there are no
illustrated panels, write "(none)".

Be factual and concise. Do not invent details that are not depicted.
"""

_QUESTION_PROMPT_ZH = """\
这是 PSLE 小六华文作文的题目页。页面通常包含印刷的题目说明、作文要求，
以及 5-6 幅按顺序排列的插图（看图作文）。

请输出两个用分隔线明确分开的部分：

=== 题目 ===
逐字转录页面上所有印刷的文字（说明、题目、任何说明文字）。尽量保留原本的
排版结构。不要意译或概括。如果页面没有印刷文字，请写 "(无)"。

=== 图片 ===
按顺序描述每一幅插图：
- 说明场景（地点、时间）。
- 指出主要人物和重要物件。
- 用具体的语言描述正在发生的事情。
- 如果插图里有文字、招牌或对话泡泡，请逐字记录。
用编号列表输出，每幅图一段。如果没有插图，请写 "(无)"。

请客观、简洁地描述，不要编造图中没有的内容。
"""

_ESSAY_PROMPT_EN = """\
Transcribe the handwritten English text in this image VERBATIM.

Rules:
- Output only the transcribed text. No commentary, no analysis, no headers.
- Preserve line breaks as they appear on the page.
- Preserve the student's spelling exactly, including any spelling mistakes.
- Preserve the student's punctuation exactly.
- If a word is illegible, write [?] in its place.
- Do not include lined-paper rules, page numbers, or printed labels.
"""

_ESSAY_PROMPT_ZH = """\
请逐字转录图片中的手写华文。

规则：
- 只输出转录的文字，不要任何注释、分析或标题。
- 严格保留原文的换行。
- 严格保留学生的写法（包括错别字），不要替学生改正。
- 严格保留学生的标点符号。
- 如果某个字看不清楚，请用 [?] 代替。
- 不要包括稿纸的格线、页码或印刷的标签。
"""


# --- Single-image call ---------------------------------------------------

def _run(prompt: str, image: Image, model: str) -> str:
    """One multimodal Gemini call: prompt + a single image, temperature 0."""
    from google.genai import types

    client = gemini_client.get_client()
    data, mime = image
    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=data, mime_type=mime),
            types.Part.from_text(text=prompt),
        ],
        config=types.GenerateContentConfig(temperature=0.0),
    )
    return (resp.text or "").strip()


# --- Public API ----------------------------------------------------------

def transcribe_essay_page(image: Image, language: Language) -> str:
    prompt = _ESSAY_PROMPT_ZH if language == "zh-Hans" else _ESSAY_PROMPT_EN
    return _run(prompt, image, gemini_client.transcribe_model())


def transcribe_essay_pages(images: list[Image], language: Language,
                           on_page: Callable[[int, int], None] | None = None) -> str:
    parts: list[str] = []
    total = len(images)
    for i, img in enumerate(images, 1):
        text = transcribe_essay_page(img, language)
        if text.strip():
            parts.append(text.strip())
        if on_page:
            on_page(i, total)
    return "\n\n".join(parts)


def transcribe_question_page(image: Image, language: Language) -> str:
    try:
        prompt = _QUESTION_PROMPT_ZH if language == "zh-Hans" else _QUESTION_PROMPT_EN
        return _run(prompt, image, gemini_client.transcribe_model())
    except Exception:
        log.exception("question transcription failed; returning empty")
        return ""


def transcribe_question_pages(images: list[Image], language: Language) -> str:
    if not images:
        return ""
    if len(images) == 1:
        return transcribe_question_page(images[0], language)
    parts: list[str] = []
    for i, img in enumerate(images, 1):
        page = transcribe_question_page(img, language)
        if page.strip():
            header = f"--- Page {i} ---" if language == "en" else f"--- 第 {i} 页 ---"
            parts.append(f"{header}\n{page}")
    return "\n\n".join(parts)


def do_transcribe(question_images: list[Image], essay_images: list[Image],
                  language: str, on_progress: ProgressCb = _noop) -> TranscribeResponse:
    """Transcribe the essay (verbatim) and the question page (printed text +
    picture descriptions). ``language`` is ``en`` / ``zh-Hans`` / ``auto``."""
    final_lang: Language = _resolve_language(language, essay_images, on_progress)

    n_essay = len(essay_images)

    def _essay_progress(done: int, total: int) -> None:
        frac = 0.10 + 0.60 * (done / max(total, 1))
        on_progress(f"transcribing essay (page {done}/{total})", frac)

    on_progress(f"transcribing essay page 1/{n_essay}", 0.10)
    essay_text = transcribe_essay_pages(essay_images, final_lang, on_page=_essay_progress)

    on_progress("transcribing question + describing pictures", 0.75)
    question_text = transcribe_question_pages(question_images, final_lang)

    on_progress("finalising", 0.95)

    # Synthesize one OcrLine per non-empty essay line to keep the response
    # shape backwards compatible. No per-line bboxes (the model doesn't expose
    # them); the in-browser review step is the real correction safety net.
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


def _resolve_language(language: str, essay_images: list[Image],
                      on_progress: ProgressCb) -> Language:
    if language != "auto":
        return language  # type: ignore[return-value]
    on_progress("detecting language", 0.05)
    sample = transcribe_essay_page(essay_images[0], "zh-Hans")
    return lang_detect.detect_language(sample)
