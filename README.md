# AI Essay Tutor

A LibreOffice Writer extension that grades PSLE-level English and Simplified Chinese composition essays locally on Intel Lunar Lake hardware. Photograph the question and the handwritten essay; the extension transcribes the essay into Writer, scores it against the PSLE rubric, and inserts tracked-change corrections plus comments — like a teacher marking the page.

**Status:** in development. v1 is a single-user dev install, not a packaged release.

## Layout

- `extension/` — LibreOffice `.oxt` source. Stdlib-only Python (no third-party deps), talks to the AI server over `127.0.0.1` HTTP.
- `server/` — FastAPI AI server. Runs in its own venv at `%LOCALAPPDATA%\AIEssayTutor\venv`. Hosts the OCR pipeline (PP-OCRv5 detector + Chinese recognizer, TrOCR for English) and the LLM grader (Qwen3.5-9B with Qwen3-8B fallback).
- `scripts/` — PowerShell scripts for bootstrap, build, install, and dev workflow.
- `samples/` — paired (question, essay) photos with ground-truth `.txt` for OCR/grading regression.
- `docs/` — architecture, rubric, manual-test checklist.

## Hardware target

- Intel Core Ultra 5 226V (Lunar Lake) + 16 GB LPDDR5X
- Windows 11
- LibreOffice 7.6+

See `C:\Users\smile\.claude\plans\i-want-to-build-zazzy-catmull.md` for the full plan.

## Quick start

```powershell
# One-time bootstrap (creates venv, downloads + converts ~7 GB of models)
.\scripts\bootstrap_server.ps1

# Build + install the extension
.\scripts\build_oxt.ps1
.\scripts\install_oxt.ps1
```

Then launch LibreOffice Writer and look for the AI Essay Tutor toolbar.
