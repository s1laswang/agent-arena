#!/usr/bin/env bash
# Pull FR8 Gemini data to the Mac (gitignored): ledger -> data/gemini/ledger/fr8/ (so the dashboard counts it),
# everything else (gateway stats, logs, ladder/atlas/swarm outputs) -> data/gemini/fr8/.
#   bash fr8/gemini/pull.sh [subdir ...]     (default: everything except the code)
set -euo pipefail
source "$(dirname "$0")/common.sh"
cd "$REPO_ROOT"
mkdir -p data/gemini/ledger/fr8 data/gemini/fr8
rsync -az "$FR8_HOST:agent-arena-data/gemini/ledger/" data/gemini/ledger/fr8/
if [ $# -gt 0 ]; then
  for d in "$@"; do mkdir -p "data/gemini/fr8/$d"; rsync -az "$FR8_HOST:agent-arena-data/gemini/$d/" "data/gemini/fr8/$d/"; done
else
  rsync -az --exclude ledger/ "$FR8_HOST:agent-arena-data/gemini/" data/gemini/fr8/
fi
echo "pulled -> data/gemini/ledger/fr8 ($(cat data/gemini/ledger/fr8/*.jsonl 2>/dev/null | wc -l | tr -d ' ') ledger rows), data/gemini/fr8"
du -sh data/gemini/fr8 2>/dev/null | tail -1
