"""Orchestration: ensure server -> show input dialog -> POST /transcribe -> show result.

Called from ``registration.AITutorJob.trigger`` on toolbar-button click.
"""
from __future__ import annotations

import traceback

from aitutor import client, debug_cache, dialog, server_proc
from aitutor.log import get_logger

log = get_logger(__name__)


def show_error(ctx, body: str) -> None:
    """Public helper used by registration.py for top-level error reporting."""
    dialog.show_error(ctx, "AI Essay Tutor - error", body)


def run_transcribe(ctx) -> None:
    log.info("run_transcribe invoked")

    # 1. Collect language + image paths + debug flag from the user FIRST so
    #    the user can opt into using cached outputs without booting the server.
    inp = dialog.TranscribeInputDialog(ctx)
    result = inp.execute()
    if result is None:
        log.info("user cancelled input dialog")
        return
    language, question_paths, essay_paths, debug_mode = result
    log.info("transcribe: language=%s question=%d image(s) essay=%d image(s) debug=%s",
             language, len(question_paths), len(essay_paths), debug_mode)

    # 2. Debug short-circuits.
    if debug_mode:
        if _try_debug_skip_all(ctx):
            return
        if _try_debug_skip_transcribe(ctx, language):
            return

    # 3. Make sure the server is running.
    try:
        server_proc.ensure_server(timeout=60.0)
    except server_proc.ServerNotInstalled as e:
        dialog.show_error(ctx, "AI Server not installed", str(e))
        return
    except server_proc.ServerStartupTimeout as e:
        dialog.show_error(ctx, "AI Server failed to start", str(e))
        return
    except Exception:
        dialog.show_error(ctx, "AI Server error", traceback.format_exc())
        return

    # 4. Sanity-check that models are ready before we send images at it.
    status = client.models_status(timeout=2.0)
    if status is None:
        dialog.show_error(ctx, "AI Server unreachable",
                          "Server started but /models/status did not respond. Check the log.")
        return
    blockers = _transcribe_blockers(status)
    if blockers:
        dialog.show_error(
            ctx, "Models not ready",
            "The AI server is still preparing its models:\n\n"
            + "\n".join(f"  - {b}" for b in blockers)
            + "\n\nLaunch scripts\\bootstrap_server.ps1 if this persists."
        )
        return
    soft = _soft_warnings(status)
    if soft:
        log.warning("proceeding without these soft-optional models: %s", soft)

    if not question_paths or not essay_paths:
        dialog.show_error(
            ctx, "Missing files",
            "Debug mode is on but no cached transcribe was found, and you "
            "didn't pick any images. Either pick images and re-run, or "
            "uncheck Debug.")
        return

    # 4. Submit the job (returns immediately with a job_id), then open a
    # progress dialog that polls /jobs/{id} every 3 s until done or error.
    # This keeps LO responsive instead of freezing for the duration.
    log.info("submitting transcribe job")
    try:
        job_id = client.start_transcribe_job(question_paths, essay_paths,
                                             language, timeout=120.0)
    except client.JobBusy as e:
        # Server already has a transcribe in flight. Don't queue a second one.
        log.info("server busy: running_job=%s", e.running_job_id)
        dialog.show_error(
            ctx, "Compo Tutor busy",
            f"Another transcribe job is currently running on the server "
            f"(job_id={e.running_job_id}). Wait for it to finish or cancel it before "
            f"starting a new one.\n\nTip: clicking the toolbar button repeatedly "
            f"queues no new work -- the server only handles one essay at a time.",
        )
        return
    except Exception:
        log.exception("failed to submit job")
        dialog.show_error(ctx, "Submit failed", traceback.format_exc())
        return
    log.info("job_id=%s; opening progress dialog", job_id)

    progress = dialog.ProgressDialog(ctx, job_id)
    body, error = progress.execute()

    if progress.cancelled:
        log.info("user cancelled; server job %s may still be running", job_id)
        return
    if error is not None:
        dialog.show_error(ctx, "Transcribe failed", error)
        return
    if body is None:
        dialog.show_error(ctx, "Transcribe failed",
                          "Job ended without a result and without an error.")
        return

    # Cache the fresh transcribe so the next debug run can skip it.
    debug_cache.save_transcribe(body)

    # 5. Show the result. The dialog has a "Grade this essay" button that
    # kicks off /jobs/grade with the transcription text. v1.5 will add a step
    # that lets the user edit the text in Writer before grading -- for v1
    # we grade what came back from the OCR directly.
    log.info("opening result dialog (essay_lines=%d)", len(body.get("essay_lines") or []))
    try:
        dialog.show_text_result(
            ctx,
            f"Compo Tutor - {body.get('language', '?')} "
            f"(avg conf {body.get('confidence', 0):.2f})",
            _format_result(body),
            extra_button=(
                "Grade this essay",
                lambda: run_grade_after_transcribe(ctx, body, language, debug_mode),
            ),
        )
    except Exception:
        log.exception("result dialog failed")
        dialog.show_error(ctx, "Result dialog failed", traceback.format_exc())


def run_grade_after_transcribe(ctx, transcribe_body: dict, language: str,
                               debug_mode: bool = False) -> None:
    """Submit /jobs/grade using the transcription we just got and show the result."""
    log.info("run_grade invoked (debug=%s)", debug_mode)

    if debug_mode:
        cached_grade = debug_cache.load_grade()
        if cached_grade is not None:
            log.info("debug: using cached grade output (skipping LLM)")
            essay_text = transcribe_body.get("essay_text", "")
            _show_grade_result(ctx, cached_grade, essay_text)
            return

    # Live grade path requires the server. Caller may not have ensured it yet
    # (e.g. when we skipped transcribe via the debug cache).
    try:
        server_proc.ensure_server(timeout=60.0)
    except Exception:
        dialog.show_error(ctx, "AI Server error", traceback.format_exc())
        return

    question_text = transcribe_body.get("question_text", "")
    essay_text = transcribe_body.get("essay_text", "")
    if not essay_text.strip():
        dialog.show_error(ctx, "Nothing to grade",
                          "The transcription has no essay text. Cannot grade.")
        return

    # Default to continuous writing for English; ignored for zh.
    paper_type = "continuous"

    log.info("submitting grade job (lang=%s, paper=%s, essay=%d chars)",
             language, paper_type, len(essay_text))
    try:
        job_id = client.start_grade_job(
            language=language,
            paper_type=paper_type,
            question_text=question_text,
            essay_text=essay_text,
        )
    except client.JobBusy as e:
        dialog.show_error(
            ctx, "Compo Tutor busy",
            f"Another job is already running on the server "
            f"(job_id={e.running_job_id}). Wait for it to finish first.",
        )
        return
    except Exception:
        log.exception("failed to submit grade job")
        dialog.show_error(ctx, "Submit failed", traceback.format_exc())
        return

    progress = dialog.ProgressDialog(ctx, job_id)
    body, error = progress.execute()
    if progress.cancelled:
        return
    if error is not None:
        dialog.show_error(ctx, "Grade failed", error)
        return
    if body is None:
        dialog.show_error(ctx, "Grade failed",
                          "Grade ended without a result and without an error.")
        return

    debug_cache.save_grade(body)
    _show_grade_result(ctx, body, essay_text)


def _show_grade_result(ctx, body: dict, essay_text: str) -> None:
    log.info("grade done; opening result dialog")
    try:
        dialog.show_text_result(
            ctx,
            "Compo Tutor - Grade",
            _format_grade_result(body),
            extra_button=(
                "Apply to document",
                lambda: _apply_grade_to_doc(ctx, body, essay_text),
            ),
        )
    except Exception:
        log.exception("grade result dialog failed")
        dialog.show_error(ctx, "Result dialog failed", traceback.format_exc())


def _try_debug_skip_all(ctx) -> bool:
    """If both transcribe AND grade caches exist, apply the cached grade
    directly to the active doc and skip both LLM popups. Returns True if
    handled (caller should return)."""
    cached_t = debug_cache.load_transcribe()
    cached_g = debug_cache.load_grade()
    if cached_t is None or cached_g is None:
        return False
    log.info("debug: both caches present; applying cached grade directly")
    essay_text = cached_t.get("essay_text", "")
    _apply_grade_to_doc(ctx, cached_g, essay_text)
    return True


def _try_debug_skip_transcribe(ctx, language: str) -> bool:
    """If only the transcribe cache exists, hand its body to the grade flow.
    Returns True if handled."""
    cached_t = debug_cache.load_transcribe()
    if cached_t is None:
        return False
    log.info("debug: transcribe cache present; running grade only")
    cached_lang = cached_t.get("language", language)
    run_grade_after_transcribe(ctx, cached_t, cached_lang, debug_mode=True)
    return True


def _apply_grade_to_doc(ctx, grade_body: dict, essay_text: str) -> None:
    """Hand the grade JSON off to writer_ops; report the outcome via dialog."""
    from aitutor import writer_ops

    log.info("applying grade to active Writer doc")
    try:
        result = writer_ops.apply_grade_to_doc(ctx, grade_body, essay_text)
    except Exception:
        log.exception("apply_grade_to_doc raised")
        dialog.show_error(ctx, "Apply failed", traceback.format_exc())
        return

    lines = [
        "Grade applied to the active Writer document.",
        "",
        f"  Backup file:        {result.backup_url or '(doc not saved; no backup made)'}",
        f"  Essay inserted:     {'yes' if result.inserted_essay else 'no (already present)'}",
        f"  Score report:       {'inserted' if result.score_report_inserted else 'skipped'}",
        f"  Improved section:   {'inserted' if result.improved_section_inserted else 'skipped (no improvement_edits)'}",
        "",
        f"  v1 tracked edits:   {result.redlines_applied} applied, {result.redlines_skipped} skipped",
        f"  v1 comments:        {result.comments_applied} applied, {result.comments_skipped} skipped",
        f"  v2 improvements:    {result.improvements_applied} applied, {result.improvements_skipped} skipped",
        f"  v2 comments:        {result.improvement_comments_applied} applied, {result.improvement_comments_skipped} skipped",
    ]
    if result.errors:
        lines.append("")
        lines.append("Errors:")
        for e in result.errors:
            lines.append(f"  - {e}")
    if result.redlines_skipped or result.comments_skipped:
        lines.append("")
        lines.append("Skipped items usually mean the LLM proposed a span that")
        lines.append("does not appear verbatim in the doc (often because the")
        lines.append("user already edited that portion).")
    dialog.show_text_result(ctx, "Compo Tutor - Apply complete", "\n".join(lines))


def _format_grade_result(body: dict) -> str:
    """Render the GradeResponse JSON as a readable plain-text report."""
    out = []
    scores = body.get("scores") or {}
    out.append("=== SCORES ===")
    out.append(f"  Total:        {scores.get('total')}/{scores.get('max_total')}  (band {scores.get('band')})")
    out.append(f"  Content:      {scores.get('content')}")
    out.append(f"  Language:     {scores.get('language')}")
    if scores.get("organization") is not None:
        out.append(f"  Organisation: {scores.get('organization')}")
    out.append("")

    out.append("=== OVERALL FEEDBACK ===")
    out.append(body.get("overall_feedback", "(empty)"))
    out.append("")

    edits = body.get("tracked_edits") or []
    out.append(f"=== TRACKED EDITS ({len(edits)}) ===")
    for i, e in enumerate(edits, 1):
        out.append(f"  {i:2d}. [{e.get('category', '?')}] {e.get('reason', '')}")
        out.append(f"      OLD: {e.get('original_span', '')!r}")
        out.append(f"      NEW: {e.get('suggested_replacement', '')!r}")
    if edits:
        out.append("")

    comments = body.get("comments") or []
    out.append(f"=== COMMENTS ({len(comments)}) ===")
    for i, c in enumerate(comments, 1):
        out.append(f"  {i:2d}. [{c.get('category', '?')}] on \"{(c.get('span') or '')[:80]}...\"")
        out.append(f"      {c.get('comment_text', '')}")
    return "\n".join(out)


def _transcribe_blockers(status: dict) -> list[str]:
    """Return human-readable strings for models that are HARD-required for /transcribe.

    /transcribe now uses Qwen2.5-VL-7B for OCR+captioning, so the **captioner**
    is the only hard-required model. The legacy paddleocr 'detector/rec_zh/rec_en'
    are no longer on the request path; they're left in /models/status for
    backwards compatibility but ignored here. The grader LLM is soft (it's only
    used by /grade later)."""
    out: list[str] = []
    cap = status.get("captioner", {})
    if cap.get("state") != "ready":
        out.append(f"Captioner ({cap.get('name', '?')}): {cap.get('state', '?')}")
    return out


def _soft_warnings(status: dict) -> list[str]:
    out: list[str] = []
    llm = status.get("llm", {})
    if llm.get("state") != "ready":
        out.append(f"LLM ({llm.get('name', '?')}): {llm.get('state', '?')}")
    return out


def _format_result(body: dict) -> str:
    """Render a TranscribeResponse as plain text for the result dialog."""
    parts = []
    parts.append("=== QUESTION ===")
    parts.append(body.get("question_text", "").rstrip() or "(empty)")
    parts.append("")
    parts.append("=== ESSAY ===")
    parts.append(body.get("essay_text", "").rstrip() or "(empty)")
    parts.append("")
    lines = body.get("essay_lines") or []
    if lines:
        parts.append(f"=== {len(lines)} essay lines (line / confidence / bbox) ===")
        for i, L in enumerate(lines, 1):
            bbox = L.get("bbox", [])
            conf = L.get("confidence", 0)
            text = (L.get("text") or "").replace("\n", " ")
            parts.append(f"  {i:2d} ({conf:.2f}) {bbox} :: {text}")
    return "\n".join(parts)
