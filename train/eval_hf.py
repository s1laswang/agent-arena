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


def common_prefix(a: list[int], b: list[int]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


class HFPolicy:
    """Greedy HF policy with prefix/KV reuse across turns.

    Every turn the FULL prompt is rendered and tokenised (cheap, CPU), then compared with the
    token ids the KV cache already covers: the cache is cropped to the longest common prefix
    and only the remaining ids are encoded. Correctness therefore never depends on chat-template
    boundary reasoning: reused ids are verified equal to a full re-encode, token by token.
    Context truncation is sticky (drops whole (assistant, tool) pairs only when needed), so
    the prefix stays stable between drops.
    """

    def __init__(self, model, tokenizer, name: str, max_ctx: int = 4096, max_new: int = 96,
                 kv_reuse: bool = True):
        self.model, self.tok, self.name = model, tokenizer, name
        self.max_ctx, self.max_new, self.kv_reuse = max_ctx, max_new, kv_reuse
        self.invalid = 0
        self.calls = 0

    def reset(self, tools_spec, instruction):
        self.tools = to_openai_tools(tools_spec)
        self.tool_names = {t["function"]["name"] for t in self.tools}
        self.instruction = instruction
        self.invalid = 0
        self.calls = 0
        self.drop = 0            # (assistant, tool) pairs dropped from the front (sticky)
        self.cache = None        # DynamicCache
        self.cache_ids: list[int] = []
        self.encoded = 0         # tokens actually run through prefill (stats)
        self.reused = 0

    def _ids(self, msgs):
        ids = self.tok.apply_chat_template(msgs, tools=self.tools, tokenize=True,
                                           add_generation_prompt=True)
        if hasattr(ids, "keys"):
            ids = ids["input_ids"]
        return list(ids)

    def _prompt_ids(self, history):
        msgs = render_messages(self.instruction, history)
        drop = getattr(self, "drop", 0)
        while True:
            cut = msgs[:2] + msgs[2 + 2 * drop:]
            ids = self._ids(cut)
            if len(ids) <= self.max_ctx - self.max_new or len(cut) <= 4:
                self.drop = drop
                return ids
            drop += max(1, (len(msgs) - 2) // 16)

    def generate_text(self, history) -> str:
        import torch
        ids = self._prompt_ids(history)
        keep = common_prefix(self.cache_ids, ids) if (self.kv_reuse and self.cache is not None) else 0
        keep = min(keep, len(ids) - 1)  # always feed >= 1 new token
        if keep > 0:
            self.cache.crop(keep)
        else:
            from transformers import DynamicCache
            self.cache = DynamicCache() if self.kv_reuse else None
        self.reused += keep
        self.encoded += len(ids) - keep
        x = torch.tensor([ids], device=self.model.device)
        with torch.no_grad():
            out = self.model.generate(input_ids=x, attention_mask=torch.ones_like(x),
                                      past_key_values=self.cache, use_cache=True,
                                      max_new_tokens=self.max_new, do_sample=False,
                                      pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id)
        seq = out[0].tolist()
        if self.kv_reuse:
            self.cache_ids = seq[:self.cache.get_seq_length()]
        return self.tok.decode(seq[len(ids):], skip_special_tokens=False)

    def act(self, history):
        self.calls += 1
        call = parse_tool_call(self.generate_text(history), self.tool_names)
        if call is None:
            self.invalid += 1
            return "status", {}
        return call


class MLXPolicy(HFPolicy):
    """Same render/parse/truncation as HFPolicy; generation via mlx-lm (greedy = temp 0)."""

    def generate_text(self, history) -> str:
        from mlx_lm import generate
        ids = self._prompt_ids(history)
        return generate(self.model, self.tok, prompt=ids, max_tokens=self.max_new, verbose=False)


def load_mlx(spec: str, adapter: str | None):
    from mlx_lm import load
    model, tok = load(spec, adapter_path=adapter)
    return model, tok, "mlx:" + spec.split("/")[-1] + ("+lora" if adapter else "")


def run_capped(env, policy, max_calls: int):
    """canary.eval.run_episode with at most max_calls policy actions (0 = no cap).
    An episode stopped by the cap gets end_reason='eval_cap' (score stays the Env's: 0)."""
    try:
        from canary.eval import run_episode as _run
    except ImportError:
        _run = None
    if _run is None:
        return run_episode(env, policy)
    if max_calls <= 0:
        return _run(env, policy)
    ep = _run(env, policy, max_iters=max_calls)
    if ep.end_reason == "error" and str(ep.meta.get("error", "")).startswith("no episode end"):
        ep.end_reason = "eval_cap"
        ep.meta.pop("error", None)
    return ep


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
            "eval_cap_rate": round(sum(e["end_reason"] == "eval_cap" for e in sub)
                                   / max(len(sub), 1), 4),
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
    ap.add_argument("--seed-offset", type=int, default=0, help="skip the first K seeds of the pool")
    ap.add_argument("--out", default="data/runs")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--max-ctx", type=int, default=4096)
    ap.add_argument("--max-minutes", type=float, default=0, help="stop starting new episodes")
    ap.add_argument("--max-calls", type=int, default=120,
                    help="per-episode tool-call budget; hitting it ends with end_reason=eval_cap")
    ap.add_argument("--max-new-tokens", type=int, default=96)
    ap.add_argument("--no-kv-reuse", action="store_true")
    ap.add_argument("--backend", choices=["hf", "mlx"], default="hf")
    ap.add_argument("--adapter", default=None, help="mlx: LoRA adapter dir")
    ap.add_argument("--fake", action="store_true", help="FakeEnv + FakeSolver (no model)")
    a = ap.parse_args(argv)

    if a.backend == "mlx" and not a.fake:
        model, tok, name = load_mlx(a.model, a.adapter)
    else:
        model, tok, name = load_model(a.model, a.fake)
    Pol = MLXPolicy if a.backend == "mlx" else HFPolicy
    tiers = a.tiers.split(",")
    if a.fake:
        seed_list = list(range(800_000, 800_000 + a.n))
    else:
        from canary import rules
        pool = list(rules.HELDOUT_SEEDS if a.seeds == "heldout" else rules.DEV_SEEDS)
        seed_list = pool[a.seed_offset:a.seed_offset + a.n]   # offset: extra-n runs pool cleanly
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
               "tiers": tiers, "seeds": a.seeds, "n": a.n, "seed_offset": a.seed_offset}, open(os.path.join(rdir, "meta.json"), "w"))

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
                    pol = Pol(model, tok, name, max_ctx=a.max_ctx, max_new=a.max_new_tokens)
                    pol.kv_reuse = a.backend == "hf" and not a.no_kv_reuse
                t_ep = time.time()
                ep = run_capped(env, pol, a.max_calls)
                ep.meta = dict(ep.meta or {})
                ep.meta["invalid_calls"] = getattr(pol, "invalid", 0)
                ep.meta["eval_seconds"] = round(time.time() - t_ep, 1)
                if getattr(pol, "encoded", None) is not None:
                    ep.meta["prefill_tokens"] = pol.encoded
                    ep.meta["reused_tokens"] = pol.reused
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
