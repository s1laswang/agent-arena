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


def load_moles(hof_path: str, top: int) -> list[tuple[str, dict, dict]]:
    moles = [("default", default_strategy_json(), {})]
    rows = [json.loads(l) for l in Path(hof_path).read_text().splitlines() if l.strip()]
    seen = set()
    for h in rows:
        if len(moles) > top:
            break
        sig = json.dumps([h.get("fitness"), h.get("solver_score"), h.get("per_investigator")], sort_keys=True)
        if sig in seen:  # behaviourally identical on the forge seeds (e.g. dead rules): skip, save budget
            continue
        seen.add(sig)
        moles.append((f"hof{h.get('rank', len(moles))}", h["strategy_json"],
                      {k: h.get(k) for k in ("fitness", "solver_score", "per_investigator")}))
    return moles


def _episode(name, strat, seed, agent, tier, client_factory):
    env = make_env(tier, seed, strat)
    sol = run_episode(env, SolverPolicy(), "solver")
    env = make_env(tier, seed, strat)
    pol = LLMPolicy(agent, client=client_factory() if client_factory else None)
    try:
        res, err = run_episode(env, pol, pol.name), None
    except Exception as e:  # noqa: BLE001
        res, err = env.result(pol.name), repr(e)
    return {"seed": seed, "agent_score": res.score, "agent_correct": res.correct, "agent_day": res.final_day,
            "solver_score": sol.score, "solver_correct": sol.correct,
            "cost_usd": float(pol.usage.get("cost_usd", 0.0) or 0.0), "error": err}


def validate(moles, agent: str, seeds, tier: str, budget: float = 25.0,
             client_factory: Callable | None = None, log=print, parallel: int = 2) -> dict:
    """Episodes run seed-major (every mole on seed 0, then seed 1, ...) so a budget stop keeps seeds paired."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock, state = threading.Lock(), {"spent": 0.0, "stopped": None}
    rows: dict[str, list] = {name: [] for name, _, _ in moles}

    def job(name, strat, seed):
        with lock:
            if state["spent"] >= budget:
                state["stopped"] = f"budget ${budget} reached"
                return
        r = _episode(name, strat, seed, agent, tier, client_factory)
        with lock:
            state["spent"] += r["cost_usd"]
            rows[name].append(r)
            log(f"{name} seed {seed}: agent={r['agent_score']:+.3f}({'ok' if r['agent_correct'] else 'x'}) "
                f"solver={r['solver_score']:+.3f}({'ok' if r['solver_correct'] else 'x'}) "
                f"cost=${r['cost_usd']:.3f} total=${state['spent']:.2f}" + (f" ERR {r['error']}" if r["error"] else ""),
                flush=True) if log is print else log(r)
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        list(ex.map(lambda a: job(*a), [(n, s, sd) for sd in seeds for n, s, _ in moles]))
    report = {"agent": agent, "tier": tier, "seeds": list(seeds), "budget": budget, "cost_usd": state["spent"],
              "stopped": state["stopped"], "moles": []}
    for name, strat, meta in moles:
        rs = sorted(rows[name], key=lambda r: r["seed"])
        if rs:
            report["moles"].append(_summ(name, strat, meta, rs))
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
    ap.add_argument("--parallel", type=int, default=2, help="concurrent episodes (rate limits)")
    a = ap.parse_args(argv)
    rep = validate(load_moles(a.hof, a.top), a.agent, parse_seeds(a.seeds), a.tier, a.budget, client_factory,
                   parallel=a.parallel)
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
