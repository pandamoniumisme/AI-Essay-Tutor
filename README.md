# PSLE Compo Tutor

Grades PSLE-level English and Simplified Chinese composition essays. Photograph
the question and the handwritten essay; the app transcribes it, scores it
against the PSLE rubric, and shows redline corrections, comments, and an
improved version — like a teacher marking the page.

Two builds share one front-end:
- **Web app** (`server/`) — online inference via Gemini or Alibaba Cloud (Qwen).
- **Android app** (`android/`) — fully on-device Qwen3.5 (2B/4B). See `android/`.

**Status:** in development. See `docs/web-solution-plan.md` for the full design.

## Web architecture

A local FastAPI server on `127.0.0.1` serves the browser UI and a JSON API.
Online inference goes to one of two interchangeable **OpenAI-compatible**
providers, selected by `AITUTOR_PROVIDER`.

```
Browser SPA ──fetch──▶ server/ FastAPI (local) ──HTTPS──▶ Gemini | Alibaba Cloud (Qwen)
 (capture →                  │  /api/transcribe   transcription (OCR + caption)
  review →                   │  /api/grade        rubric grade (JSON-constrained)
  annotated results)         │  /api/health
```

> **Privacy note:** essays are sent to the chosen provider for processing. These
> are children's essays — see the privacy section of `docs/web-solution-plan.md`
> before using on real student work. (The Android build keeps everything
> on-device.)

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

# Set your provider key (Gemini shown; or DASHSCOPE_API_KEY for Alibaba Cloud)
$env:GEMINI_API_KEY = "your-key-here"

# Run the app (opens http://127.0.0.1:8765 in the browser)
.\scripts\run_server_dev.ps1
```

Config via environment (or `.env` — see `.env.example`):

| Var | Default | Purpose |
|---|---|---|
| `AITUTOR_PROVIDER` | `gemini` | `gemini` or `dashscope` |
| `GEMINI_API_KEY` | — | Gemini key (or `gemini_api_key` in `config.json`) |
| `AITUTOR_GEMINI_MODEL` | `gemini-3.5-flash` | Gemini model id |
| `DASHSCOPE_API_KEY` | — | Alibaba Cloud Model Studio key |
| `AITUTOR_DASHSCOPE_MODEL` | `qwen3.5-flash` | Qwen model id |

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
