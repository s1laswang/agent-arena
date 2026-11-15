#!/bin/bash
# X2 DAgger round 1 (runs ON the Verda box, /root/x2 only): relabel the student rollouts with the solver, then
# LoRA SFT from the v3-4k s0 adapter at 8k context. Rollouts: train.dagger rollout (vLLM venv /root/x2/vvenv).
set -euo pipefail
export PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
R=${R:-/root/x2/r1}; OUT=${OUT:-/root/x2/dagger-r1}
. /root/venv/bin/activate; cd /root/x2/agent-arena; export PYTHONPATH=$PWD
[ -f $R/labels.jsonl ] || python -m train.dagger relabel --rollouts $R/rollouts.jsonl --out $R/labels.jsonl --workers 20 | tee $R/relabel.log
python -m train.dagger sft --model /root/models/Qwen2.5-1.5B-Instruct --adapter ${ADAPTER:-/root/x2/v3-4k-s0-lora} \
  --rollouts $R/rollouts.jsonl --labels $R/labels.jsonl --out $OUT --max-ctx 8192 \
  --keep-agree ${KEEP_AGREE:-0.25} --key-weight ${KEY_W:-3} --max-examples ${MAX_EX:-0} --epochs ${EPOCHS:-1} \
  --grad-accum 16 --lr ${LR:-5e-5} --hours ${HOURS:-1.0} 2>&1 | tee $OUT.log
touch $OUT/DONE
