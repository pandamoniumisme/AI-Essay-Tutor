"""FastAPI entry point for the web app.

Serves the installable PWA (static bundle) and the JSON API. Inference is
delegated to the local Ollama server on the same box (gemma4:26b), so nothing
leaves the machine. Grading sessions are persisted server-side and run as
background jobs, so a session started on one device can be picked up on another
over the tailnet. In production the app binds to localhost and is exposed over
HTTPS by ``tailscale serve``.
"""
from __future__ import annotations

import argparse
import logging
import mimetypes
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from aitutor_server import __version__, sessions
from aitutor_server.api import sessions as sessions_api
from aitutor_server.paths import ensure_dirs
from aitutor_server.providers import config as provider_config
from aitutor_server.util.log import setup_logging

_STATIC_DIR = Path(__file__).parent / "static"

# Serve manifest.webmanifest with the right type for PWA installability.
mimetypes.add_type("application/manifest+json", ".webmanifest")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    ensure_dirs()
    sessions.init_db()
    sessions.reset_interrupted()
    log = logging.getLogger(__name__)
    log.info("AI Essay Tutor v%s starting (backend=ollama, base_url=%s, model=%s)",
             __version__, provider_config.base_url(), provider_config.model())
    if not provider_config.reachable():
        log.warning("Ollama not reachable at %s; jobs will fail until it's up",
                    provider_config.base_url())
    yield
    log.info("AI Essay Tutor shutting down")


app = FastAPI(title="AI Essay Tutor", version=__version__, lifespan=lifespan)
app.include_router(sessions_api.router)


@app.get("/api/health")
def health() -> dict:
    h = provider_config.health()
    h["version"] = __version__
    return h


# Serve the SPA. Mounted last so /api/* routes win. ``html=True`` serves
# index.html at "/" and falls back to it for client-side routes.
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="spa")


def main() -> None:
    parser = argparse.ArgumentParser(prog="aitutor-server")
    parser.add_argument("--port", type=int, default=8765, help="TCP port (default 8765)")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--reload", action="store_true", help="dev only: uvicorn auto-reload")
    parser.add_argument("--open", action="store_true", help="open the app in a browser on start")
    args = parser.parse_args()

    ensure_dirs()
    setup_logging()
    log = logging.getLogger(__name__)

    url = f"http://{args.host}:{args.port}"
    log.info("listening on %s", url)
    if args.open:
        webbrowser.open(url)

    if args.reload:
        uvicorn.run("aitutor_server.main:app", host=args.host, port=args.port,
                    reload=True, log_config=None)
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
