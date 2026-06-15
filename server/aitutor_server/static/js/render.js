// DOM rendering for annotated essays. Uses textContent everywhere (never
// innerHTML with model output) so essay/LLM text can't inject markup.

import { buildAnnotation } from "./annotate.js";

/**
 * Render an annotated essay block.
 * @returns {{node: HTMLElement, comments: Array, skipped: number}}
 */
export function renderAnnotated(text, edits = [], comments = []) {
  const { segments, skipped } = buildAnnotation(text, edits, comments);
  const node = document.createElement("div");
  node.className = "essay";

  const commentList = [];
  for (const seg of segments) {
    if (seg.type === "text") {
      node.appendChild(document.createTextNode(seg.text));
    } else if (seg.type === "del") {
      const del = document.createElement("del");
      del.textContent = seg.text;
      node.appendChild(del);
    } else if (seg.type === "ins") {
      const ins = document.createElement("ins");
      ins.textContent = seg.text;
      if (seg.reason) ins.title = `[${seg.category || "edit"}] ${seg.reason}`;
      node.appendChild(ins);
    } else if (seg.type === "comment") {
      const sup = document.createElement("sup");
      sup.className = "cmt-marker";
      sup.id = `cmt-${seg.n}`;
      sup.textContent = `[${seg.n}]`;
      const c = seg.comment;
      sup.title = `[${c.category || "comment"}] ${c.comment_text || ""}`;
      node.appendChild(sup);
      commentList.push({ n: seg.n, category: c.category, text: c.comment_text });
    }
  }
  return { node, comments: commentList, skipped: skipped.length };
}

/** Build the side list of comments that accompanies an annotated block. */
export function renderCommentList(comments) {
  const ul = document.createElement("ol");
  ul.className = "comment-list";
  for (const c of comments) {
    const li = document.createElement("li");
    li.value = c.n;
    const tag = document.createElement("span");
    tag.className = "cat";
    tag.textContent = c.category || "comment";
    li.appendChild(tag);
    li.appendChild(document.createTextNode(" " + (c.text || "")));
    ul.appendChild(li);
  }
  return ul;
}
