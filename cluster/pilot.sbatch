#!/bin/bash
#SBATCH --job-name=sleeper-pilot
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --time=00:10:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=logs/%x-%j.out
module load pytorch-volta
date
hostname
nvidia-smi --query-gpu=name,memory.total --format=csv
curl -sS -m 10 -o /dev/null -w "hf_internet_http=%{http_code}\n" https://huggingface.co || echo hf_internet_http=none
pytorch-exec python -c "
import torch, transformers, time
print('torch', torch.__version__, 'cuda', torch.version.cuda, torch.cuda.get_device_name(0))
a = torch.randn(4096, 4096, device='cuda', dtype=torch.float16)
torch.cuda.synchronize(); t = time.time()
for _ in range(50): a @ a
torch.cuda.synchronize(); print('fp16 matmul s', round(time.time() - t, 3))
for m in ('peft', 'trl', 'accelerate', 'datasets', 'bitsandbytes', 'vllm'):
    try:
        mod = __import__(m); print(m, getattr(mod, '__version__', 'ok'))
    except Exception as e:
        print(m, 'MISSING', type(e).__name__)
print('transformers', transformers.__version__)
from transformers import AutoTokenizer, AutoModelForCausalLM
p = '$HOME/momin/sleeper/models/Qwen2.5-0.5B-Instruct'
tok = AutoTokenizer.from_pretrained(p)
model = AutoModelForCausalLM.from_pretrained(p, torch_dtype=torch.float16).cuda()
x = tok('Hello, my name is', return_tensors='pt').to('cuda')
y = model.generate(**x, max_new_tokens=20, do_sample=False)
print(tok.decode(y[0], skip_special_tokens=True))
"
date
