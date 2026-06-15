// Span-anchoring engine: the browser replacement for the LibreOffice
// writer_ops.py redline/comment placement.
//
// Pure and DOM-free so it can be unit-tested under node. Given the essay text
// plus the grader's tracked_edits and comments (each carrying an
// `original_span`/`span` and an `occurrence_index`), it produces a flat list of
// render segments. A separate render step (render.js) turns segments into DOM.
//
// Design choices mirror writer_ops.py:
//   * Edits are text mutations -> a struck-through deletion + an inserted
//     replacement. Overlapping edits can't both apply, so later overlappers are
//     dropped and counted (writer_ops counted "skipped" redlines the same way).
//   * Comments are POINT markers anchored at the start of their span, never
//     range highlights. writer_ops settled on point markers because range
//     annotations broke when a comment span overlapped a redline span. Points
//     sidestep overlap entirely.

/**
 * Offset of the `occ`-th (0-based) occurrence of `span` in `text`, or -1.
 * @param {string} text @param {string} span @param {number} occ
 */
export function resolveOccurrence(text, span, occ = 0) {
  if (!span) return -1;
  let idx = -1;
  for (let k = 0; k <= occ; k++) {
    idx = text.indexOf(span, idx + 1);
    if (idx === -1) return -1;
  }
  return idx;
}

/**
 * Apply tracked edits to `text` in JS, first matching occurrence per edit.
 * Mirrors the server's _apply_edits_to_text so the "Improved Version" base text
 * matches what the grader validated improvement_edits against.
 */
export function applyEdits(text, edits) {
  let out = text;
  for (const e of edits) {
    const span = e.original_span || "";
    const repl = e.suggested_replacement || "";
    if (span && repl && span !== repl && out.includes(span)) {
      out = out.replace(span, repl);
    }
  }
  return out;
}

/**
 * Build the render segment list.
 *
 * @param {string} text  the essay text the edits/comments were authored against
 * @param {Array} edits  tracked_edits or improvement_edits
 * @param {Array} comments  RubricComment-shaped objects (may be empty)
 * @returns {{segments: Array, skipped: Array}}
 *   segments: ordered {type:'text'|'del'|'ins'|'comment', ...}
 *   skipped:  {kind:'edit'|'comment', item} entries that couldn't be placed
 */
export function buildAnnotation(text, edits = [], comments = []) {
  const skipped = [];

  // Resolve edits to [start,end) ranges; sort; drop overlaps.
  const resolved = [];
  for (const e of edits) {
    const start = resolveOccurrence(text, e.original_span, e.occurrence_index || 0);
    if (start === -1) { skipped.push({ kind: "edit", item: e }); continue; }
    resolved.push({ start, end: start + e.original_span.length, edit: e });
  }
  resolved.sort((a, b) => a.start - b.start);
  const accepted = [];
  let lastEnd = 0;
  for (const r of resolved) {
    if (r.start < lastEnd) { skipped.push({ kind: "edit", item: r.edit }); continue; }
    accepted.push(r);
    lastEnd = r.end;
  }

  // Resolve comments to point offsets; sort.
  const points = [];
  let cn = 0;
  for (const c of comments) {
    const at = resolveOccurrence(text, c.span, c.occurrence_index || 0);
    if (at === -1) { skipped.push({ kind: "comment", item: c }); continue; }
    points.push({ at, comment: c, n: ++cn });
  }
  points.sort((a, b) => a.at - b.at);

  // Merge into ordered segments.
  const segments = [];
  let pos = 0;
  let ci = 0;
  const flushCommentsUpTo = (limit) => {
    while (ci < points.length && points[ci].at <= limit) {
      const at = points[ci].at;
      if (at > pos) { segments.push({ type: "text", text: text.slice(pos, at) }); pos = at; }
      segments.push({ type: "comment", comment: points[ci].comment, n: points[ci].n });
      ci++;
    }
  };

  for (const r of accepted) {
    flushCommentsUpTo(r.start);
    if (r.start > pos) { segments.push({ type: "text", text: text.slice(pos, r.start) }); pos = r.start; }
    segments.push({ type: "del", text: text.slice(r.start, r.end) });
    segments.push({
      type: "ins",
      text: r.edit.suggested_replacement,
      reason: r.edit.reason,
      category: r.edit.category,
    });
    pos = r.end;
  }
  flushCommentsUpTo(text.length);
  if (pos < text.length) segments.push({ type: "text", text: text.slice(pos) });

  return { segments, skipped };
}
