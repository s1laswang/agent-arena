#!/usr/bin/env bash
# LOGIN NODE (light): fetch Qwen2.5-0.5B/1.5B-Instruct weights into ~/agent-arena-data/models (≈1 GB / 3 GB).
# TRL is optional (only for BACKEND=trl): installed into ~/agent-arena-data/pylib, no deps (torch/transformers come
# from pytorch-volta). The default BACKEND=torch needs nothing beyond pytorch-volta (torch, transformers, peft).
set -euo pipefail
module load pytorch-volta
M=$HOME/agent-arena-data/models
for s in ${SIZES:-0.5B}; do
  [ -f "$M/Qwen2.5-$s-Instruct/config.json" ] && { echo "have $s"; continue; }
  pytorch-exec python -c "from huggingface_hub import snapshot_download as d; d('Qwen/Qwen2.5-$s-Instruct', local_dir='$M/Qwen2.5-$s-Instruct', allow_patterns=['*.json','*.safetensors','*.txt','merges.txt','vocab.json'])"
done
[ "${WITH_TRL:-0}" = 1 ] && pytorch-exec pip install --no-deps --target $HOME/agent-arena-data/pylib trl==0.16.1 || true
du -sh $M $HOME/agent-arena-data/pylib 2>/dev/null || true
