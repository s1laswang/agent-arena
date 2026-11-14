#!/bin/bash
# Mole Forge (CPU only). Submitted by the FR8 head: sbatch fr8/forge_job.sbatch [mutator] [run_name]
#SBATCH --job-name=canary-forge
#SBATCH --partition=normal
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=%x-%j.out
set -euo pipefail
MUTATOR=${1:-stub}
RUN=${2:-forge_${MUTATOR//:/_}_${SLURM_JOB_ID:-local}}
OUT=$HOME/agent-arena-data/forge/$RUN
mkdir -p "$OUT"
cd "$HOME/agent-arena"
# J5b: investigators = canary.baselines.Heuristic + canary.forge.investigators.HintedHeuristic (Bayesian canary bisection);
# fitness = solver - max_i investigator (FITNESS=min), feasible iff solver >= 0.5 x default and acc >= MIN_ACC (0.75)
# resumable: re-submitting with the same RUN continues from log.jsonl
uv run --python 3.12 --extra llm python -m canary.forge.evolve \
  --mutator "$MUTATOR" --tier "${TIER:-hard}" --pop 16 --gens 50 --seeds 0-19 \
  --fitness "${FITNESS:-min}" --min-solver-acc "${MIN_ACC:-0.75}" \
  --workers "${SLURM_CPUS_PER_TASK:-8}" --out "$OUT" 2>&1 | tee -a "$OUT/stdout.log"
