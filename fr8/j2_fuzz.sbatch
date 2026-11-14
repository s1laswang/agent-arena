#!/bin/bash
# J2: reward-integrity fuzz, hard tier, evolve, 12 workers, 4h (owner: HEAD-INTEGRITY).
# Submit (FR8 head only):  cd ~/agent-arena && mkdir -p ~/agent-arena-data/logs && sbatch fr8/j2_fuzz.sbatch
# Laptop throughput ~1 ms/eval/core -> 4M evals is ~1-2 h on 12 cores, leaving headroom.
#SBATCH --job-name=canary-j2-fuzz
#SBATCH --partition normal
#SBATCH --cpus-per-task 12
#SBATCH --time 04:00:00
#SBATCH --output=agent-arena-data-j2_fuzz-%j.out
set -euo pipefail
cd ~/agent-arena
OUT=~/agent-arena-data/runs
mkdir -p "$OUT" ~/agent-arena-data/logs
# Seeds: dev only (never judge seeds). Exit 1 = findings, keep going so the summary is written.
uv run --python 3.12 python -m canary.redteam.fuzz --tier hard --seeds 0-199 \
  --budget 4000000 --mode evolve --workers 12 --rng "${SLURM_JOB_ID:-0}" --out "$OUT" --report || true
uv run --python 3.12 python -m canary.redteam.fuzz --tier hard --seeds 0-199 \
  --budget 20000 --mode parallel_accuse --out "$OUT" --report || true
mv "agent-arena-data-j2_fuzz-${SLURM_JOB_ID:-0}.out" ~/agent-arena-data/logs/ 2>/dev/null || true
