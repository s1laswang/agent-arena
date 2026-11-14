"""Reference + baseline runs in the shared data/runs layout (so the gap table has a denominator).

    python -m canary.analysis.reference --tier medium --seeds 0-9 [--agents solver,do_nothing,...]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import time
from pathlib import Path

from canary import baselines
from canary.baselines import play
from canary.env import Env
from canary.solver.policy import SolverPolicy

AGENTS = {
    "solver": lambda s: SolverPolicy(),
    "do_nothing": lambda s: baselines.DoNothing(seed=s),
    "stop_early": lambda s: baselines.StopEarly(seed=s),
    "random": lambda s: baselines.RandomPolicy(seed=s),
    "restrict_all": lambda s: baselines.RestrictAll(seed=s),
    "heuristic": lambda s: baselines.Heuristic() if callable(getattr(baselines, "Heuristic", None)) else baselines.ObviousHeuristic(seed=s),
}


def parse_seeds(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return out


def run(agent: str, tier: str, seeds: list[int], root: str = "data/runs") -> Path:
    run_id = f"{agent}-{tier}-{time.strftime('%Y%m%d-%H%M')}"
    d = Path(root) / run_id
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "episodes.jsonl", "w") as f:
        for s in seeds:
            env = Env(tier, s)
            play(env, AGENTS[agent](s))
            f.write(json.dumps(dataclasses.asdict(env.result(agent))) + "\n")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (d / "meta.json").write_text(json.dumps({"agent": agent, "tier": tier, "seeds": seeds, "git_sha": sha}))
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--agents", default=",".join(AGENTS))
    ap.add_argument("--root", default="data/runs")
    a = ap.parse_args(argv)
    for ag in a.agents.split(","):
        print(run(ag, a.tier, parse_seeds(a.seeds), a.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
