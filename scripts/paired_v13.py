"""Paired v1.3 frontier-vs-solver table (no API cost).

    python scripts/paired_v13.py [--root data/runs/committed] [--seeds 0-9] [--out-md ...] [--out-json ...]

Each row is one run group on one tier, restricted to the dev seeds it shares with the reference solver.
Columns: n, mean score +/- 95% CI (normal approx), accuracy (correct / n), accused rate, mean solver
posterior P(accused is the mole) at the accusation (canary.analysis.accuse), the solver's mean on the
SAME seeds, frontier/solver = mean_F / mean_S with a paired bootstrap 95% CI over seeds, and the mean
paired difference F - S +/- 95% CI.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canary.analysis.accuse import audit_episode  # noqa: E402
from canary.analysis.gap import load_runs, mean_ci  # noqa: E402
from canary.analysis.tags import to_result  # noqa: E402

GROUPS = [  # label, subdir (relative to --root = data/runs/committed), agent name
    ("Codex gpt-5.5 over MCP (judges' shape), full run", "v1.3/codex-gpt-5.5-full", "codex:gpt-5.5"),
    ("in-process gpt-5.5, fixed loop (full history, Responses + reasoning replay, effort=medium)", "v1.3/gpt-5.5-full", "openai:gpt-5.5"),
    ("Codex gpt-5.5 over MCP, earlier sample (0933805; history)", "superseded/v1.3-codex-sample/codex-gpt-5.5", "codex:gpt-5.5"),
    ("in-process gpt-5.5, handicapped scaffold, superseded (40-turn window)", "superseded/v1.3-window-scaffold/gpt-5.5", "openai:gpt-5.5"),
    ("reference solver", "v1.3/reference", "solver"),
    ("heuristic", "v1.3/reference", "heuristic"),
    ("do_nothing", "v1.3/reference", "do_nothing"),
    ("stop_early", "v1.3/reference", "stop_early"),
]


def boot_ratio(f: list[float], s: list[float], B: int = 10000, rng_seed: int = 0) -> tuple[float, float]:
    rng = random.Random(rng_seed)
    n, vals = len(f), []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        ms = sum(s[i] for i in idx) / n
        if ms > 0:
            vals.append(sum(f[i] for i in idx) / n / ms)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def rows_for(root: Path, seeds: set[int]) -> list[dict]:
    solver = {(e["tier"], e["seed"]): e for e in load_runs(root / "v1.3" / "reference") if e["agent"] == "solver"}
    out = []
    for label, sub, agent in GROUPS:
        d = root / sub
        if not d.exists():
            continue
        eps = [e for e in load_runs(d) if e["agent"] == agent and e["seed"] in seeds]
        for tier in ("medium", "hard"):
            es = sorted((e for e in eps if e["tier"] == tier), key=lambda e: e["seed"])
            if not es:
                continue
            paired = [e for e in es if (tier, e["seed"]) in solver]
            f = [e["score"] for e in paired]
            s = [solver[(tier, e["seed"])]["score"] for e in paired]
            m, h = mean_ci([e["score"] for e in es])
            ms = sum(s) / len(s) if s else float("nan")
            dm, dh = mean_ci([a - b for a, b in zip(f, s)]) if f else (float("nan"), float("nan"))
            ps = []
            for e in es:
                if e.get("accused"):
                    try:
                        p = audit_episode(to_result(e))["p_accused"]
                    except Exception:  # noqa: BLE001
                        p = None
                    if p is not None:
                        ps.append(p)
            lo, hi = boot_ratio(f, s) if len(f) > 1 and agent != "solver" else (float("nan"), float("nan"))
            out.append(dict(label=label, group=sub, agent=agent, tier=tier, n=len(es), seeds=[e["seed"] for e in es],
                            mean=m, ci=h, accuracy=sum(bool(e["correct"]) for e in es) / len(es),
                            accused_rate=sum(1 for e in es if e.get("accused")) / len(es),
                            p_accused=(sum(ps) / len(ps)) if ps else float("nan"), n_p=len(ps),
                            solver_same_seeds=ms, ratio=(sum(f) / len(f) / ms) if f and ms > 0 else float("nan"),
                            ratio_lo=lo, ratio_hi=hi, diff=dm, diff_ci=dh))
    return out


def _f(x, nd=3):
    return "–" if x != x else f"{x:.{nd}f}"


def to_md(rows: list[dict]) -> str:
    out = ["| tier | run | n | score ± 95% CI | accuracy | accused | mean P(accused) at accusation | solver, same seeds | frontier / solver [95% CI] | paired diff ± CI |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["tier"] != "medium", GROUPS.index(next(g for g in GROUPS if g[1] == r["group"] and g[2] == r["agent"])))):
        ratio = "–" if r["agent"] == "solver" else f"{r['ratio']:.0%} [{_f(r['ratio_lo'] * 100, 0)}%, {_f(r['ratio_hi'] * 100, 0)}%]" if r["ratio"] == r["ratio"] else "–"
        if r["agent"] != "solver" and r["ratio"] == r["ratio"] and r["ratio_lo"] != r["ratio_lo"]:
            ratio = f"{r['ratio']:.0%}"
        out.append(f"| {r['tier']} | {r['label']} | {r['n']} | {_f(r['mean'])} ± {_f(r['ci'])} | {r['accuracy']:.2f} | "
                   f"{r['accused_rate']:.2f} | {_f(r['p_accused'], 2)} | {_f(r['solver_same_seeds'])} | {ratio} | "
                   f"{'–' if r['agent'] == 'solver' else _f(r['diff']) + ' ± ' + _f(r['diff_ci'])} |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/runs/committed")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--out-json", default=None)
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split("-"))
    rows = rows_for(Path(a.root), set(range(lo, hi + 1)))
    md = to_md(rows)
    print(md)
    if a.out_md:
        Path(a.out_md).write_text(md + "\n")
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
