#!/bin/bash
#SBATCH -J canary-grpo-mole
#SBATCH -p gpu
#SBATCH --gres=gpu:1
#SBATCH -c 8
#SBATCH --mem=24G
#SBATCH --time=06:00:00
#SBATCH -o /home/silas/agent-arena-data/grpo_mole/slurm-%j.out
# WS3 LLM mole (owner: HEAD-AGENTS + Momin; FR8 head submits). GRPO on a Qwen2.5 mole, fp16 AMP, LoRA.
# Rewards = CPU env rollouts in a process pool of $SLURM_CPUS_PER_TASK workers (counts toward the 24-core cap).
# Knobs (--export=ALL,VAR=..):
#   SIZE=0.5B|1.5B  STEPS=200  GROUP=8  PPS=4 (prompts/step)  NPROMPTS=256  LR=1e-5
#   BASE_POLICY=<path to rl_mole json under $CODE>  BACKEND=torch|trl  SMOKE=1 (dry-run: rewards only, no GPU use)
set -euo pipefail
CODE=${CODE:-$HOME/agent-arena}
D=$HOME/agent-arena-data/grpo_mole
SIZE=${SIZE:-0.5B}
MODEL=$HOME/agent-arena-data/models/Qwen2.5-${SIZE}-Instruct
RUN=${RUN:-$D/run-${SIZE}-${SLURM_JOB_ID:-local}}
mkdir -p "$RUN"
module load pytorch-volta
export PYTHONPATH=$CODE:$HOME/agent-arena-data/pylib PYTHONUNBUFFERED=1 HF_HOME=$HOME/agent-arena-data/cache \
       HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1
PY="pytorch-exec python"
cd "$CODE"
echo "[grpo_mole] $(date) host=$(hostname) run=$RUN model=$MODEL"
BP=${BASE_POLICY:+--base-policy $BASE_POLICY}
if [ "${SMOKE:-0}" = 1 ]; then
  $PY -m train.grpo_mole --dry-run --n-prompts 8 --group 4 $BP | tee "$RUN/dryrun.json"; echo "[grpo_mole] SMOKE OK"; exit 0
fi
[ -f "$MODEL/config.json" ] || { echo "[grpo_mole] missing $MODEL (download on the login node, see fr8/grpo_mole_setup.sh)"; exit 2; }
$PY -c "import torch;print('cuda',torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
$PY -m train.grpo_mole --model "$MODEL" --out "$RUN" --backend "${BACKEND:-torch}" $BP \
    --steps "${STEPS:-200}" --group "${GROUP:-8}" --prompts-per-step "${PPS:-4}" --n-prompts "${NPROMPTS:-256}" \
    --lr "${LR:-1e-5}" --workers "${SLURM_CPUS_PER_TASK:-8}"
echo "[grpo_mole] done $(date)"
