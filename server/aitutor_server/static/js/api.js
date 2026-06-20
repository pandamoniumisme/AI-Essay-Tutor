// Thin wrappers over the session API. The app talks to the local FastAPI
// server (served same-origin over the tailnet); work is persisted server-side
// so a session can be created on one device and read on another.

async function asDetail(resp) {
  try {
    const body = await resp.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    return `${resp.status} ${resp.statusText}`;
  }
}

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await asDetail(r));
  return r.json();
}

async function send(url, method, body) {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await asDetail(r));
  return r.json();
}

// --- public API ----------------------------------------------------------

export async function health() {
  return getJson("/api/health");
}

export async function listSessions() {
  return (await getJson("/api/sessions")).sessions;
}

export async function getSession(id) {
  return getJson(`/api/sessions/${id}`);
}

/** @param {File[]} questionFiles @param {File[]} essayFiles */
export async function createSession(questionFiles, essayFiles, language, paperType) {
  const fd = new FormData();
  for (const f of questionFiles) fd.append("question_images", f, f.name || "q.jpg");
  for (const f of essayFiles) fd.append("essay_images", f, f.name || "e.jpg");
  fd.append("language", language);
  fd.append("paper_type", paperType || "continuous");
  const r = await fetch("/api/sessions", { method: "POST", body: fd });
  if (!r.ok) throw new Error(await asDetail(r));
  return r.json();
}

export function saveTranscription(id, question_text, essay_text) {
  return send(`/api/sessions/${id}`, "PATCH", { question_text, essay_text });
}

export function gradeSession(id) {
  return send(`/api/sessions/${id}/grade`, "POST");
}

export function retranscribe(id) {
  return send(`/api/sessions/${id}/retranscribe`, "POST");
}

export function deleteSession(id) {
  return send(`/api/sessions/${id}`, "DELETE");
}
