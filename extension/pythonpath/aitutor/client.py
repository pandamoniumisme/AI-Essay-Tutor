"""Stdlib-only HTTP client for talking to the AI server.

LibreOffice's bundled Python on Windows does not have ``requests`` and may
have a partial ``ssl`` (we only talk to 127.0.0.1 over plain HTTP, so we
sidestep that). Multipart/form-data is built by hand because LO's bundled
``email.parser`` is sometimes missing pieces and we want zero surprises.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from aitutor.log import get_logger

log = get_logger(__name__)


# --- Server discovery ----------------------------------------------------

def _appdata() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "AIEssayTutor"
    return Path.home() / ".config" / "AIEssayTutor"


PORT_FILE: Path = _appdata() / "port.txt"


def read_port() -> int | None:
    try:
        return int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def base_url() -> str | None:
    port = read_port()
    if port is None:
        return None
    return f"http://127.0.0.1:{port}"


# --- Public calls --------------------------------------------------------

def healthz(timeout: float = 1.0) -> dict | None:
    """Return the parsed /healthz body, or None if the server is unreachable."""
    return _get("/healthz", timeout=timeout)


def models_status(timeout: float = 2.0) -> dict | None:
    return _get("/models/status", timeout=timeout)


def transcribe(question_paths: list[str], essay_paths: list[str], language: str,
               timeout: float = 600.0) -> dict:
    """POST /transcribe (sync). Blocks until the work is done. Used for curl/Postman
    testing; the LO extension UI uses ``start_transcribe_job`` + ``get_job`` instead
    so it can poll status without freezing the UI."""
    return _post_multipart(
        "/transcribe",
        fields={"language": language},
        files=_image_parts(question_paths, essay_paths),
        timeout=timeout,
    )


class JobBusy(RuntimeError):
    """Raised when /jobs/transcribe returns 409 because another job is running."""

    def __init__(self, running_job_id: str | None, message: str):
        super().__init__(message)
        self.running_job_id = running_job_id


def start_transcribe_job(question_paths: list[str], essay_paths: list[str],
                         language: str, timeout: float = 60.0) -> str:
    """POST /jobs/transcribe -- queue work, return job_id immediately.

    Raises ``JobBusy`` if the server already has another transcribe in flight.
    """
    try:
        body = _post_multipart(
            "/jobs/transcribe",
            fields={"language": language},
            files=_image_parts(question_paths, essay_paths),
            timeout=timeout,
        )
    except urllib.error.HTTPError as e:
        if e.code == 409:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail", {})
            except Exception:
                detail = {}
            raise JobBusy(
                running_job_id=detail.get("running_job_id"),
                message=detail.get("message", "another transcribe job is already running"),
            ) from e
        raise
    return body["job_id"]


def get_job(job_id: str, timeout: float = 5.0) -> dict | None:
    """GET /jobs/{id} -- one poll. Returns None if the server is unreachable
    (caller decides whether to retry)."""
    return _get(f"/jobs/{job_id}", timeout=timeout)


def start_grade_job(language: str, paper_type: str, question_text: str,
                    essay_text: str, student_level: str = "P6",
                    timeout: float = 30.0) -> str:
    """POST /jobs/grade -- queue a grade job, return job_id. Raises ``JobBusy``
    on 409 (another transcribe or grade is already running)."""
    payload = {
        "language": language,
        "paper_type": paper_type,
        "question_text": question_text,
        "essay_text": essay_text,
        "student_level": student_level,
    }
    url = base_url()
    if url is None:
        raise RuntimeError("AI server is not running")
    req = urllib.request.Request(
        url + "/jobs/grade",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 409:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail", {})
            except Exception:
                detail = {}
            raise JobBusy(
                running_job_id=detail.get("running_job_id"),
                message=detail.get("message", "another job is already running"),
            ) from e
        raise
    return body["job_id"]


def _image_parts(question_paths: list[str], essay_paths: list[str]) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for p in question_paths:
        files.append(("question_images", Path(p)))
    for p in essay_paths:
        files.append(("essay_images", Path(p)))
    return files


# --- Internals -----------------------------------------------------------

def _get(path: str, timeout: float) -> dict | None:
    url = base_url()
    if url is None:
        return None
    try:
        with urllib.request.urlopen(url + path, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _post_multipart(path: str, fields: dict[str, str],
                    files: list[tuple[str, Path]], timeout: float) -> dict:
    """Files is a list of (field_name, path) tuples to allow multiple files
    per field (e.g. several pages under the same ``essay_images`` field)."""
    url = base_url()
    if url is None:
        raise RuntimeError("AI server is not running (no port file). Start it first.")

    boundary = "----AITutor" + secrets.token_hex(16)
    body = _encode_multipart(boundary, fields, files)
    req = urllib.request.Request(
        url + path,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _encode_multipart(boundary: str, fields: dict[str, str],
                      files: list[tuple[str, Path]]) -> bytes:
    """Build a multipart/form-data body from scratch -- avoids any dependency
    on ``email`` or ``requests-toolbelt``."""
    crlf = b"\r\n"
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.append(
            b"--" + boundary.encode("ascii") + crlf
            + f'Content-Disposition: form-data; name="{name}"'.encode("utf-8") + crlf
            + crlf
            + str(value).encode("utf-8") + crlf
        )

    for name, path in files:
        if not path.exists():
            raise FileNotFoundError(str(path))
        ctype, _ = mimetypes.guess_type(str(path))
        if not ctype:
            ctype = "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        parts.append(
            b"--" + boundary.encode("ascii") + crlf
            + f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"'
                .encode("utf-8") + crlf
            + f"Content-Type: {ctype}".encode("ascii") + crlf
            + crlf
            + data + crlf
        )

    parts.append(b"--" + boundary.encode("ascii") + b"--" + crlf)
    return b"".join(parts)
