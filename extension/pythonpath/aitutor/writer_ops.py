"""Apply a grade JSON onto the active Writer document.

This is the highest-risk file in the extension because the UNO Track Changes
and Annotation API is fiddly. The flow is deliberately defensive:

1. Snapshot the current doc to ``<original>.bak.odt`` (skipped for unsaved
   docs -- they have no URL to anchor a backup against).
2. If the OCR'd essay text isn't already present in the doc, append it at the
   end. We do this BEFORE turning Track Changes on so the inserted essay
   isn't itself rendered as a redline insertion.
3. Anchor every ``comments`` annotation while RecordChanges is still OFF.
   Two reasons for this ordering:
     * If we attach annotations after redlines, LO throws
       "no SwTextAttr inserted" because TextField.Annotation doesn't insert
       cleanly into a range that already contains tracked changes.
     * A comment span often overlaps a redline span (e.g. "...小华上了巴工。"
       contains the redline target "巴工"); once the redline replaces the
       text, ``findAll`` can't match the original-form span anymore and the
       comment is silently dropped.
   Anchoring first sidesteps both. Annotations stay anchored across later
   text mutations.
4. Turn on RecordChanges and clear any redline-protection password.
5. For each ``tracked_edits`` entry, find the span and replace it -- with
   RecordChanges on, this becomes a redline delete + redline insert.

Spans that the LLM hallucinated (substring not present in the doc) are
silently skipped and counted -- the server already filters most of these
before returning, but we belt-and-brace here too.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import uno
from com.sun.star.text.ControlCharacter import PARAGRAPH_BREAK

from aitutor.log import get_logger

log = get_logger(__name__)

ANNOTATION_AUTHOR = "AI Tutor"


V2_BOOKMARK_NAME = "_aitutor_v2_start"


@dataclass
class ApplyResult:
    backup_url: str | None = None
    inserted_essay: bool = False
    score_report_inserted: bool = False
    improved_section_inserted: bool = False
    redlines_applied: int = 0
    redlines_skipped: int = 0
    comments_applied: int = 0
    comments_skipped: int = 0
    improvements_applied: int = 0
    improvements_skipped: int = 0
    improvement_comments_applied: int = 0
    improvement_comments_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def apply_grade_to_doc(ctx, grade_body: dict, essay_text: str) -> ApplyResult:
    """Apply the grade JSON to the current Writer document.

    Raises if there is no active Writer doc. Per-edit failures are collected
    in ``result.errors`` rather than aborting the whole apply.
    """
    doc = _get_writer_doc(ctx)
    if doc is None:
        raise RuntimeError("No active Writer document. Open a document first.")

    result = ApplyResult()
    result.backup_url = _backup_doc(doc)

    if essay_text and essay_text not in _get_full_text(doc):
        _insert_essay_text(doc, essay_text)
        result.inserted_essay = True

    scores = grade_body.get("scores") or {}
    feedback = grade_body.get("overall_feedback") or ""
    score_after_v1 = grade_body.get("score_after_v1")
    target_score = grade_body.get("target_score")
    if scores or feedback:
        try:
            _insert_score_report(doc, scores, feedback, score_after_v1, target_score)
            result.score_report_inserted = True
        except Exception as e:
            log.exception("score-report insert failed")
            result.errors.append(f"score report failed: {e}")

    tracked_edits = grade_body.get("tracked_edits") or []
    improvement_edits = grade_body.get("improvement_edits") or []

    # If the LLM provided improvement_edits, append the "Improved Version"
    # section now -- still BEFORE we toggle RecordChanges on, so neither the
    # heading nor the v1-corrected base text is rendered as a redline insert.
    if improvement_edits:
        v1_corrected = _apply_edits_to_text_python(essay_text, tracked_edits)
        try:
            _insert_improved_version_section(doc, v1_corrected, target_score, scores)
            result.improved_section_inserted = True
        except Exception as e:
            log.exception("improved-version section insert failed")
            result.errors.append(f"improved version failed: {e}")

    # Anchor every annotation while RecordChanges is still off:
    #   * Each tracked_edit's ``reason`` becomes a comment on its span in
    #     Section A (the original essay).
    #   * Each improvement_edit's ``reason`` becomes a comment on its span
    #     in Section B (scoped via the bookmark we just placed).
    #   * Any standalone ``comments`` the LLM still produced are anchored to
    #     their spans in Section A.
    for comment in grade_body.get("comments") or []:
        span = comment.get("span") or ""
        text = comment.get("comment_text") or ""
        category = comment.get("category") or "comment"
        occ = int(comment.get("occurrence_index") or 0)
        if not span or not text:
            result.comments_skipped += 1
            continue
        body = f"[{category}] {text}"
        try:
            ok = _add_comment(doc, span, body, occ)
        except Exception as e:
            log.exception("add_comment failed for span=%r", span[:60])
            result.errors.append(f"comment failed for {span[:60]!r}: {e}")
            result.comments_skipped += 1
            continue
        result.comments_applied += 1 if ok else 0
        result.comments_skipped += 0 if ok else 1

    for edit in tracked_edits:
        span = edit.get("original_span") or ""
        reason = edit.get("reason") or ""
        if not span or not reason:
            result.comments_skipped += 1
            continue
        try:
            ok = _add_comment(doc, span, _format_edit_comment(edit), 0)
        except Exception as e:
            log.exception("v1 reason annotation failed for span=%r", span[:60])
            result.errors.append(f"v1 comment failed for {span[:60]!r}: {e}")
            result.comments_skipped += 1
            continue
        result.comments_applied += 1 if ok else 0
        result.comments_skipped += 0 if ok else 1

    if result.improved_section_inserted:
        for edit in improvement_edits:
            span = edit.get("original_span") or ""
            reason = edit.get("reason") or ""
            if not span or not reason:
                result.improvement_comments_skipped += 1
                continue
            try:
                ok = _add_comment_after_bookmark(
                    doc, V2_BOOKMARK_NAME, span, _format_improvement_comment(edit),
                )
            except Exception as e:
                log.exception("v2 reason annotation failed for span=%r", span[:60])
                result.errors.append(f"v2 comment failed for {span[:60]!r}: {e}")
                result.improvement_comments_skipped += 1
                continue
            result.improvement_comments_applied += 1 if ok else 0
            result.improvement_comments_skipped += 0 if ok else 1

    # Now turn on RecordChanges and apply both rounds of redlines.
    _enable_record_changes(doc)

    for edit in tracked_edits:
        span = edit.get("original_span") or ""
        replacement = edit.get("suggested_replacement") or ""
        occ = int(edit.get("occurrence_index") or 0)
        if not span:
            result.redlines_skipped += 1
            continue
        try:
            ok = _tracked_replace(doc, span, replacement, occ)
        except Exception as e:
            log.exception("tracked_replace failed for span=%r", span[:60])
            result.errors.append(f"redline failed for {span[:60]!r}: {e}")
            result.redlines_skipped += 1
            continue
        result.redlines_applied += 1 if ok else 0
        result.redlines_skipped += 0 if ok else 1

    if result.improved_section_inserted:
        for edit in improvement_edits:
            span = edit.get("original_span") or ""
            replacement = edit.get("suggested_replacement") or ""
            if not span or replacement == span:
                result.improvements_skipped += 1
                continue
            try:
                ok = _tracked_replace_after_bookmark(
                    doc, V2_BOOKMARK_NAME, span, replacement,
                )
            except Exception as e:
                log.exception("v2 redline failed for span=%r", span[:60])
                result.errors.append(f"v2 redline failed for {span[:60]!r}: {e}")
                result.improvements_skipped += 1
                continue
            result.improvements_applied += 1 if ok else 0
            result.improvements_skipped += 0 if ok else 1

    log.info(
        "apply done: essay=%s score=%s v2=%s | v1 redlines=%d/%d comments=%d/%d | "
        "v2 redlines=%d/%d comments=%d/%d | errors=%d",
        result.inserted_essay, result.score_report_inserted, result.improved_section_inserted,
        result.redlines_applied, result.redlines_applied + result.redlines_skipped,
        result.comments_applied, result.comments_applied + result.comments_skipped,
        result.improvements_applied, result.improvements_applied + result.improvements_skipped,
        result.improvement_comments_applied,
        result.improvement_comments_applied + result.improvement_comments_skipped,
        len(result.errors),
    )
    return result


def _format_edit_comment(edit: dict) -> str:
    return f"[{edit.get('category', 'edit')}] {edit.get('reason', '')}"


def _format_improvement_comment(edit: dict) -> str:
    return f"[improvement / {edit.get('category', 'edit')}] {edit.get('reason', '')}"


def _apply_edits_to_text_python(text: str, edits: list[dict]) -> str:
    """Apply tracked_edits to ``text`` in-Python -- mirrors the server-side
    helper, but the extension can't import the server module so we inline a
    copy here. Used to compute the v1-corrected essay we insert as the base
    for Section B."""
    out = text
    for e in edits:
        span = e.get("original_span", "")
        replacement = e.get("suggested_replacement", "")
        if span and replacement and span != replacement and span in out:
            out = out.replace(span, replacement, 1)
    return out


# --- Doc lookup + backup -------------------------------------------------

def _get_writer_doc(ctx):
    """Return the current Writer doc, or None if the active component is not
    a Writer document (could be Calc, Impress, Start Center, etc.)."""
    desktop = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx,
    )
    doc = desktop.getCurrentComponent()
    if doc is None:
        return None
    if not doc.supportsService("com.sun.star.text.TextDocument"):
        return None
    return doc


def _backup_doc(doc) -> str | None:
    """Save a copy of the doc to ``<url>.bak.odt``. Returns the backup URL,
    or None if the doc has never been saved (Untitled1 has no URL)."""
    url = doc.getURL()
    if not url:
        log.info("doc is unsaved; skipping backup")
        return None
    backup_url = url + ".bak.odt"
    try:
        doc.storeToURL(backup_url, ())
        log.info("backed up doc to %s", backup_url)
        return backup_url
    except Exception:
        log.exception("backup failed; continuing without backup")
        return None


# --- Doc text helpers ----------------------------------------------------

def _get_full_text(doc) -> str:
    return doc.getText().getString()


def _insert_essay_text(doc, essay_text: str) -> None:
    """Append the essay text to the end of the doc, preserving paragraph
    breaks. Done before Track Changes is turned on, so the inserted body
    isn't rendered as a giant redline insertion."""
    body = doc.getText()
    cursor = body.createTextCursorByRange(body.getEnd())

    # Ensure a clean paragraph break between any existing content and the
    # essay we're appending.
    if body.getString().strip():
        body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)

    paragraphs = essay_text.split("\n")
    for i, para in enumerate(paragraphs):
        if i > 0:
            body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
        if para:
            body.insertString(cursor, para, False)


def _insert_score_report(doc, scores: dict, overall_feedback: str,
                         score_after_v1=None, target_score=None) -> None:
    """Append a heading + 2-column score table + overall-feedback paragraph
    to the end of the doc. Called before RecordChanges is enabled so the
    report isn't rendered as a giant tracked insertion."""
    rows = _score_table_rows(scores, score_after_v1, target_score)
    body = doc.getText()
    cursor = body.createTextCursorByRange(body.getEnd())

    body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
    body.insertString(cursor, "Score Report", False)
    body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)

    if rows:
        table = doc.createInstance("com.sun.star.text.TextTable")
        table.initialize(len(rows), 2)
        body.insertTextContent(cursor, table, False)
        for i, (label, value) in enumerate(rows, start=1):
            table.getCellByName(f"A{i}").setString(label)
            table.getCellByName(f"B{i}").setString(value)
        # The table insertion leaves the cursor before the table; jump to end.
        cursor = body.createTextCursorByRange(body.getEnd())

    if overall_feedback:
        body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
        body.insertString(cursor, "Overall feedback:", False)
        body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
        for i, para in enumerate(overall_feedback.split("\n")):
            if i > 0:
                body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
            if para:
                body.insertString(cursor, para, False)


def _score_table_rows(scores: dict, score_after_v1=None,
                      target_score=None) -> list[tuple[str, str]]:
    """Build the (label, value) row list for the score table. Returns []
    if there's nothing meaningful to show."""
    if not scores:
        return []
    max_total = scores.get("max_total")
    # Infer per-component caps from max_total. EN continuous: 36 (18+18).
    # EN situational: 14 (6+8). ZH composition: 40 (20+20).
    if max_total == 36:
        c_max, l_max = 18, 18
    elif max_total == 14:
        c_max, l_max = 6, 8
    elif max_total == 40:
        c_max, l_max = 20, 20
    else:
        c_max = l_max = None

    def fmt(v, cap):
        if v is None:
            return "-"
        v_str = f"{v:g}"  # 14.0 -> "14"
        return f"{v_str} / {cap}" if cap else v_str

    rows: list[tuple[str, str]] = [("Section", "Score")]
    if scores.get("content") is not None:
        rows.append(("Content", fmt(scores["content"], c_max)))
    if scores.get("language") is not None:
        rows.append(("Language", fmt(scores["language"], l_max)))
    if scores.get("organization") is not None:
        rows.append(("Organization", fmt(scores["organization"], None)))
    if scores.get("total") is not None:
        rows.append(("Total (original)", fmt(scores["total"], max_total)))
    if score_after_v1 is not None:
        rows.append(("After Round 1 fixes", fmt(score_after_v1, max_total)))
    if target_score is not None:
        rows.append(("After Round 2 improvements", fmt(target_score, max_total)))
    # Band is intentionally omitted from the table -- the total score and
    # max_total already convey the same information visually, and the band
    # number on its own can read as a harsh judgement to a primary student.
    return rows if len(rows) > 1 else []


# --- Improved-version section (Section B) -------------------------------

def _insert_improved_version_section(
    doc, v1_corrected_text: str, target_score, scores: dict,
) -> None:
    """Append the heading + Section-B base text (the v1-corrected essay) and
    drop a bookmark at the section's start so later operations can scope
    findNext to this section only.

    Called BEFORE RecordChanges is enabled, so the heading and v1-corrected
    paragraphs aren't rendered as a giant tracked insertion."""
    body = doc.getText()
    cursor = body.createTextCursorByRange(body.getEnd())

    # Heading
    body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
    max_total = scores.get("max_total") if scores else None
    if target_score is not None and max_total:
        heading = f"Improved Version (target {int(target_score)}/{int(max_total)})"
    elif target_score is not None:
        heading = f"Improved Version (target {int(target_score)})"
    else:
        heading = "Improved Version"
    body.insertString(cursor, heading, False)
    body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)

    # Bookmark at section start so findNext can scope subsequent searches.
    # XBookmark exposes Name via XNamed (setName / direct attribute), NOT via
    # XPropertySet -- setPropertyValue("Name", ...) raises "Property is read-only".
    bookmark = doc.createInstance("com.sun.star.text.Bookmark")
    bookmark.Name = V2_BOOKMARK_NAME
    body.insertTextContent(cursor, bookmark, False)

    # Section B body: v1-corrected essay text (paragraph-broken).
    cursor = body.createTextCursorByRange(body.getEnd())
    paragraphs = v1_corrected_text.split("\n")
    for i, para in enumerate(paragraphs):
        if i > 0:
            body.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
        if para:
            body.insertString(cursor, para, False)


def _bookmark_anchor(doc, name: str):
    bookmarks = doc.getBookmarks()
    if not bookmarks.hasByName(name):
        return None
    return bookmarks.getByName(name).getAnchor()


def _add_comment_after_bookmark(
    doc, bookmark_name: str, span: str, comment_text: str,
) -> bool:
    """Anchor an Annotation to ``span``, restricted to the doc region after
    the named bookmark. Returns False if the span isn't found there."""
    anchor = _bookmark_anchor(doc, bookmark_name)
    if anchor is None:
        log.warning("bookmark %s missing; cannot scope comment", bookmark_name)
        return False

    search = doc.createSearchDescriptor()
    search.SearchString = span
    search.SearchCaseSensitive = True
    found = doc.findNext(anchor, search)
    if found is None:
        log.info("v2 comment span not found after bookmark: %r", span[:60])
        return False

    annotation = doc.createInstance("com.sun.star.text.TextField.Annotation")
    annotation.setPropertyValue("Author", ANNOTATION_AUTHOR)
    annotation.setPropertyValue("Content", comment_text)

    text = found.getText()
    text.insertTextContent(found.getStart(), annotation, False)
    return True


def _tracked_replace_after_bookmark(
    doc, bookmark_name: str, span: str, replacement: str,
) -> bool:
    """findNext-from-bookmark version of _tracked_replace -- scopes the
    redline to Section B even if the same span happens to also appear in
    Section A's live (post-redline) text."""
    anchor = _bookmark_anchor(doc, bookmark_name)
    if anchor is None:
        log.warning("bookmark %s missing; cannot scope redline", bookmark_name)
        return False

    search = doc.createSearchDescriptor()
    search.SearchString = span
    search.SearchCaseSensitive = True
    found = doc.findNext(anchor, search)
    if found is None:
        log.info("v2 redline span not found after bookmark: %r", span[:60])
        return False
    found.setString(replacement)
    return True


# --- Track Changes -------------------------------------------------------

def _enable_record_changes(doc) -> None:
    """Turn on RecordChanges if it isn't already, and clear any redline
    protection password (otherwise our edits would be rejected)."""
    try:
        if not doc.getPropertyValue("RecordChanges"):
            doc.setPropertyValue("RecordChanges", True)
            log.info("turned on RecordChanges")
    except Exception:
        log.exception("failed to read/set RecordChanges")
        raise

    try:
        doc.setPropertyValue("RedlineProtectionKey", uno.ByteSequence(b""))
    except Exception:
        # Older LO versions name this differently or refuse to clear it; the
        # apply might still succeed if no protection was set in the first place.
        log.debug("could not clear RedlineProtectionKey (often harmless)")


def _tracked_replace(doc, span: str, replacement: str, occurrence_index: int) -> bool:
    """Replace ``span`` with ``replacement`` at the given occurrence. With
    RecordChanges on, this is rendered as a redline delete + redline insert.
    Returns False if the span couldn't be located."""
    search = doc.createSearchDescriptor()
    search.SearchString = span
    search.SearchCaseSensitive = True
    found = doc.findAll(search)
    count = found.getCount() if found is not None else 0
    if occurrence_index >= count:
        log.info("span not found (occurrence %d of %d): %r",
                 occurrence_index, count, span[:60])
        return False
    range_ = found.getByIndex(occurrence_index)
    range_.setString(replacement)
    return True


# --- Annotations ---------------------------------------------------------

def _add_comment(doc, span: str, comment_text: str, occurrence_index: int) -> bool:
    """Anchor a TextField.Annotation to ``span``. Returns False if the span
    couldn't be located."""
    search = doc.createSearchDescriptor()
    search.SearchString = span
    search.SearchCaseSensitive = True
    found = doc.findAll(search)
    count = found.getCount() if found is not None else 0
    if occurrence_index >= count:
        log.info("comment span not found (occurrence %d of %d): %r",
                 occurrence_index, count, span[:60])
        return False
    range_ = found.getByIndex(occurrence_index)

    annotation = doc.createInstance("com.sun.star.text.TextField.Annotation")
    annotation.setPropertyValue("Author", ANNOTATION_AUTHOR)
    annotation.setPropertyValue("Content", comment_text)

    # Insert as a point comment at the start of the span. We deliberately do
    # NOT use absorb=True over the range -- that codepath either throws "no
    # SwTextAttr inserted" or creates two paired anchor markers (start +
    # end) which surface as duplicate comments in the side panel on some LO
    # builds. A single point marker at the span's beginning is unambiguous
    # and reliable across LO versions; the comment text itself can quote the
    # span when context matters.
    text = range_.getText()
    text.insertTextContent(range_.getStart(), annotation, False)
    return True
