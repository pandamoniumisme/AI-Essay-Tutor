"""FastAPI entry point for the local web app.

Serves the browser SPA (static bundle) and the JSON API. Inference is
delegated to Gemini, so there is no model download, no NPU, and no port-file
handshake with a LibreOffice extension anymore -- just a fixed local port the
launcher opens in the browser.
"""
from __future__ import annotations

import argparse
import logging
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from aitutor_server import __version__
from aitutor_server.api import grade as grade_api
from aitutor_server.api import transcribe as transcribe_api
from aitutor_server.paths import ensure_dirs
from aitutor_server.providers import config as provider_config
from aitutor_server.util.log import setup_logging

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    log = logging.getLogger(__name__)
    log.info("PSLE Compo Tutor (web) v%s starting (provider=%s, model=%s)",
             __version__, provider_config.active_name(), provider_config.model())
    if not provider_config.key_present():
        log.warning("no API key for provider '%s'; /api calls return 503 until a key is set",
                    provider_config.active_name())
    yield
    log.info("AI Essay Tutor shutting down")


app = FastAPI(title="AI Essay Tutor", version=__version__, lifespan=lifespan)
app.include_router(transcribe_api.router)
app.include_router(grade_api.router)


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
