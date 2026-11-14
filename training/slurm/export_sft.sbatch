#!/bin/bash
# UNTESTED on the cluster. CPU only: builds training/data/sft.jsonl (stdlib Python, ~1 min).
# Submit from the repo root:  sbatch training/slurm/export_sft.sbatch
#SBATCH --job-name=pinbox-export
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --output=training/slurm/logs/%x-%j.out
# CHANGE: the CPU partition name on FR8.
##SBATCH --partition=cpu

source training/slurm/common.sh
python training/export_sft.py --n-per-family "${N_PER_FAMILY:-300}" --out training/data/sft.jsonl
