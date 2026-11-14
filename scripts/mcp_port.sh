#!/usr/bin/env bash
# Resolve a TCP bind port. stdout: port only. stderr: messages.
# Env: MCP_PORT (default 8000 for The Sleeper sidecar), MCP_PORT_FALLBACK (default 1), MCP_HOST (default 127.0.0.1)
set -euo pipefail
PORT="${MCP_PORT:-8000}"
FALLBACK="${MCP_PORT_FALLBACK:-1}"
HOST="${MCP_HOST:-127.0.0.1}"

is_free() {
  python3 - "$HOST" "$1" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
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
  if is_free "$p"; then
    echo "make mcp: ${HOST}:${PORT} is busy; falling back to ${HOST}:${p}." >&2
    echo "  Pin the port with: make mcp MCP_PORT=${p} MCP_PORT_FALLBACK=0" >&2
    echo "$p"
    exit 0
  fi
done
echo "make mcp: ${HOST}:${PORT} and the next ports are all busy." >&2
exit 1
