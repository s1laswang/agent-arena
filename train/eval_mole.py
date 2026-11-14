"""Held-out eval of a GRPO mole (train/grpo_mole.py): base model vs base + LoRA adapter, paired on the same states.

States are (seed, day) MoleViews collected exactly like grpo_mole.collect_prompts, but from HELDOUT_SEED_BASE (400000+),
disjoint from grpo_mole prompts (300000+), RL mole train (100000-150000) and eval (200000+), investigator GRPO (151000+)
and judge seeds (900000+). Each model answers greedily once per state; the action is scored with grpo_mole.episode_reward
(solver vs best scripted investigator, catch penalty, invalid = -1). Prints mean and 95% CI per model and for the
paired difference (adapter - base), and writes eval.json.

    python -m train.eval_mole --model Qwen/Qwen2.5-1.5B-Instruct --adapter RUN/lora-step200 --n 200 --out RUN/eval.json
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path

import train.grpo_mole as gm

HELDOUT_SEED_BASE = 400_000


def mean_ci(xs: list[float]) -> dict:
    n = len(xs)
    m = statistics.fmean(xs) if xs else float("nan")
    h = 1.96 * statistics.stdev(xs) / math.sqrt(n) if n > 1 else float("nan")
    return {"mean": m, "ci95": [m - h, m + h], "n": n}


def generate(model, tok, rows: list[dict], max_new: int, batch: int) -> list[str]:
    import torch
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    out = []
    for i in range(0, len(rows), batch):
        enc = tok([gm.chat(tok, r["prompt"]) for r in rows[i:i + batch]], return_tensors="pt", padding=True).to(model.device)
        with torch.no_grad():
            g = model.generate(**enc, max_new_tokens=max_new, do_sample=False, pad_token_id=tok.pad_token_id)
        out += tok.batch_decode(g[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)
    return out


def summarize(res: list[dict]) -> dict:
    return {"reward": mean_ci([r["reward"] for r in res]),
            "valid": mean_ci([1.0 if r["valid"] else 0.0 for r in res]),
            "solver_catch": mean_ci([1.0 if r["valid"] and r["solver"][1] else 0.0 for r in res]),
            "regret": mean_ci([r["solver"][0] - max(v[0] for v in r["inv"].values()) for r in res if r["valid"]])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--base-policy", default=None)
    ap.add_argument("--max-new", type=int, default=32)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    t0 = time.time()
    gm.PROMPT_SEED_BASE = HELDOUT_SEED_BASE
    rows = gm.collect_prompts(a.n, a.tier, a.base_policy, seed=12345)
    assert min(r["seed"] for r in rows) >= HELDOUT_SEED_BASE
    dtype = torch.float16 if a.fp16 else torch.bfloat16
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=dtype).to("cuda").eval()
    base_txt = generate(model, tok, rows, a.max_new, a.batch)
    model = PeftModel.from_pretrained(model, a.adapter).eval()
    ad_txt = generate(model, tok, rows, a.max_new, a.batch)
    pool = gm.RewardPool(a.workers)
    base_res, ad_res = pool(rows, base_txt), pool(rows, ad_txt)
    diff = mean_ci([x["reward"] - y["reward"] for x, y in zip(ad_res, base_res)])
    out = {"model": a.model, "adapter": a.adapter, "tier": a.tier, "n": len(rows),
           "seeds": [rows[0]["seed"], rows[-1]["seed"]], "heldout_seed_base": HELDOUT_SEED_BASE,
           "base": summarize(base_res), "adapter_result": summarize(ad_res), "reward_diff_adapter_minus_base": diff,
           "actions_adapter": [r.get("action") for r in ad_res], "sec": round(time.time() - t0, 1)}
    Path(a.out).write_text(json.dumps(out, indent=1))
    for k in ("base", "adapter_result"):
        s = out[k]
        print(f"{k:15} reward {s['reward']['mean']:+.3f} [{s['reward']['ci95'][0]:+.3f}, {s['reward']['ci95'][1]:+.3f}]"
              f"  solver_catch {s['solver_catch']['mean']:.3f}  valid {s['valid']['mean']:.3f}")
    print(f"paired diff     reward {diff['mean']:+.3f} [{diff['ci95'][0]:+.3f}, {diff['ci95'][1]:+.3f}]  n={diff['n']}")


if __name__ == "__main__":
    main()
