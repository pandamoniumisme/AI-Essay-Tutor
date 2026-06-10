#!/usr/bin/env bash
# One-step setup for the AI Essay Tutor web app (macOS / Linux).
# Windows users: use scripts\bootstrap_server.ps1 instead.
#
#   ./setup.sh        # create venv, install deps, scaffold .env
#   ./run.sh          # start the app (created below) and open the browser
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.11 or 3.12." >&2
  exit 1
fi

echo "==> Creating virtual env (.venv)"
"$PY" -m venv .venv

echo "==> Installing the server package"
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -e ./server

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
  echo "    Edit .env and paste your Gemini API key (GEMINI_API_KEY=...)."
else
  echo "==> .env already exists; leaving it untouched"
fi

# Convenience launcher.
cat > run.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
exec ./.venv/bin/python -m aitutor_server.main --open "$@"
EOF
chmod +x run.sh

echo
echo "Done."
echo "  1. Put your key in .env  (get one at https://aistudio.google.com/apikey)"
echo "  2. ./run.sh              # opens http://127.0.0.1:8765"
