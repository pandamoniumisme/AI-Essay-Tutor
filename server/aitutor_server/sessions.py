"""Persisted grading sessions + a serial background job runner.

A 26B model on CPU takes a while per essay, and the point of this build is that
you can shoot the pages on your phone, walk to your desktop, and pick up the
marked result there. Both need the work to live on the server, not in the
browser tab: every session (uploaded images, transcription, grade) is persisted
to SQLite + a per-session image folder, and transcription/grading run as
background jobs that outlive the request that started them.

Jobs run on a single worker thread, so only one inference job touches the model
at a time (one CPU model can't grade two essays at once anyway).
"""
from __future__ import annotations

import json
import logging
import secrets
import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

from aitutor_server.api.schemas import GradeRequest
from aitutor_server.paths import SESSIONS_DB, SESSIONS_DIR, ensure_dirs

log = logging.getLogger(__name__)

Image = tuple[bytes, str]  # (raw bytes, mime_type)

# created -> transcribing -> transcribed -> grading -> graded ; or -> error
STATUS_CREATED = "created"
STATUS_TRANSCRIBING = "transcribing"
STATUS_TRANSCRIBED = "transcribed"
STATUS_GRADING = "grading"
STATUS_GRADED = "graded"
STATUS_ERROR = "error"

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aitutor-job")


# --- DB ------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SESSIONS_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    ensure_dirs()
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id            TEXT PRIMARY KEY,
                created_at    REAL NOT NULL,
                updated_at    REAL NOT NULL,
                language      TEXT NOT NULL,
                paper_type    TEXT NOT NULL,
                student_level TEXT NOT NULL,
                status        TEXT NOT NULL,
                error         TEXT,
                question_text TEXT NOT NULL DEFAULT '',
                essay_text    TEXT NOT NULL DEFAULT '',
                grade_json    TEXT,
                images_json   TEXT NOT NULL DEFAULT '{}'
            )
        """)


def reset_interrupted() -> None:
    """A process restart orphans any in-flight job. Roll them back to a state
    the user can retry from: a half-done transcription becomes an error; a
    half-done grade falls back to ``transcribed`` (the text is still there)."""
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET status=?, error=?, updated_at=? WHERE status=?",
            (STATUS_ERROR, "interrupted by a server restart — retry", now, STATUS_TRANSCRIBING),
        )
        conn.execute(
            "UPDATE sessions SET status=?, updated_at=? WHERE status=?",
            (STATUS_TRANSCRIBED, now, STATUS_GRADING),
        )


# --- session CRUD --------------------------------------------------------

def _session_dir(session_id: str):
    return SESSIONS_DIR / session_id


def _touch(conn: sqlite3.Connection, session_id: str, **fields) -> None:
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE sessions SET {cols} WHERE id=?", (*fields.values(), session_id))


def create_session(language: str, paper_type: str, student_level: str,
                   question_images: list[Image], essay_images: list[Image]) -> str:
    session_id = secrets.token_hex(4)
    sdir = _session_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=True)

    images_meta: dict[str, list[str]] = {"question": [], "essay": []}
    for role, imgs in (("question", question_images), ("essay", essay_images)):
        for idx, (data, mime) in enumerate(imgs):
            (sdir / f"{role}-{idx}").write_bytes(data)
            images_meta[role].append(mime)

    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, updated_at, language, paper_type, "
            "student_level, status, images_json) VALUES (?,?,?,?,?,?,?,?)",
            (session_id, now, now, language, paper_type, student_level,
             STATUS_CREATED, json.dumps(images_meta)),
        )
    log.info("session %s created (lang=%s paper=%s q=%d e=%d)",
             session_id, language, paper_type, len(question_images), len(essay_images))
    return session_id


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    images = json.loads(d.pop("images_json") or "{}")
    d["question_image_count"] = len(images.get("question", []))
    d["essay_image_count"] = len(images.get("essay", []))
    grade_json = d.pop("grade_json", None)
    d["grade"] = json.loads(grade_json) if grade_json else None
    return d


def get_session(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return _row_to_dict(row) if row else None


def _title(essay_text: str) -> str:
    for line in essay_text.splitlines():
        line = line.strip()
        if line:
            return line[:60]
    return ""


def list_sessions(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, updated_at, language, paper_type, status, error, "
            "essay_text FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,),
        ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["title"] = _title(d.pop("essay_text") or "")
        out.append(d)
    return out


def update_transcription(session_id: str, question_text: str, essay_text: str) -> None:
    with _connect() as conn:
        _touch(conn, session_id, question_text=question_text, essay_text=essay_text)


def set_status(session_id: str, status: str, error: str | None = None) -> None:
    with _connect() as conn:
        _touch(conn, session_id, status=status, error=error)


def set_grade(session_id: str, grade_json: str) -> None:
    with _connect() as conn:
        _touch(conn, session_id, grade_json=grade_json, status=STATUS_GRADED, error=None)


def delete_session(session_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        deleted = cur.rowcount > 0
    shutil.rmtree(_session_dir(session_id), ignore_errors=True)
    return deleted


def load_images(session_id: str, role: str) -> list[Image]:
    s = get_session(session_id)
    if not s:
        return []
    sdir = _session_dir(session_id)
    count = s["question_image_count"] if role == "question" else s["essay_image_count"]
    mimes = _image_mimes(session_id).get(role, [])
    out: list[Image] = []
    for idx in range(count):
        path = sdir / f"{role}-{idx}"
        if path.exists():
            mime = mimes[idx] if idx < len(mimes) else "image/jpeg"
            out.append((path.read_bytes(), mime))
    return out


def _image_mimes(session_id: str) -> dict[str, list[str]]:
    with _connect() as conn:
        row = conn.execute("SELECT images_json FROM sessions WHERE id=?", (session_id,)).fetchone()
    return json.loads(row["images_json"]) if row else {}


def image_bytes(session_id: str, role: str, idx: int) -> Image | None:
    path = _session_dir(session_id) / f"{role}-{idx}"
    if not path.exists():
        return None
    mimes = _image_mimes(session_id).get(role, [])
    mime = mimes[idx] if idx < len(mimes) else "image/jpeg"
    return path.read_bytes(), mime


# --- jobs ----------------------------------------------------------------

def enqueue_transcribe(session_id: str) -> None:
    set_status(session_id, STATUS_TRANSCRIBING)
    _executor.submit(_run_transcribe, session_id)


def enqueue_grade(session_id: str) -> None:
    set_status(session_id, STATUS_GRADING)
    _executor.submit(_run_grade, session_id)


def _run_transcribe(session_id: str) -> None:
    from aitutor_server.providers import transcriber
    try:
        s = get_session(session_id)
        if not s:
            return
        q = load_images(session_id, "question")
        e = load_images(session_id, "essay")
        result = transcriber.do_transcribe(q, e, s["language"])
        with _connect() as conn:
            _touch(conn, session_id, question_text=result.question_text,
                   essay_text=result.essay_text, language=result.language,
                   status=STATUS_TRANSCRIBED, error=None)
        log.info("session %s transcribed (%d essay chars)", session_id, len(result.essay_text))
    except Exception as exc:
        log.exception("session %s transcription failed", session_id)
        set_status(session_id, STATUS_ERROR, _friendly_error(exc))


def _run_grade(session_id: str) -> None:
    from aitutor_server.providers import grader
    try:
        s = get_session(session_id)
        if not s:
            return
        req = GradeRequest(
            language=s["language"],
            paper_type=s["paper_type"],
            question_text=s["question_text"],
            essay_text=s["essay_text"],
            student_level=s["student_level"],
        )
        result = grader.grade(req)
        set_grade(session_id, result.model_dump_json())
        log.info("session %s graded", session_id)
    except Exception as exc:
        log.exception("session %s grading failed", session_id)
        set_status(session_id, STATUS_ERROR, _friendly_error(exc))


def _friendly_error(exc: Exception) -> str:
    from openai import APIConnectionError
    if isinstance(exc, APIConnectionError):
        return ("can't reach the AI server (Ollama) — check it's running and "
                "AITUTOR_OLLAMA_URL is correct")
    return f"{type(exc).__name__}: {exc}"
