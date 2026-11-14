#!/usr/bin/env bash
set -euo pipefail

PORT="${MCP_PORT:-8000}"
FALLBACK="${MCP_PORT_FALLBACK:-1}"
HOST="${MCP_HOST:-127.0.0.1}"
AVOID="${MCP_AVOID_PORT:-}"

PY_BIN=""
for cand in "${PYTHON_BIN:-}" ".venv/bin/python" "/venv/bin/python3" "python3"; do
  if [ -n "$cand" ]; then
    if [ -x "$cand" ] && [ ! -d "$cand" ]; then
      PY_BIN="$cand"
      break
    fi
    if resolved="$(command -v "$cand" 2>/dev/null)" && [ -n "$resolved" ] && [ -x "$resolved" ] && [ ! -d "$resolved" ]; then
      PY_BIN="$resolved"
      break
    fi
  fi
done

if [ -z "$PY_BIN" ]; then
  echo "make mcp: python3 not found." >&2
  exit 127
fi

is_free() {
  if [ -n "$AVOID" ] && [ "$1" = "$AVOID" ]; then
    return 1
  fi
  "$PY_BIN" - "$HOST" "$1" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

if is_free "$PORT"; then
  echo "$PORT"
  exit 0
fi

if [ "$FALLBACK" = "0" ]; then
  echo "make mcp: ${HOST}:${PORT} is already in use." >&2
  echo "  Retry with another port:  make mcp MCP_PORT=8800" >&2
  echo "  Or allow auto-fallback:   make mcp MCP_PORT_FALLBACK=1" >&2
  exit 1
fi

start=$((PORT + 2))
end=$((PORT + 50))
for p in $(seq "$start" "$end"); do
  if [ "$p" -gt 65535 ]; then
    break
  fi
  if [ -n "$AVOID" ] && [ "$p" = "$AVOID" ]; then
    continue
  fi
  if is_free "$p"; then
    echo "make mcp: ${HOST}:${PORT} is busy; falling back to ${HOST}:${p}." >&2
    echo "  Pin the port with: make mcp MCP_PORT=${p} MCP_PORT_FALLBACK=0" >&2
    echo "$p"
    exit 0
  fi
done

echo "make mcp: ${HOST}:${PORT} and the next ports are all busy." >&2
exit 1
