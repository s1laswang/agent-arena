#!/bin/bash
# Extra held-out eval n on a Verda GPU: v2 then v3-4k s0, seeds 30..59 per tier (pool with the first 30 runs).
set -uo pipefail
export PATH=$HOME/.local/bin:$PATH PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
cd /root/agent-arena
uv venv -q --clear --python 3.11 /root/venv && . /root/venv/bin/activate
uv pip install -q -e . torch==2.5.1 transformers==5.16.1 peft==0.20.0 accelerate jinja2 huggingface_hub
M=/root/models/Qwen2.5-1.5B-Instruct
[ -f $M/config.json ] || python -c "from huggingface_hub import snapshot_download as d; d('Qwen/Qwen2.5-1.5B-Instruct', local_dir='$M', allow_patterns=['*.json','*.safetensors','*.txt'])"
fix() { python -c "import json,sys; p=sys.argv[1]+'/adapter_config.json'; c=json.load(open(p)); c['base_model_name_or_path']='$M'; json.dump(c,open(p,'w'),indent=1)" "$1"; }
ev() { python -m train.eval_hf --model "$1" --tiers easy,medium,hard --seeds heldout --n 30 --seed-offset 30 \
         --max-calls 120 --max-new-tokens 96 --max-minutes ${EVAL_MIN:-110} --out /root/evals --run-id "$2" > /root/evals-$2.log 2>&1; }
python -m train.eval_hf --model $M --tiers easy,medium,hard --seeds heldout --n 30 --seed-offset 6 --max-calls 120 --max-new-tokens 96 --max-minutes 150 --out /root/evals --run-id base-off6 > /root/evals-base.log 2>&1; touch /root/evals/DONE-base; exit 0
for i in $(seq 1 240); do [ -f /root/v3s0-lora/adapter_config.json ] && break; sleep 30; done
[ -f /root/v3s0-lora/adapter_config.json ] && { fix /root/v3s0-lora; ev /root/v3s0-lora v3-4k-s0-off30; touch /root/evals/DONE-v3s0; }
