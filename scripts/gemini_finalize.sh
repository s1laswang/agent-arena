#!/usr/bin/env bash
# Merge the Gemini staging dirs into committed run dirs and regenerate every derived table (no API cost).
#   bash scripts/gemini_finalize.sh v1.4        (from the v1.4 worktree)
#   bash scripts/gemini_finalize.sh v1.3        (v1.3 analysis runs under scripts/with_tiers.py v1.3)
set -euo pipefail
V=${1:?tiers version}
SEEDS=${SEEDS:-0-29}
PY="uv run --python 3.12 --extra llm --extra dev python -W ignore"
WT=""
[ "$V" = "v1.3" ] && WT="scripts/with_tiers.py v1.3"
PRICING="gemini-4-carbon list prices per 1M tokens: input \$2.00, cached input \$0.10, output (incl. thinking) \$10.00 through 2026-11-30 (aistudio.google.com/docs/pricing, checked 2026-11-14). cost_usd_est bills cached input at \$0.10; the upper bound bills all input at \$2.00. OpenCode runs also carry OpenCode's own reported cost (models.dev prices)."
ROOT=data/runs/committed/$V
$PY scripts/merge_staging.py --staging data/runs/staging-gemini-$V --root $ROOT --planned $SEEDS --tiers-version $V \
  --map opencode=opencode-gemini-4-carbon,inproc=inproc-gemini-4-carbon --pricing "$PRICING" \
  --provenance "scripts/gemini_runner.py (one episode per process, resumable; infra-invalid attempts excluded and retried), merged by scripts/merge_staging.py"
if [ -d data/runs/staging-gemini-3.5-flash-$V ]; then
  $PY scripts/merge_staging.py --staging data/runs/staging-gemini-3.5-flash-$V --root $ROOT --planned $SEEDS --tiers-version $V \
    --map opencode=opencode-gemini-3.5-flash --pricing "gemini-3.5-flash: not on the pricing page (2026-11-14); see opencode_reported_cost_usd" \
    --provenance "scripts/gemini_runner.py --model gemini-3.5-flash, merged by scripts/merge_staging.py"
fi
RUNS=$(ls -d $ROOT/opencode-gemini-* $ROOT/inproc-gemini-* 2>/dev/null)
$PY $WT scripts/verify_replay.py $RUNS | tail -n 3
$PY $WT scripts/paired_gemini.py --version $V --seeds $SEEDS --out-md $ROOT/paired_table_gemini.md --out-json $ROOT/paired_table_gemini.json > /dev/null
for r in $RUNS; do
  [ "$V" = "v1.3" ] && M="$PY scripts/with_tiers.py v1.3 -m" || M="$PY -m"
  $M canary.analysis.tags --runs $r --out $r/tags.json > /dev/null
  $M canary.analysis.accuse --runs $r --out $r/accuse.md > /dev/null
  $PY $WT scripts/regret_report.py $(ls $r/*/episodes.jsonl) --out results --name "$(basename $r)-$V" > /dev/null 2>&1 || echo "regret_report failed for $r"
done
cat $ROOT/paired_table_gemini.md
