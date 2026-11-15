#!/usr/bin/env bash
# WS4 v3 (FR8 head only, after Silas's GPU OK via the CEO): 2 GRPO jobs (seeds 0,1; 1 GPU each, --time 7h),
# each followed (afterok) by a held-out fast eval n=30/tier (--time 3h). Ids go to OURS.txt.
# Usage: ADAPTER=~/agent-arena-data/j4/run-44410/lora bash fr8/v3_submit.sh
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
bash fr8/sync.sh
ssh freighter "ADAPTER='${ADAPTER:-\$HOME/agent-arena-data/j4/run-44410/lora}' bash -s" <<'REMOTE'
set -euo pipefail
cd ~/agent-arena; mkdir -p ~/agent-arena-data/v3 ~/agent-arena-data/jobs
ADAPTER=$(eval echo "$ADAPTER")
[ -f "$ADAPTER/adapter_config.json" ] || { echo "v2 adapter missing: $ADAPTER" >&2; exit 2; }
log() { echo "$1 $2 $(date -Iseconds) $3" >> ~/agent-arena-data/jobs/OURS.txt; }
for s in 0 1; do
  T=$(sbatch --parsable --time=07:00:00 -J canary-v3-grpo-s$s --export=ALL,ADAPTER="$ADAPTER",SEED=$s,HOURS=5.5 fr8/v3_grpo.sbatch)
  log "$T" canary-v3-grpo-s$s "from $ADAPTER easy+medium TRAIN"
  E=$(sbatch --parsable --time=03:00:00 -J canary-v3-eval-s$s --dependency=afterok:$T \
      --export=ALL,MODEL=$HOME/agent-arena-data/v3/run-$T/lora,N=30,EVAL_MIN=170,RUN_ID=v3-s$s-$T,OUT=$HOME/agent-arena-data/v3/runs fr8/j4_eval.sbatch)
  log "$E" canary-v3-eval-s$s "afterok:$T n=30/tier heldout"
  echo "seed$s train=$T eval=$E"
done
REMOTE
