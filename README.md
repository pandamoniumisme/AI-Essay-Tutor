# PSLE Compo Tutor

Grades PSLE-level English and Simplified Chinese composition essays. Photograph
the question and the handwritten essay; the app transcribes it, scores it
against the PSLE rubric, and shows redline corrections, comments, and an
improved version — like a teacher marking the page.

Two builds share one front-end:
- **Web app** (`server/`) — online inference via Hugging Face (Qwen3.5-9B).
- **Android app** (`android/`) — on-device Qwen3.5 (2B/4B), or the same
  Hugging Face online option. See `android/`.

**Status:** in development. See `docs/web-solution-plan.md` for the full design.

## Web architecture

A local FastAPI server on `127.0.0.1` serves the browser UI and a JSON API.
Online inference goes to **Hugging Face Inference Providers** (OpenAI-compatible
router) running **Qwen3.5-9B**.

```
Browser SPA ──fetch──▶ server/ FastAPI (local) ──HTTPS──▶ Hugging Face (Qwen3.5-9B)
 (capture →                  │  /api/transcribe   transcription (OCR + caption)
  review →                   │  /api/grade        rubric grade (JSON via prompt+validate)
  annotated results)         │  /api/health
```

> **Privacy note:** essays are sent to Hugging Face for processing. These are
> children's essays — see the privacy section of `docs/web-solution-plan.md`
> before using on real student work. (The Android on-device mode keeps
> everything on the phone.)

## Layout

- `server/` — FastAPI app. Serves the SPA (`aitutor_server/static/`); provider
  config + the shared OpenAI-compatible client + transcriber/grader live in
  `aitutor_server/providers/`.
- `android/` — on-device Android app (Qwen3.5 via llama.cpp). See `android/README.md`.
- `scripts/` — PowerShell helpers for venv bootstrap and the dev server.
- `extension/` — **parked.** The original LibreOffice `.oxt` front-end, kept in
  git history; not part of the web build.

## Quick start

```powershell
# One-time: create venv + install deps (no model download)
.\scripts\bootstrap_server.ps1

# Set your Hugging Face token
$env:HF_TOKEN = "hf_your-token-here"

# Run the app (opens http://127.0.0.1:8765 in the browser)
.\scripts\run_server_dev.ps1
```

Config via environment (or `.env` — see `.env.example`):

| Var | Default | Purpose |
|---|---|---|
| `HF_TOKEN` | — | Hugging Face token (or `hf_token` in `config.json`) |
| `AITUTOR_HF_MODEL` | `Qwen/Qwen3.5-9B` | model id (append `:cheapest`/`:provider` to route) |

## Front-end

A no-build vanilla-JS SPA in `server/aitutor_server/static/` (served by the
same FastAPI process — no bundler, no node runtime dependency at run time). The
span-anchoring engine that renders redlines and comments (`js/annotate.js`) is
the browser replacement for the old `writer_ops.py`.

## Tests

```bash
cd server && python -m pytest          # server + grader validation
node --test tests/js/annotate.test.mjs # front-end span-anchoring engine
```
