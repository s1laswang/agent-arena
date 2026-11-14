"""Seeds needed per tier for a 95% CI half-width < gap/3 (gap = solver − heuristic).

Input: calibration CSV with columns tier, <cell params...>, agent, seed, score, correct, final_day.
  python -m fr8.analysis.ci_sizing data/fr8/<job>/calib.csv [--solver solver --heuristic heuristic]
         [--out fr8/analysis/out/ci_sizing.md]

n is computed analytically, n = ceil((Z * sd / (gap/3))^2), for
  paired:   sd = std over seeds of (solver − heuristic) on the same seed
  unpaired: sd = sqrt(sd_solver^2 + sd_heuristic^2)
and via bootstrap: resample seeds, take the 95th percentile of the paired sd -> conservative n.
"""
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from ._common import Z95, cell_key, fmt_params, group, mean, read_rows, std


def n_needed(sd: float, gap: float) -> float:
    if gap <= 0 or math.isnan(sd):
        return float("inf")
    return max(2, math.ceil((Z95 * sd / (gap / 3)) ** 2))


def bootstrap_n(diffs: list[float], gap: float, reps: int = 2000, seed: int = 0) -> float:
    rng = random.Random(seed)
    k = len(diffs)
    sds = sorted(std([diffs[rng.randrange(k)] for _ in range(k)]) for _ in range(reps))
    return n_needed(sds[int(0.95 * (reps - 1))], gap)


def size_cells(rows: list[dict], solver: str = "solver", heuristic: str = "heuristic") -> list[dict]:
    out = []
    for (tier, params), rs in sorted(group(rows, cell_key).items(), key=lambda kv: str(kv[0])):
        by_agent = group(rs, lambda r: r["agent"])
        if solver not in by_agent or heuristic not in by_agent:
            continue
        s = {r["seed"]: r["score"] for r in by_agent[solver]}
        h = {r["seed"]: r["score"] for r in by_agent[heuristic]}
        common = sorted(set(s) & set(h))
        diffs = [s[k] - h[k] for k in common]
        gap = mean(diffs) if diffs else float("nan")
        sd_s, sd_h = std(list(s.values())), std(list(h.values()))
        row = {
            "tier": tier, "params": fmt_params(params), "n_seeds": len(common),
            "solver_mean": mean(list(s.values())), "heur_mean": mean(list(h.values())),
            "gap": gap, "sd_paired": std(diffs), "sd_solver": sd_s, "sd_heur": sd_h,
        }
        row["n_paired"] = n_needed(row["sd_paired"], gap)
        row["n_unpaired"] = n_needed(math.sqrt(sd_s ** 2 + sd_h ** 2), gap)
        row["n_bootstrap"] = bootstrap_n(diffs, gap) if len(diffs) > 1 else float("inf")
        for a, ars in sorted(by_agent.items()):
            row[f"sd[{a}]"] = std([r["score"] for r in ars])
        out.append(row)
    return out


def to_markdown(cells: list[dict]) -> str:
    cols = ["tier", "params", "n_seeds", "solver_mean", "heur_mean", "gap",
            "sd_paired", "sd_solver", "sd_heur", "n_paired", "n_unpaired", "n_bootstrap"]
    def f(v):
        return f"{v:.3f}" if isinstance(v, float) and not math.isinf(v) else str(v)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(f(c[k]) for k in cols) + " |" for c in cells]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv")
    ap.add_argument("--solver", default="solver")
    ap.add_argument("--heuristic", default="heuristic")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    md = to_markdown(size_cells(read_rows(a.csv), a.solver, a.heuristic))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md)
    print(md)


if __name__ == "__main__":
    main()
