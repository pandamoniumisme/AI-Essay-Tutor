# PSLE Compo Tutor — Web App

A small local web app that grades PSLE English and Simplified-Chinese
composition essays. Photograph the question and the handwritten essay; it
transcribes the essay, lets you fix any OCR slips, then scores it against the
PSLE rubric and shows redline corrections, comments, and an improved version —
all in the browser.

Online inference goes to **Hugging Face Inference Providers** (OpenAI-compatible
router) running **Qwen3.5-9B** — so there's no model download and no special
hardware. A single FastAPI process serves the page and the API on
`http://127.0.0.1:8765`.

> ⚠️ Essay images and text are sent to Hugging Face for processing. These are
> children's essays — make sure that's acceptable for your use.

## Setup (macOS / Linux)

```bash
./setup.sh                      # create .venv, install deps, scaffold .env
# edit .env: paste your HF_TOKEN
./run.sh                        # opens http://127.0.0.1:8765
```

## Setup (Windows)

```powershell
.\scripts\bootstrap_server.ps1          # create venv + install deps
$env:HF_TOKEN = "hf_your-token-here"
.\scripts\run_server_dev.ps1            # opens http://127.0.0.1:8765
```

## Configuration

The server reads a `.env` file in the repo root automatically. You can also set
these as environment variables, or put the matching `*_api_key` in `config.json`
under the app config dir (`%APPDATA%\AIEssayTutor` on Windows,
`~/.config/AIEssayTutor` elsewhere).

| Variable | Default | Purpose |
|---|---|---|
| `HF_TOKEN` | — | Hugging Face token ([get one](https://huggingface.co/settings/tokens)) |
| `AITUTOR_HF_MODEL` | `Qwen/Qwen3.5-9B` | model id (append `:cheapest` or `:provider` to route) |

The one model handles OCR + picture description **and** grading, for both
English and Chinese (only the prompt + rubric caps switch by language).
`GET /api/health` reports the model and whether a token is set.

## How it works

```
Browser SPA ──fetch──▶ FastAPI (local) ──HTTPS──▶ Hugging Face (Qwen3.5-9B)
  capture →            /api/transcribe   transcription (OCR + picture caption)
  review →             /api/grade        rubric grade (JSON via prompt + validate)
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
