#!/bin/bash
# J2: reward-integrity fuzz (CLI owner: HEAD-INTEGRITY, canary.redteam.fuzz). Capped at 8 cores (FR8 budget 24 total).
#SBATCH -J canary-j2
#SBATCH -p normal
#SBATCH -c 8
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH -o /home/silas/agent-arena-data/j2/slurm-%j.out
source ~/agent-arena/fr8/env.sh || exit 1
OUT=$HOME/agent-arena-data/j2; mkdir -p "$OUT"
for TIER in easy medium hard; do
  for MODE in malformed evolve random; do
    python -m canary.redteam.fuzz --tier $TIER --seeds 0-199 --budget 50000 --mode $MODE \
      --workers 8 --rng ${J2_RNG:-0} --out "$OUT" ${J2_ARGS:-} || true
  done
done
