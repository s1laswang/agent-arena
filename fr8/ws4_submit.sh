#!/usr/bin/env bash
# WS4 small investigator v2 (FR8 head only; Silas-authorised Sat 14 Nov once Momin's sky jobs are paused).
#   1 GPU: LoRA v2 train (dense 4k + --oversample-endings 3) on ~/agent-arena-data/j3v14
#   1 GPU: fast KV-cached eval of BASE (starts now)
#   1 GPU: fast KV-cached eval of v2 (afterok:train)
# Every id is appended to ~/agent-arena-data/jobs/OURS.txt. We never touch jobs we did not submit.
# Usage: bash fr8/ws4_submit.sh [--dry-run]
set -euo pipefail
DRY=${1:-}
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
bash fr8/sync.sh
run() { if [ "$DRY" = --dry-run ]; then echo "DRY: $*"; echo 0; else ssh freighter "$@"; fi; }
read -r -d '' REMOTE <<'EOF' || true
set -euo pipefail
cd ~/agent-arena; mkdir -p ~/agent-arena-data/jobs ~/agent-arena-data/j4/runs
log() { echo "$1 $2 $(date -Iseconds) $3" >> ~/agent-arena-data/jobs/OURS.txt; }
DATA=$(ls -d ~/agent-arena-data/j3v14/train/train-*.jsonl ~/agent-arena-data/j3v14/train/*/train-*.jsonl 2>/dev/null | head -1 || true)
[ -n "$DATA" ] || { echo "no j3v14 shards" >&2; exit 2; }
GLOB="$(dirname "$DATA")/train-*.jsonl"
T=$(sbatch --parsable --time=07:00:00 -J canary-ws4-train \
  --export=ALL,STAGES=train,DATA="$GLOB",MAX_EPISODES=800,TRAIN_HOURS=5,TRAIN_ARGS="--window-mode dense --max-len 4096 --oversample-endings 3" \
  fr8/j4_train.sbatch); log "$T" canary-ws4-train "data=$GLOB dense4k oe3 800ep"
B=$(sbatch --parsable --time=03:00:00 -J canary-ws4-evalbase \
  --export=ALL,MODEL=base,N=30,EVAL_MIN=150,RUN_ID=ws4-base-v14 fr8/j4_eval.sbatch); log "$B" canary-ws4-evalbase "n=30/tier heldout"
V=$(sbatch --parsable --time=03:00:00 -J canary-ws4-evalv2 --dependency=afterok:$T \
  --export=ALL,MODEL=$HOME/agent-arena-data/j4/run-$T/lora,N=30,EVAL_MIN=150,RUN_ID=ws4-v2-$T fr8/j4_eval.sbatch); log "$V" canary-ws4-evalv2 "afterok:$T n=30/tier"
echo "train=$T evalbase=$B evalv2=$V"
EOF
run "bash -s" <<<"$REMOTE"
