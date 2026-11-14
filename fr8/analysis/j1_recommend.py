"""Pick per-tier params from a J1 calibration CSV.

Constraints (contract v0.3: wrong accusation scores -1.0): stop_early mean score < 0;
solver mean clearly > 0 (lower 95% CI bound > 0); solver accuracy >= 0.90/0.90/0.80 (easy/medium/hard); random accuracy within
--rand-tol of 1/N (N = n_employees column, if present). Objective: maximise mean(solver − heuristic).
  python -m fr8.analysis.j1_recommend data/fr8/j1/calib.csv [--out fr8/analysis/out/j1_recommend.md]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ._common import ci_half, cell_key, fmt_params, group, mean, read_rows

MIN_ACC = {"easy": 0.90, "medium": 0.90, "hard": 0.80}


def evaluate(rows: list[dict], rand_tol: float = 0.1) -> list[dict]:
    cells = []
    for (tier, params), rs in group(rows, cell_key).items():
        by = group(rs, lambda r: r["agent"])
        acc = {a: mean([float(r["correct"]) for r in v]) for a, v in by.items()}
        sc = {a: mean([r["score"] for r in v]) for a, v in by.items()}
        heur = "heuristic" if "heuristic" in by else "obvious_heuristic"
        wrong = {a: mean([float(r["wrong"]) if r.get("wrong", "") != "" else float(r["score"] < 0)
                          for r in v]) for a, v in by.items()}
        s_lo = sc.get("solver", float("nan")) - ci_half([r["score"] for r in by.get("solver", [])])
        se_ok = "stop_early" not in sc or sc["stop_early"] < 0
        n_emp = dict(params).get("n_employees")
        rand_ok = True
        if "random" in acc and n_emp:
            rand_ok = abs(acc["random"] - 1 / float(n_emp)) <= rand_tol
        s_ok = acc.get("solver", 0) >= MIN_ACC.get(tier, 0.9) and s_lo > 0
        cells.append({"tier": tier, "params": fmt_params(params),
                      "solver_acc": acc.get("solver"), "random_acc": acc.get("random"),
                      "solver_ci_lo": s_lo, "stop_early_mean": sc.get("stop_early"),
                      "solver_wrong_rate": wrong.get("solver"), "heur_wrong_rate": wrong.get(heur),
                      "gap": sc.get("solver", float("nan")) - sc.get(heur, float("nan")),
                      "feasible": s_ok and rand_ok and se_ok})
    return cells


def recommend(rows: list[dict], rand_tol: float = 0.1) -> dict[str, dict | None]:
    best: dict[str, dict | None] = {}
    for c in evaluate(rows, rand_tol):
        best.setdefault(c["tier"], None)
        if c["feasible"] and (best[c["tier"]] is None or c["gap"] > best[c["tier"]]["gap"]):
            best[c["tier"]] = c
    return best


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="J1 param recommendation")
    ap.add_argument("csv"); ap.add_argument("--rand-tol", type=float, default=0.1); ap.add_argument("--out")
    a = ap.parse_args(argv)
    rec = recommend(read_rows(a.csv), a.rand_tol)
    cols = ["params", "solver_acc", "solver_ci_lo", "stop_early_mean", "random_acc",
            "solver_wrong_rate", "heur_wrong_rate", "gap"]
    f = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)
    lines = ["| tier | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    for t, c in sorted(rec.items()):
        lines.append(f"| {t} | none feasible |" + " |" * (len(cols) - 1) if c is None else
                     f"| {t} | " + " | ".join(f(c[k]) for k in cols) + " |")
    md = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(md)
    print(md)


if __name__ == "__main__":
    main()
