// Thin wrappers over the local FastAPI endpoints.

export async function health() {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error("health check failed");
  return r.json();
}

async function asDetail(resp) {
  try {
    const body = await resp.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    return `${resp.status} ${resp.statusText}`;
  }
}

/**
 * @param {File[]} questionFiles @param {File[]} essayFiles @param {string} language
 */
export async function transcribe(questionFiles, essayFiles, language) {
  const fd = new FormData();
  for (const f of questionFiles) fd.append("question_images", f, f.name || "q.jpg");
  for (const f of essayFiles) fd.append("essay_images", f, f.name || "e.jpg");
  fd.append("language", language);
  const r = await fetch("/api/transcribe", { method: "POST", body: fd });
  if (!r.ok) throw new Error(await asDetail(r));
  return r.json();
}

export async function grade({ language, paper_type, question_text, essay_text }) {
  const payload = {
    language,
    paper_type: paper_type || "continuous",
    question_text,
    essay_text,
    student_level: "P6",
  };
  const r = await fetch("/api/grade", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await asDetail(r));
  return r.json();
}
