#!/bin/sh
# Sidecar entrypoint (runs as uid canary): one Canary episode behind streamable HTTP.
# One server container per trial: the server is single-episode.
#
# No secret and no seed is in any environment variable (EXPLOITS #25). mcp_server.py reads 0600 files:
#   CANARY_EPISODE_FILE       /opt/canary-server/episode.json         {"tier", "seed"}, baked at build time
#   CANARY_WORLD_SECRET_FILE  /opt/canary-server/data/worlds/judge/SALT  world secret, baked at build time
#   CANARY_LEDGER_TOKEN_FILE  /run/canary/ledger_token                 made here; read by the collect hook too
set -eu
umask 077
if [ ! -s /opt/canary-server/data/worlds/judge/SALT ] || [ ! -s /opt/canary-server/episode.json ]; then
  echo "canary-server: build-time SALT or episode.json missing; refusing to start" >&2
  exit 3
fi
# A token from compose (shared-verifier builds only) is moved into the file; otherwise a fresh one is made.
if [ -n "${CANARY_LEDGER_TOKEN:-}" ]; then
  printf '%s' "$CANARY_LEDGER_TOKEN" > /run/canary/ledger_token
else
  python -c 'import secrets; print(secrets.token_hex(32), end="")' > /run/canary/ledger_token
fi
unset CANARY_LEDGER_TOKEN CANARY_WORLD_SECRET CANARY_ADMIN_TOKEN CANARY_ADMIN_TOKEN_FILE CANARY_TIER CANARY_SEED
exec python -m canary.mcp_server
