"""Pick per-tier params from a J1 calibration CSV.

Constraints: solver accuracy >= 0.90/0.90/0.80 (easy/medium/hard); random accuracy within
--rand-tol of 1/N (N = n_employees column, if present). Objective: maximise mean(solver − heuristic).
  python -m fr8.analysis.j1_recommend data/fr8/j1/calib.csv [--out fr8/analysis/out/j1_recommend.md]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ._common import cell_key, fmt_params, group, mean, read_rows

MIN_ACC = {"easy": 0.90, "medium": 0.90, "hard": 0.80}


def evaluate(rows: list[dict], rand_tol: float = 0.1) -> list[dict]:
    cells = []
    for (tier, params), rs in group(rows, cell_key).items():
        by = group(rs, lambda r: r["agent"])
        acc = {a: mean([float(r["correct"]) for r in v]) for a, v in by.items()}
        sc = {a: mean([r["score"] for r in v]) for a, v in by.items()}
        n_emp = dict(params).get("n_employees")
        rand_ok = True
        if "random" in acc and n_emp:
            rand_ok = abs(acc["random"] - 1 / float(n_emp)) <= rand_tol
        s_ok = acc.get("solver", 0) >= MIN_ACC.get(tier, 0.9)
        cells.append({"tier": tier, "params": fmt_params(params),
                      "solver_acc": acc.get("solver"), "random_acc": acc.get("random"),
                      "gap": sc.get("solver", float("nan")) - sc.get("heuristic", float("nan")),
                      "feasible": s_ok and rand_ok})
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
    lines = ["| tier | params | solver_acc | random_acc | gap |", "|---|---|---|---|---|"]
    for t, c in sorted(rec.items()):
        lines.append(f"| {t} | none feasible | | | |" if c is None else
                     f"| {t} | {c['params']} | {c['solver_acc']:.3f} | {c['random_acc']} | {c['gap']:.3f} |")
    md = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(md)
    print(md)


if __name__ == "__main__":
    main()
