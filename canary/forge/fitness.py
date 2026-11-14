"""Fitness of a mole strategy (CONTRACT §7).

fitness = mean over seeds x investigators of (solver score - investigator score), FEASIBLE only if
  solver score >= 0.5 x solver score on DEFAULT_STRATEGY (cached) AND solver accuracy >= 0.85; else -inf.

Episodes run through a pluggable `runner(tier, seed, strategy_json, agent_name, factory) -> (score, correct)`:
  * "real": canary.env via `make_env` (the single ENV adapter) + Policy loop;
  * "fake": deterministic test double (scores may be negative in v0.3: wrong accusation = -1) (no Env needed) used by tests and `evolve --fake`.
Factories and runners must be top-level picklable callables (multiprocessing).
"""
from __future__ import annotations

import hashlib
import math
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable

from .mutate import FRAME_SELECTORS, canonical, default_strategy_json

FEASIBLE_SOLVER_RATIO = 0.5
FEASIBLE_SOLVER_ACC = 0.85
SOLVER_NAME = "solver"


# ---------------------------------------------------------------- ENV adapter (the only ENV touch point)
def make_env(tier: str, seed: int, strategy_json: dict | None):
    """Build an Env whose mole follows `strategy_json`, via ENV's hook Env(tier, seed, mole_strategy=<MoleStrategy>).
    Requires canary.mole.dsl (MoleStrategy.from_json); without it the Env would silently use the default mole,
    so we refuse instead of producing meaningless fitness."""
    from canary.env import Env
    strat = None
    if strategy_json is not None:
        try:
            from canary.mole.dsl import MoleStrategy  # type: ignore
        except ImportError as e:
            raise RuntimeError("canary.mole.dsl not merged yet: real forge runs need MoleStrategy.from_json "
                               "(use --fake meanwhile)") from e
        strat = MoleStrategy.from_json(strategy_json)
    return Env(tier=tier, seed=seed, mole_strategy=strat)


def real_runner(tier: str, seed: int, strategy_json: dict, agent: str, factory: Callable) -> tuple[float, bool]:
    env = make_env(tier, seed, strategy_json)
    policy = factory(seed)
    policy.reset(env.tools_spec(), env.instruction())
    while not env.done:
        tool, args = policy.act(env.history)
        env.call(tool, args)
    res = env.result(getattr(policy, "name", agent))
    return float(env.score()), bool(res.correct)


# ---------------------------------------------------------------- fake double
def _u(*parts) -> float:
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def fake_runner(tier: str, seed: int, strategy_json: dict, agent: str, factory: Callable | None = None
                ) -> tuple[float, bool]:
    """Deterministic stand-in. Solver fails if the strategy never leaks; heuristics are hurt by framing,
    low-recipient leaks and rule complexity."""
    s = strategy_json
    actions = [r["then"] for r in s.get("rules", [])] + [s["default"]]
    leaks = [a.get("leak") for a in actions if a.get("leak") not in (None, "none")]
    frames = {a.get("frame") for a in actions} & (set(FRAME_SELECTORS) - {"none"})
    n_rules = len(s.get("rules", []))
    key = canonical(s)
    noise = _u(key, tier, seed, agent) - 0.5
    if agent == SOLVER_NAME:
        if not leaks:
            return 0.0, False
        correct = _u(key, seed, "acc") > 0.03 * max(0, n_rules - 8)
        return (max(0.1, 0.8 - 0.01 * n_rules + 0.1 * noise) if correct else -1.0), correct
    base = {"hinted_heuristic": 0.65}.get(agent, 0.55)
    sc = base - 0.08 * len(frames) - 0.05 * sum(l in ("fewest_recipients", "oldest") for l in leaks) \
        - 0.02 * min(n_rules, 6) + 0.2 * noise
    if not leaks:
        return 0.0, False
    sc = min(1.0, sc)
    if sc < 0.1:  # v0.3: a wrong accusation scores -1
        return -1.0, False
    return sc, True


# ---------------------------------------------------------------- evaluation
def _seed_task(args) -> dict[str, tuple[float, bool]]:
    runner, tier, seed, strategy_json, agents = args
    return {name: runner(tier, seed, strategy_json, name, fac) for name, fac in agents}


def _run(strategy_json, agents: list[tuple[str, Any]], runner, seeds, tier, workers):
    tasks = [(runner, tier, s, strategy_json, agents) for s in seeds]
    if workers and workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as ex:
            return list(ex.map(_seed_task, tasks))
    return [_seed_task(t) for t in tasks]


_BASELINE_CACHE: dict[tuple, dict] = {}


def solver_baseline(solver_factory, seeds, tier, runner=real_runner, workers=1) -> dict:
    key = (getattr(runner, "__name__", str(runner)), tier, tuple(seeds),
           getattr(solver_factory, "__name__", repr(solver_factory)))
    if key not in _BASELINE_CACHE:
        rows = _run(default_strategy_json(), [(SOLVER_NAME, solver_factory)], runner, seeds, tier, workers)
        sc = [r[SOLVER_NAME][0] for r in rows]
        _BASELINE_CACHE[key] = {"score": sum(sc) / len(sc),
                                "acc": sum(r[SOLVER_NAME][1] for r in rows) / len(rows)}
    return _BASELINE_CACHE[key]


def evaluate(strategy_json: dict, investigators: dict[str, Callable], solver_factory: Callable,
             seeds, tier: str, runner: Callable = real_runner, workers: int = 1,
             baseline: dict | None = None) -> dict:
    seeds = list(seeds)
    if baseline is None:
        baseline = solver_baseline(solver_factory, seeds, tier, runner, workers)
    agents = [(SOLVER_NAME, solver_factory)] + sorted(investigators.items())
    rows = _run(strategy_json, agents, runner, seeds, tier, workers)
    solver = [r[SOLVER_NAME][0] for r in rows]
    solver_score = sum(solver) / len(solver)
    solver_acc = sum(r[SOLVER_NAME][1] for r in rows) / len(rows)
    per_inv, regrets = {}, []
    for name in sorted(investigators):
        sc = [r[name][0] for r in rows]
        per_inv[name] = {"score": sum(sc) / len(sc), "acc": sum(r[name][1] for r in rows) / len(rows),
                         "regret": sum(a - b for a, b in zip(solver, sc)) / len(sc)}
        regrets += [a - b for a, b in zip(solver, sc)]
    feasible = (solver_score >= FEASIBLE_SOLVER_RATIO * baseline["score"]) and solver_acc >= FEASIBLE_SOLVER_ACC
    mean_regret = sum(regrets) / len(regrets) if regrets else 0.0
    return {"fitness": mean_regret if feasible else -math.inf, "regret": mean_regret,
            "solver_score": solver_score, "solver_acc": solver_acc, "per_investigator": per_inv,
            "feasible": feasible, "baseline_solver_score": baseline["score"],
            "beaten": [n for n, v in per_inv.items() if v["regret"] > 0]}


# ---------------------------------------------------------------- default investigator / solver factories
def _find(module: str, names: list[str]):
    import importlib
    try:
        m = importlib.import_module(module)
    except ImportError:
        return None
    for n in names:
        if hasattr(m, n):
            return getattr(m, n)
    return None


def _instantiate(cls, seed):
    try:
        return cls(seed=seed)
    except TypeError:
        return cls()


class ClassFactory:
    """Picklable factory: seed -> instance of module:attr (tries cls(seed=seed), then cls())."""
    def __init__(self, module: str, attr: str, **kw):
        self.module, self.attr, self.kw = module, attr, kw
        self.__name__ = f"{module}:{attr}"

    def __call__(self, seed: int):
        import importlib
        cls = getattr(importlib.import_module(self.module), self.attr)
        if self.kw:
            return cls(**self.kw)
        return _instantiate(cls, seed)


def default_investigators() -> dict[str, Callable]:
    """heuristic = canary.baselines.Heuristic (bisection, gambles at deadline; stronger than ObviousHeuristic);
    hinted_heuristic = canary.forge.investigators.HintedHeuristic (evidence-only, never gambles)."""
    inv = {}
    cls = _find("canary.baselines", ["Heuristic", "HeuristicPolicy", "ObviousHeuristic"])
    if cls is not None:
        inv["heuristic"] = ClassFactory("canary.baselines", cls.__name__)
    inv["hinted_heuristic"] = ClassFactory("canary.forge.investigators", "HintedHeuristic")
    return inv


def default_solver_factory() -> Callable:
    if _find("canary.solver.policy", ["SolverPolicy"]) is None:
        raise RuntimeError("canary.solver.policy.SolverPolicy not available")
    return ClassFactory("canary.solver.policy", "SolverPolicy")  # reads tier params from instruction


def fake_factory(seed: int):  # placeholder factory for the fake runner
    return None
