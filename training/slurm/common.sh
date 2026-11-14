#!/bin/bash
# UNTESTED. Shared setup for the FR8 Slurm jobs. Source it from the .sbatch files.
# Change the lines marked CHANGE to match the cluster (module names, paths).
set -euo pipefail

# Repo root = the folder you ran sbatch from (submit from the repo root), or set PINBOX_REPO.
REPO="${PINBOX_REPO:-${SLURM_SUBMIT_DIR:-$(pwd)}}"
cd "$REPO"

# CHANGE: load the cluster's Python / CUDA modules if it uses them.
# module load python/3.11 cuda/12.1

# Python env with the training deps (made once, see training/README.md).
VENV="${PINBOX_VENV:-$HOME/venvs/pinbox-train}"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Keep model downloads off the home quota. CHANGE to the cluster's scratch disk.
export HF_HOME="${HF_HOME:-${SCRATCH:-$HOME}/hf_cache}"
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
# V100: no bf16, no FlashAttention-2 (the scripts default to fp16 + sdpa).

echo "job ${SLURM_JOB_ID:-local} on $(hostname) in $REPO"
nvidia-smi --query-gpu=name,memory.total --format=csv || true
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" || true
