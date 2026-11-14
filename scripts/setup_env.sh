#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${VENV_DIR:-.venv}"
REQ_FILE="${REQ_FILE:-requirements.txt}"
PYTHON_BIN="${PYTHON_BIN:-}"
SETUP_CHECK_ONLY="${SETUP_CHECK_ONLY:-0}"
HOME="${HOME:-/tmp}"
export PATH="${HOME}/.local/bin:${PATH}"

is_valid_python() {
  local candidate="$1"
  local resolved=""
  if resolved="$(command -v "$candidate" 2>/dev/null)" && [ -n "$resolved" ] && [ -x "$resolved" ] && [ ! -d "$resolved" ]; then
    if "$resolved" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      return 0
    fi
    return 1
  fi
  if [ -x "$candidate" ] && [ ! -d "$candidate" ]; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

py_bin=""
if [ -n "$PYTHON_BIN" ]; then
  if is_valid_python "$PYTHON_BIN"; then
    py_bin="$(command -v "$PYTHON_BIN" 2>/dev/null || printf '%s' "$PYTHON_BIN")"
  else
    echo "setup_env: PYTHON_BIN '$PYTHON_BIN' is missing or older than Python 3.11" >&2
    exit 1
  fi
else
  for cand in python3.12 python3.13 python3.11 /venv/bin/python3 python3; do
    if is_valid_python "$cand"; then
      py_bin="$(command -v "$cand" 2>/dev/null || printf '%s' "$cand")"
      break
    fi
  done
fi

if [ "$SETUP_CHECK_ONLY" = "1" ]; then
  if [ -n "$py_bin" ]; then
    echo "setup_env: python=$py_bin ($("$py_bin" --version 2>&1))"
    exit 0
  elif command -v uv >/dev/null 2>&1; then
    echo "setup_env: uv=$(uv --version 2>&1)"
    exit 0
  else
    echo "setup_env: neither Python >=3.11 nor uv found" >&2
    exit 127
  fi
fi

if [ -n "$py_bin" ] && "$py_bin" -m venv "$VENV_DIR"; then
  :
elif command -v uv >/dev/null 2>&1; then
  uv venv --seed --python "${py_bin:-3.12}" "$VENV_DIR"
else
  echo "setup_env: failed to create virtualenv in $VENV_DIR; install Python >=3.11 with venv or uv" >&2
  exit 127
fi

if [ -x "$VENV_DIR/bin/pip" ]; then
  "$VENV_DIR/bin/pip" install -q -r "$REQ_FILE"
elif command -v uv >/dev/null 2>&1; then
  uv pip install -q --python "$VENV_DIR/bin/python" -r "$REQ_FILE"
else
  echo "setup_env: pip missing in $VENV_DIR and uv not found" >&2
  exit 1
fi

"$VENV_DIR/bin/python" --version
