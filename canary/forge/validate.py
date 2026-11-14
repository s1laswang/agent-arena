"""Check Forge hall-of-fame moles against a real LLM investigator.

python -m canary.forge.validate --hof data/forge/<run>/hall_of_fame.jsonl --top 3 \
    --agent openai:gpt-5.5 --seeds 0-4 --tier hard [--budget 25] [--out <path.json>]

For the default mole and each of the top-k evolved moles, plays LLMPolicy (canary.agents.llm_policy, through
canary.agents.loop.run_episode) and the solver on the same seeds, printing running cost; stops before the
budget is exceeded. Report: per mole, agent score/accuracy vs solver score/accuracy and the gap.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Callable

from canary.agents.llm_policy import LLMPolicy
from canary.agents.loop import run_episode
from canary.solver.policy import SolverPolicy

from .evolve import parse_seeds
from .fitness import make_env
from .mutate import default_strategy_json


class BudgetExceeded(RuntimeError):
    pass


def load_moles(hof_path: str, top: int) -> list[tuple[str, dict, dict]]:
    moles = [("default", default_strategy_json(), {})]
    rows = [json.loads(l) for l in Path(hof_path).read_text().splitlines() if l.strip()]
    for h in rows[:top]:
        moles.append((f"hof{h.get('rank', len(moles))}", h["strategy_json"],
                      {k: h.get(k) for k in ("fitness", "solver_score", "per_investigator")}))
    return moles


def validate(moles, agent: str, seeds, tier: str, budget: float = 25.0,
             client_factory: Callable | None = None, log=print) -> dict:
    spent, report = 0.0, {"agent": agent, "tier": tier, "seeds": list(seeds), "budget": budget, "moles": []}
    try:
        for name, strat, forge_meta in moles:
            rows = []
            for seed in seeds:
                if spent >= budget:
                    raise BudgetExceeded(f"budget ${budget} reached (${spent:.2f})")
                env = make_env(tier, seed, strat)
                sol = run_episode(env, SolverPolicy(), "solver")
                env = make_env(tier, seed, strat)
                pol = LLMPolicy(agent, client=client_factory() if client_factory else None)
                try:
                    res = run_episode(env, pol, pol.name)
                    err = None
                except Exception as e:  # noqa: BLE001
                    res, err = env.result(pol.name), repr(e)
                cost = float(pol.usage.get("cost_usd", 0.0) or 0.0)
                spent += cost
                rows.append({"seed": seed, "agent_score": res.score, "agent_correct": res.correct,
                             "agent_day": res.final_day, "solver_score": sol.score, "solver_correct": sol.correct,
                             "cost_usd": cost, "error": err})
                log(f"{name} seed {seed}: agent={res.score:+.3f}({'ok' if res.correct else 'x'}) "
                    f"solver={sol.score:+.3f}({'ok' if sol.correct else 'x'}) cost=${cost:.3f} total=${spent:.2f}")
            report["moles"].append(_summ(name, strat, forge_meta, rows))
    except BudgetExceeded as e:
        log(str(e))
        report["stopped"] = str(e)
    report["cost_usd"] = spent
    return report


def _summ(name, strat, forge_meta, rows):
    a, s = [r["agent_score"] for r in rows], [r["solver_score"] for r in rows]
    return {"mole": name, "strategy_json": strat, "forge": forge_meta, "episodes": rows,
            "agent_score": mean(a), "agent_acc": mean(r["agent_correct"] for r in rows),
            "solver_score": mean(s), "solver_acc": mean(r["solver_correct"] for r in rows),
            "gap": mean(s) - mean(a)}


def main(argv=None, client_factory=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hof", required=True)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--agent", default="openai:gpt-5.5")
    ap.add_argument("--seeds", default="0-4")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--budget", type=float, default=25.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    rep = validate(load_moles(a.hof, a.top), a.agent, parse_seeds(a.seeds), a.tier, a.budget, client_factory)
    out = Path(a.out) if a.out else Path(a.hof).with_name(f"validate_{a.agent.replace(':', '_')}_{a.tier}.json")
    out.write_text(json.dumps(rep, indent=1))
    print(f"{'mole':8} {'agent':>7} {'acc':>5} {'solver':>7} {'acc':>5} {'gap':>6}")
    for m in rep["moles"]:
        print(f"{m['mole']:8} {m['agent_score']:+7.3f} {m['agent_acc']:5.2f} {m['solver_score']:+7.3f} "
              f"{m['solver_acc']:5.2f} {m['gap']:+6.3f}")
    print(f"cost ${rep['cost_usd']:.2f}; wrote {out}")
    return rep


if __name__ == "__main__":
    main()
    sys.exit(0)
