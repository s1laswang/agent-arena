#!/bin/bash
#SBATCH -J canary-ws3-grpo
#SBATCH -p gpu
#SBATCH --gres=gpu:1
#SBATCH -c 6
#SBATCH --mem=28G
#SBATCH --time=06:00:00
#SBATCH -o /home/silas/agent-arena-data/ws3/slurm-%j.out
# WS3 LLM mole: TRL GRPO on Qwen2.5-0.5B (then 1.5B), fp16 on V100 (no bf16/FA2/vLLM).
# Needs train/grpo_mole.py (AGENTS/Momin) and fr8/ws3_trl_setup.sh run once on the login node.
# FR8 head submits, e.g. (up to 3 jobs, one GPU each, different SEED):
#   sbatch --time=06:00:00 --export=ALL,SIZE=0.5B,SEED=0 fr8/ws3_grpo.sbatch
# Env: SIZE (0.5B|1.5B) SEED GRPO_ARGS (passed through) CHECK_ONLY=1 (import + CUDA check, exits)
set -euo pipefail
CODE=${CODE:-$HOME/agent-arena}
D=$HOME/agent-arena-data/ws3
SIZE=${SIZE:-0.5B}
MODEL=$HOME/agent-arena-data/models/Qwen2.5-$SIZE-Instruct
OUT=${OUT:-$D/run-${SLURM_JOB_ID:-local}}
mkdir -p "$OUT"
module load pytorch-volta
export PYTHONPATH=$CODE:$HOME/agent-arena-data/pylib-trl PYTHONUNBUFFERED=1 HF_HOME=$HOME/agent-arena-data/cache \
       HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-4}
PY="pytorch-exec python"
cd "$CODE"
echo "[ws3] $(date) host=$(hostname) size=$SIZE seed=${SEED:-0} out=$OUT"
$PY -c "import torch,trl;print('cuda',torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else '','trl',trl.__version__)"
[ "${CHECK_ONLY:-0}" = 1 ] && { echo "[ws3] CHECK OK"; exit 0; }
[ -d "$MODEL" ] || { echo "[ws3] missing $MODEL (download on login node)"; exit 2; }
[ -f train/grpo_mole.py ] || { echo "[ws3] train/grpo_mole.py not synced yet"; exit 2; }
[ -n "${SLURM_JOB_ID:-}" ] && date -d "$(squeue -j $SLURM_JOB_ID -h -o %e)" +%s > "$OUT/deadline.txt" || true
$PY -m train.grpo_mole --model "$MODEL" --out "$OUT" --seed "${SEED:-0}" --fp16 \
    --workers $(( ${SLURM_CPUS_PER_TASK:-6} - 1 )) ${GRPO_ARGS:-}
echo "[ws3] done $(date)"
