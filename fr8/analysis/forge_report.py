"""Mole Forge report (CONTRACT §7): fitness per generation, solver constraint, top strategies.

  python -m fr8.analysis.forge_report data/forge/<run> [--top 5]
Writes <run>/report.md and <run>/fitness.png (needs matplotlib: `uv run --with matplotlib`).

Key names are read tolerantly since evolve.py's exact log schema isn't frozen:
  log.jsonl line: gen|generation, best|best_fitness, mean|mean_fitness,
                  solver_score|solver_ratio (constraint >= 0.5 x default), solver_acc|solver_accuracy
  hall_of_fame.jsonl line: fitness, strategy (DSL json), optional gen, solver_score, solver_acc
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ALIASES = {
    "gen": ("gen", "generation"),
    "best": ("best", "best_fitness", "max_fitness"),
    "mean": ("mean", "mean_fitness", "avg_fitness"),
    "solver": ("solver_ratio", "solver_score", "solver_score_ratio"),
    "acc": ("solver_acc", "solver_accuracy"),
}


def pick(d: dict, key: str):
    for k in ALIASES[key]:
        if k in d:
            return d[k]
    return None


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def normalise_log(rows: list[dict]) -> list[dict]:
    out = [{k: pick(r, k) for k in ALIASES} for r in rows]
    for i, r in enumerate(out):
        if r["gen"] is None:
            r["gen"] = i
    return sorted(out, key=lambda r: r["gen"])


def describe_strategy(s: dict) -> str:
    rules = s.get("rules", []) if isinstance(s, dict) else []
    parts = []
    for r in rules[:4]:
        cond = " and ".join(" ".join(map(str, c)) if isinstance(c, list) else str(c) for c in r.get("if", []))
        then = r.get("then", {})
        parts.append(f"if {cond or 'always'} -> leak={then.get('leak')} frame={then.get('frame')}")
    more = f" (+{len(rules) - 4} more)" if len(rules) > 4 else ""
    return "; ".join(parts) + more if parts else json.dumps(s)[:200]


def report(run: Path, top: int = 5) -> str:
    log = normalise_log(load_jsonl(run / "log.jsonl"))
    hof = sorted(load_jsonl(run / "hall_of_fame.jsonl"), key=lambda r: -float(r.get("fitness", 0)))
    lines = [f"# Forge report: {run.name}", ""]
    if log:
        last = log[-1]
        lines += [f"- generations: {len(log)}; final best={last['best']}, mean={last['mean']}",
                  f"- solver constraint at last gen: score ratio={last['solver']} (>=0.5), acc={last['acc']} (>=0.85)"]
        viol = [r["gen"] for r in log if (r["solver"] is not None and r["solver"] < 0.5)
                or (r["acc"] is not None and r["acc"] < 0.85)]
        lines.append(f"- generations reporting a constraint violation: {viol or 'none'}")
    else:
        lines.append("- no log.jsonl")
    lines += ["", f"## Top {top} strategies", "", "| # | fitness | solver | acc | rules |", "|---|---|---|---|---|"]
    for i, h in enumerate(hof[:top], 1):
        lines.append(f"| {i} | {h.get('fitness')} | {pick(h, 'solver')} | {pick(h, 'acc')} | "
                     f"{describe_strategy(h.get('strategy', {})).replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def plot(run: Path, png: Path) -> bool:
    log = normalise_log(load_jsonl(run / "log.jsonl"))
    if not log:
        return False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib missing: `uv run --with matplotlib ...` for the PNG", file=sys.stderr)
        return False
    g = [r["gen"] for r in log]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.6))
    a1.plot(g, [r["best"] for r in log], label="best")
    a1.plot(g, [r["mean"] for r in log], label="mean")
    a1.set_xlabel("generation"); a1.set_ylabel("fitness (regret)"); a1.legend(frameon=False)
    if any(r["solver"] is not None for r in log):
        a2.plot(g, [r["solver"] for r in log], label="solver score ratio")
        a2.axhline(0.5, ls="--", c="grey")
    if any(r["acc"] is not None for r in log):
        a2.plot(g, [r["acc"] for r in log], label="solver accuracy")
        a2.axhline(0.85, ls=":", c="grey")
    a2.set_xlabel("generation"); a2.set_title("catchability constraint"); a2.legend(frameon=False)
    for a in (a1, a2):
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(png, dpi=130)
    return True


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="forge report")
    ap.add_argument("run"); ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args(argv)
    run = Path(a.run)
    md = report(run, a.top)
    (run / "report.md").write_text(md)
    plot(run, run / "fitness.png")
    print(md)


if __name__ == "__main__":
    main()
