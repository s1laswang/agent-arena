#!/usr/bin/env bash
# M1 smoke: one ledgered Gemini call from a compute node through the login-node gateway (5-minute srun).
#   bash fr8/gemini/smoke.sh [model]
set -euo pipefail
source "$(dirname "$0")/common.sh"
MODEL=${1:-gemini-3.1-flash-lite}
ssh "$FR8_HOST" "cd $GEM_CODE && test -s run/gateway.url || { echo 'gateway not up (fr8/gemini/gateway_up.sh)'; exit 1; } && \
  srun -p normal --time=00:05:00 -c 1 --mem=1G -J canary-gem-smoke env \
    GEMINI_GATEWAY_URL=\$(cat run/gateway.url) GEMINI_GATEWAY_TOKEN_FILE=$GEM_CODE/.gateway_token GEMINI_API_KEY= \
    CANARY_GEMINI_LEDGER_DIR=$GEM_DATA/ledger \
    bash -c 'echo \"internet from \$(hostname): \$(curl -s -m 5 -o /dev/null -w %{http_code} https://generativelanguage.googleapis.com || true)\"; .venv/bin/python -m canary.gemini.sdk $MODEL'"
