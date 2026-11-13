import subprocess, sys, time
for m in ("peft", "transformers", "trl", "accelerate"):
    try:
        __import__(m)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", m])
import torch, transformers, peft
print("torch", torch.__version__, "transformers", transformers.__version__, "peft", peft.__version__)
n = torch.cuda.device_count()
print("gpus", n)
for i in range(n):
    f, t = torch.cuda.mem_get_info(i)
    print(i, torch.cuda.get_device_name(i), "free/total GB", round(f / 2**30, 1), round(t / 2**30, 1))
a = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)
torch.cuda.synchronize(); s = time.time()
for _ in range(50):
    a @ a
torch.cuda.synchronize(); print("fp16 matmul s", round(time.time() - s, 3))
from transformers import AutoTokenizer, AutoModelForCausalLM
p = "Qwen/Qwen2.5-0.5B-Instruct"
tok = AutoTokenizer.from_pretrained(p)
model = AutoModelForCausalLM.from_pretrained(p, torch_dtype=torch.float16).cuda()
x = tok("Hello, my name is", return_tensors="pt").to("cuda")
y = model.generate(**x, max_new_tokens=20, do_sample=False)
print("peak_alloc_GB", round(torch.cuda.max_memory_allocated() / 2**30, 2))
print(tok.decode(y[0], skip_special_tokens=True))
