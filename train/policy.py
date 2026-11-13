import json, re
from train.window import prompt, ensure_template, SYSTEM

class Policy:
    def __init__(self, base="Qwen/Qwen2.5-0.5B-Instruct", lora=None, max_new=256):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        gpu = torch.cuda.is_available()
        self.dev = "cuda" if gpu else "cpu"
        self.tok = ensure_template(AutoTokenizer.from_pretrained(base))
        m = AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.float16 if gpu else torch.float32, attn_implementation="sdpa")
        if lora:
            from peft import PeftModel
            m = PeftModel.from_pretrained(m, lora).merge_and_unload()
        self.model = m.to(self.dev).eval()
        self.max_new = max_new

    def act(self, system, seat, history, header):
        msgs = prompt(system, seat, history, header)
        ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(self.dev)
        with self.torch.no_grad():
            out = self.model.generate(ids, max_new_tokens=self.max_new, do_sample=False)
        return parse_call(self.tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True))

def parse_call(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0))
        return {"tool": d["tool"], "args": d.get("args", {})}
    except Exception:
        return {"tool": "end_turn", "args": {}}

class LocalSeat:
    def __init__(self, policy, system=SYSTEM, budget=60):
        self.p = policy
        self.system = system
        self.budget = budget
        self.hist = []

    def turn(self, seat, view, tools, call):
        n = 0
        while n < self.budget:
            c = self.p.act(self.system, seat, self.hist, view)
            n += 1
            eff = call(c["tool"], c["args"])
            self.hist.append({**c, "effect": eff})
            if c["tool"] == "end_turn":
                break
        return {"calls": n}
