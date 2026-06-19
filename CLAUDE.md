# AI Essay Tutor

Grades PSLE (Primary 6 Singapore) **English** and **Simplified Chinese**
composition essays. Photograph the question page and the handwritten essay; the
app transcribes it (OCR + picture description), scores it against the PSLE
rubric, and renders redline corrections, comments, and an improved version — like
a teacher marking the page.

Two builds share one front-end (the vanilla-JS SPA in
`server/aitutor_server/static/`):

- **Web app** (`server/`) — a local FastAPI server that delegates inference to
  the **cloud** (Hugging Face Inference Providers, Qwen3.5-9B).
- **Android app** (`android/`) — a Kotlin app that runs inference **on-device**
  via llama.cpp (or, optionally, the same HF cloud / a LAN server).

Full design plan: `docs/web-solution-plan.md`.

## PRIVACY — essays go to the cloud (web build)

The web build is **NOT local-only.** `POST /api/transcribe` and `POST /api/grade`
send the uploaded essay/question images (as inline base64) and the transcribed
text to **Hugging Face Inference Providers** over HTTPS. These are children's
handwritten essays — read the privacy section of `docs/web-solution-plan.md`
before using on real student work. Only the **Android on-device** mode keeps
everything on the phone.

## Architecture

### Web build (`server/`) — cloud-backed, synchronous

```
Browser SPA ──fetch──▶ FastAPI (127.0.0.1) ──HTTPS──▶ Hugging Face router (Qwen3.5-9B)
 (capture →                 │ POST /api/transcribe   OCR + picture description (vision)
  review →                  │ POST /api/grade        rubric grade (JSON via prompt + validate)
  annotated results)        │ GET  /api/health
```

- **Synchronous API.** Each endpoint runs the cloud call inline and returns the
  result; the browser shows a spinner. There is **no job queue, no `/jobs/*`, no
  serial gate / 409, no `port.txt` handshake** — those belonged to the retired
  LibreOffice extension flow.
- **Single online provider.** `providers/config.py` defines one provider,
  `huggingface` (base_url `https://router.huggingface.co/v1`, default model
  `Qwen/Qwen3.5-9B`). The key comes from `HF_TOKEN` / `HUGGINGFACE_API_KEY` (or
  `hf_token` in `config.json`); the model is overridable via `AITUTOR_HF_MODEL`
  (append `:cheapest` or a `:provider` suffix to steer routing). Missing key →
  the API returns **503**.
- **One OpenAI SDK client.** `providers/client.py` wraps
  `openai.OpenAI(base_url=...).chat.completions.create`. `generate_vision` sends
  one image + prompt as a base64-inlined `image_url` part; `generate_text` does
  the text-only grade call.
- **Language is per-request, not per-model.** Both languages hit the *same*
  Qwen3.5-9B endpoint; the only fork is which prompt is sent. The request's
  `language` (`en` / `zh-Hans` / `auto`) selects EN vs ZH prompts in
  `providers/transcriber.py` and `providers/grader.py`. `auto` runs a cheap ZH
  transcription of the first page and classifies it with `lang_detect.py` (a CJK
  Unicode-range heuristic). There is **no `route_for`, no per-language model
  dispatch, no NPU/iGPU device selection** — all of that was deleted with the
  on-device build.

### Android build (`android/`) — genuinely on-device

A Kotlin app (Samsung Z Flip 5 target, 8 GB) that loads the **same SPA** in a
`WebView`. `static/js/api.js` detects `window.AndroidBridge` and routes
`transcribe()`/`grade()` to native code instead of HTTP, so one SPA serves both
surfaces. Inference runs **Qwen3.5 (2B/4B) via llama.cpp** fully offline (vision
OCR + text grading), with optional **LAN server** and **HF cloud** modes
selectable in Settings.

- `core/` builds on a plain JVM (no Android SDK) and holds the ported,
  platform-independent logic — prompts, grade JSON schema, JSON
  validation/clamping, language detection, data schemas — and is unit-tested
  there (`cd android/core && gradle test`).
- `app/` is the WebView host + JS bridge + inference (`StubInference` fallback +
  the `LlamaInference`/`cpp/llama_jni.cpp` native path) + foreground service.
  The native engine is a **bring-up scaffold, OFF by default** (`externalNativeBuild`
  commented out), so the default CI APK ships the stub. See `android/README.md`
  and `android/SETUP.md`.

### Extension (`extension/`) — PARKED / broken if re-enabled

The original LibreOffice Writer `.oxt` UNO front-end. It is **not part of any
current build** and still speaks the **deleted** server API — `port.txt`,
`/healthz`, `/models/status`, `POST /jobs/{transcribe,grade}`, `GET /jobs/{id}`
(see `extension/pythonpath/aitutor/client.py`). None of those endpoints exist on
the current server, so the extension is **broken if re-enabled**. Its
browser-side replacement is the SPA's span-anchoring engine (`static/js/annotate.js`,
which supersedes the old `writer_ops.py`). Leave it parked unless explicitly
reviving it.

## Key files

| File | What |
|---|---|
| `server/aitutor_server/main.py` | FastAPI app: mounts the SPA, includes the routers, `GET /api/health`; `main()` runs uvicorn on `127.0.0.1:8765` |
| `server/aitutor_server/api/transcribe.py` | `POST /api/transcribe` — reads uploads, calls `transcriber.do_transcribe` (synchronous) |
| `server/aitutor_server/api/grade.py` | `POST /api/grade` — calls `grader.grade` (synchronous) |
| `server/aitutor_server/api/schemas.py` | Pydantic v2 contracts: `TranscribeResponse`, `GradeRequest`/`GradeResponse`, `TrackedEdit`, `RubricScores`, etc. |
| `server/aitutor_server/providers/config.py` | The one online provider (`huggingface`): base_url, model, key resolution, `health()` |
| `server/aitutor_server/providers/client.py` | OpenAI-compatible client; `generate_vision` (base64 image) + `generate_text` |
| `server/aitutor_server/providers/transcriber.py` | OCR + picture-description prompts (EN/ZH) and `do_transcribe`; `auto` language detect |
| `server/aitutor_server/providers/grader.py` | `grade()`: builds prompts + JSON schema, calls the model, then lenient-parses / validates / clamps the output |
| `server/aitutor_server/providers/prompts/grader_{en,zh}.md` | Grader system prompts; both carry the Singapore-vocabulary allowlists |
| `server/aitutor_server/lang_detect.py` | CJK Unicode-range heuristic for `language="auto"` |
| `server/aitutor_server/paths.py` | Roaming config dir (`config.json`, `server.log`) — no model tree anymore |
| `server/aitutor_server/static/js/{annotate,render,scores,api,app}.js` | The SPA: span anchoring (redlines/comments), rendering, score table, backend wrapper, app glue |
| `android/core/` | Ported JVM-testable logic (prompts, schema, validation, lang detect) |
| `android/app/` | WebView host, JS bridge, llama.cpp inference, foreground service |

## Grading flow (server-side)

1. `grader.grade(req)` builds the EN/ZH system prompt (from `grader_{en,zh}.md`)
   + a user prompt, and a JSON **schema** scoped to the route's score caps
   (EN continuous 18/18→36, EN situational 6/8→14, ZH 20/20→40).
2. `client.generate_text` is called with that schema — but the provider's
   `structured` mode is **`"none"`**, so the schema is **NOT sent on the wire**
   (no `response_format`). HF routes to many providers with mixed structured-output
   support, so we rely on the **prompt** to ask for JSON and on a **lenient
   parser** (`_parse_json_lenient`, code-fence/trailing-prose/truncation repair)
   to extract it. The schema is effectively decorative for output constraint; its
   real job is documenting/deriving the per-route caps.
3. `_parse_and_validate` is the model-independent safety net and earns its keep:
   it **drops hallucinated spans** (any `original_span` not literally present in
   the essay / v1-corrected essay), drops no-op edits, **clamps scores** to the
   route's max_total, and computes the v1-corrected essay used to validate Round-2
   improvement spans. This is the logic the offline tests exercise.

## Conventions / gotchas

- **Stale "Gemini" mentions.** A few docstrings (`main.py`, `paths.py`,
  `grader.py`) and `server/pyproject.toml` still say "Gemini" / "two providers".
  The **only wired provider is Hugging Face / Qwen3.5-9B** (`providers/config.py`).
  Trust the code, not those comments; don't act on the Gemini wording.
- **`structured="none"` is intentional.** Don't "fix" it to `json_schema`
  assuming the schema is being enforced — broad HF provider support is the reason
  the prompt + lenient parser carry JSON correctness instead.
- **Span validation is load-bearing.** Tracked/improvement edits whose
  `original_span` isn't an exact substring of the (v1-corrected) essay are
  dropped server-side. Front-end `annotate.js` re-anchors by occurrence index, so
  spans must stay verbatim slices.
- **One SPA, two backends.** Never add a server-only assumption to
  `static/js/`: `api.js` also runs in the Android WebView over `window.AndroidBridge`.
  Keep `transcribe()`/`grade()`/`health()` shapes backend-agnostic.
- **Singapore vocabulary.** Both grader prompts (`grader_en.md`, `grader_zh.md`)
  carry explicit allowlists (HDB, MRT, kopitiam, char kway teow, 巴刹, 组屋,
  椰浆饭, "Auntie/Uncle" in dialogue, British vs American spelling, etc.).
  **Don't tighten these without asking.**
- **PSLE scope.** EN Paper 1 has Situational (14) and Continuous (36); ZH has one
  composition format (40), so `paper_type` is ignored for `zh-Hans`. Traditional
  Chinese is out of scope.

## Run / test (web build)

```powershell
.\scripts\bootstrap_server.ps1   # one-time: create venv + install deps (no model download)
$env:HF_TOKEN = "hf_your-token"
.\scripts\run_server_dev.ps1     # uvicorn --reload on 127.0.0.1:8765, opens the browser
```

```bash
cd server && python -m pytest                  # offline: grader validation (tests/test_grader_validation.py)
node --test server/tests/js/annotate.test.mjs  # SPA span-anchoring / score-row engine
```

(`scripts/build_oxt.ps1`, `reload_oxt.ps1`, `install_oxt.ps1` only matter to the
parked extension.)

## House rules

- Don't add features, refactor, or introduce abstractions beyond what the task asks.
- Default to no comments. Only write a comment when the *why* is non-obvious.
- Don't summarize at the end of every response — the user reads the diff.
- For risky / hard-to-reverse actions (force push, deleting branches, dropping
  tables, modifying CI), confirm before acting.
