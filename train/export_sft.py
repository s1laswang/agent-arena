"""Export solver episodes as chat transcripts for SFT.

    python -m train.export_sft --split train|val --tier easy|medium|hard|all --n N --out DIR
                               [--seed-offset K] [--workers W] [--shard-size S] [--all-episodes]
                               [--policy solver|fake]

Seeds: TRAIN seeds only. train = 100000..189999, val = 190000..199999 (disjoint slices of
TRAIN_SEEDS). Held-out (800000+) and judge (900000+) seeds are never touched (asserted).
Per tier, episode i uses seed = split_base + seed_offset + i.
By default only correct episodes are written (the solver's good play); --all-episodes keeps all.
Output: DIR/<split>-<tier>-<k>.jsonl shards, one train.render.render_episode record per line,
plus DIR/<split>-manifest.json.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor

from train.render import render_episode

TIERS = ("easy", "medium", "hard")
SPLIT_RANGES = {"train": (100_000, 190_000), "val": (190_000, 200_000)}


def split_seeds(split: str, n: int, offset: int = 0) -> list[int]:
    lo, hi = SPLIT_RANGES[split]
    seeds = list(range(lo + offset, lo + offset + n))
    if seeds and seeds[-1] >= hi:
        raise ValueError(f"{split}: offset+n exceeds the split range [{lo},{hi})")
    assert all(100_000 <= s < 200_000 for s in seeds), "only TRAIN seeds may be exported"
    return seeds


def run_episode(env, policy):
    """canary.eval.run_episode if available, else the minimal contract loop."""
    try:
        from canary.eval import run_episode as _run  # type: ignore
        return _run(env, policy)
    except ImportError:
        pass
    policy.reset(env.tools_spec(), env.instruction())
    while not env.done:
        tool, args = policy.act(env.history)
        env.call(tool, args)
    return env.result(policy.name)


def make_env_policy(policy: str, tier: str, seed: int):
    if policy == "fake":
        from train.fake import FakeEnv, FakeSolver
        return FakeEnv(tier, seed), FakeSolver()
    from canary.env import Env
    from canary.solver import SolverPolicy  # type: ignore
    return Env(tier=tier, seed=seed), SolverPolicy()


def play_one(job: tuple[str, str, int]) -> dict:
    policy, tier, seed = job
    env, pol = make_env_policy(policy, tier, seed)
    tools, instr = env.tools_spec(), env.instruction()
    ep = run_episode(env, pol)
    return render_episode(ep, instr, tools)


def export(split: str, tiers: list[str], n: int, out: str, seed_offset: int = 0,
           workers: int = 1, shard_size: int = 1000, only_correct: bool = True,
           policy: str = "solver") -> dict:
    os.makedirs(out, exist_ok=True)
    stats: dict = {"split": split, "policy": policy, "tiers": {}, "files": []}
    t0 = time.time()
    for tier in tiers:
        jobs = [(policy, tier, s) for s in split_seeds(split, n, seed_offset)]
        if workers > 1:
            with ProcessPoolExecutor(workers) as ex:
                recs = list(ex.map(play_one, jobs, chunksize=8))
        else:
            recs = [play_one(j) for j in jobs]
        kept = [r for r in recs if r["correct"] or not only_correct]
        for k in range(0, max(len(kept), 1), shard_size):
            chunk = kept[k:k + shard_size]
            if not chunk:
                break
            path = os.path.join(out, f"{split}-{tier}-{k // shard_size:03d}.jsonl")
            with open(path, "w") as f:
                for r in chunk:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
            stats["files"].append(os.path.basename(path))
        n_ep = len(recs)
        stats["tiers"][tier] = {
            "episodes": n_ep, "kept": len(kept),
            "accuracy": sum(r["correct"] for r in recs) / max(n_ep, 1),
            "mean_score": sum(r["score"] for r in recs) / max(n_ep, 1),
            "mean_assistant_turns": sum(len(r["messages"]) - 2 for r in recs) / max(2 * n_ep, 1),
        }
    stats["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(out, f"{split}-manifest.json"), "w") as f:
        json.dump(stats, f, indent=2)
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=list(SPLIT_RANGES), default="train")
    ap.add_argument("--tier", choices=[*TIERS, "all"], default="all")
    ap.add_argument("--n", type=int, required=True, help="episodes per tier")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--shard-size", type=int, default=1000)
    ap.add_argument("--all-episodes", action="store_true", help="keep incorrect episodes too")
    ap.add_argument("--policy", choices=["solver", "fake"], default="solver")
    a = ap.parse_args(argv)
    tiers = list(TIERS) if a.tier == "all" else [a.tier]
    stats = export(a.split, tiers, a.n, a.out, a.seed_offset, a.workers, a.shard_size,
                   not a.all_episodes, a.policy)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
