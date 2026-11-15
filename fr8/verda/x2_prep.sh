#!/bin/bash
# Pre-stage X2 box: same torch/transformers/peft stack as v3, base 1.5B model, v3-4k s0 adapter in /root/x2.
export PATH=$HOME/.local/bin:$PATH
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
cd /root/agent-arena && uv venv -q --clear --python 3.11 /root/venv && . /root/venv/bin/activate
uv pip install -q -e . torch==2.5.1 transformers==5.16.1 peft==0.20.0 accelerate jinja2 huggingface_hub verda
M=/root/models/Qwen2.5-1.5B-Instruct
[ -f $M/config.json ] || python -c "from huggingface_hub import snapshot_download as d; d('Qwen/Qwen2.5-1.5B-Instruct', local_dir='$M', allow_patterns=['*.json','*.safetensors','*.txt'])"
python -c "import json; p='/root/x2/v3-4k-s0-lora/adapter_config.json'; c=json.load(open(p)); c['base_model_name_or_path']='$M'; json.dump(c,open(p,'w'),indent=1)"
python -c "import torch;print('cuda',torch.cuda.is_available(),torch.cuda.get_device_name(0))"
touch /root/x2/PREP_DONE
