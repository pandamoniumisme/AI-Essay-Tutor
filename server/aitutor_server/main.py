"""FastAPI entry point.

Two run modes:
- Auto-spawn (extension calls this): pick an ephemeral port, write %APPDATA%\\AIEssayTutor\\port.txt
  so the LO extension can discover it, then bind that socket and serve.
- Dev (run_server_dev.ps1): --port 8765 --reload, fixed port, uvicorn auto-reload on edits.
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from aitutor_server import __version__
from aitutor_server.api import grade as grade_api
from aitutor_server.api import jobs as jobs_api
from aitutor_server.api import transcribe as transcribe_api
from aitutor_server.api.schemas import ModelsStatus
from aitutor_server.models import manager as model_manager
from aitutor_server.models.paths import PID_FILE, PORT_FILE, ensure_dirs
from aitutor_server.util.log import setup_logging


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Under uvicorn --reload the worker is a separate child process that imports
    # this module but never calls main(); setup_logging is idempotent so we
    # call it here too to make sure the child writes to server.log.
    setup_logging()
    log = logging.getLogger(__name__)
    log.info("AI Essay Tutor server v%s starting", __version__)
    # Background download of any missing models. The endpoints stay responsive
    # while this runs; clients poll /models/status.
    if os.environ.get("AITUTOR_SKIP_MODEL_FETCH") != "1":
        model_manager.ensure_models_async()
    yield
    log.info("AI Essay Tutor server shutting down")


app = FastAPI(title="AI Essay Tutor", version=__version__, lifespan=lifespan)
app.include_router(transcribe_api.router)
app.include_router(grade_api.router)
app.include_router(jobs_api.router)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/models/status", response_model=ModelsStatus)
def models_status() -> ModelsStatus:
    return model_manager.get_status()


def _write_pidfile() -> None:
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _write_portfile(port: int) -> None:
    PORT_FILE.write_text(str(port), encoding="utf-8")


def _cleanup_runtime_files() -> None:
    PORT_FILE.unlink(missing_ok=True)
    PID_FILE.unlink(missing_ok=True)


def _bind_port(requested: int) -> tuple[socket.socket, int]:
    """Pre-bind a TCP socket on 127.0.0.1. If port==0, kernel picks an ephemeral one."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", requested))
    return sock, sock.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser(prog="aitutor-server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AITUTOR_PORT", "0")),
        help="TCP port (default: ephemeral 0). Use a fixed port for dev with --reload.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="dev only: enable uvicorn auto-reload (requires fixed --port).",
    )
    args = parser.parse_args()

    ensure_dirs()
    setup_logging()
    log = logging.getLogger(__name__)
    _write_pidfile()

    try:
        if args.reload:
            if args.port == 0:
                print(
                    "--reload requires a fixed --port (cannot use ephemeral port with reload)",
                    file=sys.stderr,
                )
                sys.exit(2)
            _write_portfile(args.port)
            log.info("dev mode (reload): http://127.0.0.1:%d", args.port)
            uvicorn.run(
                "aitutor_server.main:app",
                host="127.0.0.1",
                port=args.port,
                reload=True,
                log_config=None,
            )
            return

        sock, port = _bind_port(args.port)
        _write_portfile(port)
        log.info("listening on http://127.0.0.1:%d", port)

        cfg = uvicorn.Config(app, log_config=None, access_log=False)
        server = uvicorn.Server(cfg)
        server.run(sockets=[sock])
    finally:
        _cleanup_runtime_files()


if __name__ == "__main__":
    main()
