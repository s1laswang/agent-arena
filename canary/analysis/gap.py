"""Aggregate data/runs/*/episodes.jsonl into the gap table (CONTRACT §6).

    python -m canary.analysis.gap [--runs data/runs] [--solver solver] [--out docs/reports/gap_table.md]
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

Episode = dict[str, Any]


def load_runs(root: str | Path = "data/runs") -> list[Episode]:
    eps: list[Episode] = []
    for f in sorted(Path(root).glob("*/episodes.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                e.setdefault("meta", {})["run_id"] = f.parent.name
                eps.append(e)
    return eps


def mean_ci(xs: list[float]) -> tuple[float, float]:
    """Mean and half-width of a normal-approx 95% CI (0 for n<2)."""
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan")
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def pass_hat_k(successes_by_seed: dict[Any, list[bool]], k: int) -> float:
    """pass^k (tau-bench): P(all k sampled runs succeed), averaged over seeds with >=k runs."""
    vals = []
    for runs in successes_by_seed.values():
        n, c = len(runs), sum(runs)
        if n >= k:
            vals.append(math.comb(c, k) / math.comb(n, k))
    return sum(vals) / len(vals) if vals else float("nan")


def summarize(eps: Iterable[Episode], solver_agent: str = "solver") -> list[dict]:
    eps = list(eps)
    solver_score = {(e["tier"], e["seed"]): e["score"] for e in eps if e["agent"] == solver_agent}
    groups: dict[tuple[str, str], list[Episode]] = defaultdict(list)
    for e in eps:
        groups[(e["agent"], e["tier"])].append(e)
    rows = []
    for (agent, tier), es in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        m, h = mean_ci([e["score"] for e in es])
        acc_days = [e["final_day"] for e in es if e.get("end_reason") == "accused"]
        norm = [e["score"] / solver_score[(tier, e["seed"])] for e in es
                if solver_score.get((tier, e["seed"]), 0) > 0]
        by_seed: dict[Any, list[bool]] = defaultdict(list)
        for e in es:
            by_seed[e["seed"]].append(bool(e["correct"]))
        rows.append(dict(
            agent=agent, tier=tier, n=len(es), seeds=len(by_seed), mean=m, ci=h,
            accuracy=sum(bool(e["correct"]) for e in es) / len(es),
            accuse_day=(sum(acc_days) / len(acc_days)) if acc_days else float("nan"),
            norm=(sum(norm) / len(norm)) if norm else float("nan"),
            pass3=pass_hat_k(by_seed, 3),
        ))
    return rows


def _f(x: float, nd: int = 3) -> str:
    return "–" if x != x else f"{x:.{nd}f}"


def gap_table_md(rows: list[dict]) -> str:
    out = ["| tier | agent | n | score ± 95% CI | accuracy | accuse day | / solver | pass^3 |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['tier']} | {r['agent']} | {r['n']} | {_f(r['mean'])} ± {_f(r['ci'])} | "
                   f"{_f(r['accuracy'], 2)} | {_f(r['accuse_day'], 1)} | {_f(r['norm'], 2)} | {_f(r['pass3'], 2)} |")
    return "\n".join(out)


def gap_alert(rows: list[dict], tier: str = "medium", threshold: float = 0.85,
              solver_agent: str = "solver") -> list[str]:
    """Kill switch: agents whose mean score is >= threshold x the solver's on `tier`."""
    sol = next((r for r in rows if r["agent"] == solver_agent and r["tier"] == tier), None)
    if not sol or not sol["mean"] > 0:
        return []
    return [f"{r['agent']}: {r['mean']:.3f} vs solver {sol['mean']:.3f} ({r['mean']/sol['mean']:.0%})"
            for r in rows if r["tier"] == tier and r["agent"] != solver_agent
            and r["mean"] >= threshold * sol["mean"]]


def tag_counts(eps: Iterable[Episode], attribute: Callable[[Episode], list[dict]] | None = None) -> dict[str, Counter]:
    """Per-agent counts of regret tags plus the summed regret per tag.

    `attribute` defaults to canary.solver.regret.attribute (ENV). Returns {agent: Counter(tag -> count)}
    and {agent+'#regret': Counter(tag -> total regret)}.
    """
    if attribute is None:
        from canary.solver.regret import attribute as _attr  # type: ignore
        attribute = _attr
    out: dict[str, Counter] = defaultdict(Counter)
    for e in eps:
        for item in attribute(e) or []:
            for t in item.get("tags", []):
                out[e["agent"]][t] += 1
                out[e["agent"] + "#regret"][t] += float(item.get("regret", 0.0))
    return dict(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="data/runs")
    ap.add_argument("--solver", default="solver")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rows = summarize(load_runs(a.runs), a.solver)
    md = gap_table_md(rows)
    alerts = gap_alert(rows, solver_agent=a.solver)
    if alerts:
        md += "\n\n**GAP ALERT (>=85% of solver on medium):** " + "; ".join(alerts)
    print(md)
    if a.out:
        Path(a.out).write_text(md + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
