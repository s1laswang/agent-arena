import json, re, torch
from train.window import prompt
from transformers import AutoModelForCausalLM, AutoTokenizer

class Policy:
    def __init__(self, base="Qwen/Qwen2.5-0.5B-Instruct", lora=None, max_new=256):
        gpu = torch.cuda.is_available()
        self.dev = "cuda" if gpu else "cpu"
        self.tok = AutoTokenizer.from_pretrained(base)
        m = AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.float16 if gpu else torch.float32)
        if lora:
            from peft import PeftModel
            m = PeftModel.from_pretrained(m, lora).merge_and_unload()
        self.model = m.to(self.dev).eval()
        self.max_new = max_new

    def act(self, system, seat, history, observation):
        msgs = prompt(system, seat, history, observation)
        ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(self.dev)
        with torch.no_grad():
            out = self.model.generate(ids, max_new_tokens=self.max_new, do_sample=False)
        return parse_call(self.tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True))

def parse_call(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0))
        return {"tool": d["tool"], "args": d.get("args", {})}
    except Exception:
        return {"tool": "end_turn", "args": {}}
