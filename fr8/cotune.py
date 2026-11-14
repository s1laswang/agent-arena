"""Tiers v1.2 co-tune: solver behaviour weight x tier params (CEO objective). <=3 processes.

  uv run --python 3.12 --extra dev python fr8/cotune.py [--seeds 200] [--procs 3] [--out data/fr8/cotune]
Behaviour weight: SolverPolicy(behaviour_weight=w) (3c46a20+; older code fell back to
behaviour_temper=w) (the existing multiplier on behavioural log-likelihoods, belief.posterior).
The column `bw_kwarg` records which one was used. Non-solver agents ignore it (run once per cell anyway, same seeds).
Outputs parts/<cell>.csv (one row per agent x seed), summary.csv (per cell x agent), triples.csv, top.json.
"""
import argparse, csv, dataclasses, inspect, itertools, json, math, os, statistics as st, sys, time
from multiprocessing import Pool
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import subprocess
SHA = subprocess.run(["git", "log", "-1", "--format=%h", "--", "canary/solver"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
BWS = [0.6, 0.7, 0.8, 0.9, 1.0]
AGENTS = ["solver", "heuristic", "logs_only", "stop_early", "random"]


def tier_cells(hard_n=False):
    out = [("easy", {})]
    out += [("medium", {"fingerprint_accuracy": f}) for f in (1.0, 0.9)]
    hn = [{}] if not hard_n else [{"n_employees": 25}, {"n_employees": 30}]
    out += [("hard", {"fingerprint_accuracy": f, "framing_rate": fr, **n})
            for f, fr, n in itertools.product((1.0, 0.9, 0.85, 0.8), (2.0, 2.5, 3.0), hn)]
    return out


def cells(hard_n=False, fp=None):
    """fp='1' -> only fingerprint_accuracy==1.0 cells; fp='lt1' -> only < 1.0; None -> all."""
    keep = lambda p: fp is None or (p.get("fingerprint_accuracy", 1.0) == 1.0) == (fp == "1")
    return [(bw, t, p) for bw in BWS for t, p in tier_cells(hard_n) if keep(p)]


def cell_id(bw, tier, p):
    return f"bw{bw}_{tier}" + "".join(f"_{k[:4]}{v}" for k, v in sorted(p.items()))


def work(args):
    bw, tier, params, seeds, outdir = args
    path = Path(outdir) / "parts" / f"{cell_id(bw, tier, params)}.csv"
    if path.exists():
        return path.name, 0.0
    from canary import rules
    from canary.env import Env
    from canary.solver.policy import SolverPolicy
    from canary.baselines import BASELINES, CALIBRATION_POLICIES
    from fr8.j1_grid import run
    pols = {**BASELINES, **CALIBRATION_POLICIES}
    rules.TIERS[tier] = dataclasses.replace(rules.TIERS[tier], **params)
    kw = "behaviour_weight" if "behaviour_weight" in inspect.signature(SolverPolicy).parameters else "behaviour_temper"
    t0, rows = time.time(), []
    for agent in AGENTS:
        for s in seeds:
            pol = SolverPolicy(**{kw: bw}) if agent == "solver" else pols[agent](seed=s)
            r = run(Env(tier=tier, seed=s), pol, agent)
            rows.append({"cell": cell_id(bw, tier, params), "bw": bw, "bw_kwarg": kw, "tier": tier,
                         "n_employees": rules.TIERS[tier].n_employees,
                         "fingerprint_accuracy": rules.TIERS[tier].fingerprint_accuracy,
                         "framing_rate": rules.TIERS[tier].framing_rate, "solver_sha": SHA, "agent": agent, "seed": s,
                         "score": r.score, "correct": int(r.correct), "none": int(r.accused is None),
                         "wrong": int(r.accused is not None and not r.correct), "final_day": r.final_day})
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, rows[0].keys()); w.writeheader(); w.writerows(rows)
    tmp.rename(path)
    return path.name, time.time() - t0


def ci(x):
    return 1.96 * st.stdev(x) / math.sqrt(len(x)) if len(x) > 1 else float("nan")


def analyse(outdir):
    out = Path(outdir); summ = {}; raw = {}
    for p in sorted((out / "parts").glob("*.csv")):
        rows = list(csv.DictReader(open(p)))
        c = rows[0]["cell"]; raw[c] = rows
        for a in AGENTS:
            g = [r for r in rows if r["agent"] == a]
            sc = [float(r["score"]) for r in g]
            summ[(c, a)] = {k: rows[0][k] for k in ("cell", "bw", "bw_kwarg", "tier", "n_employees", "fingerprint_accuracy", "framing_rate")} | {
                "agent": a, "n": len(g), "mean": round(st.mean(sc), 4), "ci95": round(ci(sc), 4),
                "acc": round(st.mean(int(r["correct"]) for r in g), 4), "none": round(st.mean(int(r["none"]) for r in g), 4),
                "wrong": round(st.mean(int(r["wrong"]) for r in g), 4)}
    with open(out / "summary.csv", "w", newline="") as fh:
        v = list(summ.values()); w = csv.DictWriter(fh, v[0].keys()); w.writeheader(); w.writerows(v)

    def stats(c):
        n = int(summ[(c, "solver")]["n_employees"])
        s = {r["seed"]: float(r["score"]) for r in raw[c] if r["agent"] == "solver"}
        h = {r["seed"]: float(r["score"]) for r in raw[c] if r["agent"] == "heuristic"}
        d = [s[k] - h[k] for k in s]
        so, he, lo = summ[(c, "solver")], summ[(c, "heuristic")], summ[(c, "logs_only")]
        return {"cell": c, "n": so["n"], "fp": float(so["fingerprint_accuracy"]), "framing": float(so["framing_rate"]),
                "N": n, "solver_mean": so["mean"], "solver_ci": so["ci95"], "solver_acc": so["acc"],
                "solver_none": so["none"], "solver_wrong": so["wrong"], "heur_mean": he["mean"], "heur_acc": he["acc"],
                "gap": round(st.mean(d), 4), "gap_ci": round(ci(d), 4), "logs_only_acc": lo["acc"],
                "logs_ok": lo["acc"] <= 2 / n, "stop_early_mean": summ[(c, "stop_early")]["mean"],
                "random_mean": summ[(c, "random")]["mean"]}
    trip = []
    for bw in sorted({v["bw"] for v in summ.values()}):
        by = {t: [c for (c, a), v in summ.items() if a == "solver" and v["bw"] == bw and v["tier"] == t] for t in ("easy", "medium", "hard")}
        for e, m, h in itertools.product(by["easy"], by["medium"], by["hard"]):
            E, M, H = stats(e), stats(m), stats(h)
            viol = []
            if not (E["solver_mean"] > M["solver_mean"] > H["solver_mean"]): viol.append("monotone")
            for nm, X in (("medium", M), ("hard", H)):
                if X["solver_acc"] < 0.85: viol.append(f"{nm}_acc")
                if X["solver_none"] > 0.12: viol.append(f"{nm}_none")
                if not X["logs_ok"]: viol.append(f"{nm}_logs_only")
                if X["gap"] - X["gap_ci"] <= 0: viol.append(f"{nm}_gap")
            trip.append({"bw": bw, "feasible": not viol, "violations": ";".join(viol),
                         **{f"{t}_{k}": v for t, X in (("easy", E), ("medium", M), ("hard", H)) for k, v in X.items()}})
    trip.sort(key=lambda r: (not r["feasible"], len(r["violations"].split(";")) if r["violations"] else 0,
                             r["hard_fp"], -r["hard_gap"]))
    with open(out / "triples.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, trip[0].keys()); w.writeheader(); w.writerows(trip)
    (out / "top.json").write_text(json.dumps(trip[:5], indent=2))
    return trip


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--hard-n", action="store_true", help="also n_employees 25 vs 30 on hard")
    ap.add_argument("--out", default=str(ROOT / "data/fr8/cotune"))
    ap.add_argument("--fp", choices=["1", "lt1"], help="run only fp==1.0 or fp<1.0 cells")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    assert a.procs <= 3
    (Path(a.out) / "parts").mkdir(parents=True, exist_ok=True)
    if not a.analyse_only:
        jobs = [(bw, t, p, range(a.seeds), a.out) for bw, t, p in cells(a.hard_n, a.fp)]
        with Pool(a.procs) as pool:
            for name, secs in pool.imap_unordered(work, jobs):
                print(f"{name} {secs:.1f}s", flush=True)
    trip = analyse(a.out)
    print(f"{sum(t['feasible'] for t in trip)} feasible of {len(trip)} triples")
    for t in trip[:2]:
        print(json.dumps(t))
