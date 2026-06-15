// Thin wrappers over inference. Two backends, same shapes:
//   * Web build  -> HTTP to the local FastAPI server (/api/*).
//   * Android app -> a native bridge (window.AndroidBridge) backed by on-device
//     llama.cpp. The bridge is synchronous (@JavascriptInterface), so long jobs
//     return via global callbacks keyed by a token (see nativeCall below).
//
// app.js calls transcribe()/grade()/health() without caring which backend runs.

const bridge = () => (typeof window !== "undefined" ? window.AndroidBridge : undefined);

// --- native bridge plumbing ---------------------------------------------

let _seq = 0;
const _pending = new Map();

if (typeof window !== "undefined") {
  // The Kotlin host calls these after a job finishes.
  window.__nativeResolve = (token, json) => {
    const p = _pending.get(token);
    if (p) { _pending.delete(token); p.resolve(json ? JSON.parse(json) : null); }
  };
  window.__nativeReject = (token, message) => {
    const p = _pending.get(token);
    if (p) { _pending.delete(token); p.reject(new Error(message || "native error")); }
  };
  window.__nativeProgress = (token, message, fraction) => {
    const p = _pending.get(token);
    if (p && p.onProgress) p.onProgress(message, fraction);
  };
}

function nativeCall(method, payload, onProgress) {
  return new Promise((resolve, reject) => {
    const token = String(++_seq);
    _pending.set(token, { resolve, reject, onProgress });
    try {
      bridge()[method](token, JSON.stringify(payload));
    } catch (e) {
      _pending.delete(token);
      reject(e);
    }
  });
}

function fileToPart(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("could not read image"));
    reader.onload = () => {
      // dataURL -> "data:<mime>;base64,<data>"
      const url = String(reader.result);
      const comma = url.indexOf(",");
      const mime = (url.slice(5, url.indexOf(";")) || "image/jpeg");
      resolve({ mime, data: url.slice(comma + 1) });
    };
    reader.readAsDataURL(file);
  });
}

// --- HTTP helpers --------------------------------------------------------

async function asDetail(resp) {
  try {
    const body = await resp.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    return `${resp.status} ${resp.statusText}`;
  }
}

// --- public API ----------------------------------------------------------

export async function health() {
  if (bridge()) return JSON.parse(bridge().health());
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error("health check failed");
  return r.json();
}

// Settings (Android only — the web build is configured server-side via env).
export function hasSettings() { return !!bridge(); }
export function getSettings() { return bridge() ? JSON.parse(bridge().getSettings()) : null; }
export function saveSettings(patch) { if (bridge()) bridge().setSettings(JSON.stringify(patch)); }
export function pingLocal(url) {
  return bridge() ? nativeCall("pingServer", { url }) : Promise.reject(new Error("native only"));
}

/**
 * @param {File[]} questionFiles @param {File[]} essayFiles @param {string} language
 */
export async function transcribe(questionFiles, essayFiles, language, onProgress) {
  if (bridge()) {
    const question_images = await Promise.all(questionFiles.map(fileToPart));
    const essay_images = await Promise.all(essayFiles.map(fileToPart));
    return nativeCall("transcribe", { question_images, essay_images, language }, onProgress);
  }
  const fd = new FormData();
  for (const f of questionFiles) fd.append("question_images", f, f.name || "q.jpg");
  for (const f of essayFiles) fd.append("essay_images", f, f.name || "e.jpg");
  fd.append("language", language);
  const r = await fetch("/api/transcribe", { method: "POST", body: fd });
  if (!r.ok) throw new Error(await asDetail(r));
  return r.json();
}

export async function grade({ language, paper_type, question_text, essay_text }, onProgress) {
  const payload = {
    language,
    paper_type: paper_type || "continuous",
    question_text,
    essay_text,
    student_level: "P6",
  };
  if (bridge()) return nativeCall("grade", payload, onProgress);
  const r = await fetch("/api/grade", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await asDetail(r));
  return r.json();
}
