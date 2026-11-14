#!/bin/bash
# J2: reward-integrity fuzz on FR8 (owner: HEAD-INTEGRITY). Do not submit from CI.
#SBATCH --job-name=canary-fuzz
#SBATCH --partition normal
#SBATCH --cpus-per-task 12
#SBATCH --time 04:00:00
#SBATCH --output=/home/%u/agent-arena-data/logs/j2_fuzz-%j.out
set -euo pipefail
cd ~/agent-arena
OUT=~/agent-arena-data/runs
mkdir -p "$OUT" ~/agent-arena-data/logs
for TIER in easy medium hard; do
  for MODE in malformed evolve random; do
    uv run --python 3.12 python -m canary.redteam.fuzz --tier $TIER --seeds 0-199 \
      --budget 50000 --mode $MODE --workers 12 --rng $SLURM_JOB_ID --out "$OUT" || true
  done
done
