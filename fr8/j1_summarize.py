"""Merge J1 parts and recommend params per tier (stdlib only).

  python fr8/j1_summarize.py [DIR]   (default ~/agent-arena-data/j1) -> DIR/merged.csv, summary.csv, recommend.json
Rule: solver accuracy >= 0.90/0.90/0.80 (easy/medium/hard); random accuracy within [0, 2/N];
pick the cell maximising mean(solver score) - mean(heuristic score). seeds_for_ci = seeds needed
for a 95% CI half-width < gap/3 on the per-seed solver-heuristic difference.
"""
import csv, json, os, statistics as st, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from canary import rules
from fr8.j1_grid import GRID

TARGET = {"easy": 0.90, "medium": 0.90, "hard": 0.80}
d = Path(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/agent-arena-data/j1"))
rows = []
for p in sorted((d / "parts").glob("cell*.csv")):
    rows += list(csv.DictReader(open(p)))
if not rows:
    sys.exit(f"no rows under {d}/parts")
with open(d / "merged.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, rows[0].keys()); w.writeheader(); w.writerows(rows)
by = defaultdict(lambda: defaultdict(dict))  # cell -> agent -> seed -> (score, correct)
meta = {}
for r in rows:
    by[r["cell"]][r["agent"]][r["seed"]] = (float(r["score"]), int(r["correct"]), int(r.get("wrong", 0)))
    meta[r["cell"]] = {"tier": r["tier"], **{k: r[k] for k in GRID}}
summ = []
for c, ag in by.items():
    row = {"cell": int(c), **meta[c]}
    for a, sd in ag.items():
        row[f"{a}_score"] = st.mean(v[0] for v in sd.values())
        row[f"{a}_acc"] = st.mean(v[1] for v in sd.values())
        row[f"{a}_wrong"] = st.mean(v[2] for v in sd.values())
        row[f"{a}_n"] = len(sd)
    row["gap"] = row.get("solver_score", 0) - row.get("heuristic_score", 0)
    summ.append(row)
summ.sort(key=lambda r: r["cell"])
cols = sorted({k for r in summ for k in r}, key=lambda k: (k not in ("cell", "tier", *GRID), k))
with open(d / "summary.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, cols); w.writeheader(); w.writerows(summ)
rec = {}
for tier in rules.TIERS:
    g = [r for r in summ if r["tier"] == tier]
    if not g: continue
    n = rules.TIERS[tier].n_employees
    ok = [r for r in g if r.get("solver_acc", 0) >= TARGET[tier] and r.get("random_acc", 1 / n) <= 2 / n]
    if not ok:
        rec[tier] = {"status": "no cell meets targets", "best_solver_acc": max(r.get("solver_acc", 0) for r in g)}; continue
    b = max(ok, key=lambda r: r["gap"])
    s, h = by[str(b["cell"])]["solver"], by[str(b["cell"])].get("heuristic", {})
    diff = [s[k][0] - h.get(k, (0, 0))[0] for k in s]
    n_ci = int((1.96 * st.stdev(diff) / (b["gap"] / 3)) ** 2) + 1 if b["gap"] > 0 and len(diff) > 1 else None
    rec[tier] = {"cell": b["cell"], "params": {k: b[k] for k in GRID}, "solver_acc": b["solver_acc"],
                 "heuristic_acc": b.get("heuristic_acc"), "solver_wrong": b.get("solver_wrong"), "random_acc": b.get("random_acc"),
                 "gap": b["gap"], "seeds_for_ci": n_ci, "n_cells_ok": len(ok)}
(d / "recommend.json").write_text(json.dumps(rec, indent=2))
print(json.dumps(rec, indent=2))
