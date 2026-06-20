// App controller: home (recent sessions) -> capture -> review -> marked.
// No framework. Work is persisted server-side, so a session created on a phone
// shows up in the recent list on a desktop; opening it polls until it's marked.
//
// Top-level navigation is hash-routed (#new, #s/<id>) so a session link can be
// opened on another device. Within a session, screens are rendered directly.

import * as api from "./api.js";
import { renderAnnotated, renderCommentList } from "./render.js";
import { applyEdits } from "./annotate.js";
import { scoreRows } from "./scores.js";

const MAX_EDGE = 2000; // client-side downscale ceiling (handwriting stays legible)
const POLL_MS = 2500;

const state = {
  language: "zh-Hans",
  paperType: "continuous",
  questionFiles: [],
  essayFiles: [],
};

// Bumped on every screen render; in-flight poll loops stop when it changes.
let nav = 0;

const app = () => document.getElementById("app");
const overlay = () => document.getElementById("overlay");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const STATUS = {
  created: { label: "Queued", cls: "badge" },
  transcribing: { label: "Transcribing…", cls: "badge work" },
  transcribed: { label: "Ready to grade", cls: "badge ready" },
  grading: { label: "Grading…", cls: "badge work" },
  graded: { label: "Marked", cls: "badge done" },
  error: { label: "Error", cls: "badge err" },
};

// --- tiny DOM helper -----------------------------------------------------

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

function showOverlay(msg) {
  document.getElementById("overlay-msg").textContent = msg || "Working…";
  overlay().classList.remove("hidden");
}
function hideOverlay() { overlay().classList.add("hidden"); }

function ago(epoch) {
  const s = Math.max(0, Date.now() / 1000 - epoch);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

const langLabel = (l) => (l === "en" ? "English" : "中文");

function goHome() { location.hash = ""; }
function goNew() { location.hash = "#new"; }
function goSession(id) { location.hash = `#s/${id}`; }

// --- image downscale -----------------------------------------------------

async function downscale(file) {
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, MAX_EDGE / Math.max(bmp.width, bmp.height));
    if (scale >= 1) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.9));
    return blob ? new File([blob], (file.name || "page") + ".jpg", { type: "image/jpeg" }) : file;
  } catch {
    return file;
  }
}

// --- health banner -------------------------------------------------------

async function refreshHealth() {
  const el = document.getElementById("health");
  try {
    const hh = await api.health();
    if (hh.reachable) {
      el.className = "health ok";
      el.textContent = `On your AI server · ${hh.model}`;
    } else {
      el.className = "health warn";
      el.textContent = "AI server (Ollama) unreachable.";
    }
  } catch {
    el.className = "health warn";
    el.textContent = "Server unreachable.";
  }
}

// --- screen: home (recent sessions) --------------------------------------

async function renderHome() {
  const myNav = ++nav;
  const root = app();
  clear(root);

  root.appendChild(h("section", { class: "card" },
    h("h2", {}, "AI Essay Tutor"),
    h("p", { class: "privacy" }, "Everything stays on your AI server — nothing leaves your private network."),
    h("div", { class: "actions" },
      h("button", { class: "primary", onclick: goNew }, "＋ New essay"))));

  const listCard = h("section", { class: "card" }, h("h2", {}, "Recent"));
  const listBox = h("div", { class: "session-list" }, h("p", { class: "hint" }, "Loading…"));
  listCard.appendChild(listBox);
  root.appendChild(listCard);

  // Poll the list so a session shot on the phone appears here on the desktop.
  while (myNav === nav) {
    let sessions;
    try {
      sessions = await api.listSessions();
    } catch {
      if (myNav === nav) { clear(listBox); listBox.appendChild(h("p", { class: "hint" }, "Server unreachable.")); }
      await sleep(POLL_MS);
      continue;
    }
    if (myNav !== nav) return;
    drawSessionList(listBox, sessions);
    await sleep(POLL_MS * 1.5);
  }
}

function drawSessionList(box, sessions) {
  clear(box);
  if (!sessions.length) {
    box.appendChild(h("p", { class: "hint" }, "No essays yet. Tap “New essay” to start."));
    return;
  }
  for (const s of sessions) {
    const meta = STATUS[s.status] || STATUS.created;
    const del = h("button", {
      class: "rm-row", title: "delete",
      onclick: async (e) => {
        e.stopPropagation();
        if (!confirm("Delete this session?")) return;
        try { await api.deleteSession(s.id); row.remove(); } catch (err) { alert(err.message); }
      },
    }, "×");
    const row = h("div", { class: "session-row", onclick: () => goSession(s.id) },
      h("span", { class: meta.cls }, meta.label),
      h("span", { class: "session-title" }, s.title || "(untitled)"),
      h("span", { class: "session-meta" }, `${langLabel(s.language)} · ${ago(s.updated_at)}`),
      del);
    box.appendChild(row);
  }
}

// --- screen: capture -----------------------------------------------------

function fileSlot(label, kind) {
  const list = h("div", { class: "thumbs" });

  const drawThumbs = () => {
    clear(list);
    const files = kind === "question" ? state.questionFiles : state.essayFiles;
    files.forEach((f, i) => {
      const url = URL.createObjectURL(f);
      const img = h("img", { src: url, alt: f.name || "page" });
      const rm = h("button", {
        class: "rm", title: "remove",
        onclick: () => { files.splice(i, 1); drawThumbs(); },
      }, "×");
      list.appendChild(h("div", { class: "thumb" }, img, rm));
    });
  };

  const addFiles = (fileList) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    if (kind === "question") state.questionFiles = state.questionFiles.concat(files);
    else state.essayFiles = state.essayFiles.concat(files);
    drawThumbs();
  };

  const pickButton = (text, camera) => {
    const attrs = { type: "file", accept: "image/*", class: "file-input",
      onchange: (e) => { addFiles(e.target.files); e.target.value = ""; } };
    if (camera) attrs.capture = "environment"; else attrs.multiple = true;
    return h("label", { class: "pick-btn" }, text, h("input", attrs));
  };

  return h("div", { class: "slot" },
    h("label", {}, label),
    h("div", { class: "pick-row" },
      pickButton("📷 Camera", true),
      pickButton("🖼 Gallery", false)),
    list);
}

function renderCapture() {
  ++nav;
  state.questionFiles = [];
  state.essayFiles = [];
  const root = app();
  clear(root);

  const enOnly = h("div", { class: "paper-row" + (state.language === "en" ? "" : " hidden") },
    h("label", {}, "Paper type:"),
    h("select", { onchange: (e) => { state.paperType = e.target.value; } },
      h("option", { value: "continuous", selected: state.paperType === "continuous" }, "Continuous (36)"),
      h("option", { value: "situational", selected: state.paperType === "situational" }, "Situational (14)")));

  const langRadio = (val, text) =>
    h("label", { class: "radio" },
      h("input", {
        type: "radio", name: "lang", value: val, checked: state.language === val,
        onchange: () => { state.language = val; enOnly.classList.toggle("hidden", val !== "en"); },
      }), text);

  root.appendChild(h("section", { class: "card" },
    h("h2", {}, "New essay"),
    h("p", { class: "privacy" }, "Photos are processed on your own AI server and never leave your network."),
    h("div", { class: "lang-row" },
      h("span", {}, "Language:"),
      langRadio("zh-Hans", "简体中文"),
      langRadio("en", "English")),
    enOnly,
    fileSlot("Question pages (in order)", "question"),
    fileSlot("Essay pages (in order)", "essay"),
    h("div", { class: "actions" },
      h("button", { onclick: goHome }, "← Home"),
      h("button", { class: "primary", onclick: onCreate }, "Transcribe"))));
}

async function onCreate() {
  if (!state.questionFiles.length || !state.essayFiles.length) {
    alert("Add at least one question page and one essay page.");
    return;
  }
  showOverlay("Uploading…");
  try {
    const q = await Promise.all(state.questionFiles.map(downscale));
    const e = await Promise.all(state.essayFiles.map(downscale));
    const { id } = await api.createSession(q, e, state.language, state.paperType);
    goSession(id); // hashchange -> openSession -> waits on transcription
  } catch (err) {
    alert("Couldn't start:\n" + err.message);
  } finally {
    hideOverlay();
  }
}

// --- session routing + waiting -------------------------------------------

async function openSession(id) {
  showOverlay("Loading…");
  let s;
  try {
    s = await api.getSession(id);
  } catch (err) {
    hideOverlay();
    renderMessage("Session not found", err.message, true);
    return;
  }
  hideOverlay();
  routeSession(s);
}

function routeSession(s) {
  switch (s.status) {
    case "graded": return renderResults(s);
    case "transcribed": return renderReview(s);
    case "error": return renderError(s);
    case "grading": return waitThenRoute(s.id, "Grading the essay…");
    default: return waitThenRoute(s.id, "Transcribing the essay…"); // created / transcribing
  }
}

async function waitThenRoute(id, msg) {
  renderWaiting(id, msg);
  const myNav = nav;
  while (myNav === nav) {
    let s;
    try {
      s = await api.getSession(id);
    } catch {
      await sleep(POLL_MS);
      continue;
    }
    if (myNav !== nav) return;
    if (["transcribed", "graded", "error"].includes(s.status)) {
      routeSession(s);
      return;
    }
    const line = document.getElementById("wait-status");
    if (line) line.textContent = (STATUS[s.status] || STATUS.created).label;
    await sleep(POLL_MS);
  }
}

function copyLinkButton() {
  return h("button", {
    onclick: (e) => {
      navigator.clipboard?.writeText(location.href);
      e.target.textContent = "Link copied ✓";
    },
  }, "Copy link for another device");
}

function renderWaiting(id, msg) {
  ++nav;
  const root = app();
  clear(root);
  root.appendChild(h("section", { class: "card waiting" },
    h("div", { class: "spinner" }),
    h("h2", {}, msg),
    h("p", { id: "wait-status", class: "hint" }, "Working…"),
    h("p", { class: "hint" }, "This runs on your AI server — you can close this and pick it up on any device from the Home list."),
    h("div", { class: "actions" },
      h("button", { onclick: goHome }, "← Home"),
      copyLinkButton())));
}

function renderMessage(title, body, showHome) {
  ++nav;
  const root = app();
  clear(root);
  root.appendChild(h("section", { class: "card" },
    h("h2", {}, title),
    h("p", { class: "hint" }, body || ""),
    showHome ? h("div", { class: "actions" }, h("button", { onclick: goHome }, "← Home")) : null));
}

function renderError(s) {
  ++nav;
  const root = app();
  clear(root);
  root.appendChild(h("section", { class: "card" },
    h("h2", {}, "Something went wrong"),
    h("p", { class: "mem-warn" }, s.error || "Unknown error."),
    h("div", { class: "actions" },
      h("button", { onclick: goHome }, "← Home"),
      h("button", {
        class: "primary",
        onclick: async () => {
          try { await api.retranscribe(s.id); openSession(s.id); } catch (e) { alert(e.message); }
        },
      }, "Retry transcription"))));
}

// --- screen: review ------------------------------------------------------

function renderReview(s) {
  ++nav;
  const root = app();
  clear(root);

  const qta = h("textarea", { class: "edit", rows: "5" });
  qta.value = s.question_text || "";
  const eta = h("textarea", { class: "edit", rows: "16" });
  eta.value = s.essay_text || "";

  root.appendChild(h("section", { class: "card" },
    h("h2", {}, "Review transcription"),
    h("p", { class: "hint" }, "Fix any OCR slips before grading — the grader sees this text."),
    h("label", {}, "Question"),
    qta,
    h("label", {}, "Essay"),
    eta,
    h("div", { class: "actions" },
      h("button", { onclick: goHome }, "← Home"),
      h("button", {
        class: "primary",
        onclick: async () => {
          showOverlay("Starting grading…");
          try {
            await api.saveTranscription(s.id, qta.value, eta.value);
            await api.gradeSession(s.id);
            hideOverlay();
            openSession(s.id);
          } catch (err) {
            hideOverlay();
            alert("Couldn't grade:\n" + err.message);
          }
        },
      }, "Grade this essay"))));
}

// --- screen: marked results ----------------------------------------------

function scoreTable(g) {
  const rows = scoreRows(g.scores, g.score_after_v1, g.target_score);
  if (!rows.length) return null;
  const tbody = h("tbody", {}, ...rows.map(([label, value]) =>
    h("tr", {}, h("th", {}, label), h("td", {}, value))));
  return h("table", { class: "scores" }, tbody);
}

function annotatedBlock(title, text, edits, comments) {
  const { node, comments: cl, skipped } = renderAnnotated(text, edits, comments);
  const parts = [h("h3", {}, title), node];
  if (cl.length) parts.push(renderCommentList(cl));
  if (skipped) parts.push(h("p", { class: "skipped" },
    `${skipped} annotation(s) couldn't be placed (text edited after transcription).`));
  return h("div", { class: "annotated" }, ...parts);
}

function renderResults(s) {
  ++nav;
  const root = app();
  clear(root);
  const g = s.grade;
  const essay = s.essay_text;

  const section = h("section", { class: "card results" }, h("h2", {}, "Marked essay"));

  const table = scoreTable(g);
  if (table) section.appendChild(table);

  const r1Comments = (g.comments || []).concat(
    (g.tracked_edits || []).map((e) => ({
      span: e.original_span,
      occurrence_index: e.occurrence_index || 0,
      comment_text: e.reason,
      category: e.category,
    })));
  section.appendChild(annotatedBlock("Original (Round 1: mechanical fixes)",
    essay, g.tracked_edits || [], r1Comments));

  if ((g.improvement_edits || []).length) {
    const v1 = applyEdits(essay, g.tracked_edits || []);
    const r2Comments = (g.improvement_edits || []).map((e) => ({
      span: e.original_span,
      occurrence_index: e.occurrence_index || 0,
      comment_text: e.reason,
      category: e.category,
    }));
    const target = g.target_score != null ? ` (target ${Math.round(g.target_score)}/${g.scores.max_total})` : "";
    section.appendChild(annotatedBlock("Improved Version" + target,
      v1, g.improvement_edits, r2Comments));
  }

  if (g.overall_feedback) {
    section.appendChild(h("div", { class: "feedback" },
      h("h3", {}, "Overall feedback"),
      h("p", {}, g.overall_feedback)));
  }

  section.appendChild(h("div", { class: "actions" },
    h("button", { onclick: goHome }, "← Home"),
    h("button", { onclick: () => renderReview(s) }, "Edit text & re-grade"),
    h("button", { class: "primary", onclick: goNew }, "Grade another"),
    h("button", { onclick: () => window.print() }, "Print / Save PDF")));

  root.appendChild(section);
}

// --- router + boot -------------------------------------------------------

function router() {
  const hash = location.hash.replace(/^#/, "");
  if (hash === "new") return renderCapture();
  const m = hash.match(/^s\/(.+)$/);
  if (m) return openSession(m[1]);
  return renderHome();
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

window.addEventListener("hashchange", router);
refreshHealth();
router();
