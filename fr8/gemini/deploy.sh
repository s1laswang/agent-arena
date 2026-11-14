#!/usr/bin/env bash
# One command: push this branch's code to freighter:~/agent-arena-gemini, build/refresh the uv env, make sure the
# gateway token (0600) and the server-side key file (0600, ~/agent-arena-gemini/.gateway.env) exist, then verify the
# env on a compute node with a 5-minute srun. The key is streamed over ssh stdin: never on argv, never echoed.
#   bash fr8/gemini/deploy.sh [--no-verify] [--rotate-key]
set -euo pipefail
source "$(dirname "$0")/common.sh"
cd "$REPO_ROOT"
VERIFY=1; ROTATE=0
for a in "$@"; do case $a in --no-verify) VERIFY=0;; --rotate-key) ROTATE=1;; *) echo "unknown arg $a" >&2; exit 2;; esac; done

ssh "$FR8_HOST" "mkdir -p $GEM_CODE $GEM_DATA/{ledger,gateway,logs,jobs} && chmod 700 $GEM_CODE"
rsync -e "$FR8_RSYNC_RSH" -az --delete \
  --exclude .git --exclude .venv --exclude 'data/gemini/' --exclude 'data/fr8/' --include 'data/runs/committed/***' \
  --exclude 'data/runs/*' --exclude 'results/latest/' --exclude '.env' --exclude '.env.*' \
  --exclude .gateway_token --exclude .gateway.env --exclude run/ --exclude __pycache__ --exclude .pytest_cache \
  --exclude node_modules --exclude 'game/site/' \
  ./ "$FR8_HOST:agent-arena-gemini/"
echo "deploy: synced $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD)) -> $FR8_HOST:$GEM_CODE"

# server-side key file: only GEMINI_API_KEY, 0600, written from stdin (umask 077 before the file exists)
if [ "$ROTATE" = 1 ] || ! ssh "$FR8_HOST" "test -s $GEM_CODE/.gateway.env"; then
  grep -E '^[[:space:]]*(export[[:space:]]+)?GEMINI_API_KEY=' .env | head -1 | sed -E 's/^[[:space:]]*(export[[:space:]]+)?//' \
    | ssh "$FR8_HOST" "umask 077 && cat > $GEM_CODE/.gateway.env.tmp && chmod 600 $GEM_CODE/.gateway.env.tmp && mv $GEM_CODE/.gateway.env.tmp $GEM_CODE/.gateway.env"
  echo "deploy: wrote $GEM_CODE/.gateway.env (0600)"
fi
# gateway token: generated on the server, 0600, never leaves FR8 (workers read the file over the shared /home)
ssh "$FR8_HOST" "cd $GEM_CODE && if [ ! -s .gateway_token ]; then (umask 077; python3 -c 'import secrets;print(secrets.token_urlsafe(32))' > .gateway_token); echo 'deploy: new gateway token'; fi; chmod 600 .gateway_token .gateway.env; stat -c '%a %n' .gateway_token .gateway.env"

# uv env (login node, niced: download/link only, warm shared cache; compute nodes have no internet)
ssh "$FR8_HOST" "cd $GEM_CODE && export UV_CACHE_DIR=\$HOME/agent-arena-data/cache/uv UV_PYTHON_INSTALL_DIR=\$HOME/agent-arena-data/cache/python && nice -n 19 \$HOME/.local/bin/uv sync -q --python 3.12 --extra llm --extra dev && echo 'deploy: uv env ok'"

if [ "$VERIFY" = 1 ]; then
  ssh "$FR8_HOST" "cd $GEM_CODE && srun -p normal --time=00:05:00 -c 1 --mem=1G -J canary-gem-verify .venv/bin/python -c 'import socket, google.genai, httpx2, canary.gemini.gateway, canary.gemini.sdk; print(\"deploy: compute env ok on\", socket.gethostname())'"
fi
