// App controller: capture -> transcription review -> annotated results.
// No framework -- each screen re-renders into #app and wires its own handlers.

import * as api from "./api.js";
import { renderAnnotated, renderCommentList } from "./render.js";
import { applyEdits } from "./annotate.js";
import { scoreRows } from "./scores.js";

const MAX_EDGE = 2000; // client-side downscale ceiling (handwriting stays legible)

const state = {
  language: "zh-Hans",
  paperType: "continuous",
  questionFiles: [],
  essayFiles: [],
  transcript: null, // {language, question_text, essay_text}
  grade: null,
};

const app = () => document.getElementById("app");
const overlay = () => document.getElementById("overlay");

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
    if (hh.on_device) {
      // On-device build: show the RAM-based model recommendation at setup,
      // before any download.
      el.className = "health ok";
      if (hh.model_ready) {
        el.textContent = `on-device · ${hh.model}`;
      } else {
        const rec = hh.recommended_model_name
          ? ` · recommended ${hh.recommended_model_name} (~${hh.recommended_download_gb} GB)` : "";
        el.textContent = `device ${hh.ram_gb} GB${rec} · model not downloaded`;
      }
    } else if (hh.key_present) {
      el.className = "health ok";
      el.textContent = `${hh.provider_label || hh.provider} · ${hh.model}`;
    } else {
      el.className = "health warn";
      el.textContent = `No API key for ${hh.provider_label || hh.provider || "the provider"} — set it and restart.`;
    }
  } catch {
    el.className = "health warn";
    el.textContent = "Server unreachable.";
  }
}

// --- screen 1: capture ---------------------------------------------------

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

  // A button that wraps a hidden file input. `camera` sets capture so the
  // WebView opens the camera; otherwise it's the gallery/file picker.
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
  const root = app();
  clear(root);

  const enOnly = h("div", { class: "paper-row" + (state.language === "en" ? "" : " hidden") },
    h("label", {}, "Paper type:"),
    h("select", {
      onchange: (e) => { state.paperType = e.target.value; },
    },
      h("option", { value: "continuous", selected: state.paperType === "continuous" }, "Continuous (36)"),
      h("option", { value: "situational", selected: state.paperType === "situational" }, "Situational (14)")));

  const langRadio = (val, text) =>
    h("label", { class: "radio" },
      h("input", {
        type: "radio", name: "lang", value: val, checked: state.language === val,
        onchange: () => {
          state.language = val;
          enOnly.classList.toggle("hidden", val !== "en");
        },
      }),
      text);

  const settings = api.getSettings();   // null on the web build
  let privacy;
  if (settings && !settings.online) {
    privacy = "Everything stays on your device — nothing is uploaded.";
  } else {
    const label = providerLabel((settings && settings.provider) || null);
    privacy = `Photos and text are sent to ${label} for processing.`;
  }

  const actions = h("div", { class: "actions" },
    h("button", { class: "primary", onclick: onTranscribe }, "Transcribe"));
  if (api.hasSettings()) {
    actions.appendChild(h("button", { onclick: renderSettings }, "⚙ Settings"));
  }

  root.appendChild(h("section", { class: "card" },
    h("h2", {}, "1. Capture"),
    h("p", { class: "privacy" }, privacy),
    h("div", { class: "lang-row" },
      h("span", {}, "Language:"),
      langRadio("zh-Hans", "简体中文"),
      langRadio("en", "English")),
    enOnly,
    fileSlot("Question pages (in order)", "question"),
    fileSlot("Essay pages (in order)", "essay"),
    actions));
}

function providerLabel(id) {
  if (id === "dashscope") return "Alibaba Cloud (Qwen)";
  if (id === "gemini") return "Gemini";
  return "your configured AI provider";
}

// --- settings screen (Android only) --------------------------------------

function renderSettings() {
  const root = app();
  clear(root);
  const s = api.getSettings() || { online: false, provider: "gemini", geminiKey: "", dashscopeKey: "", geminiModel: "", dashscopeModel: "", offlineModel: "auto", ramGb: 0, recommendedModelName: "Qwen3.5-2B" };

  // --- offline block: recommended model + 2B/4B choice ---
  const offlineBlock = h("div", { class: "online-block" + (s.online ? " hidden" : "") },
    h("p", { class: "hint" },
      `This device has ${s.ramGb} GB RAM — recommended: ${s.recommendedModelName}.`),
    h("label", {}, "On-device model"),
    h("select", { onchange: (e) => { s.offlineModel = e.target.value; } },
      h("option", { value: "auto", selected: s.offlineModel === "auto" },
        `Recommended (${s.recommendedModelName})`),
      h("option", { value: "qwen3.5-2b", selected: s.offlineModel === "qwen3.5-2b" }, "Qwen3.5-2B (smaller, fits 8 GB)"),
      h("option", { value: "qwen3.5-4b", selected: s.offlineModel === "qwen3.5-4b" }, "Qwen3.5-4B (better, needs ~12 GB)")),
    h("p", { class: "hint" }, "4B may be too large for phones under 12 GB."));

  const onlineBlock = h("div", { class: "online-block" + (s.online ? "" : " hidden") });
  const keyInput = h("input", { type: "password", class: "edit", placeholder: "Paste API key" });
  const modelInput = h("input", { type: "text", class: "edit" });
  const providerSel = h("select", {
    onchange: (e) => { s.provider = e.target.value; syncProviderFields(); },
  },
    h("option", { value: "gemini", selected: s.provider === "gemini" }, "Gemini"),
    h("option", { value: "dashscope", selected: s.provider === "dashscope" }, "Alibaba Cloud (Qwen)"));

  function syncProviderFields() {
    const isDash = s.provider === "dashscope";
    keyInput.value = isDash ? s.dashscopeKey : s.geminiKey;
    modelInput.value = isDash ? s.dashscopeModel : s.geminiModel;
    modelInput.placeholder = isDash ? "qwen3.5-flash" : "gemini-3.5-flash";
  }
  keyInput.addEventListener("input", () => {
    if (s.provider === "dashscope") s.dashscopeKey = keyInput.value; else s.geminiKey = keyInput.value;
  });
  modelInput.addEventListener("input", () => {
    if (s.provider === "dashscope") s.dashscopeModel = modelInput.value; else s.geminiModel = modelInput.value;
  });
  syncProviderFields();

  onlineBlock.appendChild(h("label", {}, "Provider"));
  onlineBlock.appendChild(providerSel);
  onlineBlock.appendChild(h("label", {}, "API key"));
  onlineBlock.appendChild(keyInput);
  onlineBlock.appendChild(h("label", {}, "Model (optional)"));
  onlineBlock.appendChild(modelInput);
  onlineBlock.appendChild(h("p", { class: "hint" }, "Essays are sent to this provider when online."));

  const modeRadio = (online, text, sub) =>
    h("label", { class: "radio mode" },
      h("input", {
        type: "radio", name: "mode", checked: s.online === online,
        onchange: () => {
          s.online = online;
          onlineBlock.classList.toggle("hidden", !online);
          offlineBlock.classList.toggle("hidden", online);
        },
      }),
      h("span", {}, text), sub ? h("span", { class: "hint" }, " " + sub) : null);

  root.appendChild(h("section", { class: "card" },
    h("h2", {}, "Settings"),
    h("div", {}, modeRadio(false, "On-device (offline)", "— private, slower")),
    h("div", {}, modeRadio(true, "Online provider", "— faster, sends data out")),
    offlineBlock,
    onlineBlock,
    h("div", { class: "actions" },
      h("button", { onclick: renderCapture }, "← Back"),
      h("button", {
        class: "primary",
        onclick: () => {
          api.saveSettings(s);
          refreshHealth();
          renderCapture();
        },
      }, "Save"))));
}

async function onTranscribe() {
  if (!state.questionFiles.length || !state.essayFiles.length) {
    alert("Add at least one question page and one essay page.");
    return;
  }
  showOverlay("Transcribing…");
  try {
    const q = await Promise.all(state.questionFiles.map(downscale));
    const e = await Promise.all(state.essayFiles.map(downscale));
    state.transcript = await api.transcribe(q, e, state.language);
    renderReview();
  } catch (err) {
    alert("Transcribe failed:\n" + err.message);
  } finally {
    hideOverlay();
  }
}

// --- screen 2: transcription review --------------------------------------

function renderReview() {
  const root = app();
  clear(root);
  const t = state.transcript;

  const qta = h("textarea", { class: "edit", rows: "5" });
  qta.value = t.question_text || "";
  const eta = h("textarea", { class: "edit", rows: "16" });
  eta.value = t.essay_text || "";

  root.appendChild(h("section", { class: "card" },
    h("h2", {}, "2. Review transcription"),
    h("p", { class: "hint" }, "Fix any OCR slips before grading — the grader sees this text."),
    h("label", {}, "Question"),
    qta,
    h("label", {}, "Essay"),
    eta,
    h("div", { class: "actions" },
      h("button", { onclick: renderCapture }, "← Back"),
      h("button", {
        class: "primary",
        onclick: () => {
          state.transcript.question_text = qta.value;
          state.transcript.essay_text = eta.value;
          onGrade();
        },
      }, "Grade this essay"))));
}

async function onGrade() {
  if (!state.transcript.essay_text.trim()) {
    alert("Nothing to grade — the essay text is empty.");
    return;
  }
  showOverlay("Grading…");
  try {
    state.grade = await api.grade({
      language: state.transcript.language || state.language,
      paper_type: state.paperType,
      question_text: state.transcript.question_text,
      essay_text: state.transcript.essay_text,
    });
    renderResults();
  } catch (err) {
    alert("Grade failed:\n" + err.message);
  } finally {
    hideOverlay();
  }
}

// --- screen 3: annotated results -----------------------------------------

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

function renderResults() {
  const root = app();
  clear(root);
  const g = state.grade;
  const essay = state.transcript.essay_text;

  const section = h("section", { class: "card results" }, h("h2", {}, "3. Marked essay"));

  const table = scoreTable(g);
  if (table) section.appendChild(table);

  // Original essay with Round-1 redlines + the per-edit reasons as comments.
  const r1Comments = (g.comments || []).concat(
    (g.tracked_edits || []).map((e) => ({
      span: e.original_span,
      occurrence_index: e.occurrence_index || 0,
      comment_text: e.reason,
      category: e.category,
    })));
  section.appendChild(annotatedBlock("Original (Round 1: mechanical fixes)",
    essay, g.tracked_edits || [], r1Comments));

  // Improved Version: Round-2 edits over the v1-corrected text.
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
    h("button", { onclick: renderReview }, "← Back to text"),
    h("button", { class: "primary", onclick: resetAndCapture }, "Grade another"),
    h("button", { onclick: () => window.print() }, "Print / Save PDF")));

  root.appendChild(section);
}

function resetAndCapture() {
  state.questionFiles = [];
  state.essayFiles = [];
  state.transcript = null;
  state.grade = null;
  renderCapture();
}

// --- boot ----------------------------------------------------------------

refreshHealth();
renderCapture();
