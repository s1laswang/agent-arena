#!/usr/bin/env bash
# v1.5-candidate spot check (gemini-4-carbon, OpenCode over MCP, hard seeds 0-9): merge, replay-verify, paired table, audit.
set -euo pipefail
PY="uv run --python 3.12 --extra llm --extra dev python -W ignore"
R=data/runs/committed/v1.5-candidate
$PY scripts/merge_staging.py --staging data/runs/staging-gemini-v1.5-candidate --root $R --planned 0-9 \
  --tiers-version v1.5-candidate --map opencode=opencode-gemini-4-carbon \
  --pricing "gemini-4-carbon \$2/\$10 per 1M, cached \$0.10 (aistudio pricing 2026-11-14)" \
  --provenance "scripts/with_tiers.py v1.5-candidate scripts/gemini_runner.py (OpenCode 1.18.29 over MCP), merged by scripts/merge_staging.py"
echo "replay under v1.5-candidate:"; $PY scripts/with_tiers.py v1.5-candidate scripts/verify_replay.py $R/opencode-gemini-4-carbon | tail -n 1
echo "replay under v1.4 (control):"; $PY scripts/verify_replay.py $R/opencode-gemini-4-carbon | tail -n 1 || true
$PY scripts/with_tiers.py v1.5-candidate scripts/paired_gemini.py --version v1.5-candidate --seeds 0-9 \
  --out-md $R/paired_table_gemini.md --out-json $R/paired_table_gemini.json
$PY scripts/with_tiers.py v1.5-candidate -m canary.analysis.accuse --runs $R/opencode-gemini-4-carbon --out $R/opencode-gemini-4-carbon/accuse.md
$PY scripts/with_tiers.py v1.5-candidate -m canary.analysis.tags --runs $R/opencode-gemini-4-carbon --out $R/opencode-gemini-4-carbon/tags.json > /dev/null
