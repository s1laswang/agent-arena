#!/bin/bash
#SBATCH -J canary-j4
#SBATCH -p gpu
#SBATCH --gres=gpu:1
#SBATCH -c 6
#SBATCH --mem=28G
#SBATCH --time=06:00:00
#SBATCH -o /home/silas/agent-arena-data/j4/slurm-%j.out
# J4 (owner: FR8 trainer): pilot timing -> LoRA SFT -> eval base vs LoRA on held-out seeds.
# Submit (FR8 head only):  sbatch fr8/j4_train.sbatch
# Knobs (export before sbatch, or --export=ALL,VAR=..):
#   DATA       glob of SFT shards      (default ~/agent-arena-data/j3/train/*/train-*.jsonl)
#   EPOCHS=1  MAX_STEPS=0  TRAIN_HOURS=3.5  N_EVAL=30 (seeds/tier)  EVAL_MIN=40 (per model)
#   STAGES="pilot train eval"   SMOKE=1 -> CPU-safe tiny-model run on fake data (any partition)
# Uses the pytorch-volta container (torch 2.5.1/cu121, transformers, peft); code = ~/agent-arena.
set -euo pipefail
CODE=${CODE:-$HOME/agent-arena}
D=$HOME/agent-arena-data/j4
MODEL=$HOME/agent-arena-data/models/Qwen2.5-1.5B-Instruct
RUN=${RUN:-$D/run-${SLURM_JOB_ID:-local}}
DATA=${DATA:-"$HOME/agent-arena-data/j3/train/*/train-*.jsonl"}
STAGES=${STAGES:-"pilot train eval"}
mkdir -p "$RUN"
module load pytorch-volta
export PYTHONPATH=$CODE PYTHONUNBUFFERED=1 HF_HOME=$HOME/agent-arena-data/cache \
       HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-4}
PY="pytorch-exec python"
cd "$CODE"
echo "[j4] $(date) host=$(hostname) run=$RUN stages=$STAGES max_episodes=${MAX_EPISODES:-all}"
# deadline file for lora_sft's time budget (squeue is not visible inside the container)
[ -n "${SLURM_JOB_ID:-}" ] && date -d "$(squeue -j $SLURM_JOB_ID -h -o %e)" +%s > "$D/deadline-$SLURM_JOB_ID.txt" || true
EPI=${MAX_EPISODES:+--max-episodes $MAX_EPISODES}
$PY -c "import torch;print('cuda',torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"

if [ "${SMOKE:-0}" = 1 ]; then
  $PY -m train.export_sft --policy fake --split train --tier all --n 8 --out "$RUN/fake"
  $PY -m train.lora_sft --data "$RUN/fake" --out "$RUN/smoke-lora" --model "$MODEL" --tiny \
      --max-steps 2 --grad-accum 2 --max-len 1024
  $PY -m train.eval_hf --fake --n 3 --tiers easy --out "$RUN/runs" --run-id smoke
  echo "[j4] SMOKE OK"; exit 0
fi

for s in $STAGES; do case $s in
  pilot)
    $PY -m train.lora_sft --data "$DATA" --out "$RUN/pilot" --model "$MODEL" --pilot $EPI ${TRAIN_ARGS:-} \
        --pilot-steps 5 --epochs "${EPOCHS:-1}" --max-steps "${MAX_STEPS:-0}" ;;
  train)
    $PY -m train.lora_sft --data "$DATA" --out "$RUN/lora" --model "$MODEL" $EPI ${TRAIN_ARGS:-} \
        --epochs "${EPOCHS:-1}" --max-steps "${MAX_STEPS:-0}" --max-hours "${TRAIN_HOURS:-3.5}" ;;
  eval)
    for m in base "$RUN/lora"; do
      [ "$m" = base ] || [ -f "$m/adapter_config.json" ] || { echo "[j4] no adapter, skip"; continue; }
      tag=$([ "$m" = base ] && echo base || echo lora)
      $PY -m train.eval_hf --model "$m" --tiers easy,medium,hard --seeds heldout \
          --n "${N_EVAL:-30}" --max-minutes "${EVAL_MIN:-40}" --out "$RUN/runs" --run-id "eval-$tag"
    done
    for tag in base lora; do f="$RUN/runs/eval-$tag/summary.json"; [ -f "$f" ] && { echo "== $tag"; cat "$f"; }; done ;;
esac; done
echo "[j4] done $(date)"
