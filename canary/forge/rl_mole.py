"""WS3 light: an RL-trained mole (CPU, numpy only).

Policy: a 1-hidden-layer MLP over MoleView features -> two softmax heads (leak selector, frame selector), the
same action vocabulary as the Mole DSL (canary/mole/dsl.py), so the env needs nothing new: RLMole implements
`decide(view, rng)` and is passed as `Env(..., mole_strategy=RLMole(...))`. Sampling uses the env's own RNG, so
an episode is fully determined by (tier, seed, policy weights, investigator actions).

Objective (NEXT-LEVEL WS3): J = solver score - max_k score_k over investigators k in {grok_tactics, heuristic,
hinted_heuristic}, subject to solver accuracy >= 0.75 (the mole must stay catchable by the reference run).
REINFORCE decomposes J by episode:
  * solver episodes reward the mole with  S + lam * correct      (lam = Lagrange multiplier, dual ascent)
  * investigator-k episodes reward it with -w_k * score_k         (w = softmax of mean score_k -> soft max_k)
Per-agent running-mean baselines; Adam. All randomness is seeded.

    uv run python -m canary.forge.rl_mole train --iters 120 --batch 48 --workers 8 --out data/rl_mole
    uv run python -m canary.forge.rl_mole eval --policy data/rl_mole/policy_best.json --seeds 100
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from canary.mole.dsl import FRAME_SELECTORS, LEAK_SELECTORS, MoleView, _select_frame, _select_leak

FEATURE_NAMES = ("day", "days_since_last_leak", "i_am_restricted", "n_restricted_colleagues",
                 "recent_low_recipient_docs", "n_leakable", "min_recipient_count", "max_recipient_count",
                 "newest_doc_age_days", "can_leak")
SCALE = np.array([14, 14, 1, 10, 6, 12, 20, 30, 3, 1], dtype=np.float64)
N_FEAT = len(FEATURE_NAMES) + 1  # + bias-like constant
N_LEAK, N_FRAME = len(LEAK_SELECTORS), len(FRAME_SELECTORS)
INVESTIGATORS = ("grok_tactics", "heuristic", "hinted_heuristic")
MIN_SOLVER_ACC = 0.75
TRAIN_SEED_BASE = 100_000   # dev seeds, disjoint from judge seeds (900000+) and the game's 3000+ range
EVAL_SEED_BASE = 200_000    # held out from training


def features(view: MoleView) -> np.ndarray:
    raw = [view.day, view.days_since_last_leak, view.i_am_restricted, view.n_restricted_colleagues,
           view.recent_low_recipient_docs, view.feature("n_leakable"), view.feature("min_recipient_count"),
           view.feature("max_recipient_count"), min(view.feature("newest_doc_age_days"), 3), float(view.can_leak)]
    return np.concatenate([np.clip(np.asarray(raw, dtype=np.float64) / SCALE, 0, 2), [1.0]])


def _softmax(z):
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


def init_params(hidden: int = 16, seed: int = 0) -> dict:
    r = np.random.default_rng(seed)
    return {"W1": r.normal(0, 0.5, (N_FEAT, hidden)), "b1": np.zeros(hidden),
            "Wl": r.normal(0, 0.1, (hidden, N_LEAK)), "bl": np.zeros(N_LEAK),
            "Wf": r.normal(0, 0.1, (hidden, N_FRAME)), "bf": np.zeros(N_FRAME)}


def default_like_params(hidden: int = 16, seed: int = 0) -> dict:
    """Start near the default mole (leak random_seeded, frame none) so training explores from the shipped mole."""
    p = init_params(hidden, seed)
    p["bl"][LEAK_SELECTORS.index("random_seeded")] = 2.0
    p["bf"][FRAME_SELECTORS.index("none")] = 2.0
    return p


def forward(p: dict, x: np.ndarray):
    h = np.tanh(x @ p["W1"] + p["b1"])
    return h, _softmax(h @ p["Wl"] + p["bl"]), _softmax(h @ p["Wf"] + p["bf"])


class RLMole:
    """A Mole DSL-compatible strategy backed by an MLP. `trace` (list) records (x, leak_idx, frame_idx)."""

    def __init__(self, params: dict, greedy: bool = False, trace: list | None = None, name: str = "rl_mole"):
        self.p = {k: np.asarray(v, dtype=np.float64) for k, v in params.items()}
        self.greedy, self.trace, self.name = greedy, trace, name

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        x = features(view)
        _, pl, pf = forward(self.p, x)
        if self.greedy:
            li, fi = int(pl.argmax()), int(pf.argmax())
        else:  # inverse-CDF with the env RNG: deterministic per episode
            li = int(np.searchsorted(np.cumsum(pl), rng.random() * pl.sum()))
            fi = int(np.searchsorted(np.cumsum(pf), rng.random() * pf.sum()))
            li, fi = min(li, N_LEAK - 1), min(fi, N_FRAME - 1)
        if self.trace is not None:
            self.trace.append((x, li, fi))
        return {"leak": _select_leak(LEAK_SELECTORS[li], view, rng),
                "frame": _select_frame(FRAME_SELECTORS[fi], view, rng)}

    def to_json(self) -> dict:
        return {"kind": "rl_mole", "name": self.name, "greedy": self.greedy,
                "features": list(FEATURE_NAMES), "leak_selectors": list(LEAK_SELECTORS),
                "frame_selectors": list(FRAME_SELECTORS),
                "params": {k: v.tolist() for k, v in self.p.items()}}

    @classmethod
    def from_json(cls, obj: dict) -> "RLMole":
        if obj.get("kind") != "rl_mole" or list(obj.get("leak_selectors", [])) != list(LEAK_SELECTORS) \
                or list(obj.get("frame_selectors", [])) != list(FRAME_SELECTORS):
            raise ValueError("not an rl_mole policy for this DSL vocabulary")
        return cls(obj["params"], greedy=bool(obj.get("greedy", False)), name=obj.get("name", "rl_mole"))


# ---------------------------------------------------------------- rollouts
def _agent(name: str, tier: str, seed: int):
    from canary.baselines import GrokTactics, Heuristic
    from canary.forge.investigators import HintedHeuristic
    from canary.solver.policy import SolverPolicy
    if name == "solver":
        return SolverPolicy(tier)
    if name == "grok_tactics":
        try:
            return GrokTactics(seed=seed)
        except TypeError:
            return GrokTactics()
    if name == "heuristic":
        return Heuristic(seed=seed)
    if name == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    raise ValueError(name)


def rollout(task) -> dict:
    """task = (params, tier, seed, agents, greedy) -> {agent: (score, correct, trace)}"""
    from canary.env import Env
    from canary.eval import run_episode
    params, tier, seed, agents, greedy = task
    out = {}
    for name in agents:
        tr: list = []
        r = run_episode(Env(tier, seed, mole_strategy=RLMole(params, greedy=greedy, trace=tr)), _agent(name, tier, seed))
        out[name] = (float(r.score), bool(r.correct), tr)
    return out


def run_batch(params, tier, seeds, workers, agents=("solver",) + INVESTIGATORS, greedy=False, ex=None):
    tasks = [(params, tier, s, agents, greedy) for s in seeds]
    if ex is not None:
        return list(ex.map(rollout, tasks, chunksize=max(1, len(tasks) // (4 * workers))))
    return [rollout(t) for t in tasks]


def summarize(rows, agents=("solver",) + INVESTIGATORS) -> dict:
    n = len(rows)
    s = {a: {"score": sum(r[a][0] for r in rows) / n, "acc": sum(r[a][1] for r in rows) / n} for a in agents}
    inv = [a for a in agents if a != "solver"]
    if "solver" in s and inv:
        s["min_regret"] = s["solver"]["score"] - max(s[a]["score"] for a in inv)
        s["strongest"] = max(inv, key=lambda a: s[a]["score"])
        s["feasible"] = s["solver"]["acc"] >= MIN_SOLVER_ACC
    return s


# ---------------------------------------------------------------- REINFORCE
def _grad_logp(p, x, li, fi):
    h, pl, pf = forward(p, x)
    dl = -pl; dl[li] += 1.0
    df = -pf; df[fi] += 1.0
    g = {"Wl": np.outer(h, dl), "bl": dl, "Wf": np.outer(h, df), "bf": df}
    dh = (p["Wl"] @ dl + p["Wf"] @ df) * (1 - h * h)
    g["W1"], g["b1"] = np.outer(x, dh), dh
    return g, -(pl * np.log(pl + 1e-12)).sum() - (pf * np.log(pf + 1e-12)).sum()


def _grad_entropy(p, x):
    """d/dtheta of the summed head entropies (exact, via the softmax Jacobian)."""
    h, pl, pf = forward(p, x)
    g = {}
    dz = {}
    for k, pr in (("l", pl), ("f", pf)):
        lg = np.log(pr + 1e-12)
        dz[k] = -pr * (lg - (pr * lg).sum())
    g["Wl"], g["bl"] = np.outer(h, dz["l"]), dz["l"]
    g["Wf"], g["bf"] = np.outer(h, dz["f"]), dz["f"]
    dh = (p["Wl"] @ dz["l"] + p["Wf"] @ dz["f"]) * (1 - h * h)
    g["W1"], g["b1"] = np.outer(x, dh), dh
    return g


class Adam:
    def __init__(self, params, lr=0.03, b1=0.9, b2=0.999):
        self.lr, self.b1, self.b2, self.t = lr, b1, b2, 0
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}

    def step(self, params, grad):  # gradient ASCENT
        self.t += 1
        for k in params:
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * grad[k]
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * grad[k] ** 2
            mh = self.m[k] / (1 - self.b1 ** self.t)
            vh = self.v[k] / (1 - self.b2 ** self.t)
            params[k] = params[k] + self.lr * mh / (np.sqrt(vh) + 1e-8)


def train(iters=120, batch=48, workers=8, tier="hard", lr=0.03, hidden=16, seed=0, ent=0.01, lam0=1.0,
          lam_lr=2.0, acc_margin=0.05, temp=0.05, out: str | Path = "data/rl_mole", log=print) -> dict:
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    params = default_like_params(hidden, seed)
    opt = Adam(params, lr)
    lam = lam0
    base = {a: None for a in ("solver",) + INVESTIGATORS}
    curve, best = [], None
    rng = random.Random(seed)
    ex = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    try:
        for it in range(iters):
            t0 = time.time()
            seeds = [TRAIN_SEED_BASE + rng.randrange(50_000) for _ in range(batch)]
            rows = run_batch({k: v.copy() for k, v in params.items()}, tier, seeds, workers, ex=ex)
            st = summarize(rows)
            inv_scores = np.array([st[a]["score"] for a in INVESTIGATORS])
            w = _softmax(inv_scores / temp)  # soft "strongest investigator"
            grad = {k: np.zeros_like(v) for k, v in params.items()}
            n_steps = 0
            for r in rows:
                for ai, a in enumerate(("solver",) + INVESTIGATORS):
                    score, corr, tr = r[a]
                    if a == "solver":
                        R = score + lam * float(corr)
                        coef = 1.0
                    else:
                        R = -score
                        coef = float(w[ai - 1]) * len(INVESTIGATORS)
                    b = base[a] if base[a] is not None else R
                    adv = coef * (R - b)
                    for x, li, fi in tr:
                        g, _ = _grad_logp(params, x, li, fi)
                        ge = _grad_entropy(params, x)
                        for k in grad:
                            grad[k] += adv * g[k] + ent * ge[k]
                        n_steps += 1
            for a in base:  # update baselines after computing advantages
                Rm = (np.mean([r[a][0] + lam * r[a][1] for r in rows]) if a == "solver"
                      else -np.mean([r[a][0] for r in rows]))
                base[a] = Rm if base[a] is None else 0.8 * base[a] + 0.2 * Rm
            grad = {k: v / max(1, len(rows)) for k, v in grad.items()}
            opt.step(params, grad)
            lam = max(0.0, lam + lam_lr * (MIN_SOLVER_ACC + acc_margin - st["solver"]["acc"]))
            row = {"iter": it, "min_regret": st["min_regret"], "strongest": st["strongest"],
                   "solver_score": st["solver"]["score"], "solver_acc": st["solver"]["acc"],
                   **{f"{a}_score": st[a]["score"] for a in INVESTIGATORS}, "lam": lam,
                   "steps": n_steps, "sec": round(time.time() - t0, 2)}
            curve.append(row)
            log(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}))
            (out / "curve.jsonl").write_text("".join(json.dumps(c) + "\n" for c in curve))
            if st["feasible"] and (best is None or st["min_regret"] > best[0]):
                best = (st["min_regret"], it)
            if it % 10 == 9 or it == iters - 1:
                (out / f"policy_it{it + 1:03d}.json").write_text(
                    json.dumps(RLMole(params, name=f"rl_mole_it{it + 1}").to_json()))
        (out / "policy_final.json").write_text(json.dumps(RLMole(params, name="rl_mole_final").to_json()))
    finally:
        if ex is not None:
            ex.shutdown()
    return {"curve": curve, "params": params, "best_train_iter": best}


def evaluate_policy(policy: RLMole | None, tier="hard", n=100, workers=8, base=EVAL_SEED_BASE) -> dict:
    """Held-out eval. policy=None -> the shipped default mole (same seeds), for comparison."""
    from canary.env import Env
    from canary.eval import run_episode
    seeds = list(range(base, base + n))
    if policy is None:
        tasks = [(None, tier, s) for s in seeds]
        with ProcessPoolExecutor(max_workers=workers) as ex:
            rows = list(ex.map(_default_rollout, tasks))
        return summarize(rows)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = run_batch({k: v for k, v in policy.p.items()}, tier, seeds, workers, greedy=policy.greedy, ex=ex)
    return summarize(rows)


def _default_rollout(task):
    from canary.env import Env
    from canary.eval import run_episode
    _, tier, seed = task
    return {a: (float((r := run_episode(Env(tier, seed), _agent(a, tier, seed))).score), bool(r.correct), [])
            for a in ("solver",) + INVESTIGATORS}


def action_profile(policy: RLMole, tier="hard", n=20) -> dict:
    """How often the policy picks each selector (sampled over solver episodes): makes the learned mole legible."""
    from collections import Counter
    rows = run_batch(policy.p, tier, list(range(EVAL_SEED_BASE, EVAL_SEED_BASE + n)), 1, agents=("solver",))
    cl, cf = Counter(), Counter()
    for r in rows:
        for _, li, fi in r["solver"][2]:
            cl[LEAK_SELECTORS[li]] += 1
            cf[FRAME_SELECTORS[fi]] += 1
    tot = sum(cl.values()) or 1
    return {"leak": {k: round(v / tot, 3) for k, v in cl.most_common()},
            "frame": {k: round(v / tot, 3) for k, v in cf.most_common()}}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="canary.forge.rl_mole")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--iters", type=int, default=120)
    t.add_argument("--batch", type=int, default=48)
    t.add_argument("--workers", type=int, default=8)
    t.add_argument("--tier", default="hard")
    t.add_argument("--lr", type=float, default=0.03)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--out", default="data/rl_mole")
    e = sub.add_parser("eval")
    e.add_argument("--policy", default=None, help="policy json; omit for the default mole")
    e.add_argument("--seeds", type=int, default=100)
    e.add_argument("--workers", type=int, default=8)
    e.add_argument("--tier", default="hard")
    e.add_argument("--greedy", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "train":
        train(a.iters, a.batch, a.workers, a.tier, a.lr, seed=a.seed, out=a.out)
    else:
        pol = None
        if a.policy:
            pol = RLMole.from_json(json.loads(Path(a.policy).read_text()))
            pol.greedy = a.greedy or pol.greedy
        res = evaluate_policy(pol, a.tier, a.seeds, a.workers)
        if pol is not None:
            res["profile"] = action_profile(pol, a.tier)
        print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
