# AI Essay Tutor

LibreOffice Writer extension for PSLE (Primary 6 Singapore) English & Simplified Chinese composition grading. **Local-only.** Hardware target: Intel Lunar Lake Core Ultra 5 226V, 16 GB RAM, Windows 11.

Full design plan: `C:\Users\smile\.claude\plans\i-want-to-build-zazzy-catmull.md`.

## Architecture

Two processes over `127.0.0.1` HTTP:

```
LibreOffice Writer
  └─ extension/  (Python via UNO, stdlib-only — LO bundled Python lacks `requests`)
                                                         │ HTTP
                                                         ▼
                          server/  (FastAPI + uvicorn, separate venv)
```

**Two language routes** (selected from the dialog's language radio; resolved server-side by `models.manager.route_for(language)`):

| Route | Captioner (OCR + picture description) | Grader (PSLE rubric → structured JSON) |
|---|---|---|
| `en` | Gemma 3 4B-IT (NPU, multimodal, gated repo) | Gemma 3 4B-IT — same VLMPipeline reused for text-only generation |
| `zh-Hans` | Qwen2.5-VL-7B (iGPU) | Qwen3-8B INT4-cw (NPU) |

Default: Chinese.

(Earlier "Fast" mode using Qwen2.5-VL-3B captioner + Qwen3-4B grader was retired on 2026-05-07: 3B's OCR was unreliable on primary-school handwriting, and 4B's grader feedback was noticeably weaker than 8B's. Both models are deleted from disk.)

Server venv: `%LOCALAPPDATA%\AIEssayTutor\venv`. Models: `%LOCALAPPDATA%\AIEssayTutor\models\` — 3 directories (gemma_3_4b_it, qwen2_5_vl_7b, qwen3_8b), ~12 GB total.

**Async job pattern.** Extension never blocks on ML calls. `POST /jobs/{transcribe|grade}` → `job_id`; client polls `GET /jobs/{id}` every 3 s. A serial gate (`_RUNNING_JOB_ID` in `api/jobs.py`) returns 409 on concurrent submission — only one ML job at a time.

## Key files

| File | What |
|---|---|
| `extension/pythonpath/aitutor/handler.py` | Orchestration: `run_transcribe`, `run_grade_after_transcribe`, `_format_grade_result`, `_apply_grade_to_doc` |
| `extension/pythonpath/aitutor/writer_ops.py` | Apply grade JSON to doc: backup, insert essay, RecordChanges + tracked replaces + Annotation comments |
| `extension/pythonpath/aitutor/debug_cache.py` | On-disk cache of last transcribe + grade JSON at `%APPDATA%\AIEssayTutor\debug\` for the dialog's Debug checkbox |
| `extension/pythonpath/aitutor/dialog.py` | `TranscribeInputDialog` (one-page-per-slot, MAX_PAGES=4, progressive reveal); `ProgressDialog` (3 s polling) |
| `extension/pythonpath/aitutor/client.py` | `urllib` + manual multipart |
| `extension/pythonpath/aitutor/server_proc.py` | Spawn / health-check / shutdown server subprocess |
| `server/aitutor_server/api/jobs.py` | Job queue, serial gate, `start_transcribe_job`, `start_grade_job` |
| `server/aitutor_server/api/transcribe.py` | `do_transcribe(question_imgs, essay_imgs, language, on_progress)` |
| `server/aitutor_server/vision/captioner.py` | VLMPipeline lazy load; `transcribe_essay_pages`, `transcribe_question_pages`, `caption_question`, `unload` |
| `server/aitutor_server/llm/grader.py` | LLMPipeline on NPU with `MAX_PROMPT_LEN=4096` (int!), xgrammar structured JSON |
| `server/aitutor_server/llm/prompts/grader_{en,zh}.md` | Grader system prompts; both contain Singapore-vocabulary allowlists |
| `server/aitutor_server/models/manager.py` | First-run download + IR fetch; `_ensure_paddleocr` is now a no-op (paddle retired 2026-05-07) |
| `server/aitutor_server/models/paths.py` | `CAPTIONER_DIR`, `LLM_FALLBACK_DIR` |

## Conventions / gotchas (don't re-learn the hard way)

- **LO Python is stripped down.** Extension code uses only `urllib`, `json`, `email.message` (multipart). No `requests`, `ssl`, etc. Add deps to the server venv, never the LO-bundled one.
- **UNO threading.** `dlg.getControl(...)` returns `None` from non-main threads. ProgressDialog uses static text + only `endExecute()` from the worker thread — no cross-thread `setText`.
- **Button auto-dismiss.** `PushButtonType=1` (OK) dismisses the dialog *before* the action listener fires. Use `pushtype=0` (Standard) for any button that runs work and then closes the dialog itself.
- **FilePicker.** Use `getSelectedFiles()` (XFilePicker2), not `getFiles()` (legacy: directory + filenames split).
- **Pycache cleanup.** `__pycache__` can hold stale bytecode after edits — `watchfiles --reload` doesn't always invalidate. `scripts/run_server_dev.ps1` clears it on start.
- **NPU `MAX_PROMPT_LEN` must be an `int`.** Passing `"4096"` errors with `Type mismatch: expected types: int or int64_t`.
- **Captioner IR layout.** Multi-component VLM IRs have `openvino_language_model.xml`, not `openvino_model.xml`. `_get_pipeline()` checks for either.
- **OCR is captioner-only.** Paddleocr was retired 2026-05-07 (PIR/oneDNN crashes on Lunar Lake). Qwen2.5-VL-7B handles all OCR + picture description. To revert, see comment in `server/pyproject.toml` and `_ensure_paddleocr` in `manager.py`.
- **Singapore vocabulary.** Both grader prompts have explicit allowlists (HDB, MRT, kopitiam, char kway teow, 巴刹, 组屋, 椰浆饭, "Auntie/Uncle" in dialogue, British vs American spelling, etc.). Don't tighten these without asking.
- **Multi-route model dispatch.** `route_for(language, fast)` in `models/manager.py` returns the captioner/grader dirs and devices for one of three routes (en, zh-fast, zh-normal). Both `vision/captioner.py` and `llm/grader.py` cache one pipeline keyed by `(language, fast)` and unload+reload on route change. For the EN route the captioner and grader share the same Gemma 3 VLMPipeline instance (one model, both jobs); for ZH the grader is a dedicated LLMPipeline that calls `captioner.unload()` first.
- **Debug cache.** Every successful transcribe/grade is written to `%APPDATA%\AIEssayTutor\debug\last_{transcribe,grade}.json`. The dialog's "Debug" checkbox short-circuits matching LLM steps. With both caches present, Start applies directly to the doc — useful for iterating on `writer_ops` without paying the LLM cost. Hand-edit the JSON to test specific edge cases.
- **NPU grader output cap (open).** Qwen3-8B on NPU has been observed truncating mid-string at ~150 generated tokens despite `max_new_tokens=1800` and ~2000 tokens of headroom in `MAX_PROMPT_LEN=4096`. Worth chasing by toggling `structured_output_config` off, moving grader to GPU, or trimming the rubric prompts.
- **Memory budget.** Captioner and grader don't co-reside. Grader's `_get_pipeline()` calls `captioner.unload()` first. Don't change this without verifying on 16 GB.

## Dev loop

```powershell
.\scripts\run_server_dev.ps1     # kill any prior server, clear pycache, uvicorn --reload
.\scripts\reload_oxt.ps1         # unopkg remove + add --force, then restart LO
.\scripts\build_oxt.ps1          # produce dist\AIEssayTutor.oxt
.\scripts\bootstrap_server.ps1   # first-run: create venv, install deps, fetch models
```

## Phase status

- Phase 1–3 done: OCR via captioner → transcription dialog → grading with structured JSON popup.
- Phase 4 in progress: tracked changes + comments wired (`writer_ops.py` + "Apply to document" button on the grade popup); score table still pending.

## House rules

- Don't add features, refactor, or introduce abstractions beyond what the task asks.
- Default to no comments. Only write a comment when the *why* is non-obvious.
- Don't summarize at the end of every response — the user reads the diff.
- For risky / hard-to-reverse actions (force push, deleting branches, dropping tables, modifying CI), confirm before acting.
