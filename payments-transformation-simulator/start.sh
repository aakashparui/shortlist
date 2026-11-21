#!/usr/bin/env bash
# Start the Payments Transformation Simulator locally (backend + frontend).
#
#   ./start.sh            start both
#   ./start.sh --reset    drop the local SQLite database first
#
# Requires Python 3.11+ and Node 20+. Nothing else: the default database is
# SQLite and is created on first start.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-5173}"

info()  { printf '\033[36m==>\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m==>\033[0m %s\n' "$1"; }
fail()  { printf '\033[31m==>\033[0m %s\n' "$1" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 \
  || fail "Python 3.11+ is required but was not found on PATH."
command -v node >/dev/null 2>&1 || fail "Node 20+ is required but was not found on PATH."

PYTHON="$(command -v python3 || command -v python)"

if [[ "${1:-}" == "--reset" ]]; then
  warn "Removing the local SQLite database"
  rm -f "$BACKEND"/data/simulator.db*
fi

# --- backend ---------------------------------------------------------------
if [[ ! -d "$BACKEND/.venv" ]]; then
  info "Creating the backend virtual environment"
  "$PYTHON" -m venv "$BACKEND/.venv"
fi

VENV_BIN="$BACKEND/.venv/bin"
[[ -d "$VENV_BIN" ]] || VENV_BIN="$BACKEND/.venv/Scripts"   # Windows layout

info "Installing backend dependencies"
"$VENV_BIN/python" -m pip install --quiet --upgrade pip
"$VENV_BIN/python" -m pip install --quiet -e "$BACKEND[dev]"

# --- frontend --------------------------------------------------------------
if [[ ! -d "$FRONTEND/node_modules" ]]; then
  info "Installing frontend dependencies"
  (cd "$FRONTEND" && npm install --no-audit --no-fund)
fi

cleanup() {
  info "Shutting down"
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${UI_PID:-}" ]]  && kill "$UI_PID"  2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

info "Starting the API on http://localhost:$API_PORT"
(cd "$BACKEND" && "$VENV_BIN/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT") &
API_PID=$!

info "Waiting for the API to become ready (first run seeds the demo book)"
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then
    info "API is ready"
    break
  fi
  sleep 1
done

info "Starting the console on http://localhost:$UI_PORT"
(cd "$FRONTEND" && npm run dev -- --port "$UI_PORT") &
UI_PID=$!

cat <<EOF

  Payments Transformation Simulator
  ---------------------------------
  Console   http://localhost:$UI_PORT
  API docs  http://localhost:$API_PORT/docs
  Health    http://localhost:$API_PORT/health

  Simulated environment. All data is fictional.
  Press Ctrl+C to stop both.

EOF

wait
