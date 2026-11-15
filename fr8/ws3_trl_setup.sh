#!/usr/bin/env bash
# WS3: install TRL next to pytorch-volta (login node has internet; compute nodes don't).
# Run on freighter LOGIN node:  bash ~/agent-arena/fr8/ws3_trl_setup.sh   (light: pip download/install only)
# Then verify on a GPU node inside ws3_grpo.sbatch (CHECK_ONLY=1).
set -euo pipefail
LIB=$HOME/agent-arena-data/pylib-trl
module load pytorch-volta
pytorch-exec python -c "import torch,transformers,peft;print(torch.__version__,transformers.__version__,peft.__version__)"
# --no-deps: keep the container's torch/transformers; add only trl + its light deps
pytorch-exec python -m pip install --no-cache-dir --target "$LIB" --no-deps "trl==${TRL_VERSION:-0.14.0}" rich
PYTHONPATH=$LIB pytorch-exec python -c "import trl;print('trl',trl.__version__)"
du -sh "$LIB"
