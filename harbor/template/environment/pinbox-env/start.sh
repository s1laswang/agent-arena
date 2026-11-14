#!/bin/sh
# Start the Poisoned Inbox MCP server for one episode (runs inside pinbox-env).
#   start.sh FAMILY:SEED:DIFFICULTY
# Admin token: from $PINBOX_ADMIN_TOKEN if set (shared-verifier builds), else a
# fresh random one. Either way it is saved in a folder only this container's
# user can read, so the collect hook can fetch the grade after the agent stops.
set -eu

SPEC="${1:-${PINBOX_EPISODE:-}}"
if [ -z "$SPEC" ]; then
    echo "start.sh: no episode spec given" >&2
    exit 2
fi

mkdir -p /srv/pinbox/state /srv/pinbox/out /srv/pinbox/secret
chmod 0700 /srv/pinbox/secret

if [ -z "${PINBOX_ADMIN_TOKEN:-}" ]; then
    PINBOX_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
fi
( umask 077 && printf '%s' "$PINBOX_ADMIN_TOKEN" > /srv/pinbox/secret/admin_token )
export PINBOX_ADMIN_TOKEN

echo "pinbox-env: serving $SPEC (payload sources: ${PINBOX_PAYLOAD_SOURCES:-handwritten})" >&2
exec python -m pinbox serve "$SPEC" --transport http --host 0.0.0.0 --port 8000
