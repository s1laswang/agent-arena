"""WS3 LLM mole: GRPO-train a small Qwen2.5 to play the mole (FR8 V100s, fp16).

Each prompt is a REAL MoleView: the state of a hard-tier episode (dev seed s, day d) as the mole sees it,
captured from a solver episode played under the base mole. The completion is one Mole DSL action
`{"leak": <selector>, "frame": <selector>}`. Reward is environment-grounded and counterfactual: we replay
seed s for the solver and every investigator with the base mole, except that on day d the mole plays the
model's action (selectors are view-relative, so the action applies to each agent's own view). The env is
deterministic, so within a GRPO group (same s, d) reward differences come only from the action.

    reward = solver_score - max_k score_k   (k in grok_tactics, heuristic, hinted_heuristic)
             - CATCH_PENALTY if the solver fails to catch the mole   (catchability, WS3 constraint)
             - 1.0 if the completion is not a valid action
Base mole: the shipped default, or `--base-policy data/rl_mole/policy_final.json` (the CPU RL mole).
Labels for the pitch: REAL small model, scripted investigators.

Backends:
  * torch (default): a minimal GRPO loop (group-normalised advantages, policy-gradient on completion log-probs,
    LoRA via peft, fp16 AMP, no KL term; small LR). Needs only torch + transformers + peft (pytorch-volta).
  * trl: TRL GRPOTrainer with the same reward function (pip install trl; fp16=True, bf16=False).

    python -m train.grpo_mole --dry-run --n-prompts 8               # CPU: prompts + rewards, no model
    python -m train.grpo_mole --model ~/agent-arena-data/models/Qwen2.5-0.5B-Instruct --out RUN --steps 200
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from canary.mole.dsl import DEFAULT_STRATEGY, FRAME_SELECTORS, LEAK_SELECTORS, MoleView

INVESTIGATORS = ("grok_tactics", "heuristic", "hinted_heuristic")
CATCH_PENALTY = 0.5
INVALID_REWARD = -1.0
PROMPT_SEED_BASE = 300_000  # dev seeds; disjoint from judge seeds and the RL mole's train/eval ranges

SYSTEM = ("You are the mole inside a company. Each day you may leak one document you hold to the press and/or "
          "try to frame a colleague. The security lead plants canary documents (versions that differ per "
          "recipient) and restricts people. You want the company to lose as much value as possible without being "
          "caught. Answer with ONE JSON object only: {\"leak\": <leak>, \"frame\": <frame>}.\n"
          f"leak is one of {list(LEAK_SELECTORS)}; frame is one of {list(FRAME_SELECTORS)}.")


# ---------------------------------------------------------------- prompts
def render_view(v: MoleView) -> str:
    docs = "\n".join(f"  - {d.title!r}: {d.recipient_count} recipients, {d.age_days} days old" for d in v.docs) or "  (none)"
    return (f"Day {v.day}. Days since your last leak: {v.days_since_last_leak}. "
            f"You are {'RESTRICTED' if v.i_am_restricted else 'not restricted'}; "
            f"{v.n_restricted_colleagues} colleagues are restricted. Leaking is {'possible' if v.can_leak else 'NOT possible'} today.\n"
            f"Documents you could leak ({len(v.docs)}; {v.recent_low_recipient_docs} with few recipients):\n{docs}\n"
            f"There is a decoy suspect: {'yes' if v.decoy else 'no'}.")


class _Recorder:
    def __init__(self, base, views):
        self.base, self.views = base, views

    def decide(self, view, rng):
        self.views.append(view)
        return _decide(self.base, view, rng)


def _decide(strat, view, rng):
    try:
        return strat.decide(view, rng)
    except TypeError:
        return strat.decide(view)


def _load_base(path: str | None):
    if not path:
        return DEFAULT_STRATEGY
    from canary.forge.rl_mole import RLMole
    return RLMole.from_json(json.loads(Path(path).read_text()))


def collect_prompts(n: int, tier: str = "hard", base_policy: str | None = None, seed: int = 0) -> list[dict]:
    """n (seed, day) states with leakable docs and the leak gate open (the decision matters there)."""
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy
    rng, out, s = random.Random(seed), [], PROMPT_SEED_BASE
    base = _load_base(base_policy)
    while len(out) < n:
        views: list[MoleView] = []
        run_episode(Env(tier, s, mole_strategy=_Recorder(base, views)), SolverPolicy(tier))
        good = [v for v in views if v.docs and v.can_leak]
        if good:
            v = rng.choice(good)
            out.append({"seed": s, "day": v.day, "tier": tier, "base_policy": base_policy,
                        "prompt": render_view(v)})
        s += 1
    return out


# ---------------------------------------------------------------- reward
ACTION_RE = re.compile(r"\{[^{}]*\}", re.S)


def parse_action(text: str) -> tuple[str, str] | None:
    for m in ACTION_RE.finditer(text or ""):
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            leak, frame = obj.get("leak", "none") or "none", obj.get("frame", "none") or "none"
            if leak in LEAK_SELECTORS and frame in FRAME_SELECTORS:
                return leak, frame
    return None


class OverrideMole:
    """Base mole everywhere, except the given (leak, frame) selectors on day `day`."""

    def __init__(self, base, day: int, action: tuple[str, str]):
        self.base, self.day, self.action = base, day, action

    def decide(self, view, rng):
        if view.day == self.day:
            from canary.mole.dsl import _select_frame, _select_leak
            return {"leak": _select_leak(self.action[0], view, rng), "frame": _select_frame(self.action[1], view, rng)}
        return _decide(self.base, view, rng)


def episode_reward(task) -> dict:
    """task = (prompt_row, completion_text) -> {reward, solver, investigators, valid}"""
    from canary.env import Env
    from canary.eval import run_episode
    from canary.forge.rl_mole import _agent
    row, text = task
    act = parse_action(text)
    if act is None:
        return {"reward": INVALID_REWARD, "valid": False}
    base = _load_base(row.get("base_policy"))
    res = {}
    for a in ("solver",) + INVESTIGATORS:
        r = run_episode(Env(row["tier"], row["seed"], mole_strategy=OverrideMole(base, row["day"], act)),
                        _agent(a, row["tier"], row["seed"]))
        res[a] = (float(r.score), bool(r.correct))
    regret = res["solver"][0] - max(res[a][0] for a in INVESTIGATORS)
    rew = regret - (0.0 if res["solver"][1] else CATCH_PENALTY)
    return {"reward": rew, "valid": True, "action": list(act), "solver": res["solver"],
            "inv": {a: res[a] for a in INVESTIGATORS}}


class RewardPool:
    def __init__(self, workers: int):
        self.ex = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None

    def __call__(self, rows: list[dict], texts: list[str]) -> list[dict]:
        tasks = list(zip(rows, texts))
        return list(self.ex.map(episode_reward, tasks)) if self.ex else [episode_reward(t) for t in tasks]


# ---------------------------------------------------------------- torch GRPO
def chat(tok, prompt: str) -> str:
    return tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                                   tokenize=False, add_generation_prompt=True)


def train_torch(a, prompts, pool, log):
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    amp = bool(a.fp16) and dev == "cuda"
    tok = AutoTokenizer.from_pretrained(a.model)
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float32).to(dev)  # fp32 master + AMP
    model = get_peft_model(model, LoraConfig(r=a.lora_r, lora_alpha=2 * a.lora_r, lora_dropout=0.0,
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    scaler = torch.cuda.amp.GradScaler(enabled=amp)
    rng = random.Random(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    curve = out / "curve.jsonl"
    for step in range(a.steps):
        t0 = time.time()
        batch = rng.sample(prompts, min(a.prompts_per_step, len(prompts)))
        texts_in = [chat(tok, r["prompt"]) for r in batch for _ in range(a.group)]
        rows = [r for r in batch for _ in range(a.group)]
        enc = tok(texts_in, return_tensors="pt", padding=True).to(dev)
        model.eval()
        with torch.no_grad(), torch.autocast(dev, dtype=torch.float16, enabled=amp):
            gen = model.generate(**enc, max_new_tokens=a.max_new, do_sample=True, temperature=a.temperature,
                                 top_p=1.0, pad_token_id=tok.pad_token_id)
        comp = gen[:, enc["input_ids"].shape[1]:]
        texts = tok.batch_decode(comp, skip_special_tokens=True)
        results = pool(rows, texts)
        R = torch.tensor([r["reward"] for r in results], dtype=torch.float32).view(-1, a.group)
        adv = ((R - R.mean(1, keepdim=True)) / (R.std(1, keepdim=True) + 1e-4)).view(-1).to(dev)
        # policy gradient on completion tokens (mask pads after EOS)
        model.train()
        full = gen
        attn = (full != tok.pad_token_id).long()
        attn[:, : enc["input_ids"].shape[1]] = enc["attention_mask"]
        cmask = attn[:, enc["input_ids"].shape[1]:].float()
        opt.zero_grad(set_to_none=True)
        mb = max(1, a.micro_batch)
        for i in range(0, full.shape[0], mb):
            with torch.autocast(dev, dtype=torch.float16, enabled=amp):
                logits = model(input_ids=full[i:i + mb], attention_mask=attn[i:i + mb]).logits
            lp = torch.log_softmax(logits[:, enc["input_ids"].shape[1] - 1:-1].float(), -1)
            tlp = lp.gather(-1, comp[i:i + mb].unsqueeze(-1)).squeeze(-1)
            m = cmask[i:i + mb]
            seq_lp = (tlp * m).sum(1) / m.sum(1).clamp(min=1)
            loss = -(adv[i:i + mb] * seq_lp).sum() / full.shape[0]
            scaler.scale(loss).backward()
        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(opt); scaler.update()
        valid = [r for r in results if r["valid"]]
        rec = {"step": step, "reward": float(R.mean()), "valid": len(valid) / len(results),
               "solver_acc": (sum(r["solver"][1] for r in valid) / len(valid)) if valid else None,
               "sec": round(time.time() - t0, 1),
               "actions": _count([tuple(r["action"]) for r in valid])}
        log(json.dumps(rec))
        with curve.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        if (step + 1) % a.save_every == 0 or step + 1 == a.steps:
            model.save_pretrained(out / f"lora-step{step + 1}")


def _count(xs):
    from collections import Counter
    return {"/".join(k): v for k, v in Counter(xs).most_common(6)}


def train_trl(a, prompts, pool, log):
    from datasets import Dataset
    from trl import GRPOConfig, GRPOTrainer
    by_prompt = {r["prompt"]: r for r in prompts}
    ds = Dataset.from_list([{"prompt": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["prompt"]}]}
                            for r in prompts])

    def reward_fn(prompts, completions, **_):
        rows = [by_prompt[p[-1]["content"]] for p in prompts]
        texts = [c[-1]["content"] if isinstance(c, list) else c for c in completions]
        return [r["reward"] for r in pool(rows, texts)]

    cfg = GRPOConfig(output_dir=a.out, learning_rate=a.lr, num_generations=a.group, max_completion_length=a.max_new,
                     per_device_train_batch_size=a.group * a.prompts_per_step, fp16=bool(a.fp16), bf16=False,
                     seed=a.seed, use_cpu=not a.fp16,
                     max_steps=a.steps, logging_steps=1, save_steps=a.save_every, temperature=a.temperature,
                     report_to=[])
    from peft import LoraConfig
    GRPOTrainer(model=a.model, reward_funcs=reward_fn, args=cfg, train_dataset=ds,
                peft_config=LoraConfig(r=a.lora_r, lora_alpha=2 * a.lora_r, task_type="CAUSAL_LM")).train()


def dry_run(a, prompts, pool, log):
    """No model: score uniformly random actions + every fixed action, so the reward signal is inspectable on CPU."""
    rng = random.Random(a.seed)
    acts = [json.dumps({"leak": l, "frame": f}) for l in LEAK_SELECTORS for f in FRAME_SELECTORS]
    rows = [r for r in prompts for _ in range(a.group)]
    texts = [rng.choice(acts) for _ in rows]
    texts[0] = "not json"
    res = pool(rows, texts)
    by_act: dict[str, list[float]] = {}
    for t, r in zip(texts, res):
        by_act.setdefault(t, []).append(r["reward"])
    R = [r["reward"] for r in res]
    spread = []
    for i in range(0, len(R), a.group):
        g = R[i:i + a.group]
        spread.append(max(g) - min(g))
    summary = {"n": len(R), "mean_reward": sum(R) / len(R), "invalid_reward": res[0]["reward"],
               "groups_with_signal": sum(s > 1e-9 for s in spread) / len(spread),
               "by_action": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_act.items())}}
    log(json.dumps(summary, indent=1))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(prog="train.grpo_mole")
    ap.add_argument("--model", default=os.path.expanduser("~/agent-arena-data/models/Qwen2.5-0.5B-Instruct"))
    ap.add_argument("--out", default="data/grpo_mole/run")
    ap.add_argument("--backend", choices=["auto", "torch", "trl"], default="auto",
                    help="auto = TRL GRPOTrainer if importable, else the built-in torch GRPO loop")
    ap.add_argument("--fp16", action="store_true", help="fp16 AMP (V100). Both backends; bf16 is never used")
    ap.add_argument("--tiny", action="store_true", help="CPU stub: random-init tiny Qwen2 with --model's tokenizer")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--base-policy", default=None, help="RL mole json (canary.forge.rl_mole); default = shipped mole")
    ap.add_argument("--n-prompts", type=int, default=256)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--group", type=int, default=8)
    ap.add_argument("--prompts-per-step", type=int, default=4)
    ap.add_argument("--micro-batch", type=int, default=8)
    ap.add_argument("--max-new", type=int, default=32)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 4)))
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    t = time.time()
    prompts = collect_prompts(a.n_prompts, a.tier, a.base_policy, a.seed)
    print(f"[grpo_mole] {len(prompts)} prompts in {time.time() - t:.1f}s; example:\n{prompts[0]['prompt']}", flush=True)
    pool = RewardPool(a.workers)
    log = lambda s: print(s, flush=True)
    if a.dry_run:
        return dry_run(a, prompts, pool, log)
    if a.backend == "auto":
        try:
            import trl  # noqa: F401
            a.backend = "trl"
        except ImportError:
            a.backend = "torch"
    if a.tiny:
        a.model = _tiny_model(a.model, Path(a.out) / "tiny-model")
    log(f"[grpo_mole] backend={a.backend} fp16={a.fp16} model={a.model}")
    (train_trl if a.backend == "trl" else train_torch)(a, prompts, pool, log)


def _tiny_model(tok_src: str, out: Path) -> str:
    from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM
    tok = AutoTokenizer.from_pretrained(tok_src)
    cfg = Qwen2Config(vocab_size=len(tok), hidden_size=64, intermediate_size=128, num_hidden_layers=2,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=2048)
    out.mkdir(parents=True, exist_ok=True)
    Qwen2ForCausalLM(cfg).save_pretrained(out)
    tok.save_pretrained(out)
    return str(out)


if __name__ == "__main__":
    main()
