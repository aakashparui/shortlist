#!/usr/bin/env bash
# Start the Payments Transformation Simulator locally (backend + frontend).
#
#   ./start.sh            start both
#   ./start.sh --reset    drop the local SQLite database first
#
# Requires Python 3.11+ and Node 20+. Nothing else: the default database is
# SQLite and is created on first start.
#
# Set PYTHON=/path/to/python to choose an interpreter explicitly.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-5173}"
PY_MIN_MINOR=11

info()  { printf '\033[36m==>\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m==>\033[0m %s\n' "$1"; }
fail()  { printf '\033[31m==>\033[0m %s\n' "$1" >&2; exit 1; }

RESET=0
while (($#)); do
  case "$1" in
    --reset) RESET=1 ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) fail "Unknown argument '$1'. Try --help." ;;
  esac
  shift
done

# --- interpreter discovery -------------------------------------------------
# Windows ships "App Execution Alias" stubs for `python` and `python3`: shims
# that resolve on PATH, print "Python was not found; run without arguments to
# install from the Microsoft Store" and exit 49. `command -v python3` therefore
# succeeds on a machine with no Python at all. Every candidate below is proved
# by *running* it, which also rejects an interpreter that is real but too old
# (an Anaconda 3.9 earlier on PATH, say).
PY=()
PY_VERSION=""

probe_python() {
  local -a cmd=("$@")
  local version
  version="$("${cmd[@]}" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || return 1
  [[ "$version" =~ ^3\.([0-9]+)$ ]] || return 1
  ((BASH_REMATCH[1] >= PY_MIN_MINOR)) || return 1
  PY=("${cmd[@]}")
  PY_VERSION="$version"
}

find_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    probe_python "$PYTHON" && return 0
    fail "PYTHON is set to '$PYTHON', which is not a working Python 3.$PY_MIN_MINOR+ interpreter."
  fi
  local candidate tag
  for candidate in python3 python; do
    command -v "$candidate" >/dev/null 2>&1 && probe_python "$candidate" && return 0
  done
  # The Windows launcher reaches interpreters that are not on PATH at all.
  if command -v py >/dev/null 2>&1; then
    for tag in -3.14 -3.13 -3.12 -3.11 -3; do
      probe_python py "$tag" && return 0
    done
  fi
  return 1
}

if ! find_python; then
  hint=""
  if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    hint="

  'python' does resolve on PATH here but does not run. On Windows that is
  almost always the Microsoft Store alias stub. Either install Python from
  python.org, or turn the stub off under
  Settings > Apps > Advanced app settings > App execution aliases."
  fi
  fail "No working Python 3.$PY_MIN_MINOR+ interpreter was found.

  Tried: PYTHON, python3, python, py -3.x
  Install Python 3.$PY_MIN_MINOR or newer, or point PYTHON at one:
    PYTHON=/path/to/python ./start.sh$hint"
fi

command -v node >/dev/null 2>&1 || fail "Node 20+ is required but was not found on PATH."
command -v npm  >/dev/null 2>&1 || fail "npm is required but was not found on PATH."

info "Using Python $PY_VERSION (${PY[*]})"

if ((RESET)); then
  warn "Removing the local SQLite database"
  rm -f "$BACKEND"/data/simulator.db*
fi

# --- backend ---------------------------------------------------------------
if [[ ! -d "$BACKEND/.venv" ]]; then
  info "Creating the backend virtual environment"
  "${PY[@]}" -m venv "$BACKEND/.venv"
fi

VENV_PY=""
for candidate in "$BACKEND/.venv/bin/python" "$BACKEND/.venv/Scripts/python.exe"; do
  [[ -x "$candidate" ]] && VENV_PY="$candidate" && break
done
[[ -n "$VENV_PY" ]] || fail "The virtual environment at $BACKEND/.venv has no interpreter. Delete it and re-run."

# An existing venv may well be a different version from the interpreter found
# above, which is only used to *create* one. Report what actually runs the API.
VENV_VERSION="$("$VENV_PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo unknown)"
info "Backend environment: Python $VENV_VERSION"

# A venv made by `uv venv` (or `python -m venv --without-pip`) has no pip, so an
# existing environment cannot be assumed to have one.
if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
  info "Bootstrapping pip into the existing virtual environment"
  "$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1 \
    || fail "The virtual environment at $BACKEND/.venv has no pip and ensurepip failed. Delete it and re-run."
fi

info "Installing backend dependencies"
"$VENV_PY" -m pip install --quiet --upgrade pip
# Installed from inside $BACKEND with a relative requirement on purpose. Under
# Git Bash an absolute path is an MSYS path (/c/Users/...), which MSYS rewrites
# to a Windows path when it passes it to a native program -- but the "[dev]"
# extras suffix defeats that rewriting, so pip would receive /c/Users/... and
# reject it as "not a valid editable requirement".
(cd "$BACKEND" && "$VENV_PY" -m pip install --quiet -e ".[dev]")

# --- frontend --------------------------------------------------------------
if [[ ! -d "$FRONTEND/node_modules" ]]; then
  info "Installing frontend dependencies"
  (cd "$FRONTEND" && npm install --no-audit --no-fund)
fi

# Signalling the direct child is not enough. On Windows `npm` is itself a shell
# script, so the dev server is a *grandchild*: killing the child orphans Vite,
# which goes on holding the port. The next start then silently binds 5174 while
# the banner still advertises 5173. Job control (set -m) puts each server in its
# own process group so shutdown can signal the whole tree with `kill -- -PID`.
set -m

stop_tree() {
  local pid="${1:-}"
  [[ -n "$pid" ]] || return 0
  kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
}

CLEANED=0
cleanup() {
  # INT/TERM runs this, and so does the EXIT that follows it. Only once.
  ((CLEANED)) && return 0
  CLEANED=1
  info "Shutting down"
  stop_tree "${UI_PID:-}"
  stop_tree "${API_PID:-}"
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# `exec` so the job's leader is the server itself rather than a wrapping
# subshell, which keeps the process group tight.
info "Starting the API on http://localhost:$API_PORT"
(cd "$BACKEND" && exec "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT") &
API_PID=$!

info "Waiting for the API to become ready (first run seeds the demo book)"
API_READY=0
for _ in $(seq 1 90); do
  kill -0 "$API_PID" 2>/dev/null \
    || fail "The API exited before it became ready. Its output is above."
  if curl -fsS "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then
    API_READY=1
    info "API is ready"
    break
  fi
  sleep 1
done
((API_READY)) || fail "The API did not answer http://127.0.0.1:$API_PORT/health within 90s."

info "Starting the console on http://localhost:$UI_PORT"
(cd "$FRONTEND" && exec npm run dev -- --port "$UI_PORT") &
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

# Stop as soon as *either* process does, so a crashed API cannot leave a
# half-running stack that still looks healthy. `wait -n` needs bash 4.3+.
if ((BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 3))); then
  wait -n
else
  wait
fi
