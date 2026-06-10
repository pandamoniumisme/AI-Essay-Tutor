# AI Essay Tutor — Web App

A small local web app that grades PSLE English and Simplified-Chinese
composition essays. Photograph the question and the handwritten essay; it
transcribes the essay, lets you fix any OCR slips, then scores it against the
PSLE rubric and shows redline corrections, comments, and an improved version —
all in the browser.

Inference runs on Google's **Gemini API**, so there is no model download and no
special hardware. A single FastAPI process serves both the page and the API on
`http://127.0.0.1:8765`.

> ⚠️ Essay images and text are sent to Google for processing. These are
> children's essays — make sure that's acceptable for your use.

## Setup (macOS / Linux)

```bash
./setup.sh                      # create .venv, install deps, scaffold .env
# put your key in .env  (get one at https://aistudio.google.com/apikey)
./run.sh                        # opens http://127.0.0.1:8765
```

## Setup (Windows)

```powershell
.\scripts\bootstrap_server.ps1          # create venv + install deps
$env:GEMINI_API_KEY = "your-key-here"
.\scripts\run_server_dev.ps1            # opens http://127.0.0.1:8765
```

## Configuration

The server reads a `.env` file in the repo root automatically. You can also set
these as environment variables, or put `gemini_api_key` in
`config.json` under the app config dir (`%APPDATA%\AIEssayTutor` on Windows,
`~/.config/AIEssayTutor` elsewhere).

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | your Gemini API key |
| `AITUTOR_TRANSCRIBE_MODEL` | `gemini-3.5-flash` | OCR + picture description |
| `AITUTOR_GRADE_MODEL` | `gemini-3.5-flash` | rubric grading |

`GET /api/health` reports whether a key is configured and which models are in
use — the home page shows this too.

## How it works

```
Browser SPA ──fetch──▶ FastAPI (local) ──HTTPS──▶ Gemini API
  capture →            /api/transcribe   transcription (OCR + picture caption)
  review →             /api/grade        rubric grade (structured JSON)
  marked essay         /api/health
```

- `aitutor_server/gemini/` — Gemini client, transcriber, grader.
- `aitutor_server/api/` — the `/api/*` endpoints + Pydantic contracts.
- `aitutor_server/static/` — the no-build vanilla-JS front-end. The redline /
  comment placement lives in `static/js/annotate.js`.

## Tests

```bash
cd server && ../.venv/bin/python -m pytest   # server + grader validation
node --test tests/js/annotate.test.mjs       # front-end annotation engine
```
