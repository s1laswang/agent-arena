#!/bin/bash
# UNTESTED on the cluster. Before/after table: base model vs base + LoRA on eval episodes (1 GPU).
# Submit from the repo root:  sbatch training/slurm/eval_small_model.sbatch
#SBATCH --job-name=pinbox-eval-small
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=training/slurm/logs/%x-%j.out
# CHANGE: the GPU partition name on FR8.
##SBATCH --partition=gpu

source training/slurm/common.sh
MODEL="${MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
ADAPTER="${ADAPTER:-training/out/$(basename "$MODEL")-lora}"

python training/eval_small_model.py --model "$MODEL" --adapter "$ADAPTER" \
    --limit "${LIMIT:-10}" --save-runs runs/small_model --out training/out/small_model_eval.json
# Re-grade the saved runs with the normal eval (no GPU needed):
#   python -m pinbox eval --include-recorded runs/small_model
