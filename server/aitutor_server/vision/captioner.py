"""Visual grounding captioner.

PSLE picture-composition prompts (English Continuous Writing has 3-4 picture
stimuli; Chinese 看图作文 has 5-6 numbered panels) embed illustrated content
that the student must describe or use in their narrative. Without seeing the
illustrations the grader is picture-blind: it cannot judge whether the
student's plot matches the depicted sequence, whether they invented details
that contradict the pictures, or whether they ignored a stimulus they were
required to use.

Solution: a small vision-language model captions the question image at
/transcribe time and the caption is concatenated into ``question_text`` so
the (text-only) Qwen3-8B grader sees the picture context in plain prose.

Model: Qwen2.5-VL-7B-Instruct, official Intel-maintained INT4 OpenVINO IR
       at OpenVINO/Qwen2.5-VL-7B-Instruct-int4-ov.
Device: iGPU (Arc 130V on Lunar Lake 226V) - 7B VLMs with vision encoders
        don't compile cleanly to NPU, and the captioner only runs once per
        /transcribe call so NPU energy efficiency is moot.

API: openvino_genai.VLMPipeline.generate(prompt, image=ov.Tensor(np_img), ...)
     -- singular ``image=``; pass an ov.Tensor wrapping a (H, W, 3) uint8
     numpy array (the model card's example pattern).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

import cv2
import numpy as np

from aitutor_server.api.schemas import Language
from aitutor_server.models import manager as model_manager

log = logging.getLogger(__name__)

_PIPELINE_LOCK = threading.Lock()
_PIPELINE: Any | None = None


# --- Prompts -------------------------------------------------------------

# Question prompt: full transcription + picture descriptions in one VLM call.
# We dropped paddleocr; the VLM does both jobs.

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

# Essay prompt: pure verbatim transcription, no commentary.

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


# --- Public API ----------------------------------------------------------

def transcribe_question_page(bgr: np.ndarray, language: Language,
                             max_new_tokens: int = 1200) -> str:
    """Transcribe printed text + describe illustrated panels in a question page.

    Single VLM call, returns the model's two-section output verbatim. Caller
    uses this as the question_text (which already has the section headers
    baked into the prompt). Returns empty string on error.
    """
    try:
        pipeline = _get_pipeline()
        prompt = _QUESTION_PROMPT_ZH if language == "zh-Hans" else _QUESTION_PROMPT_EN
        rgb = _bgr_to_rgb(bgr)
        log.info("VLM question page (lang=%s, %dx%d)",
                 language, rgb.shape[1], rgb.shape[0])
        return _run(pipeline, prompt, rgb, max_new_tokens)
    except Exception:
        log.exception("VLM question failed; returning empty")
        return ""


def transcribe_question_pages(bgrs: list[np.ndarray], language: Language,
                              max_new_tokens: int = 1200) -> str:
    """Concatenate the per-page output across multiple question pages."""
    if not bgrs:
        return ""
    if len(bgrs) == 1:
        return transcribe_question_page(bgrs[0], language, max_new_tokens)

    parts: list[str] = []
    for i, img in enumerate(bgrs, 1):
        page = transcribe_question_page(img, language, max_new_tokens)
        if page.strip():
            header = f"--- Page {i} ---" if language == "en" else f"--- 第 {i} 页 ---"
            parts.append(f"{header}\n{page}")
    return "\n\n".join(parts)


def transcribe_essay_page(bgr: np.ndarray, language: Language,
                          max_new_tokens: int = 1500) -> str:
    """Verbatim transcription of a single handwritten essay page.

    Replaces paddleocr for handwriting OCR. We trade a specialised OCR engine
    for a general-purpose VLM, accepting somewhat worse character-level
    accuracy in return for the pipeline actually finishing on Lunar Lake. The
    user reviews + corrects the transcription in Writer before grading
    anyway, so OCR errors are recoverable.
    """
    pipeline = _get_pipeline()
    prompt = _ESSAY_PROMPT_ZH if language == "zh-Hans" else _ESSAY_PROMPT_EN
    rgb = _bgr_to_rgb(bgr)
    log.info("VLM essay page (lang=%s, %dx%d)",
             language, rgb.shape[1], rgb.shape[0])
    return _run(pipeline, prompt, rgb, max_new_tokens)


def transcribe_essay_pages(bgrs: list[np.ndarray], language: Language,
                           max_new_tokens: int = 1500,
                           on_page: "Callable[[int, int], None] | None" = None
                           ) -> str:
    """Transcribe each essay page in order. ``on_page(i, total)`` is called
    after each page so callers can update progress."""
    parts: list[str] = []
    total = len(bgrs)
    for i, img in enumerate(bgrs, 1):
        text = transcribe_essay_page(img, language, max_new_tokens)
        if text.strip():
            parts.append(text.strip())
        if on_page:
            on_page(i, total)
    return "\n\n".join(parts)


# --- Implementation ------------------------------------------------------

def _get_pipeline() -> Any:
    """Lazy-load the OpenVINO GenAI VLMPipeline (Qwen2.5-VL-7B) on iGPU."""
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is not None:
            return _PIPELINE

        captioner_dir = model_manager.active_captioner_dir()
        ir_present = (
            (captioner_dir / "openvino_language_model.xml").exists()
            or (captioner_dir / "openvino_model.xml").exists()
        )
        if not ir_present:
            raise FileNotFoundError(
                f"captioner IR missing at {captioner_dir}; "
                "run scripts/bootstrap_server.ps1 to fetch + convert"
            )

        # Lazy import - openvino_genai is heavy.
        import openvino_genai

        log.info("loading captioner IR from %s on GPU...", captioner_dir)
        _PIPELINE = openvino_genai.VLMPipeline(str(captioner_dir), "GPU")
        log.info("captioner ready")
        return _PIPELINE


def _bgr_to_rgb(bgr: np.ndarray) -> np.ndarray:
    """Convert OpenCV BGR (or grayscale, or BGRA) to a contiguous (H,W,3) uint8 RGB array."""
    if bgr.ndim == 2:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_GRAY2RGB)
    elif bgr.shape[2] == 4:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGRA2RGB)
    else:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if rgb.dtype != np.uint8:
        rgb = rgb.astype(np.uint8)
    return np.ascontiguousarray(rgb)


def _run(pipeline: Any, prompt: str, rgb: np.ndarray, max_new_tokens: int) -> str:
    """Invoke the VLMPipeline and return its text output.

    Per the official model card example, we pass the image as an
    ``openvino.Tensor`` wrapping a (H, W, 3) uint8 numpy array, using the
    singular ``image=`` kwarg to ``generate``.
    """
    import openvino as ov
    import openvino_genai

    image_tensor = ov.Tensor(rgb)

    config = openvino_genai.GenerationConfig()
    config.max_new_tokens = max_new_tokens
    config.do_sample = False  # deterministic captions

    result = pipeline.generate(prompt, image=image_tensor, generation_config=config)
    # VLMPipeline returns a DecodedResults object whose str() is the text.
    return str(result).strip()


def unload() -> None:
    """Free the captioner from RAM. Call between /transcribe and /grade if memory pressure
    on a 16 GB system requires it. Subsequent transcribe_*() calls reload lazily."""
    global _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is not None:
            log.info("unloading captioner")
            _PIPELINE = None


