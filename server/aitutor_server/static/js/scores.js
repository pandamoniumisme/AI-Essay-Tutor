// Score-report rows. Mirrors writer_ops._score_table_rows: infer per-component
// caps from max_total (EN continuous 36=18/18, EN situational 14=6/8,
// ZH 40=20/20). Band is intentionally omitted -- the total conveys the same
// thing and a bare band number reads harshly to a P6 student.

function caps(maxTotal) {
  if (maxTotal === 36) return [18, 18];
  if (maxTotal === 14) return [6, 8];
  if (maxTotal === 40) return [20, 20];
  return [null, null];
}

function fmt(v, cap) {
  if (v === null || v === undefined) return "-";
  const s = Number.isInteger(v) ? String(v) : String(+v.toFixed(1));
  return cap ? `${s} / ${cap}` : s;
}

/**
 * @returns {Array<[string,string]>} (label, value) rows; [] if nothing to show.
 */
export function scoreRows(scores, scoreAfterV1, targetScore) {
  if (!scores) return [];
  const maxTotal = scores.max_total;
  const [cMax, lMax] = caps(maxTotal);
  const rows = [];
  if (scores.content != null) rows.push(["Content", fmt(scores.content, cMax)]);
  if (scores.language != null) rows.push(["Language", fmt(scores.language, lMax)]);
  if (scores.organization != null) rows.push(["Organization", fmt(scores.organization, null)]);
  if (scores.total != null) rows.push(["Total (original)", fmt(scores.total, maxTotal)]);
  if (scoreAfterV1 != null) rows.push(["After Round 1 fixes", fmt(scoreAfterV1, maxTotal)]);
  if (targetScore != null) rows.push(["After Round 2 improvements", fmt(targetScore, maxTotal)]);
  return rows;
}
