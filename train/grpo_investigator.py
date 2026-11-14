"""WS4 v3: decision-point GRPO for the small investigator, starting from the v2 SFT LoRA (FR8 V100s, fp16).

Full multi-turn GRPO (8 sampled episodes of ~40-120 tool calls per group) does not fit 2 GPUs x 6 h, so each
GRPO prompt is ONE decision point of a real episode, and the reward is the env's own final score:

  state  = (tier, seed, t): the reference solver plays TRAIN seed `seed` for t steps (deterministic replay).
  prompt = train.render of that history: byte-identical to the SFT windows and to eval_hf (HFPolicy._prompt_ids).
  action = the model's next tool call (G = --group samples per state).
  reward = Env score after: replay t solver steps -> the model's call -> the solver finishes the episode.
           Invalid call: -1. The score comes from the Env only (no hand-made shaping on the reward).

Since everything except the action at step t is fixed and the env is deterministic, reward differences within a
group come only from the action. The signal is concentrated where J4/v2 fail: the COMMIT decision (accuse the
right person now vs. keep investigating vs. accuse wrongly). States are sampled with weight on the last
--late-window steps before the solver's accusation (--late-frac), the rest uniformly.

Anti-collapse (WS3 collapsed onto one action): group >= 8, an entropy bonus (--ent-coef), a KL penalty to the
frozen v2 adapter (--kl-coef, k3 estimator), zero-variance groups contribute nothing, std floor on advantages.

Seeds: TRAIN only (rules.TRAIN_SEEDS, base --seed-base 150000, disjoint from the j3v14 SFT range).
Held-out and judge seeds are asserted never to be touched. Tiers: easy, medium.

    python -m train.grpo_investigator --dry-run --n-states 64            # CPU: states + rewards, no model
    python -m train.grpo_investigator --model ~/agent-arena-data/models/Qwen2.5-1.5B-Instruct \
        --adapter ~/agent-arena-data/j4/run-44410/lora --out RUN --fp16 --hours 5.5
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

INVALID_REWARD = -1.0
SEED_BASE = 150_000


# ---------------------------------------------------------------- env side (CPU, picklable)
def _check_seed(seed: int) -> None:
    from canary import rules
    assert seed in rules.TRAIN_SEEDS, f"seed {seed} not in TRAIN_SEEDS"
    assert seed not in rules.HELDOUT_SEEDS and seed not in rules.JUDGE_SEEDS


def _replay(tier: str, seed: int, t: int):
    """Env + solver after the solver's first t calls (deterministic)."""
    from canary.env import Env
    from canary.solver import SolverPolicy
    _check_seed(seed)
    env, sol = Env(tier=tier, seed=seed), SolverPolicy()
    sol.reset(env.tools_spec(), env.instruction())
    for _ in range(t):
        if env.done:
            break
        env.call(*sol.act(list(env.history)))
    return env, sol


def collect_states(n: int, tiers: list[str], seed_base: int, late_window: int, late_frac: float,
                   per_episode: int, rng_seed: int) -> list[dict]:
    """Decision points from solver episodes on TRAIN seeds. Each: {tier, seed, t, solver_score, solver_len, target}."""
    from canary.eval import run_episode
    from canary.env import Env
    from canary.solver import SolverPolicy
    rng = random.Random(rng_seed)
    out, i = [], 0
    while len(out) < n:
        tier = tiers[i % len(tiers)]
        seed = seed_base + i // len(tiers)
        i += 1
        _check_seed(seed)
        ep = run_episode(Env(tier=tier, seed=seed), SolverPolicy())
        L = len(ep.steps)
        if L < 2 or not ep.correct:   # learn the commit from episodes where committing was right
            continue
        for _ in range(per_episode):
            if rng.random() < late_frac:
                t = rng.randint(max(0, L - late_window), L - 1)   # includes the accuse step itself
            else:
                t = rng.randint(0, L - 1)
            out.append({"tier": tier, "seed": seed, "t": t, "solver_score": float(ep.score), "solver_len": L,
                        "target": ep.steps[-1].args.get("employee")})
    rng.shuffle(out)
    return out[:n]


def state_history(row: dict):
    env, _ = _replay(row["tier"], row["seed"], row["t"])
    return env.instruction(), env.tools_spec(), list(env.history)


def branch_reward(task) -> dict:
    """(state_row, parsed_call | None) -> reward dict. Model call at step t, then the solver finishes."""
    from canary.eval import MAX_ITERS
    row, call = task
    if call is None:
        return {"reward": INVALID_REWARD, "valid": False, "tool": None}
    tool, args = call
    env, sol = _replay(row["tier"], row["seed"], row["t"])
    if not env.done:
        sol.act(list(env.history))   # keep the solver's internal phase in step; its call is replaced by the model's
    env.call(tool, args)
    n = 0
    while not env.done and n < MAX_ITERS:
        env.call(*sol.act(list(env.history)))
        n += 1
    res = env.result("grpo-branch")
    return {"reward": float(res.score) if env.done else 0.0, "valid": True, "tool": tool,
            "correct": bool(res.correct), "early_accuse": tool == "accuse" and row["t"] < row["solver_len"] - 1}


class RewardPool:
    def __init__(self, workers: int):
        # spawn (not fork): the trainer initialises CUDA, forking after that is unsafe; warm the workers now
        import multiprocessing as mp
        self.ex = ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) if workers > 1 else None
        if self.ex:
            list(self.ex.map(_check_seed, [SEED_BASE] * workers))

    def __call__(self, rows, calls):
        tasks = list(zip(rows, calls))
        return list(self.ex.map(branch_reward, tasks, chunksize=4)) if self.ex else [branch_reward(t) for t in tasks]


# ---------------------------------------------------------------- model side (GPU)
def train(a, states, pool, log):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from train.eval_hf import HFPolicy
    from train.render import parse_tool_call

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    amp = bool(a.fp16) and dev == "cuda"
    tok = AutoTokenizer.from_pretrained(a.adapter if (Path(a.adapter) / "tokenizer.json").exists() else a.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    base = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float32).to(dev)  # fp32 master + AMP
    base.gradient_checkpointing_enable()
    base.enable_input_require_grads()
    model = PeftModel.from_pretrained(base, a.adapter, adapter_name="default", is_trainable=True)
    use_ref = a.kl_coef > 0
    if use_ref:
        model.load_adapter(a.adapter, adapter_name="ref", is_trainable=False)
    model.set_adapter("default")
    params = [p for n, p in model.named_parameters() if p.requires_grad and ".default." in n]
    opt = torch.optim.AdamW(params, lr=a.lr)
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    pol = HFPolicy(model, tok, "v3", max_ctx=a.max_ctx, max_new=a.max_new, kv_reuse=False)

    rng = random.Random(a.seed)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    curve = out / "curve.jsonl"
    deadline = time.time() + a.hours * 3600 if a.hours > 0 else float("inf")
    if a.deadline_file and Path(a.deadline_file).exists():   # slurm end - margin
        deadline = min(deadline, float(Path(a.deadline_file).read_text().split()[0]) - a.margin_min * 60)
    t_start, step = time.time(), 0
    while step < a.steps and time.time() < deadline:
        t0 = time.time()
        batch = rng.sample(states, min(a.prompts_per_step, len(states)))
        prompts, tool_names = [], []
        for row in batch:
            instr, spec, hist = state_history(row)
            pol.reset(spec, instr)
            ids = pol._prompt_ids(hist)          # same render + truncation as eval_hf
            prompts.append(ids)
            tool_names.append(pol.tool_names)
        # ---- sample G completions per prompt (one prompt at a time: prompts can be ~4k tokens)
        seqs, rows, calls, plen = [], [], [], []
        model.eval()
        for row, ids, names in zip(batch, prompts, tool_names):
            x = torch.tensor([ids], device=dev)
            with torch.no_grad(), torch.autocast(dev, dtype=torch.float16, enabled=amp):
                g = model.generate(input_ids=x.expand(a.group, -1), attention_mask=torch.ones_like(x).expand(a.group, -1),
                                   max_new_tokens=a.max_new, do_sample=True, temperature=a.temperature, top_p=1.0,
                                   pad_token_id=tok.pad_token_id)
            for k in range(a.group):
                comp = g[k, len(ids):]
                eos = (comp == tok.eos_token_id) | (comp == tok.pad_token_id)
                n = int(eos.nonzero()[0]) + 1 if eos.any() else len(comp)   # keep the first EOS as a target
                seqs.append((ids, comp[:n].tolist()))
                rows.append(row)
                calls.append(parse_tool_call(tok.decode(comp[:n], skip_special_tokens=False), names))
                plen.append(len(ids))
        results = pool(rows, calls)
        R = torch.tensor([r["reward"] for r in results], dtype=torch.float32).view(-1, a.group)
        std = R.std(1, keepdim=True)
        adv = ((R - R.mean(1, keepdim=True)) / std.clamp(min=a.std_floor))
        adv[(std < 1e-6).expand_as(adv)] = 0.0           # no signal in zero-variance groups
        adv = adv.view(-1)
        # ---- policy gradient + entropy bonus + KL(v2) penalty, one sequence per micro step
        model.train()
        opt.zero_grad(set_to_none=True)
        stats = {"ent": 0.0, "kl": 0.0}
        active = [i for i in range(len(seqs)) if adv[i] != 0 or a.ent_coef > 0 or a.kl_coef > 0]
        for i in active:
            p_ids, c_ids = seqs[i]
            if not c_ids:
                continue
            full = torch.tensor([p_ids + c_ids], device=dev)
            P = len(p_ids)
            tgt = full[:, P:]
            if use_ref:
                model.set_adapter("ref")
                with torch.no_grad(), torch.autocast(dev, dtype=torch.float16, enabled=amp):
                    ref_lp = torch.log_softmax(model(input_ids=full).logits[:, P - 1:-1].float(), -1) \
                        .gather(-1, tgt.unsqueeze(-1)).squeeze(-1)
                model.set_adapter("default")
            with torch.autocast(dev, dtype=torch.float16, enabled=amp):
                logits = model(input_ids=full).logits[:, P - 1:-1].float()
            lp_all = torch.log_softmax(logits, -1)
            tlp = lp_all.gather(-1, tgt.unsqueeze(-1)).squeeze(-1)          # [1, C]
            ent = -(lp_all.exp() * lp_all).sum(-1).mean()
            loss = -adv[i].to(dev) * tlp.mean() - a.ent_coef * ent
            if use_ref:
                d = ref_lp - tlp
                kl = (d.exp() - d - 1).mean()                                  # k3, >= 0
                loss = loss + a.kl_coef * kl
                stats["kl"] += float(kl) / len(active)
            stats["ent"] += float(ent) / len(active)
            scaler.scale(loss / len(active)).backward()
        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        scaler.step(opt); scaler.update()
        valid = [r for r in results if r["valid"]]
        tools = Counter(r["tool"] for r in valid)
        # valid-only signal (WS3 lesson: raw reward can rise just because invalid -1s vanish)
        vgain = [r["reward"] - row["solver_score"] for r, row in zip(results, rows) if r["valid"]]
        ents = []                                        # per-state entropy of the sampled call distribution
        for g in range(len(batch)):
            cs = Counter(json.dumps(c, sort_keys=True) if c else "INVALID" for c in calls[g * a.group:(g + 1) * a.group])
            ents.append(-sum(v / a.group * math.log(v / a.group) for v in cs.values()))
        rec = {"step": step, "reward": round(float(R.mean()), 4),
               "reward_valid": round(sum(r["reward"] for r in valid) / len(valid), 4) if valid else None,
               "gain_vs_solver_valid": round(sum(vgain) / len(vgain), 4) if vgain else None,
               "action_entropy": round(sum(ents) / len(ents), 3),
               "continue_frac": round(sum(1 for r in valid if r["tool"] != "accuse") / max(1, len(results)), 3),
               "late_state_frac": round(sum(row["t"] >= row["solver_len"] - a.late_window for row in batch) / len(batch), 2),
               "solver_ref": round(sum(r["solver_score"] for r in batch) / len(batch), 4),
               "valid": round(len(valid) / len(results), 3),
               "accuse_frac": round(tools.get("accuse", 0) / max(1, len(results)), 3),
               "accuse_correct": round(sum(r.get("correct", False) for r in valid if r["tool"] == "accuse")
                                       / max(1, tools.get("accuse", 0)), 3),
               "distinct_tools": len(tools), "top_tool_share": round(tools.most_common(1)[0][1] / len(results), 3) if tools else 0,
               "zero_var_groups": int((std < 1e-6).sum()), "ent": round(stats["ent"], 4), "kl": round(stats["kl"], 5),
               "sec": round(time.time() - t0, 1), "elapsed_h": round((time.time() - t_start) / 3600, 3)}
        log(json.dumps(rec))
        with curve.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        step += 1
        if step % a.save_every == 0:
            model.save_pretrained(out / f"lora-step{step}", selected_adapters=["default"])
    final = out / "lora"
    model.save_pretrained(out / "_final", selected_adapters=["default"])
    src = out / "_final" if (out / "_final" / "adapter_config.json").exists() else out / "_final" / "default"
    src.rename(final) if not final.exists() else None
    tok.save_pretrained(final)
    (final / "train_summary.json").write_text(json.dumps({"steps": step, "hours": (time.time() - t_start) / 3600,
                                                         "args": vars(a)}, default=str, indent=1))
    log(f"[v3] saved {final} after {step} steps")


def dry_run(a, states, pool, log):
    """CPU: rewards for (solver's own next call, accuse the right / a wrong employee now, an invalid call) per state."""
    rows, calls = [], []
    for row in states:
        env, sol = _replay(row["tier"], row["seed"], row["t"])
        nxt = sol.act(list(env.history))
        wrong = "e00" if row["target"] != "e00" else "e01"
        rows += [row, row, row, row]
        calls += [nxt, ("accuse", {"employee": row["target"]}), ("accuse", {"employee": wrong}), None]
    res = pool(rows, calls)
    per = [res[i:i + 4] for i in range(0, len(res), 4)]
    own = [p[0]["reward"] for p in per]
    log(json.dumps({"states": len(states), "solver_next_mean": round(sum(own) / len(own), 4),
                    "accuse_right_now_mean": round(sum(p[1]["reward"] for p in per) / len(per), 4),
                    "accuse_wrong_now_mean": round(sum(p[2]["reward"] for p in per) / len(per), 4),
                    "invalid": per[0][3]["reward"],
                    "solver_ref_mean": round(sum(r["solver_score"] for r in states) / len(states), 4),
                    "replay_matches_ref": sum(abs(p[0]["reward"] - s["solver_score"]) < 1e-9 for p, s in zip(per, states)),
                    "tiers": dict(Counter(s["tier"] for s in states))}))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=str(Path("~/agent-arena-data/models/Qwen2.5-1.5B-Instruct").expanduser()))
    ap.add_argument("--adapter", default=None, help="v2 SFT LoRA dir (trainable start + frozen KL reference)")
    ap.add_argument("--out", default="data/grpo_inv")
    ap.add_argument("--tiers", default="easy,medium")
    ap.add_argument("--seed-base", type=int, default=SEED_BASE)
    ap.add_argument("--n-states", type=int, default=2000)
    ap.add_argument("--per-episode", type=int, default=3)
    ap.add_argument("--late-window", type=int, default=6)
    ap.add_argument("--late-frac", type=float, default=0.6)
    ap.add_argument("--steps", type=int, default=100000)
    ap.add_argument("--hours", type=float, default=0.0)
    ap.add_argument("--deadline-file", default=None)
    ap.add_argument("--margin-min", type=float, default=10)
    ap.add_argument("--group", type=int, default=8)
    ap.add_argument("--prompts-per-step", type=int, default=2)
    ap.add_argument("--max-new", type=int, default=48)
    ap.add_argument("--max-ctx", type=int, default=4096)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=5e-6)
    ap.add_argument("--ent-coef", type=float, default=0.01)
    ap.add_argument("--kl-coef", type=float, default=0.04)
    ap.add_argument("--std-floor", type=float, default=0.1)
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.group < 8 and not a.dry_run:
        raise SystemExit("--group must be >= 8 (anti-collapse)")
    tiers = [t for t in a.tiers.split(",") if t]
    assert set(tiers) <= {"easy", "medium"}, "v3 trains on easy+medium TRAIN seeds only"
    log = lambda s: print(s, flush=True)  # noqa: E731
    t0 = time.time()
    states = collect_states(a.n_states, tiers, a.seed_base + 1000 * a.seed, a.late_window, a.late_frac,
                            a.per_episode, a.seed)
    log(f"[v3] {len(states)} states from TRAIN seeds {a.seed_base + 1000 * a.seed}+ tiers={tiers} "
        f"({time.time() - t0:.1f}s)")
    pool = RewardPool(a.workers)
    if a.dry_run:
        dry_run(a, states, pool, log)
        return
    if not a.adapter:
        raise SystemExit("--adapter (v2 LoRA) is required")
    train(a, states, pool, log)


if __name__ == "__main__":
    main()
