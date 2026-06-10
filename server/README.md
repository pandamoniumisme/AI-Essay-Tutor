# PSLE Compo Tutor — Web App

A small local web app that grades PSLE English and Simplified-Chinese
composition essays. Photograph the question and the handwritten essay; it
transcribes the essay, lets you fix any OCR slips, then scores it against the
PSLE rubric and shows redline corrections, comments, and an improved version —
all in the browser.

Online inference goes to one of two interchangeable **OpenAI-compatible**
providers — **Gemini** or **Alibaba Cloud (Qwen)** — so there's no model
download and no special hardware. A single FastAPI process serves the page and
the API on `http://127.0.0.1:8765`.

> ⚠️ Essay images and text are sent to the chosen provider for processing.
> These are children's essays — make sure that's acceptable for your use.

## Setup (macOS / Linux)

```bash
./setup.sh                      # create .venv, install deps, scaffold .env
# edit .env: pick AITUTOR_PROVIDER and paste that provider's key
./run.sh                        # opens http://127.0.0.1:8765
```

## Setup (Windows)

```powershell
.\scripts\bootstrap_server.ps1          # create venv + install deps
$env:GEMINI_API_KEY = "your-key-here"   # or $env:DASHSCOPE_API_KEY
.\scripts\run_server_dev.ps1            # opens http://127.0.0.1:8765
```

## Configuration

The server reads a `.env` file in the repo root automatically. You can also set
these as environment variables, or put the matching `*_api_key` in `config.json`
under the app config dir (`%APPDATA%\AIEssayTutor` on Windows,
`~/.config/AIEssayTutor` elsewhere).

| Variable | Default | Purpose |
|---|---|---|
| `AITUTOR_PROVIDER` | `gemini` | which online provider: `gemini` or `dashscope` |
| `GEMINI_API_KEY` | — | Gemini key ([get one](https://aistudio.google.com/apikey)) |
| `AITUTOR_GEMINI_MODEL` | `gemini-3.5-flash` | Gemini model id |
| `DASHSCOPE_API_KEY` | — | Alibaba Cloud Model Studio key |
| `AITUTOR_DASHSCOPE_MODEL` | `qwen3.5-flash` | Qwen model id |

The same model handles OCR + picture description **and** grading, for both
English and Chinese (only the prompt + rubric caps switch by language).
`GET /api/health` reports the active provider, model, and whether a key is set.

## How it works

```
Browser SPA ──fetch──▶ FastAPI (local) ──HTTPS──▶ Gemini | Alibaba Cloud (Qwen)
  capture →            /api/transcribe   transcription (OCR + picture caption)
  review →             /api/grade        rubric grade (JSON-constrained)
  marked essay         /api/health
```

- `aitutor_server/providers/` — provider config + a shared OpenAI-compatible
  client, plus the transcriber and grader (prompts + JSON validation).
- `aitutor_server/api/` — the `/api/*` endpoints + Pydantic contracts.
- `aitutor_server/static/` — the no-build vanilla-JS front-end. The redline /
  comment placement lives in `static/js/annotate.js`.

## Tests

```bash
cd server && ../.venv/bin/python -m pytest   # server + grader validation
node --test tests/js/annotate.test.mjs       # front-end annotation engine
```
