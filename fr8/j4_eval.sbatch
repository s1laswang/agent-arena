#!/bin/bash
#SBATCH -J canary-j4-eval
#SBATCH -p gpu
#SBATCH --gres=gpu:1
#SBATCH -c 4
#SBATCH --mem=24G
#SBATCH --time=01:30:00
#SBATCH -o /home/silas/agent-arena-data/j4/eval-%j.out
# Fast held-out eval (KV reuse, per-episode call cap). FR8 head submits:
#   sbatch --export=ALL,MODEL=base,N=30 fr8/j4_eval.sbatch
#   sbatch --export=ALL,MODEL=$HOME/agent-arena-data/j4/run-44397/lora,N=30 fr8/j4_eval.sbatch
# Env: MODEL (base | LoRA adapter dir | HF dir), ADAPTER (optional: LoRA dir applied on MODEL),
#      N (seeds/tier, 30), TIERS (easy,medium,hard), MAX_CALLS (120), MAX_NEW (96),
#      EVAL_MIN (75: stop starting new episodes), RUN_ID, OUT (~/agent-arena-data/j4/runs)
set -euo pipefail
CODE=${CODE:-$HOME/agent-arena}
MODEL=${MODEL:-base}
if [ -n "${ADAPTER:-}" ]; then MODEL=$ADAPTER; fi   # eval_hf reads the base from adapter_config.json
TAG=$([ "$MODEL" = base ] && echo base || basename "$(dirname "$MODEL")")-$(basename "$MODEL")
OUT=${OUT:-$HOME/agent-arena-data/j4/runs}
RUN_ID=${RUN_ID:-fast-$TAG-${SLURM_JOB_ID:-local}}
module load pytorch-volta
export PYTHONPATH=$CODE PYTHONUNBUFFERED=1 HF_HOME=$HOME/agent-arena-data/cache HF_HUB_OFFLINE=1 \
       TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-4}
cd "$CODE"
echo "[j4-eval] $(date) host=$(hostname) model=$MODEL run=$RUN_ID"
pytorch-exec python -m train.eval_hf --model "$MODEL" --tiers "${TIERS:-easy,medium,hard}" \
  --seeds heldout --n "${N:-30}" --seed-offset "${SEED_OFFSET:-0}" --max-calls "${MAX_CALLS:-120}" --max-new-tokens "${MAX_NEW:-96}" \
  --max-minutes "${EVAL_MIN:-75}" --out "$OUT" --run-id "$RUN_ID"
echo "[j4-eval] done $(date) -> $OUT/$RUN_ID"
