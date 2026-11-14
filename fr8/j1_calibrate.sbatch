#!/bin/bash
#SBATCH -J canary-j1
#SBATCH -p normal
#SBATCH -c 1
#SBATCH --mem=2G
#SBATCH --time=02:00:00
#SBATCH --array=0-257%16
#SBATCH -o /home/silas/agent-arena-data/j1/slurm-%A_%a.out
# Pilot: sbatch --array=0 --export=ALL,J1_SEEDS=20 fr8/j1_calibrate.sbatch   (16 cores max: %16 x -c 1)
source ~/agent-arena/fr8/env.sh || exit 1
python fr8/j1_grid.py --task "$SLURM_ARRAY_TASK_ID" --seeds "${J1_SEEDS:-500}" \
  --out "${J1_OUT:-$HOME/agent-arena-data/j1}" ${J1_ARGS:-}
