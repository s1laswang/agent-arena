"""`make clash`: the LLM (Gemini) mole vs investigators, plus one PAIRED designer round.

    python -m canary.agents.clash [--llm stub|gemini:<m>] [--investigator heuristic|solver|<policy spec>]
                                  [--tier medium] [--seeds 0 1 2] [--no-designer]

Arena mode only (never the judge path). Runs end-to-end with --llm stub. If the real Env is not
on this branch yet, exits with code 2 and a clear message. `run_arena` takes factories so tests
can drive it with fakes.
"""
from __future__ import annotations

import argparse
import importlib
import statistics
import sys
from typing import Any, Callable

from ._common import resolve_client
from .designer import design_round
from .mole_arena import LLMMole, attach_mole

_POLICY_CANDIDATES = {
    "solver": [("canary.solver.policy", "SolverPolicy"), ("canary.solver", "SolverPolicy"),
               ("canary.baselines", "SolverPolicy")],
    "heuristic": [("canary.baselines", "ObviousHeuristic"), ("canary.baselines", "HeuristicPolicy"), ("canary.baselines.heuristic", "HeuristicPolicy"),
                  ("canary.agents.heuristic", "HeuristicPolicy"), ("canary.solver.heuristic", "HeuristicPolicy")],
}


def resolve_policy(spec: str) -> Callable[[], Any]:
    for mod, cls in _POLICY_CANDIDATES.get(spec, []):
        try:
            return getattr(importlib.import_module(mod), cls)
        except (ImportError, AttributeError):
            continue
    if spec in _POLICY_CANDIDATES:
        raise RuntimeError(f"investigator {spec!r} not found on this branch (looked in "
                           f"{[m for m, _ in _POLICY_CANDIDATES[spec]]}); merge origin/justSilas.")
    try:
        from canary.agents.llm_policy import LLMPolicy  # type: ignore
    except ImportError as e:
        raise RuntimeError(f"LLM investigator {spec!r} needs canary.agents.llm_policy ({e})") from e
    return lambda: LLMPolicy(spec)


def make_real_env_factory() -> Callable[[str, int], Any]:
    from canary.env import Env
    try:
        Env(tier="easy", seed=0)
    except NotImplementedError as e:
        raise RuntimeError("canary.env.Env is not implemented on this branch yet (ENV lands ~02:45; "
                           "git merge origin/justSilas).") from e
    return lambda tier, seed, mole_strategy=None: Env(tier=tier, seed=seed, mole_strategy=mole_strategy)


def play(env, policy, agent_name: str, max_steps: int = 400):
    policy.reset(env.tools_spec(), env.instruction())
    for _ in range(max_steps):
        if env.done:
            break
        tool, args = policy.act(env.history)
        env.call(tool, args)
    return env.result(agent_name)


def run_arena(make_env: Callable[[str, int], Any], make_policy: Callable[[], Any], mole_factory,
              seeds: list[int], tier: str = "medium") -> list[dict]:
    rows = []
    for seed in seeds:
        mole = mole_factory()
        try:
            env = make_env(tier, seed, mole_strategy=mole)   # Env(tier, seed, mole_strategy=...) hook
            hooked = mole is not None
        except TypeError:
            env = make_env(tier, seed)
            hooked = attach_mole(env, mole) if mole is not None else False
        policy = make_policy()
        res = play(env, policy, getattr(policy, "name", "investigator"))
        rows.append({"seed": seed, "mole": getattr(mole, "name", "default") if hooked else "default",
                     "investigator": getattr(policy, "name", "?"), "score": res.score,
                     "correct": res.correct, "day": res.final_day, "end": res.end_reason,
                     "mole_llm_errors": sum(1 for x in getattr(mole, "log", []) if x.get("error"))})
    return rows


def table(rows: list[dict]) -> str:
    out = [f"{'seed':>6} {'mole':<10} {'investigator':<16} {'score':>6} {'correct':>7} {'day':>4} end"]
    for r in rows:
        out.append(f"{r['seed']:>6} {r['mole']:<10} {r['investigator'][:16]:<16} {r['score']:>+6.3f} "
                   f"{str(r['correct']):>7} {r['day']:>4} {r['end']}")
    if rows:
        sc = [r["score"] for r in rows]
        out.append(f"mean score {statistics.mean(sc):+.3f} (wrong accusation = -1.0 under contract v0.3)  "
                   f"min {min(sc):+.3f}  accuracy {sum(r['correct'] for r in rows)}/{len(rows)}")
    return "\n".join(out)


def designer_table(rep: dict) -> str:
    out = [f"designer round tier={rep['tier']} keep iff solver>={rep['X']} and agent<={rep['Y']}  "
           f"(llm_ok={rep['meta']['llm_ok']}, llm_valid={rep['meta']['n_llm_valid']})"]
    for r in rep["rows"]:
        out.append(f"  {r['name'][:24]:<24} solver={r['solver']:+.3f} agent={r['agent']:+.3f} regret={r['regret']:+.3f} -> {r['why']}")
    return "\n".join(out)


def _mean_score_eval(make_env, make_policy, seeds, tier):
    def ev(candidate: dict) -> float:
        try:
            from canary.mole.dsl import MoleStrategy  # type: ignore
            strat = lambda: MoleStrategy.from_json(candidate["mole_strategy"])  # noqa: E731
        except ImportError:
            strat = lambda: None  # noqa: E731
        rows = run_arena(make_env, make_policy, strat, seeds, tier)
        return statistics.mean(r["score"] for r in rows)
    return ev


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="canary.agents.clash")
    ap.add_argument("--llm", default="stub")
    ap.add_argument("--investigator", default="heuristic")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", type=int, nargs="*", default=[0, 1, 2])
    ap.add_argument("--no-designer", action="store_true")
    ap.add_argument("--X", type=float, default=0.5)
    ap.add_argument("--Y", type=float, default=0.3)
    a = ap.parse_args(argv)
    try:
        client = resolve_client(a.llm)
        make_env = make_real_env_factory()
        make_inv = resolve_policy(a.investigator)
    except RuntimeError as e:
        print(f"clash: cannot run yet: {e}", file=sys.stderr)
        return 2
    try:
        make_solver = resolve_policy("solver")
    except RuntimeError as e:
        make_solver = resolve_policy("heuristic")
        print(f"clash: no solver yet ({e}); designer uses the heuristic as a PROXY solver", file=sys.stderr)
    print(f"== arena: LLM mole ({a.llm}) vs {a.investigator}, tier={a.tier}, seeds={a.seeds}")
    print(table(run_arena(make_env, make_inv, lambda: LLMMole(client), a.seeds, a.tier)))
    print(f"\n== baseline: default mole vs {a.investigator}")
    print(table(run_arena(make_env, make_inv, lambda: None, a.seeds, a.tier)))
    if not a.no_designer and make_solver is not None:
        rep = design_round(client, _mean_score_eval(make_env, make_solver, a.seeds, a.tier),
                           _mean_score_eval(make_env, make_inv, a.seeds, a.tier), a.X, a.Y, tier=a.tier, n=3)
        print("\n" + designer_table(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
