#!/usr/bin/env bash
# Runs ON the Verda instance (Ubuntu + CUDA). Code in ~/agent-arena, v2 adapter in ~/v2-lora.
# v3 seed 0: decision-point GRPO from v2 (same settings as FR8 44555, --hours HOURS), then held-out eval n=30/tier.
set -euo pipefail
HOURS=${HOURS:-3.5}
cd ~
export PATH=$HOME/.local/bin:$PATH
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/agent-arena
uv venv -q --python 3.11 ~/venv && . ~/venv/bin/activate
uv pip install -q -e . torch==2.5.1 "transformers==4.57.*" "peft==0.17.*" accelerate jinja2 huggingface_hub
python -c "import torch,transformers,peft;print('cuda',torch.cuda.is_available(),torch.cuda.get_device_name(0),'tf',transformers.__version__,'peft',peft.__version__)"
M=$HOME/models/Qwen2.5-1.5B-Instruct
[ -f $M/config.json ] || python -c "from huggingface_hub import snapshot_download as d; d('Qwen/Qwen2.5-1.5B-Instruct', local_dir='$M', allow_patterns=['*.json','*.safetensors','*.txt'])"
# adapter_config points at the FR8 path; repoint it to the local base
python - <<PY
import json; p="$HOME/v2-lora/adapter_config.json"; c=json.load(open(p)); c["base_model_name_or_path"]="$M"; json.dump(c,open(p,"w"),indent=1)
PY
OUT=$HOME/v3/run-verda-s0; mkdir -p $OUT
export PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
W=$(( $(nproc) - 4 )); [ $W -gt 16 ] && W=16
python -m train.grpo_investigator --model $M --adapter ~/v2-lora --out $OUT --fp16 --seed 0 --hours $HOURS --workers $W \
  2>&1 | tee $OUT/train.log
python - <<PY
import json; p="$OUT/lora/adapter_config.json"; c=json.load(open(p)); c["base_model_name_or_path"]="$M"; json.dump(c,open(p,"w"),indent=1)
PY
python -m train.eval_hf --model $OUT/lora --tiers easy,medium,hard --seeds heldout --n 30 --max-calls 120 \
  --max-new-tokens 96 --max-minutes ${EVAL_MIN:-120} --out $HOME/v3/runs --run-id v3-verda-s0 2>&1 | tee $OUT/eval.log
touch $HOME/v3/DONE
