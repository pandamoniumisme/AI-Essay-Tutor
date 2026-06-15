// Run: node --test server/tests/js/
import { test } from "node:test";
import assert from "node:assert/strict";

const base = "../../aitutor_server/static/js/";
const { resolveOccurrence, applyEdits, buildAnnotation } = await import(base + "annotate.js");
const { scoreRows } = await import(base + "scores.js");

test("resolveOccurrence finds nth occurrence", () => {
  const t = "the cat sat on the mat";
  assert.equal(resolveOccurrence(t, "the", 0), 0);
  assert.equal(resolveOccurrence(t, "the", 1), 15);
  assert.equal(resolveOccurrence(t, "dog", 0), -1);
  assert.equal(resolveOccurrence(t, "the", 2), -1);
});

test("buildAnnotation emits del + ins for an edit", () => {
  const t = "I goed home.";
  const { segments, skipped } = buildAnnotation(t, [
    { original_span: "goed", suggested_replacement: "went", reason: "past tense", category: "spelling" },
  ]);
  assert.equal(skipped.length, 0);
  const types = segments.map((s) => s.type);
  assert.deepEqual(types, ["text", "del", "ins", "text"]);
  assert.equal(segments[1].text, "goed");
  assert.equal(segments[2].text, "went");
  assert.equal(segments[2].reason, "past tense");
});

test("buildAnnotation drops a hallucinated span", () => {
  const { segments, skipped } = buildAnnotation("hello world", [
    { original_span: "not here", suggested_replacement: "x", reason: "r", category: "spelling" },
  ]);
  assert.equal(skipped.length, 1);
  assert.equal(skipped[0].kind, "edit");
  assert.equal(segments.length, 1);
  assert.equal(segments[0].text, "hello world");
});

test("buildAnnotation drops the second of two overlapping edits", () => {
  const t = "abcdef";
  const { skipped, segments } = buildAnnotation(t, [
    { original_span: "abcd", suggested_replacement: "X", reason: "r", category: "spelling" },
    { original_span: "cdef", suggested_replacement: "Y", reason: "r", category: "spelling" },
  ]);
  assert.equal(skipped.length, 1);
  const ins = segments.filter((s) => s.type === "ins");
  assert.equal(ins.length, 1);
  assert.equal(ins[0].text, "X");
});

test("buildAnnotation anchors a comment as a point marker", () => {
  const t = "good story here";
  const { segments } = buildAnnotation(t, [], [
    { span: "story", occurrence_index: 0, comment_text: "nice", category: "praise" },
  ]);
  const cmt = segments.find((s) => s.type === "comment");
  assert.ok(cmt);
  assert.equal(cmt.n, 1);
  assert.equal(cmt.comment.comment_text, "nice");
  // marker sits before "story"
  const before = segments.slice(0, segments.indexOf(cmt)).filter((s) => s.type === "text").map((s) => s.text).join("");
  assert.equal(before, "good ");
});

test("applyEdits replaces first occurrence only", () => {
  assert.equal(applyEdits("the the the", [
    { original_span: "the", suggested_replacement: "a" },
  ]), "a the the");
});

test("scoreRows infers caps and omits band", () => {
  const rows = scoreRows({ content: 14, language: 15, total: 29, max_total: 40, band: 4 }, 31, 34);
  const map = Object.fromEntries(rows);
  assert.equal(map["Content"], "14 / 20");
  assert.equal(map["Language"], "15 / 20");
  assert.equal(map["Total (original)"], "29 / 40");
  assert.equal(map["After Round 1 fixes"], "31 / 40");
  assert.equal(map["After Round 2 improvements"], "34 / 40");
  assert.ok(!("Band" in map));
});
