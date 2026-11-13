#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --job-name=sleeper-train
#SBATCH --output=logs/%x-%j.out
module load pytorch-volta
export HF_HOME=$HOME/momin/sleeper/hf
export HF_HUB_OFFLINE=1
cd $HOME/momin/sleeper
MODEL=${MODEL:-$HOME/momin/sleeper/models/Qwen2.5-1.5B-Instruct}
DATA=${DATA:-train/data/train.jsonl}
OUT=$HOME/momin/sleeper/runs/$SLURM_JOB_ID
mkdir -p $OUT
pytorch-exec python -m train.sft --model $MODEL --data $DATA --out $OUT $EXTRA
