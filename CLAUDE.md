# AI Essay Tutor

Grades PSLE (Primary 6 Singapore) **English** and **Simplified Chinese**
composition essays. Photograph the question page and the handwritten essay; the
app transcribes it (OCR + picture description), scores it against the PSLE
rubric, and renders redline corrections, comments, and an improved version — like
a teacher marking the page.

The app is an **installable PWA served from a self-hosted AI server** — an Ubuntu
box running **Ollama with `gemma4:26b`** — reached over **Tailscale**. Inference
is fully on that box; nothing leaves the private tailnet. (Deployment — systemd
service + `tailscale serve` HTTPS — lives in the sibling `ubuntuserver` repo,
`provision-essay-tutor.sh`.)

Full design plan: `docs/web-solution-plan.md`.

## PRIVACY — local-only, on your own hardware

Essays are transcribed and graded **entirely on your AI server** via the local
Ollama endpoint. There is **no cloud provider and no API key**. Uploaded images
and transcriptions are persisted on that server (SQLite + per-session image
folders) so a session can be picked up from another device; delete a session
from the Home list to remove it. Access control is the tailnet itself
(`tailscale serve` over HTTPS, no public ingress).

## Architecture (`server/`) — local, async, session-based

```
Any tailnet device ──https──▶ tailscale serve ──▶ FastAPI (127.0.0.1:8765)
 (PWA: home/recent →              (TLS on *.ts.net)      │ POST /api/sessions          create + enqueue transcribe
  capture → review →                                     │ GET  /api/sessions[/{id}]   list / poll
  marked results)                                        │ PATCH/POST .../grade        edit text / enqueue grade
                                                         │ GET  /api/health
                                                         ▼
                                          Ollama /v1 (localhost) → gemma4:26b
                                          OCR + picture description + grading
```

- **Sessions persist server-side, jobs run in the background.** A 26B model on
  CPU is slow and the point is cross-device hand-off, so neither can live in the
  browser tab. `sessions.py` stores each session (images, transcription, grade,
  status) in SQLite (`$AITUTOR_DATA_DIR`) and runs transcription/grading on a
  **single-worker** `ThreadPoolExecutor` — one inference job at a time (one CPU
  model can't grade two essays at once). Status transitions
  (`created → transcribing → transcribed → grading → graded`, or `error`) are
  persisted; on restart, in-flight jobs are rolled back (`reset_interrupted`).
- **One local backend.** `providers/config.py` points at the Ollama
  OpenAI-compatible API (`AITUTOR_OLLAMA_URL`, default
  `http://127.0.0.1:11434/v1`) with model `AITUTOR_MODEL` (default `gemma4:26b`).
  No key — `health()` reports `reachable` from a `/models` probe instead.
- **One OpenAI SDK client.** `providers/client.py` wraps `openai.OpenAI` with a
  placeholder key (Ollama ignores it) and a 600 s timeout. `generate_vision`
  sends one base64-inlined image; `generate_text` does the grade call.
- **`gemma4:26b` is multimodal** — it does both the OCR/picture-description and
  the grading. There is no separate vision model.
- **Language is per-request, not per-model.** `language` (`en` / `zh-Hans` /
  `auto`) selects EN vs ZH prompts in `providers/transcriber.py` and
  `providers/grader.py`. `auto` runs a cheap ZH transcription of the first page
  and classifies it with `lang_detect.py`.

### Front-end — installable PWA

A no-build vanilla-JS PWA in `static/`. `app.js` is hash-routed (`#new`,
`#s/<id>`) so a session link opens on any device; `api.js` is a thin HTTP
wrapper over the session API. The Home screen polls `GET /api/sessions` so a
phone-shot session appears on the desktop; session screens poll
`GET /api/sessions/{id}` until the job finishes. `manifest.webmanifest` + `sw.js`
make it installable; the service worker uses **network-first for the shell and
never caches `/api/*`** (inference is always server-side). Icons are generated
by `scripts/make_icons.py` (stdlib-only PNG writer).

### Parked surfaces

- **`android/`** — the former on-device Kotlin build. **Parked**, kept in git
  history; the PWA over Tailscale replaces it. Its CI (`.github/workflows/android.yml`)
  still exists — remove it if the parking is permanent.
- **`extension/`** — the original LibreOffice `.oxt` UNO front-end. **Parked**;
  speaks a long-deleted server API. Its browser-side replacement is the SPA's
  span-anchoring engine (`static/js/annotate.js`).

## Key files

| File | What |
|---|---|
| `server/aitutor_server/main.py` | FastAPI app: mounts the PWA, includes the sessions router, `GET /api/health`, DB init; `main()` runs uvicorn on `127.0.0.1:8765` |
| `server/aitutor_server/sessions.py` | Persisted sessions (SQLite + image folders) + the serial background job runner (transcribe/grade) |
| `server/aitutor_server/api/sessions.py` | The session API: create/list/get/patch/grade/retranscribe/delete + image serving |
| `server/aitutor_server/api/schemas.py` | Pydantic v2 contracts: `TranscribeResponse`, `GradeRequest`/`GradeResponse`, `TrackedEdit`, `RubricScores`, etc. |
| `server/aitutor_server/providers/config.py` | The local Ollama backend: base_url, model, `reachable()`, `health()` |
| `server/aitutor_server/providers/client.py` | OpenAI-compatible client; `generate_vision` (base64 image) + `generate_text` |
| `server/aitutor_server/providers/transcriber.py` | OCR + picture-description prompts (EN/ZH) and `do_transcribe`; `auto` language detect |
| `server/aitutor_server/providers/grader.py` | `grade()`: builds prompts + JSON schema, calls the model, then lenient-parses / validates / clamps the output |
| `server/aitutor_server/providers/prompts/grader_{en,zh}.md` | Grader system prompts; both carry the Singapore-vocabulary allowlists |
| `server/aitutor_server/lang_detect.py` | CJK Unicode-range heuristic for `language="auto"` |
| `server/aitutor_server/paths.py` | Data dir (`$AITUTOR_DATA_DIR`): config.json, server.log, sessions.db, sessions/ |
| `server/aitutor_server/static/` | The PWA: `index.html`, `manifest.webmanifest`, `sw.js`, `icons/`, `js/{app,api,annotate,render,scores}.js` |
| `scripts/make_icons.py` | Regenerates the PWA icons (no deps) |

## Grading flow (server-side)

1. `grader.grade(req)` builds the EN/ZH system prompt (from `grader_{en,zh}.md`)
   + a user prompt, and a JSON **schema** scoped to the route's score caps
   (EN continuous 18/18→36, EN situational 6/8→14, ZH 20/20→40).
2. `client.generate_text` asks the backend for a JSON **object**
   (`response_format={"type": "json_object"}` — Ollama honours it). The schema
   itself is **not** sent on the wire; its real job is documenting/deriving the
   per-route caps. A **lenient parser** (`_parse_json_lenient`, code-fence /
   trailing-prose / truncation repair) still extracts the JSON.
3. `_parse_and_validate` is the model-independent safety net: it **drops
   hallucinated spans** (any `original_span` not literally present in the
   essay / v1-corrected essay), drops no-op edits, **clamps scores** to the
   route's max_total, and computes the v1-corrected essay used to validate
   Round-2 improvement spans. This is the logic the offline tests exercise.

## Conventions / gotchas

- **Local-only, on purpose.** Don't reintroduce a cloud provider or an API key.
  The whole pivot was to keep children's essays on the user's own hardware.
- **Sessions + async are load-bearing.** Don't "simplify" grading back to a
  synchronous request — a 26B CPU grade must outlive the tab, and cross-device
  hand-off needs server-side state. Keep jobs on the single worker (serial).
- **PWA needs a secure context.** Installability / the service worker require
  HTTPS (or `localhost`). In production that's `tailscale serve`; a plain
  `http://<tailscale-ip>` will silently fail to install. The service worker must
  never cache `/api/*`.
- **Span validation is load-bearing.** Tracked/improvement edits whose
  `original_span` isn't an exact substring of the (v1-corrected) essay are
  dropped server-side. Front-end `annotate.js` re-anchors by occurrence index, so
  spans must stay verbatim slices.
- **Singapore vocabulary.** Both grader prompts (`grader_en.md`, `grader_zh.md`)
  carry explicit allowlists (HDB, MRT, kopitiam, char kway teow, 巴刹, 组屋,
  椰浆饭, "Auntie/Uncle" in dialogue, British vs American spelling, etc.).
  **Don't tighten these without asking.**
- **PSLE scope.** EN Paper 1 has Situational (14) and Continuous (36); ZH has one
  composition format (40), so `paper_type` is ignored for `zh-Hans`. Traditional
  Chinese is out of scope.

## Run / test

```bash
cd server
python -m pip install -e '.[dev]'
export AITUTOR_OLLAMA_URL=http://aiserver:11434/v1   # or localhost if co-located
python -m aitutor_server.main --host 127.0.0.1 --port 8765 --open
```

```bash
cd server && python -m pytest                  # offline: grader validation (tests/test_grader_validation.py)
node --test server/tests/js/annotate.test.mjs  # SPA span-anchoring / score-row engine
python3 scripts/make_icons.py                  # regenerate PWA icons
```

## House rules

- Don't add features, refactor, or introduce abstractions beyond what the task asks.
- Default to no comments. Only write a comment when the *why* is non-obvious.
- Don't summarize at the end of every response — the user reads the diff.
- For risky / hard-to-reverse actions (force push, deleting branches, dropping
  tables, modifying CI), confirm before acting.
