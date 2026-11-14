"""Solver accusation-threshold sweep (one process). v0.3 scoring, dev seeds.

  uv run --python 3.12 --extra dev python fr8/tau_sweep.py [--seeds 200] [--out data/fr8/tau]
  uv run --python 3.12 --extra dev --with matplotlib python fr8/tau_sweep.py --plot-only
Writes rows.csv (per episode), summary.csv (per tier x tau, plus heuristic as tau='heuristic'),
best.json (max mean score; tiebreak higher accuracy; flag acc < 0.90) and tau_curve.png.
"""
import argparse, csv, json, math, statistics as st, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TAUS = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.99]
TIERS = ["easy", "medium", "hard"]


def run_all(seeds, out):
    from canary.env import Env
    from canary.solver.policy import SolverPolicy
    from canary.baselines import BASELINES, CALIBRATION_POLICIES
    from fr8.j1_grid import run
    H = {**BASELINES, **CALIBRATION_POLICIES}["heuristic"]
    rows = []
    for tier in TIERS:
        for tau in [*TAUS, "heuristic"]:
            t0 = time.time()
            for s in seeds:
                pol = H(seed=s) if tau == "heuristic" else SolverPolicy(threshold=tau)
                r = run(Env(tier=tier, seed=s), pol, "heuristic" if tau == "heuristic" else "solver")
                rows.append({"tier": tier, "tau": tau, "seed": s, "score": r.score, "correct": int(r.correct),
                             "wrong": int(r.accused is not None and not r.correct), "accused": r.accused or "",
                             "final_day": r.final_day})
            print(f"{tier} tau={tau} {time.time()-t0:.1f}s", flush=True)
    with open(out / "rows.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, rows[0].keys()); w.writeheader(); w.writerows(rows)


def summarize(out):
    rows = list(csv.DictReader(open(out / "rows.csv")))
    summ = []
    for tier in TIERS:
        for tau in [*map(str, TAUS), "heuristic"]:
            g = [r for r in rows if r["tier"] == tier and r["tau"] == tau]
            sc = [float(r["score"]) for r in g]
            acc_days = [int(r["final_day"]) for r in g if r["accused"]]
            summ.append({"tier": tier, "tau": tau, "n": len(g), "mean_score": round(st.mean(sc), 4),
                         "ci95": round(1.96 * st.stdev(sc) / math.sqrt(len(sc)), 4),
                         "accuracy": round(st.mean(int(r["correct"]) for r in g), 4),
                         "wrong_rate": round(st.mean(int(r["wrong"]) for r in g), 4),
                         "mean_accuse_day": round(st.mean(acc_days), 2) if acc_days else ""})
    with open(out / "summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, summ[0].keys()); w.writeheader(); w.writerows(summ)
    best = {}
    for tier in TIERS:
        g = [r for r in summ if r["tier"] == tier and r["tau"] != "heuristic"]
        b = max(g, key=lambda r: (r["mean_score"], r["accuracy"]))
        best[tier] = {**b, "flag_acc_below_0.90": b["accuracy"] < 0.90}
    (out / "best.json").write_text(json.dumps(best, indent=2))
    return summ, best


def plot(out, summ):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5, 3.2), dpi=120)
    for i, tier in enumerate(TIERS):
        g = [r for r in summ if r["tier"] == tier and r["tau"] != "heuristic"]
        x = [float(r["tau"]) for r in g]
        ax.errorbar(x, [r["mean_score"] for r in g], yerr=[r["ci95"] for r in g], marker="o", ms=3, capsize=2, label=tier, color=f"C{i}")
        h = next(r for r in summ if r["tier"] == tier and r["tau"] == "heuristic")
        ax.axhline(h["mean_score"], ls=":", lw=1, color=f"C{i}")
    ax.set_xlabel("solver accusation threshold τ"); ax.set_ylabel("mean score (v0.3)")
    ax.set_title("Score vs τ (dotted: heuristic)", fontsize=9); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(out / "tau_curve.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--out", default=str(ROOT / "data/fr8/tau"))
    ap.add_argument("--plot-only", action="store_true")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    if not a.plot_only:
        run_all(range(a.seeds), out)
    summ, best = summarize(out)
    try:
        plot(out, summ)
    except ImportError:
        print("matplotlib missing: rerun with --with matplotlib --plot-only")
    print(json.dumps(best, indent=2))
