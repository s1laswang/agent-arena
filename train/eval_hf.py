"""Evaluate a HF model (base or LoRA) as a Canary investigator, greedy decoding.

    python -m train.eval_hf --model base|<lora_dir>|<hf path> --tiers easy,medium,hard
        --seeds heldout --n 200 [--out data/runs] [--max-minutes M] [--fake]

The prompt is built by train.render.render_messages, the SAME format as the SFT export.
When the context exceeds --max-ctx, the oldest (assistant, tool) pairs are dropped (the header
is kept), mirroring the training windows. Unparseable output = a wasted `status` call
(counts toward the tool cap) and is counted in meta.invalid_calls.
Writes <out>/<run_id>/{episodes.jsonl, meta.json, summary.json}; prints the summary.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import subprocess
import time
from collections import Counter

from train.export_sft import run_episode
from train.render import parse_tool_call, render_messages, to_openai_tools

BASE = os.path.expanduser("~/agent-arena-data/models/Qwen2.5-1.5B-Instruct")


class HFPolicy:
    def __init__(self, model, tokenizer, name: str, max_ctx: int = 4096, max_new: int = 160):
        self.model, self.tok, self.name = model, tokenizer, name
        self.max_ctx, self.max_new = max_ctx, max_new
        self.invalid = 0
        self.calls = 0

    def reset(self, tools_spec, instruction):
        self.tools = to_openai_tools(tools_spec)
        self.tool_names = {t["function"]["name"] for t in self.tools}
        self.instruction = instruction
        self.invalid = 0
        self.calls = 0

    def _prompt_ids(self, history):
        msgs = render_messages(self.instruction, history)
        while True:
            ids = self.tok.apply_chat_template(msgs, tools=self.tools, tokenize=True,
                                               add_generation_prompt=True)
            if hasattr(ids, "keys"):
                ids = ids["input_ids"]
            if len(ids) <= self.max_ctx - self.max_new or len(msgs) <= 4:
                return ids
            msgs = msgs[:2] + msgs[2 + 2 * max(1, (len(msgs) - 2) // 8):]

    def generate_text(self, history) -> str:
        import torch
        ids = self._prompt_ids(history)
        x = torch.tensor([ids], device=self.model.device)
        with torch.no_grad():
            out = self.model.generate(input_ids=x, attention_mask=torch.ones_like(x),
                                      max_new_tokens=self.max_new, do_sample=False,
                                      pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id)
        return self.tok.decode(out[0, len(ids):], skip_special_tokens=False)

    def act(self, history):
        self.calls += 1
        call = parse_tool_call(self.generate_text(history), self.tool_names)
        if call is None:
            self.invalid += 1
            return "status", {}
        return call


def mean_ci(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def summarize(eps: list[dict]) -> dict:
    out = {}
    for tier in sorted({e["tier"] for e in eps}) + ["all"]:
        sub = [e for e in eps if tier == "all" or e["tier"] == tier]
        m, h = mean_ci([e["score"] for e in sub])
        tags = Counter(t for e in sub for t in e.get("meta", {}).get("regret_tags", []))
        out[tier] = {
            "n": len(sub), "mean_score": round(m, 4), "ci95": round(h, 4),
            "accuracy": round(sum(e["correct"] for e in sub) / max(len(sub), 1), 4),
            "mean_final_day": round(sum(e["final_day"] for e in sub) / max(len(sub), 1), 2),
            "end_reasons": dict(Counter(e["end_reason"] for e in sub)),
            "invalid_call_rate": round(sum(e["meta"].get("invalid_calls", 0) for e in sub)
                                       / max(sum(len(e["steps"]) for e in sub), 1), 4),
            "regret_tags": dict(tags.most_common(10)),
        }
    return out


def regret_tags(ep) -> list[str] | None:
    try:
        from canary.solver.regret import attribute  # type: ignore
    except ImportError:
        return None
    try:
        return sorted({t for r in attribute(ep) for t in r.get("tags", [])})
    except Exception as e:  # never kill an eval over attribution
        return [f"regret_error:{type(e).__name__}"]


def load_model(spec: str, fake: bool):
    if fake:
        return None, None, "fake_solver"
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    path = BASE if spec == "base" else spec
    if os.path.exists(os.path.join(path, "adapter_config.json")):
        from peft import PeftModel
        base_path = json.load(open(os.path.join(path, "adapter_config.json")))[
            "base_model_name_or_path"]
        model = AutoModelForCausalLM.from_pretrained(base_path, dtype=dtype,
                                                     attn_implementation="sdpa")
        model = PeftModel.from_pretrained(model, path).merge_and_unload()
        name = "hf-lora:" + os.path.basename(os.path.normpath(path))
    else:
        model = AutoModelForCausalLM.from_pretrained(path, dtype=dtype, attn_implementation="sdpa")
        name = "hf:" + os.path.basename(os.path.normpath(path))
    tok = AutoTokenizer.from_pretrained(path)
    model.to(dev).eval()
    return model, tok, name


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="base")
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--seeds", choices=["heldout", "dev"], default="heldout")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--out", default="data/runs")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--max-ctx", type=int, default=4096)
    ap.add_argument("--max-minutes", type=float, default=0, help="stop starting new episodes")
    ap.add_argument("--fake", action="store_true", help="FakeEnv + FakeSolver (no model)")
    a = ap.parse_args(argv)

    model, tok, name = load_model(a.model, a.fake)
    tiers = a.tiers.split(",")
    if a.fake:
        seed_list = list(range(800_000, 800_000 + a.n))
    else:
        from canary import rules
        pool = list(rules.HELDOUT_SEEDS if a.seeds == "heldout" else rules.DEV_SEEDS)
        seed_list = pool[:a.n]
    run_id = a.run_id or f"{name.replace(':', '-').replace('/', '_')}-{'+'.join(tiers)}-" \
                         f"{time.strftime('%Y%m%d-%H%M')}"
    rdir = os.path.join(a.out, run_id)
    os.makedirs(rdir, exist_ok=True)
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True).stdout.strip()
    except OSError:
        sha = ""
    json.dump({"agent": name, "model": a.model, "provider": "hf", "git_sha": sha,
               "tiers": tiers, "seeds": a.seeds, "n": a.n}, open(os.path.join(rdir, "meta.json"), "w"))

    t0, eps = time.time(), []
    with open(os.path.join(rdir, "episodes.jsonl"), "w") as f:
        for i in range(len(seed_list)):  # interleave tiers so a time box stays balanced
            for tier in tiers:
                if a.max_minutes and time.time() - t0 > 60 * a.max_minutes:
                    break
                seed = seed_list[i]
                if a.fake:
                    from train.fake import FakeEnv, FakeSolver
                    env, pol = FakeEnv(tier, seed), FakeSolver()
                else:
                    from canary.env import Env
                    env = Env(tier=tier, seed=seed)
                    pol = HFPolicy(model, tok, name, max_ctx=a.max_ctx)
                ep = run_episode(env, pol)
                ep.meta = dict(ep.meta or {})
                ep.meta["invalid_calls"] = getattr(pol, "invalid", 0)
                tags = regret_tags(ep)
                if tags is not None:
                    ep.meta["regret_tags"] = tags
                d = dataclasses.asdict(ep)
                eps.append(d)
                f.write(json.dumps(d, default=str) + "\n")
                f.flush()
                print(f"[ep] {tier} {seed} score={ep.score:.3f} correct={ep.correct} "
                      f"steps={len(ep.steps)} invalid={ep.meta['invalid_calls']} "
                      f"t={time.time() - t0:.0f}s", flush=True)
    summ = {"run_id": run_id, "agent": name, "seconds": round(time.time() - t0, 1),
            "by_tier": summarize(eps)}
    json.dump(summ, open(os.path.join(rdir, "summary.json"), "w"), indent=2)
    print("[summary] " + json.dumps(summ), flush=True)


if __name__ == "__main__":
    main()
