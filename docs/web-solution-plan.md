# Web Solution Plan — AI Essay Tutor

**Status:** proposal / planning. Nothing here is built yet.
**Date:** 2026-06-06.
**Decisions locked in (from product owner):**

1. **Local web app, Gemini (online) for inference.** The app still runs on the
   user's own machine — a local server plus a browser UI — but the heavy ML
   (OCR + picture description + grading) is delegated to Google's Gemini API
   over the network instead of the on-device OpenVINO/NPU model stack.
2. **In-browser annotated view** is the output surface. No LibreOffice, no UNO,
   no `.docx`/`.odt` export. Scores, redline edits, comments and the Improved
   Version are rendered as interactive HTML in the browser.

This is a significant pivot away from the current design (LibreOffice Writer
extension → local FastAPI → OpenVINO models on Lunar Lake NPU/iGPU). The good
news: the **server's data contracts and grading logic survive almost intact**;
only the inference backend and the front-of-house UI change.

---

## 1. What changes, at a glance

```
BEFORE
  LibreOffice Writer  ──UNO──▶  extension/ (stdlib Python)
                                      │ 127.0.0.1 HTTP (multipart + JSON jobs)
                                      ▼
                                server/ FastAPI ──▶ OpenVINO GenAI
                                                     ├─ Qwen2.5-VL-7B (iGPU) OCR+caption
                                                     └─ Qwen3-8B INT4 (NPU)  grade

AFTER
  Browser SPA  ──fetch──▶  server/ FastAPI (still local, 127.0.0.1)
   (capture +                    │
    review +                     │  google-genai SDK over HTTPS
    annotated                    ▼
    results)              Gemini API (online)
                            ├─ gemini-2.5-flash : OCR + picture description
                            └─ gemini-2.5-pro   : rubric grading (structured JSON)
```

| Layer | Today | After |
|---|---|---|
| Front-of-house UI | LibreOffice extension (`extension/`, UNO dialogs) | Browser SPA served by the local server |
| Output | Tracked changes + comments injected into a Writer `.odt` (`writer_ops.py`) | Interactive annotated view rendered in the browser |
| OCR + picture caption | `vision/captioner.py` → OpenVINO VLMPipeline | `gemini/transcriber.py` → Gemini multimodal |
| Grader | `llm/grader.py` → OpenVINO LLMPipeline + xgrammar | `gemini/grader.py` → Gemini `response_schema` (structured JSON) |
| Model lifecycle | `models/manager.py` (download/convert ~12 GB IRs, NPU probe) | **Deleted.** Replaced by an API-key check |
| Serial job gate | `_RUNNING_JOB_ID` (one ML job at a time on 16 GB) | **Removed.** Online API has no single-GPU bottleneck |
| Server discovery | `port.txt` + `server_proc.py` spawn from LO | Launcher script opens `http://127.0.0.1:<port>` in the browser |
| Privacy posture | Fully local, nothing leaves the device | **Essays now leave the device** → see §6 |

### Code that survives unchanged or nearly so

- **`api/schemas.py`** — the Pydantic contracts (`TranscribeResponse`,
  `GradeRequest`, `GradeResponse`, `TrackedEdit`, `RubricComment`,
  `RubricScores`) stay as the single source of truth. They now also drive the
  frontend's TypeScript types.
- **`llm/grader.py` validation half** — `_parse_and_validate`,
  `_parse_json_lenient`, span-existence filtering, score clamping, the
  v1-corrected-text computation. This logic is independent of *which* model
  produced the JSON and is still valuable (Gemini can still hallucinate spans).
- **The grader prompts** (`llm/prompts/grader_{en,zh}.md`) and the Singapore
  vocabulary allowlists — ported verbatim into the Gemini call.
- **The captioner prompts** (currently inline in `captioner.py`:
  `_QUESTION_PROMPT_{EN,ZH}`, `_ESSAY_PROMPT_{EN,ZH}`) — ported verbatim.
- **The JSON schema builder** `_grade_response_json_schema` — adapted to
  Gemini's `responseSchema` subset (see §4.2).

### Code that is retired

- All of `extension/` (the LibreOffice `.oxt`), `writer_ops.py`, `dialog.py`,
  `server_proc.py`, `client.py`, `handler.py`, `debug_cache.py`, the PowerShell
  `*_oxt.ps1` scripts. **Parked, not deleted** — keep the directory in git
  history in case a "push to Writer" export is ever wanted again, but it leaves
  the active build.
- `vision/captioner.py`, `llm/grader.py` pipeline halves, `models/manager.py`,
  `models/paths.py`, `ocr/`, and the OpenVINO/optimum/transformers/opencv
  dependency block in `pyproject.toml`.

---

## 2. Target architecture

Two pieces, both shipped together and run locally:

1. **`server/` (FastAPI, local)** — unchanged role as the API host, plus it now
   also serves the static frontend bundle. Endpoints:
   - `GET  /`                 → the SPA (index.html + assets)
   - `POST /api/transcribe`   → multipart images in, `TranscribeResponse` out
   - `POST /api/grade`        → `GradeRequest` in, `GradeResponse` out
   - `GET  /api/health`       → `{ ok, gemini_key_present, model_ids }`
   The async job queue (`/jobs/*` + polling) can be **dropped** — Gemini calls
   return in seconds, so synchronous endpoints with a frontend spinner are
   simpler. (Optionally keep a thin streaming variant via SSE for live
   "transcribing page 2/3…" progress — see §5.3.)

2. **Browser SPA** — capture → transcription review → grading → annotated
   results. See §5.

There is no second process to spawn and no `port.txt` handshake; a launcher
(`scripts/run_app.ps1` / `.sh`) starts uvicorn and opens the browser.

---

## 3. Why these model choices

| Job | Model | Rationale |
|---|---|---|
| OCR + picture description | `gemini-2.5-flash` | Strong multimodal OCR incl. handwriting and CJK; cheap and fast; the captioner job is "read this image", which flash handles well. |
| Rubric grading | `gemini-2.5-pro` | Grading is the reasoning-heavy step (rubric judgement, edit selection, two-round scoring). Pro's quality justifies the cost on the once-per-essay grade call. |

> **Verify model IDs at implementation time** against Google's current model
> list — the flash/pro tier names move. Make both IDs config values
> (`AITUTOR_TRANSCRIBE_MODEL`, `AITUTOR_GRADE_MODEL`) so they can be bumped
> without a code change. Start with both on `flash` if cost is a concern and
> promote grading to `pro` if quality demands it.

SDK: the unified **`google-genai`** Python package
(`from google import genai`). Single dependency, replaces the entire
OpenVINO/optimum/transformers/opencv/huggingface stack.

---

## 4. Server changes in detail

### 4.1 Transcribe (`gemini/transcriber.py`)

Replaces `vision/captioner.py` + the OpenVINO half of `api/transcribe.py`.
Keep the same public shape so the rest of the server is untouched:

```python
def do_transcribe(question_imgs, essay_imgs, language, on_progress=_noop) -> TranscribeResponse
```

- Images arrive as uploaded bytes; pass them to Gemini as inline image parts
  (base64) — no OpenCV decode/BGR dance needed (drop the `cv2` import). Light
  client-side downscaling (see §5.1) keeps payloads small.
- **Essay pages:** one Gemini call per page with `_ESSAY_PROMPT_{EN,ZH}`,
  concatenated in order — mirrors `transcribe_essay_pages`. (Or a single call
  with all pages as ordered parts; per-page keeps progress granular.)
- **Question pages:** one call with `_QUESTION_PROMPT_{EN,ZH}` → the two-section
  (`=== Prompt === / === Pictures ===`) verbatim output, same as today.
- `language="auto"` detection: simplest is to ask Gemini to also report the
  script, or keep the existing `ocr/lang_detect.py` heuristic on the first
  page's text. The browser UI sends an explicit `en`/`zh-Hans` anyway, so this
  path is rarely hit.
- `essay_lines` / `OcrLine`: keep synthesizing one line per non-empty text line
  with `confidence=1.0`, `bbox=(0,0,0,0)` — preserves the response shape. (Real
  bboxes aren't available and aren't needed for the in-browser view.)

### 4.2 Grade (`gemini/grader.py`)

Replaces the pipeline half of `llm/grader.py`; **keep the validation half.**

- Build the prompt with the existing `_build_prompt` logic, but without the
  Qwen/Gemma chat-template wrappers — `google-genai` takes a system instruction
  + user content directly. Pass `grader_{en,zh}.md` as the system instruction.
- Structured output: set
  `config = GenerateContentConfig(response_mime_type="application/json",
  response_schema=...)`. Two options for the schema:
  - **(a) Reuse `_grade_response_json_schema(req)`** adapted to Gemini's
    subset. Gemini's `responseSchema` is a constrained OpenAPI 3.0 subset:
    drop `additionalProperties:false`, `const` (encode `max_total` as a fixed
    value in validation instead), and `default`. The dynamic per-paper caps
    (content/18 vs /20, situational /6+/8 vs continuous /18+/18, ZH /20+/20)
    are still expressible via `minimum`/`maximum`.
  - **(b) Hand the Pydantic `GradeResponse` model** straight to
    `response_schema` (google-genai accepts Pydantic models). Cleanest, but the
    per-paper caps become *post-hoc* validation only (the model is static).
  Recommendation: **(a)** — keep the caps in the schema so the model is steered
  correctly, and still run `_parse_and_validate` afterward as the safety net.
- After generation, run the **unchanged** `_parse_and_validate(raw, req)`:
  lenient JSON parse, drop hallucinated/no-op spans, clamp scores, compute the
  v1-corrected text for improvement-edit validation. With structured output
  this should mostly be a no-op, but it's cheap insurance.
- The NPU truncation workaround (`_close_open_brackets`, `MIN_RESPONSE_LEN`,
  `MAX_PROMPT_LEN`) is **no longer needed** — that was an NPU buffer-sizing bug.
  Gemini has a large output budget. Keep `_close_open_brackets` only as a
  defensive fallback in `_parse_json_lenient`.

### 4.3 Config & secrets

- `GEMINI_API_KEY` read from environment or a local config file
  (`%LOCALAPPDATA%\AIEssayTutor\config.json` or `.env`). **Never** commit it;
  add to `.gitignore`. `/api/health` reports whether the key is present so the
  UI can show a friendly "set your API key" state instead of failing mid-job.
- Model IDs and the API key are the only runtime config. The bootstrap/venv
  scripts shrink dramatically (no 12 GB model download).

### 4.4 Dependency diff (`pyproject.toml`)

Remove: `openvino`, `openvino-genai`, `optimum[openvino]`, `transformers`,
`huggingface-hub`, `opencv-python`, `numpy` (keep only if still used elsewhere —
likely droppable), the paddle note.
Add: `google-genai`.
Keep: `fastapi`, `uvicorn`, `python-multipart`, `pydantic`, `pillow` (handy for
server-side downscale/validate of uploads).

---

## 5. Frontend

A single-page app served from `server/aitutor_server/static/` (or a
`frontend/` build output copied in). The annotated-view rendering is the only
genuinely new engineering; everything else is standard forms.

**Stack recommendation:** keep it light to honour the project's "no abstractions
beyond what the task needs" house rule. Options, in order of preference:
1. **Vanilla TS + Vite**, no UI framework — the app is ~4 screens and one
   custom render component; a framework earns little here.
2. **Preact/Svelte + Vite** if the team prefers component ergonomics.
Generate TS types from the Pydantic schemas (e.g. `datamodel-codegen` →
`pydantic2ts`, or hand-write a small `types.ts`) so the contract stays in sync.

### 5.1 Screen 1 — Capture

- Language toggle: **English / 简体中文** (default Chinese, matching today).
- Paper type (English only): Situational / Continuous.
- Two ordered, multi-page uploaders: **Question pages** and **Essay pages**.
  - Drag-drop **and** `<input type="file" accept="image/*" capture="environment"
    multiple>` so phones/tablets shoot straight from the camera — a big UX win
    over the LibreOffice FilePicker.
  - Reorderable thumbnails (the order matters: it's the page order of the
    essay). Mirrors the dialog's "one image per slot, in order" invariant but
    far friendlier.
  - Downscale client-side (e.g. longest edge ~2000 px) before upload to cut
    bandwidth and Gemini token cost; keep enough resolution for handwriting.
- "Transcribe" button → `POST /api/transcribe`.

### 5.2 Screen 2 — Transcription review *(new capability)*

The LibreOffice version graded raw OCR directly (a noted v1.5 TODO was to let
the user edit first). The web UI gets this for free:

- Show the transcribed **question** and **essay** in editable text areas.
- Let the student/teacher fix OCR slips before grading — directly improves grade
  quality since the grader sees corrected text.
- "Grade this essay" → `POST /api/grade` with the (possibly edited) text.

### 5.3 Screen 3 — Progress

Gemini calls take a few seconds to tens of seconds. A spinner with a status
line is enough. If per-page transcription progress is wanted, expose an SSE
stream (`GET /api/transcribe/stream`) that emits `transcribing page i/N`
events — the server already has the `on_progress` callback plumbed through
`do_transcribe`, so this is a small adapter, not new logic.

### 5.4 Screen 4 — Annotated results *(the core new component)*

This is the browser replacement for `writer_ops.py`. The server returns
`GradeResponse`; the frontend renders:

1. **Score report** — cards/table: Content (x/cap), Language (x/cap), Total
   (x/max_total), plus "After Round 1 fixes" (`score_after_v1`) and "After Round
   2 improvements" (`target_score`). Reuse the cap-inference logic from
   `_score_table_rows` (36→18/18, 14→6/8, 40→20/20). Band is intentionally
   **not** shown (matches the current product decision — it reads harsh to a P6
   student).

2. **Original essay with Round-1 redlines + comments.** Render `essay_text`,
   then overlay:
   - Each `tracked_edits` entry as an inline **redline**: original span struck
     through, `suggested_replacement` inserted next to it, on hover/tap a
     popover shows `[category] reason`.
   - Each `comments` entry (and each edit's `reason`) as a **highlight + margin
     note**, anchored to its `span`.

3. **Improved Version section** — the v1-corrected essay (compute it in JS with
   the same first-occurrence replace as `_apply_edits_to_text_python`) with the
   Round-2 `improvement_edits` rendered as a second layer of redlines +
   comments. Mirrors today's "Section B".

4. **Overall feedback** — `overall_feedback` as a paragraph.

5. Actions: print / save-as-PDF (browser native), "Grade another".

#### The span-anchoring engine (the one hard part)

`writer_ops.py` used UNO `findAll().getByIndex(occurrence_index)` to locate
spans; the browser must do the equivalent against the rendered text. Design:

- Treat the essay as a plain string. For each edit/comment, resolve
  `(original_span, occurrence_index)` → a `[start, end)` character range by
  finding the nth occurrence.
- Collect all ranges (deletions, insertions-anchored-at-a-point, comment
  highlights), **sort by start offset**, and **detect overlaps**. Overlapping
  annotations are the known failure mode (a comment span containing a redline
  target). Resolution order, matching the server's intent:
  - Comments are highlights (can co-exist / nest visually).
  - Redlines are the authoritative text mutation.
  - On a hard conflict, prefer the redline and drop/relax the overlapping
    highlight, surfacing a small "N annotations couldn't be placed" note —
    same spirit as `writer_ops`'s skipped-items count.
- Build a segmented DOM: walk the string left→right emitting `<span>` runs of
  plain / deleted / inserted / highlighted text with `data-*` attributes
  carrying the reason+category for the popover.
- Because the server already validates that every span exists in the submitted
  essay (`_parse_and_validate`), most spans resolve cleanly; the engine still
  needs the skip-on-not-found path for the occasional edited-after-transcribe
  case.

This is well-bounded, testable pure-function work (string in → segment list
out) and should have unit tests with fixtures drawn from real `GradeResponse`
JSON (the retired `debug_cache` samples are perfect seed data).

---

## 6. Privacy & safety — must be addressed, not glossed over

The original design was **local-only on purpose**: these are *primary-school
children's* handwritten essays, often with names and personal details. Routing
them to Google Gemini means that data now leaves the device. This is a real
change in posture and needs an explicit, deliberate decision trail:

- **Informed consent.** A clear first-run notice that images + text are sent to
  Google for processing, with a link to Google's data-use terms for the API.
- **Use a no-retention configuration.** Paid Gemini API (AI Studio/Vertex) data
  is not used to train Google's models, but confirm and document the exact
  tier/terms in use. Prefer a billing setup with the strongest data-handling
  guarantees available.
- **Minimise.** Downscale images; don't send more pages than needed; don't log
  essay content server-side (the current server logs prompt prefixes — scrub
  that for the web build).
- **No accounts / no persistence by default.** Local-only storage; nothing
  uploaded anywhere except the Gemini call itself.
- Surface a short privacy statement in the README and in-app.

If the privacy trade-off later proves unacceptable, the architecture keeps the
door open to swap `gemini/` back for a local-inference module behind the same
`do_transcribe` / `grade` interfaces.

---

## 7. Phasing

**Phase A — Server backend swap (no UI yet).**
- Add `google-genai`; write `gemini/transcriber.py` and `gemini/grader.py`
  behind the existing `do_transcribe` / `grade` signatures.
- Port the four captioner prompts + two grader prompts.
- Adapt `_grade_response_json_schema` to Gemini's schema subset; keep
  `_parse_and_validate`.
- Add `/api/transcribe`, `/api/grade`, `/api/health`; delete `models/`, `ocr/`,
  job queue/serial gate; trim `pyproject.toml`.
- Verify with `curl`/HTTPie against real sample images before any UI exists.

**Phase B — Frontend.**
- Vite project, the 4 screens, TS types from the schemas.
- Build + unit-test the span-anchoring render engine against `GradeResponse`
  fixtures first (highest-risk component), then wire the screens.
- Serve the build from the FastAPI static mount; `run_app` launcher.

**Phase C — Polish & ship.**
- Mobile camera capture, client-side downscale, SSE progress (optional).
- Consent flow + privacy copy; API-key onboarding screen.
- Print-to-PDF styling for the results view; error states (no key, Gemini
  error, network down, span-not-found notice).
- Retire the `extension/` build from the active workflow; update README.

---

## 8. Open questions for the product owner

1. **Cost ceiling.** `pro` for grading is materially pricier than `flash`. OK to
   default grading to `pro`, or start everything on `flash`?
2. **Privacy sign-off.** Are we comfortable sending minors' essays to Gemini
   under the paid no-training tier? (Blocking — see §6.)
3. **API key ownership.** One shared key baked into the local config (you pay),
   or each user supplies their own key in-app?
4. **Keep the transcription-review step?** It improves grades but adds a click.
   (Recommended: yes.)
5. **Drop async jobs entirely, or keep an SSE progress stream?** (Recommended:
   synchronous endpoints + optional SSE for transcribe progress.)
6. **Frontend stack:** vanilla TS+Vite (recommended) vs Preact/Svelte?
7. **Park or delete `extension/`?** (Recommended: park in git, drop from build.)

---

## 9. Risks

- **Span-anchoring overlaps** — the same class of bug `writer_ops.py` fought
  (comments overlapping redlines). Mitigated by making the render engine a
  tested pure function with real-data fixtures, and a visible skip count.
- **Gemini schema subset** — `const`/`additionalProperties`/`default` aren't all
  supported; the grade schema needs adapting and testing against the live API.
- **Handwriting OCR quality** — flash is strong but unverified on *this* corpus
  (primary-school handwriting, CJK). Validate against the `samples/` ground
  truth before committing; the transcription-review step is the safety net.
- **Privacy/compliance** — the dominant non-technical risk (§6); needs an
  explicit decision before Phase A ships to real essays.
- **Cost drift** — per-essay token cost (multi-page images + long grade output)
  should be measured early so there are no billing surprises.
