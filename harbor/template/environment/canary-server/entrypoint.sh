#!/bin/sh
# Sidecar entrypoint (runs as uid canary): one Canary episode (CANARY_TIER / CANARY_SEED from compose)
# behind streamable HTTP. One server container per trial: the server is single-episode.
#
# Secrets:
# - World secret: the build-time 0600 file /opt/canary-server/data/worlds/judge/SALT (read by canary/world.py).
#   CANARY_WORLD_SECRET is deliberately NOT used, so the secret is in no process environment.
# - Ledger token: created here, written to a 0600 file in this container only (read by the collect hook).
#   mcp_server.py currently takes it from the environment only, so it is exported to the server process
#   here; that environ lives in this container's PID namespace, which the agent container cannot see.
#   (Proposed: CANARY_LEDGER_TOKEN_FILE / CANARY_WORLD_SECRET_FILE in mcp_server.py, see harbor/README.md.)
set -eu
umask 077
unset CANARY_WORLD_SECRET CANARY_ADMIN_TOKEN   # no env secret; /admin/reset stays disabled
if [ ! -s /opt/canary-server/data/worlds/judge/SALT ]; then
  echo "canary-server: build-time SALT missing; refusing to start (judge worlds must be paired)" >&2
  exit 3
fi
if [ -z "${CANARY_LEDGER_TOKEN:-}" ]; then
  CANARY_LEDGER_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
fi
printf '%s' "$CANARY_LEDGER_TOKEN" > /run/canary/ledger_token
export CANARY_LEDGER_TOKEN
exec python -m canary.mcp_server
