"""Re-validate a Mole Forge hall of fame on the current tiers (CONTRACT §7 feasibility).

  python -m fr8.analysis.forge_validate <run_dir> --tier hard --seeds 2000:2200 --workers 2 \
      --out fr8/analysis/out/forge_v12_validation

For every hall-of-fame strategy (plus the default mole) on FRESH seeds: solver score/accuracy/none-rate,
heuristic score/accuracy, regret = solver - heuristic. Feasible iff solver score >= 0.5 x solver score on
the default mole AND solver accuracy >= 0.85 (constants from canary.forge.fitness). Reuses
canary.forge.fitness.make_env + default factories; this module only adds the none-rate bookkeeping.
Judge-set candidates: feasible AND regret CI lower bound > 0.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ._common import ci_half, mean, write_rows


class _Recorder:
    """Proxy around a MoleStrategy that logs every decide() output (behavioural fingerprint)."""
    def __init__(self, strat, log):
        self._s, self._log = strat, log

    def decide(self, *a, **k):
        d = self._s.decide(*a, **k)
        self._log.append(json.dumps(d, sort_keys=True, default=str))
        return d

    def __getattr__(self, n):
        return getattr(self._s, n)


def _episode(tier, seed, strat, factory, name, log=None):
    from canary.env import Env
    from canary.mole.dsl import MoleStrategy
    ms = MoleStrategy.from_json(strat)
    env = Env(tier, seed, mole_strategy=_Recorder(ms, log) if log is not None else ms)
    pol = factory(seed)
    pol.reset(env.tools_spec(), env.instruction())
    while not env.done:
        tool, args = pol.act(env.history)
        env.call(tool, args)
    r = env.result(name)
    return float(env.score()), bool(r.correct), r.accused in (None, "")


def eval_strategy(args) -> dict:
    sid, strat, tier, seeds = args
    from canary.forge.fitness import default_investigators, default_solver_factory
    sf, invs = default_solver_factory(), default_investigators()
    log: list[str] = []
    S, I = [], {n: [] for n in invs}
    for s in seeds:
        log.append(f"#S{s}"); S.append(_episode(tier, s, strat, sf, "solver", log))
        for n, fac in sorted(invs.items()):
            log.append(f"#{n}{s}"); I[n].append(_episode(tier, s, strat, fac, n, log))
    import hashlib
    from canary.forge.mutate import canonical
    row = {"strategy": sid, "n": len(seeds),
           "solver_score": mean([x[0] for x in S]), "solver_ci": ci_half([x[0] for x in S]),
           "solver_acc": mean([float(x[1]) for x in S]), "solver_none": mean([float(x[2]) for x in S])}
    regs = {}
    for n in sorted(invs):
        reg = [a[0] - b[0] for a, b in zip(S, I[n])]
        regs[n] = reg
        short = "heur" if n == "heuristic" else n
        row[f"{short}_score"] = mean([x[0] for x in I[n]])
        row[f"{short}_acc"] = mean([float(x[1]) for x in I[n]])
        row[f"regret[{n}]"] = mean(reg)
        row[f"regret_ci[{n}]"] = ci_half(reg)
    strongest = min(regs, key=lambda n: mean(regs[n]))   # canary.forge.fitness "min" mode
    row["strongest"] = strongest
    row["regret"] = mean(regs[strongest])
    row["regret_ci"] = ci_half(regs[strongest])
    row["canon"] = hashlib.sha256(canonical(strat).encode()).hexdigest()[:10]
    row["behaviour"] = hashlib.sha256("\n".join(log).encode()).hexdigest()[:10]
    return row


def validate(hof: list[dict], tier: str, seeds: list[int], workers: int = 2,
             min_acc: float | None = None) -> list[dict]:
    from canary.forge.fitness import FEASIBLE_SOLVER_ACC, FEASIBLE_SOLVER_RATIO
    try:
        from canary.forge.fitness import tier_defaults
        run_acc = tier_defaults(tier)["min_solver_acc"] if min_acc is None else min_acc
    except ImportError:
        run_acc = FEASIBLE_SOLVER_ACC if min_acc is None else min_acc
    from canary.forge.mutate import default_strategy_json
    tasks = [("default", default_strategy_json(), tier, seeds)]
    tasks += [(f"hof#{h.get('rank', i + 1)}", h["strategy_json"], tier, seeds) for i, h in enumerate(hof)]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            rows = list(ex.map(eval_strategy, tasks))
    else:
        rows = [eval_strategy(t) for t in tasks]
    base = rows[0]["solver_score"]
    for r, h in zip(rows, [None] + hof):
        r["ratio_vs_default"] = r["solver_score"] / base if base else float("nan")
        ratio_ok = r["solver_score"] >= FEASIBLE_SOLVER_RATIO * base
        r["feasible"] = ratio_ok and r["solver_acc"] >= run_acc
        r["strict_s7"] = ratio_ok and r["solver_acc"] >= FEASIBLE_SOLVER_ACC
        r["judge_candidate"] = r["strategy"] != "default" and r["feasible"] and r["regret"] - r["regret_ci"] > 0
        r["v1_fitness"] = h.get("fitness") if h else None
    groups: dict[str, list[str]] = {}
    for r in rows:
        groups.setdefault(r["behaviour"], []).append(r["strategy"])
    for r in rows:
        g = groups[r["behaviour"]]
        r["behaviour_group"] = g[0]
        r["distinct"] = r["strategy"] == g[0]
        r["n_canon_in_group"] = len({x["canon"] for x in rows if x["behaviour"] == r["behaviour"]})
    return rows


def to_markdown(rows, run, tier, seeds, tier_params: dict, code_sha="?", tiers_version="?", hof_gen="?") -> str:
    f = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)
    cols = ["strategy", "n", "solver_score", "solver_ci", "solver_acc", "solver_none",
            *[k for k in rows[0] if k.endswith(("_score", "_acc")) and not k.startswith("solver")],
            "regret", "regret_ci", "ratio_vs_default", "feasible", "strict_s7", "judge_candidate", "v1_fitness",
            "canon", "behaviour", "behaviour_group"]
    cand = [r["strategy"] for r in rows if r["judge_candidate"] and r["distinct"]]
    inv_cols = [k for k in rows[0] if k.endswith(("_score", "_acc")) and not k.startswith("solver")] + \
        [k for k in rows[0] if k.startswith("regret[") or k.startswith("regret_ci[")]
    dcols = ["behaviour_group", "members", "n_canon_in_group", "solver_score", "solver_ci", "solver_acc",
             "solver_none", *inv_cols, "strongest", "regret", "regret_ci", "ratio_vs_default", "feasible",
             "strict_s7", "judge_candidate"]
    out = [f"# Forge hall-of-fame re-validation", "", f"- code sha: {code_sha}; TIERS_VERSION {tiers_version}; HoF generation {hof_gen}",
           f"- run: `{run}`", f"- tier: {tier}, fresh seeds {seeds[0]}–{seeds[-1]} (n={len(seeds)})",
           f"- tier params: " + ", ".join(f"{k}={tier_params[k]}" for k in
                                          ("fingerprint_accuracy", "framing_rate", "n_employees", "delay_choices")
                                          if k in tier_params),
           "- feasible: solver score ≥ 0.5 × default-mole score AND solver acc ≥ tier min (canary.forge.fitness.tier_defaults; hard 0.75); "
           "strict_s7: same with acc ≥ 0.85; regret = vs the strongest investigator (min over investigators); "
           "judge candidate: feasible AND regret 95% CI lower bound > 0",
           f"- feasible: {sum(r['feasible'] for r in rows if r['strategy'] != 'default')}/{len(rows) - 1}; "
           f"distinct judge-set candidates (deduped by behaviour): {', '.join(cand) or 'none'}", "",
           "## Distinct behaviours (identical per-seed mole decisions on all eval episodes = one group)", "",
           "| " + " | ".join(dcols) + " |", "|" + "---|" * len(dcols)]
    for r in rows:
        if r["distinct"]:
            mem = [x["strategy"] for x in rows if x["behaviour"] == r["behaviour"]]
            out.append("| " + " | ".join(f(r.get(c)) if c != "members" else ", ".join(mem) for c in dcols) + " |")
    out += ["", "## All strategies", "",
           "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(f(r.get(c)) for c in cols) + " |" for r in rows]
    return "\n".join(out) + "\n"


HOF_KEYS = ["rank", "fitness", "solver_score", "solver_acc", "per_investigator", "strategy_json"]  # evolve._write_hof


def _per_inv(r: dict) -> dict:
    names = [k[7:-1] for k in r if k.startswith("regret[")]
    if not names:  # legacy single-investigator rows
        return {"heuristic": {"score": float(r["heur_score"]), "acc": float(r["heur_acc"]), "regret": float(r["regret"])}}
    out = {}
    for n in names:
        short = "heur" if n == "heuristic" else n
        out[n] = {"score": float(r[f"{short}_score"]), "acc": float(r[f"{short}_acc"]),
                  "regret": float(r[f"regret[{n}]"])}
    return out


def survivors(rows: list[dict], hof: list[dict]) -> list[dict]:
    """Feasible, behaviour-deduped (best regret per group), re-ranked by v1.2 regret; evolve's HoF line format."""
    by_sid = {f"hof#{h.get('rank', i + 1)}": h for i, h in enumerate(hof)}
    best: dict[str, dict] = {}
    for r in rows:
        if r["strategy"] == "default" or str(r["feasible"]) not in ("True", "1", "true"):
            continue
        b = best.get(r["behaviour"])
        if b is None or float(r["regret"]) > float(b["regret"]):
            best[r["behaviour"]] = r
    keep = sorted(best.values(), key=lambda r: -float(r["regret"]))
    return [{"rank": i + 1, "fitness": float(r["regret"]), "solver_score": float(r["solver_score"]),
             "solver_acc": float(r["solver_acc"]),
             "per_investigator": _per_inv(r),
             "strategy_json": by_sid[r["strategy"]]["strategy_json"]} for i, r in enumerate(keep)]


def write_survivors(rows, hof, path: str, meta: dict) -> list[dict]:
    out = survivors(rows, hof)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(h) + "\n" for h in out))
    meta = {**meta, "n_survivors": len(out),
            "source_strategies": [r["strategy"] for r in rows if r["strategy"] != "default"]}
    Path(str(path).removesuffix(".jsonl") + ".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="forge HoF re-validation")
    ap.add_argument("run"); ap.add_argument("--tier", default="hard"); ap.add_argument("--seeds", default="2000:2200")
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--hof-out", help="write survivors (evolve HoF format) here, e.g. data/forge/hall_of_fame_v1.2.jsonl")
    ap.add_argument("--from-csv", help="skip evaluation; reuse rows from a previous --out CSV")
    a = ap.parse_args(argv)
    from canary.rules import TIERS
    lo, hi = (int(x) for x in a.seeds.split(":"))
    seeds = list(range(lo, hi))
    hof = [json.loads(l) for l in (Path(a.run) / "hall_of_fame.jsonl").read_text().splitlines() if l.strip()]
    hof = hof[: a.limit] if a.limit else hof
    if a.from_csv:
        import csv
        with open(a.from_csv, newline="") as fh:
            rows = list(csv.DictReader(fh))
    else:
        rows = validate(hof, a.tier, seeds, a.workers)
        write_rows(a.out + ".csv", rows)
    import subprocess
    from canary.rules import TIERS_VERSION
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "canary"], capture_output=True, text=True).stdout.strip()
    logp = Path(a.run) / "log.jsonl"
    gen = json.loads(logp.read_text().splitlines()[-1])["gen"] if logp.exists() else "?"
    if a.hof_out:
        write_survivors(rows, hof, a.hof_out, {
            "code_sha": sha + ("+dirty" if dirty else ""), "tiers_version": TIERS_VERSION, "tier": a.tier,
            "seeds": f"{lo}:{hi}", "hof_source": str(Path(a.run) / "hall_of_fame.jsonl"), "hof_generation": gen,
            "command": "python -m fr8.analysis.forge_validate " + " ".join(argv if argv is not None else __import__("sys").argv[1:]),
            "feasibility": "solver_score >= 0.5 x default-mole solver score AND solver_acc >= tier min (canary.forge.fitness.tier_defaults); fitness = regret vs strongest investigator; deduped by behaviour"})
    if a.from_csv:
        return
    md = to_markdown(rows, a.run, a.tier, seeds, dataclasses.asdict(TIERS[a.tier]),
                     sha + ("+dirty" if dirty else ""), TIERS_VERSION, gen)
    Path(a.out + ".md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
