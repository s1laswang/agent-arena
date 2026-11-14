#!/usr/bin/env bash
# Push code (not data/secrets) to freighter:~/agent-arena. Run from anywhere.
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
rsync -az --delete --exclude .git --exclude .venv --exclude data/runs --exclude data/fr8 \
  --exclude .env --exclude '.env.*' --exclude __pycache__ --exclude .pytest_cache \
  ./ freighter:~/agent-arena/
echo "synced $(git rev-parse --short HEAD) -> freighter:~/agent-arena"
