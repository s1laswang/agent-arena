#!/bin/bash
# UNTESTED on the cluster. LoRA SFT on 1 V100 (fp16, sdpa).
# Submit from the repo root:  sbatch training/slurm/train_lora.sbatch
# Smaller / faster:           MODEL=Qwen/Qwen2.5-1.5B-Instruct sbatch training/slurm/train_lora.sbatch
#SBATCH --job-name=pinbox-lora
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=12:00:00
#SBATCH --output=training/slurm/logs/%x-%j.out
# CHANGE: the GPU partition name on FR8 (and the gres type, e.g. gpu:v100:1, if needed).
##SBATCH --partition=gpu
#SBATCH --requeue

source training/slurm/common.sh
MODEL="${MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
OUT="${OUT:-training/out/$(basename "$MODEL")-lora}"

python training/train_lora.py --dry-run --model "$MODEL" --out "$OUT"
# --resume picks up the newest checkpoint if the job was requeued.
python training/train_lora.py --model "$MODEL" --out "$OUT" --resume \
    --data training/data/sft.jsonl --max-len "${MAX_LEN:-16384}" --epochs "${EPOCHS:-2}"
