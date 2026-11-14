#!/bin/bash
#SBATCH -J canary-j5
#SBATCH -p normal
#SBATCH -c 8
#SBATCH --mem=8G
#SBATCH --time=05:00:00
#SBATCH -o /home/silas/agent-arena-data/j5/slurm-%j.out
# TODO(AGENTS): confirm canary.forge.evolve CLI when it lands. Override with J5_ARGS.
# Compute nodes have NO internet (curl rc=6): --llm gemini:* cannot run here; stub only.
source ~/agent-arena/fr8/env.sh || exit 1
python -m canary.forge.evolve --llm stub --seed 0 --workers 8 \
  --out $HOME/agent-arena-data/j5/run-$SLURM_JOB_ID ${J5_ARGS:-}
