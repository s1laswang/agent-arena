"""Pick per-tier params from a J1 calibration CSV (CEO objective, contract v0.3: wrong accusation = -1).

Feasible cell (per tier):
  * solver accuracy >= 0.90
  * medium: heuristic mean <= 0.55 x solver mean
  * medium/hard: logs_only accuracy <= 2 x chance (1/N, N = n_employees column or rules.TIERS)
  * stop_early mean < 0
Among feasible cells: maximise mean(solver - heuristic); tiebreak on smaller solver CI.
If none is feasible the report names the binding constraint(s) and lists the closest cells.
  python -m fr8.analysis.j1_recommend <csv>... [--out fr8/analysis/out/j1_recommendation.md]
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ._common import ci_half, cell_key, fmt_params, group, mean, read_rows
from .ci_sizing import n_needed
from ._common import std

MIN_SOLVER_ACC = 0.90
MED_HEUR_RATIO = 0.55
LOGS_CHANCE_MULT = 2.0


def _n_emp(tier: str, params: dict):
    if "n_employees" in params:
        return float(params["n_employees"])
    try:
        from canary.rules import TIERS
        return float(TIERS[tier].n_employees)
    except Exception:
        return None


def _heur(by: dict) -> str:
    for h in ("heuristic", "obvious_heuristic"):
        if h in by:
            return h
    return "heuristic"


def evaluate(rows: list[dict]) -> list[dict]:
    cells = []
    for (tier, params), rs in group(rows, cell_key).items():
        by = group(rs, lambda r: r["agent"])
        H = _heur(by)
        acc = {a: mean([float(r["correct"]) for r in v]) for a, v in by.items()}
        sc = {a: mean([r["score"] for r in v]) for a, v in by.items()}
        ci = {a: ci_half([r["score"] for r in v]) for a, v in by.items()}
        n = {a: len(v) for a, v in by.items()}
        wrong = {a: mean([float(r["wrong"]) if r.get("wrong", "") not in ("", None) else float(r["score"] < 0)
                          for r in v]) for a, v in by.items()}
        s = {r["seed"]: r["score"] for r in by.get("solver", [])}
        h = {r["seed"]: r["score"] for r in by.get(H, [])}
        diffs = [s[k] - h[k] for k in s if k in h]
        gap = mean(diffs) if diffs else float("nan")
        N = _n_emp(tier, dict(params))
        viol = []
        if acc.get("solver", 0) < MIN_SOLVER_ACC:
            viol.append("solver_acc<0.90")
        if tier == "medium" and not (sc.get(H, 1e9) <= MED_HEUR_RATIO * sc.get("solver", 0)):
            viol.append("heur>0.55*solver")
        if tier in ("medium", "hard") and N and acc.get("logs_only") is not None \
                and acc["logs_only"] > LOGS_CHANCE_MULT / N:
            viol.append("logs_only>2x_chance")
        if not (sc.get("stop_early", 1.0) < 0):
            viol.append("stop_early>=0")
        missing = [a for a in ("solver", H, "stop_early") + (("logs_only",) if tier != "easy" else ())
                   if a not in by]
        if missing:
            viol.append("missing:" + "/".join(missing))
        cells.append({
            "tier": tier, "params": fmt_params(params), "heur": H, "n": n.get("solver", 0),
            "solver_mean": sc.get("solver"), "solver_ci": ci.get("solver"), "solver_acc": acc.get("solver"),
            "heur_mean": sc.get(H), "heur_ci": ci.get(H), "heur_acc": acc.get(H),
            "logs_only_acc": acc.get("logs_only"), "chance": (1 / N) if N else None,
            "stop_early_mean": sc.get("stop_early"), "random_acc": acc.get("random"),
            "solver_wrong_rate": wrong.get("solver"), "heur_wrong_rate": wrong.get(H),
            "gap": gap, "gap_ci": ci_half(diffs) if len(diffs) > 1 else float("nan"),
            "seeds_for_ci_gap3": n_needed(std(diffs), gap) if len(diffs) > 1 else float("inf"),
            "violations": viol, "feasible": not viol,
        })
    return cells


def _rank(c):
    g = c["gap"] if c["gap"] == c["gap"] else -1e9
    sci = c["solver_ci"] if c["solver_ci"] == c["solver_ci"] else 1e9
    return (-g, sci)


def recommend(rows: list[dict]) -> dict[str, dict | None]:
    best: dict[str, dict | None] = {}
    for tier, cs in group(evaluate(rows), lambda c: c["tier"]).items():
        feas = sorted((c for c in cs if c["feasible"]), key=_rank)
        best[tier] = feas[0] if feas else None
    return best


def _f(v, d=3):
    if v is None:
        return "-"
    if isinstance(v, float):
        return "inf" if v == float("inf") else f"{v:.{d}f}"
    return str(v)


def _line(c):
    return (f"| {c['params']} | {c['n']} | {_f(c['solver_mean'])} ± {_f(c['solver_ci'])} | {_f(c['solver_acc'])} | "
            f"{_f(c['heur_mean'])} ± {_f(c['heur_ci'])} | {_f(c['heur_acc'])} | {_f(c['logs_only_acc'])} (chance {_f(c['chance'])}) | "
            f"{_f(c['stop_early_mean'])} | {_f(c['solver_wrong_rate'])}/{_f(c['heur_wrong_rate'])} | "
            f"{_f(c['gap'])} ± {_f(c['gap_ci'])} | {_f(c['seeds_for_ci_gap3'])} | {', '.join(c['violations']) or 'ok'} |")


HDR = ("| params | n | solver mean ± CI95 | solver acc | heur mean ± CI95 | heur acc | logs_only acc | "
       "stop_early mean | wrong rate solver/heur | gap ± CI95 | seeds for CI<gap/3 | constraints |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|")


FP = "fingerprint_accuracy"


def fp_curve(rows: list[dict]) -> dict[str, list[dict]]:
    """Per tier: solver vs heuristic accuracy/mean at each fingerprint_accuracy (pooled over other params)."""
    out = {}
    rows = [r for r in rows if r.get(FP) not in (None, "")]
    for tier, rs in group(rows, lambda r: r["tier"]).items():
        pts = []
        for fp, frs in sorted(group(rs, lambda r: float(r[FP])).items(), reverse=True):
            by = group(frs, lambda r: r["agent"])
            H = _heur(by)
            pt = {"fp": fp}
            for lab, a in (("solver", "solver"), ("heur", H)):
                v = by.get(a, [])
                pt[lab + "_acc"] = mean([float(r["correct"]) for r in v]) if v else None
                pt[lab + "_mean"] = mean([r["score"] for r in v]) if v else None
                pt[lab + "_ci"] = ci_half([r["score"] for r in v]) if v else None
                pt[lab + "_n"] = len(v)
            pts.append(pt)
        out[tier] = pts
    return out


def lowest_fp(pts: list[dict]) -> float | None:
    ok = [p["fp"] for p in pts if p["solver_acc"] is not None and p["solver_acc"] >= MIN_SOLVER_ACC]
    return min(ok) if ok else None


def fp_markdown(rows: list[dict]) -> list[str]:
    curves = fp_curve(rows)
    if not curves:
        return []
    out = ["## fingerprint_accuracy curve (pooled over other params)", ""]
    for tier, pts in sorted(curves.items()):
        out += [f"### {tier}: lowest fingerprint_accuracy with solver acc ≥ 0.90 = {_f(lowest_fp(pts), 2)}", "",
                "| fp_acc | solver acc | solver mean ± CI95 (n) | heuristic acc | heuristic mean ± CI95 (n) |",
                "|---|---|---|---|---|"]
        out += [f"| {p['fp']:.2f} | {_f(p['solver_acc'])} | {_f(p['solver_mean'])} ± {_f(p['solver_ci'])} ({p['solver_n']}) | "
                f"{_f(p['heur_acc'])} | {_f(p['heur_mean'])} ± {_f(p['heur_ci'])} ({p['heur_n']}) |" for p in pts]
        out.append("")
    return out


def to_markdown(rows: list[dict], sources: list[str], closest: int = 3) -> str:
    cells = evaluate(rows)
    out = ["# J1 recommendation", "", f"Sources: {', '.join(sources)}  ", f"Rows: {len(rows)}", "",
           "Objective: solver acc ≥ 0.90; medium heur ≤ 0.55×solver; medium/hard logs_only acc ≤ 2/N; "
           "stop_early < 0; maximise solver−heuristic gap (tiebreak smaller solver CI). "
           "Seeds column: paired n for 95% CI half-width < gap/3.", ""]
    for tier, cs in sorted(group(cells, lambda c: c["tier"]).items()):
        feas = sorted((c for c in cs if c["feasible"]), key=_rank)
        out.append(f"## {tier} ({len(cs)} cells, {len(feas)} feasible)")
        if feas:
            out += [f"**Recommend:** `{feas[0]['params']}`", "", HDR] + [_line(c) for c in feas[:closest]]
        else:
            binds = Counter(v.split(":")[0] for c in cs for v in c["violations"])
            out.append(f"**No feasible cell.** Constraint violations across cells: {dict(binds)}")
            near = sorted(cs, key=lambda c: (len(c["violations"]),) + _rank(c))[:closest]
            out += ["", "Closest cells:", "", HDR] + [_line(c) for c in near]
        out.append("")
    out += fp_markdown(rows)
    return "\n".join(out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="J1 param recommendation")
    ap.add_argument("csv", nargs="+"); ap.add_argument("--out"); ap.add_argument("--closest", type=int, default=3)
    a = ap.parse_args(argv)
    rows = [r for c in a.csv for r in read_rows(c)]
    md = to_markdown(rows, a.csv, a.closest)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(md)
    print(md)


if __name__ == "__main__":
    main()
