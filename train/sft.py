import argparse, json, torch
from train.window import ensure_template
from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup
from peft import LoraConfig, get_peft_model

def encode(tok, messages, max_len):
    prompt = tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
    p = tok(prompt, add_special_tokens=False)["input_ids"]
    a = tok(messages[-1]["content"] + (tok.eos_token or ""), add_special_tokens=False)["input_ids"]
    ids = (p + a)[-max_len:]
    labels = ([-100] * len(p) + a)[-max_len:]
    return ids, labels

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--data", default="train/data/train.jsonl")
    ap.add_argument("--out", default="train/out")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--max_len", type=int, default=4096)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-ckpt", action="store_true")
    a = ap.parse_args()
    gpu = torch.cuda.is_available()
    dev = "cuda" if gpu else "cpu"
    tok = ensure_template(AutoTokenizer.from_pretrained(a.model))
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float32, attn_implementation="sdpa").to(dev)
    if a.grad_ckpt:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM"))
    rows = [encode(tok, json.loads(l)["messages"], a.max_len) for l in open(a.data)]
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr)
    steps = max(1, a.epochs * (len(rows) // a.batch) // a.accum)
    sch = get_cosine_schedule_with_warmup(opt, max(1, steps // 20), steps)
    scaler = torch.cuda.amp.GradScaler(enabled=gpu)
    model.train()
    n = 0
    for ep in range(a.epochs):
        for k in range(0, len(rows) - a.batch + 1, a.batch):
            chunk = rows[k:k + a.batch]
            w = max(len(i) for i, _ in chunk)
            pad = tok.pad_token_id if tok.pad_token_id is not None else 0
            x = torch.tensor([i + [pad] * (w - len(i)) for i, _ in chunk], device=dev)
            y = torch.tensor([l + [-100] * (w - len(l)) for _, l in chunk], device=dev)
            m = torch.tensor([[1] * len(i) + [0] * (w - len(i)) for i, _ in chunk], device=dev)
            with torch.autocast(dev, dtype=torch.float16, enabled=gpu):
                loss = model(input_ids=x, attention_mask=m, labels=y).loss / a.accum
            scaler.scale(loss).backward()
            n += 1
            if n % a.accum == 0:
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                scaler.step(opt); scaler.update(); opt.zero_grad(); sch.step()
                print(f"step {n // a.accum}/{steps} loss {loss.item() * a.accum:.4f}", flush=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)

if __name__ == "__main__":
    main()
