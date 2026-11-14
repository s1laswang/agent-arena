#!/bin/bash
#SBATCH -J canary-v3-grpo
#SBATCH -p gpu
#SBATCH --gres=gpu:1
#SBATCH -c 6
#SBATCH --mem=32G
#SBATCH --time=07:00:00
#SBATCH -o /home/silas/agent-arena-data/v3/slurm-%j.out
# WS4 v3: decision-point GRPO from the v2 SFT LoRA (train/grpo_investigator.py), fp16 V100, easy+medium TRAIN seeds.
# FR8 head submits ONLY after Silas's GPU OK (relayed by the CEO): bash fr8/v3_submit.sh
# Env: ADAPTER (v2 LoRA dir, required) SEED HOURS (5.5) V3_ARGS (extra args)
set -euo pipefail
CODE=${CODE:-$HOME/agent-arena}
MODEL=$HOME/agent-arena-data/models/Qwen2.5-1.5B-Instruct
OUT=${OUT:-$HOME/agent-arena-data/v3/run-${SLURM_JOB_ID:-local}}
mkdir -p "$OUT"
module load pytorch-volta
export PYTHONPATH=$CODE PYTHONUNBUFFERED=1 HF_HOME=$HOME/agent-arena-data/cache HF_HUB_OFFLINE=1 \
       TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1
cd "$CODE"
[ -f "${ADAPTER:?ADAPTER=v2 lora dir}/adapter_config.json" ] || { echo "[v3] no adapter at $ADAPTER"; exit 2; }
[ -n "${SLURM_JOB_ID:-}" ] && date -d "$(squeue -j $SLURM_JOB_ID -h -o %e)" +%s > "$OUT/deadline.txt" || true
echo "[v3] $(date) host=$(hostname) adapter=$ADAPTER seed=${SEED:-0} out=$OUT"
pytorch-exec python -m train.grpo_investigator --model "$MODEL" --adapter "$ADAPTER" --out "$OUT" --fp16 \
  --seed "${SEED:-0}" --hours "${HOURS:-5.5}" --deadline-file "$OUT/deadline.txt" --margin-min 15 \
  --workers $(( ${SLURM_CPUS_PER_TASK:-6} - 2 )) ${V3_ARGS:-}
echo "[v3] done $(date)"
