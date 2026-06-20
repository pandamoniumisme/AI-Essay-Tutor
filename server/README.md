# AI Essay Tutor — Web App / PWA

An installable PWA that grades PSLE English and Simplified-Chinese composition
essays. Photograph the question and the handwritten essay; it transcribes the
essay, lets you fix any OCR slips, then scores it against the PSLE rubric and
shows redline corrections, comments, and an improved version — all in the
browser.

Inference runs on a **local Ollama server (`gemma4:26b`)** — there is no cloud
provider and no API key. A single FastAPI process serves the page and the API on
`http://127.0.0.1:8765`; in production it sits behind `tailscale serve` for HTTPS
on the tailnet. Sessions are persisted server-side and graded by a background
job, so you can shoot the pages on a phone and pick up the marked result on a
desktop.

> Essay images and text are processed entirely on your own AI server and never
> leave your network.

## Setup (macOS / Linux)

```bash
./setup.sh                      # create .venv, install deps, scaffold .env
# edit .env only if Ollama isn't on this box (AITUTOR_OLLAMA_URL=...)
./run.sh                        # opens http://127.0.0.1:8765
```

## Setup (Windows)

```powershell
.\scripts\bootstrap_server.ps1          # create venv + install deps
.\scripts\run_server_dev.ps1            # opens http://127.0.0.1:8765
```

## Configuration

The server reads a `.env` file in the repo root automatically (see
`.env.example`). All settings are optional; the defaults assume Ollama runs on
the same box.

| Variable | Default | Purpose |
|---|---|---|
| `AITUTOR_OLLAMA_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible Ollama base URL |
| `AITUTOR_MODEL` | `gemma4:26b` | model tag |
| `AITUTOR_DATA_DIR` | `~/.local/share/AIEssayTutor` | sessions DB + uploaded images |

The one model handles OCR + picture description **and** grading, for both
English and Chinese (only the prompt + rubric caps switch by language).
`GET /api/health` reports the model and whether Ollama is reachable.

## How it works

```
PWA ──fetch──▶ FastAPI (local) ──/v1──▶ Ollama (gemma4:26b)
  capture →    POST /api/sessions          create + enqueue transcription
  review →     GET  /api/sessions[/{id}]   list / poll status
  marked essay POST /api/sessions/{id}/grade
```

- `aitutor_server/providers/` — the Ollama client config + a shared
  OpenAI-compatible client, plus the transcriber and grader (prompts + JSON
  validation).
- `aitutor_server/sessions.py` — persisted sessions (SQLite + image folders) and
  the serial background job runner.
- `aitutor_server/api/sessions.py` — the `/api/sessions/*` endpoints.
- `aitutor_server/static/` — the no-build vanilla-JS PWA. The redline / comment
  placement lives in `static/js/annotate.js`.

## Tests

```bash
cd server && ../.venv/bin/python -m pytest   # grader validation (offline)
node --test tests/js/annotate.test.mjs       # front-end annotation engine
```
