"""Episode runner + eval CLI (CONTRACT §5, §6). Owner: HARNESS.

    python -m canary.eval --agent <baseline|solver> --tier easy|medium|hard|all --seeds dev20|judge|n:N|N|a-b|a,b,c --provider template

Writes data/runs/<run_id>/episodes.jsonl (one types.EpisodeResult per line) and meta.json,
then prints mean score ± 95% CI, accuracy and mean accusation day per tier.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .rules import TRACKS
from .types import EpisodeResult, Step

MAX_ITERS = 1000
TIERS = ("easy", "medium", "hard")


class AgentUnavailable(RuntimeError):
    pass


# --------------------------------------------------------------------------- runner
def run_episode(env, policy, max_iters: int = MAX_ITERS) -> EpisodeResult:
    """Play one episode through the public tool interface; the score comes from the Env only."""
    policy.reset(env.tools_spec(), env.instruction())
    error: str | None = None
    for _ in range(max_iters):
        if env.done:
            break
        try:
            tool, args = policy.act(list(env.history))
        except Exception as exc:  # a crashing policy ends its own episode, never the run
            error = f"policy error: {type(exc).__name__}: {exc}"
            break
        env.call(tool, args)
    res = env.result(getattr(policy, "name", type(policy).__name__))
    if not env.done:
        res.end_reason = "error"
        res.meta["error"] = error or f"no episode end after {max_iters} iterations"
    return res


def episode_from_dict(d: dict) -> EpisodeResult:
    """Inverse of dataclasses.asdict for one episodes.jsonl line."""
    d = dict(d)
    d["steps"] = [Step(**s) for s in d.get("steps", [])]
    return EpisodeResult(**d)


# --------------------------------------------------------------------------- agents / seeds
def make_policy_factory(agent: str) -> Callable[[int], Any]:
    """Returns seed -> fresh Policy. Raises AgentUnavailable with a readable message."""
    from .baselines import BASELINES, CALIBRATION_POLICIES

    if agent in BASELINES or agent in CALIBRATION_POLICIES:
        cls = BASELINES.get(agent) or CALIBRATION_POLICIES[agent]
        return lambda seed: cls(seed=seed)
    if agent == "solver":
        try:
            from .solver.policy import SolverPolicy
        except ImportError as exc:
            raise AgentUnavailable(f"solver not available yet (canary.solver.policy.SolverPolicy: {exc})") from exc
        return lambda seed: SolverPolicy()
    if ":" in agent:  # openai:<model>, gemini:<model>
        raise AgentUnavailable(f"LLM agent '{agent}' is not wired into canary.eval yet; "
                               "run it over MCP (make mcp + configs/README.md) instead")
    names = sorted(set(BASELINES) | set(CALIBRATION_POLICIES) | {"solver"})
    raise AgentUnavailable(f"unknown agent '{agent}'. Known: {', '.join(names)}")


MAX_COUNT_SPEC = 1000      # a bare integer <= this is a count (0..N-1); above it, a single seed
MAX_EPISODES = 10_000      # refuse any seed (x tier) expansion larger than this


def parse_seeds(spec: str) -> list[int]:
    """Seed spec -> list of seeds.

    dev20 | judge | n:N (count: 0..N-1) | N (count if N <= 1000, else the single seed N, e.g. 900003)
    | a-b (inclusive range) | a,b,c (lists; parts may be ranges). Raises ValueError on a bad spec or
    an expansion over MAX_EPISODES seeds.
    """
    spec = str(spec).strip()
    if spec == "dev20":
        return list(range(20))
    if spec == "judge":
        from .rules import JUDGE_SEEDS
        return list(JUDGE_SEEDS)

    def _count(n: int) -> list[int]:
        if n > MAX_EPISODES:
            raise ValueError(f"--seeds: {n} seeds is over the {MAX_EPISODES} limit")
        return list(range(n))

    try:
        if spec.startswith("n:"):
            return _count(int(spec[2:]))
        if spec.isdigit():
            n = int(spec)
            return _count(n) if n <= MAX_COUNT_SPEC else [n]
        out: list[int] = []
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                a, b = (int(x) for x in part.split("-", 1))
                if b < a:
                    raise ValueError(f"--seeds: empty range '{part}'")
                if len(out) + (b - a + 1) > MAX_EPISODES:
                    raise ValueError(f"--seeds: '{spec}' expands to more than {MAX_EPISODES} seeds")
                out.extend(range(a, b + 1))
            elif part:
                out.append(int(part))
    except ValueError as exc:
        if str(exc).startswith("--seeds"):
            raise
        raise ValueError(f"--seeds: cannot parse '{spec}' "
                         "(use dev20 | judge | n:N | N | a-b | a,b,c)") from exc
    if not out:
        raise ValueError(f"--seeds: '{spec}' selects no seeds")
    return out


def make_env(tier: str, seed: int, provider: str = "template"):
    from .env import Env
    text = None
    if provider != "template":
        from .text.gemini import get_provider
        text = get_provider(provider)
    return Env(tier, seed, text_provider=text)


# --------------------------------------------------------------------------- run + report
def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parent, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def summarize(eps: list[EpisodeResult]) -> dict:
    from .analysis.gap import mean_ci
    m, h = mean_ci([e.score for e in eps])
    days = [e.final_day for e in eps if e.end_reason == "accused"]
    return {"n": len(eps), "mean": m, "ci": h,
            "accuracy": sum(e.correct for e in eps) / len(eps) if eps else float("nan"),
            "accuse_day": sum(days) / len(days) if days else float("nan"),
            "accused": len(days)}


def _f(x: float, nd: int = 3, sign: bool = False) -> str:
    if x != x:
        return "-"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def format_table(agent: str, by_tier: dict[str, list[EpisodeResult]]) -> str:
    rows = [f"{'tier':<7} {'agent':<18} {'n':>4} {'score ± 95% CI':>18} {'accuracy':>9} {'accused':>8} {'accuse day':>11}"]
    for tier, eps in by_tier.items():
        s = summarize(eps)
        score = f"{_f(s['mean'], sign=True)} ± {_f(s['ci'])}"
        rows.append(f"{tier:<7} {agent:<18} {s['n']:>4} {score:>18} {_f(s['accuracy'], 2):>9} "
                    f"{s['accused']:>8} {_f(s['accuse_day'], 1):>11}")
    return "\n".join(rows)


def run_eval(agent: str, tiers: list[str], seeds: list[int], provider: str = "template",
             out_root: str | Path = "data/runs", seeds_spec: str | None = None) -> tuple[Path, dict[str, list[EpisodeResult]]]:
    factory = make_policy_factory(agent)
    tier_label = tiers[0] if len(tiers) == 1 else "all"
    run_id = f"{agent.replace(':', '_').replace('/', '_')}-{tier_label}-{time.strftime('%Y%m%d-%H%M%S')}"
    out = Path(out_root) / run_id
    out.mkdir(parents=True, exist_ok=False)
    by_tier: dict[str, list[EpisodeResult]] = {}
    with open(out / "episodes.jsonl", "w") as fh:
        for tier in tiers:
            by_tier[tier] = []
            for seed in seeds:
                res = run_episode(make_env(tier, seed, provider), factory(seed))
                by_tier[tier].append(res)
                fh.write(json.dumps(asdict(res), sort_keys=True) + "\n")
    meta = {"run_id": run_id, "agent": agent, "model": agent.split(":", 1)[1] if ":" in agent else None,
            "provider": provider, "tier": tier_label, "tiers": tiers, "seeds_spec": seeds_spec, "seeds": seeds,
            "git_sha": git_sha(), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "summary": {t: summarize(e) for t, e in by_tier.items()}}
    (out / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    return out, by_tier


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.eval", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", default="solver")
    ap.add_argument("--tier", default="all", choices=[*TIERS, *TRACKS, "all"])
    ap.add_argument("--seeds", default="dev20", help="dev20 | judge | n:N (count) | N (count if <=1000, else one seed) | a-b | a,b,c")
    ap.add_argument("--provider", default="template")
    ap.add_argument("--out", default="data/runs")
    ap.add_argument("--reproduce", action="store_true",
                    help="judge table on the frozen judge seeds (see canary/reproduce.py)")
    ap.add_argument("--repro-seeds", type=int, default=None,
                    help="with --reproduce: seeds per tier (default all JUDGE_SEEDS; env REPRO_SEEDS / REPRO_FAST=1)")
    ap.add_argument("--results-dir", default=None,
                    help="with --reproduce: output directory (default results/latest/, gitignored)")
    ap.add_argument("--update-committed", action="store_true",
                    help="with --reproduce: overwrite the committed results/judge_table.md, "
                         "judge_episodes.jsonl and gap_chart.png (team use)")
    a = ap.parse_args(argv)
    if a.reproduce:
        from .reproduce import reproduce, results_dir_for
        try:
            out = results_dir_for(a.update_committed, a.results_dir)
        except ValueError as exc:
            print(f"canary.eval: {exc}", file=sys.stderr)
            return 2
        reproduce(a.repro_seeds, out)
        return 0
    tiers = list(TIERS) if a.tier == "all" else [a.tier]
    try:
        seeds = parse_seeds(a.seeds)
        if len(seeds) * len(tiers) > MAX_EPISODES:
            raise ValueError(f"--seeds/--tier: {len(seeds)} seeds x {len(tiers)} tiers = "
                             f"{len(seeds) * len(tiers)} episodes is over the {MAX_EPISODES} limit")
    except ValueError as exc:
        print(f"canary.eval: {exc}", file=sys.stderr)
        return 2
    try:
        out, by_tier = run_eval(a.agent, tiers, seeds, a.provider, a.out, a.seeds)
    except AgentUnavailable as exc:
        print(f"canary.eval: {exc}", file=sys.stderr)
        return 2
    print(format_table(a.agent, by_tier))
    print(f"\nwrote {out}/episodes.jsonl and meta.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
