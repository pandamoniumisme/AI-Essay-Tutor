# AI Essay Tutor

A local web app that grades PSLE-level English and Simplified Chinese
composition essays. Photograph the question and the handwritten essay; the app
transcribes the essay, scores it against the PSLE rubric, and shows
tracked-change corrections plus comments — like a teacher marking the page.

**Status:** in development. The server backend (Phase A) is Gemini-backed and
working; the browser front-end (Phase B) is not built yet. See
`docs/web-solution-plan.md` for the full design.

## Architecture

A single local FastAPI server runs on `127.0.0.1`, serving both the browser UI
and a JSON API. All inference (OCR + picture description + rubric grading) is
delegated to Google's **Gemini API** over the network.

```
Browser SPA ──fetch──▶ server/ FastAPI (local) ──HTTPS──▶ Gemini API
 (capture →                  │  /api/transcribe   gemini-2.5-flash (OCR + caption)
  review →                   │  /api/grade        gemini-2.5-pro|flash (grading)
  annotated results)         │  /api/health
```

> **Privacy note:** essays are sent to Google for processing. These are
> children's essays — see the privacy section of `docs/web-solution-plan.md`
> before using on real student work.

## Layout

- `server/` — FastAPI app. Serves the SPA (`aitutor_server/static/`) and the
  API; Gemini calls live in `aitutor_server/gemini/`.
- `scripts/` — PowerShell helpers for venv bootstrap and the dev server.
- `extension/` — **parked.** The original LibreOffice `.oxt` front-end, kept in
  git history; not part of the web build.

## Quick start

```powershell
# One-time: create venv + install deps (no model download anymore)
.\scripts\bootstrap_server.ps1

# Set your Gemini API key (or put it in %APPDATA%\AIEssayTutor\config.json)
$env:GEMINI_API_KEY = "your-key-here"

# Run the app (opens http://127.0.0.1:8765 in the browser)
.\scripts\run_server_dev.ps1
```

Config via environment:

| Var | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini API key (or `gemini_api_key` in `config.json`) |
| `AITUTOR_TRANSCRIBE_MODEL` | `gemini-2.5-flash` | model for OCR + picture description |
| `AITUTOR_GRADE_MODEL` | `gemini-2.5-flash` | model for rubric grading (bump to a `pro` tier for quality) |

## Tests

```bash
cd server && python -m pytest
```
