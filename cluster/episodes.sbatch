#!/bin/bash
#SBATCH --partition=normal
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --job-name=sleeper-episodes
#SBATCH --array=0-19
#SBATCH --output=logs/%x-%A_%a.out
cd $HOME/momin/sleeper
TEAM=${TEAM:-oracle}
START=$((1000+SLURM_ARRAY_TASK_ID*10))
venv/bin/python -m lab.run --team $TEAM --day-start $START --days 10
