"""J4 proxy metrics for tiny held-out evals (base vs LoRA, descriptive only).

  python -m fr8.analysis.j4_proxy RUN_DIR [RUN_DIR ...] --out fr8/analysis/out/j4_proxy.md [--no-solver-agree]

Each RUN_DIR holds episodes.jsonl (types.EpisodeResult dicts) + meta.json (train/eval_hf.py). If RUN_DIR has
no episodes.jsonl directly, its subdirectories are searched (eval_hf writes <out>/<run_id>/).

Invalid outputs: eval_hf turns an unparseable model output into a `status` call with args {} and only counts
it in ep.meta["invalid_calls"]; there is no per-step marker. So the invalid share is meta.invalid_calls / steps,
and invalid steps are hidden inside the `status` share (status share is reported both raw and net of invalid).
valid tool-call rate = (steps - invalid - steps whose result ok != True) / steps.
Solver agreement: one canary.solver SolverPolicy (reset with the episode's instruction) is fed the recorded
steps[:t] and asked for its next action; we compare tool names. Its queued plan is dropped whenever the agent's
actual call differs, so it re-plans from the agent's state. No env replay is needed (the solver only reads history);
sanity check: on the solver's own episodes agreement is ~1.0. Differences in the solver's own tiers version can make this approximate.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ._common import ci_half, mean

KINDS = ["plant_canary", "check_leak_feed", "advance_day", "read_access_logs", "interview", "accuse", "status"]


def find_runs(d: Path) -> list[Path]:
    if (d / "episodes.jsonl").exists():
        return [d]
    return sorted(p.parent for p in d.glob("*/episodes.jsonl"))


def load_run(d: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    eps = [json.loads(l) for l in (d / "episodes.jsonl").read_text().splitlines() if l.strip()]
    return meta, eps


def _key(st):
    return st["tool"], json.dumps(st.get("args") or {}, sort_keys=True)


def solver_agreement(ep: dict) -> tuple[int, int]:
    from canary.env import Env
    from canary.solver.policy import SolverPolicy
    from canary.types import Step
    env = Env(ep["tier"], ep["seed"])
    spec, instr = env.tools_spec(), env.instruction()
    steps = [Step(**{k: s[k] for k in ("t", "day", "tool", "args", "result")}) for s in ep["steps"]]
    agree = n = 0
    pol = SolverPolicy(ep["tier"])
    pol.reset(spec, instr)
    for i, st in enumerate(steps):
        try:
            tool, args = pol.act(steps[:i])
        except Exception:
            continue
        n += 1
        agree += tool == st.tool
        if (tool, args) != (st.tool, st.args):
            pol.queue = []      # agent deviated: the solver's queued plan is stale, re-plan next step
    return agree, n


def summarize(eps: list[dict], solver_agree: bool = True) -> dict:
    steps = [s for e in eps for s in e["steps"]]
    ns = len(steps)
    inv = sum((e.get("meta") or {}).get("invalid_calls", 0) for e in eps)
    not_ok = sum(1 for s in steps if not (s.get("result") or {}).get("ok"))
    mix = Counter(s["tool"] if s["tool"] in KINDS else "other" for s in steps)
    rep = sum(1 for e in eps for a, b in zip(e["steps"], e["steps"][1:]) if _key(a) == _key(b))
    scores = [e["score"] for e in eps]
    r = {"n_episodes": len(eps), "n_steps": ns,
         "valid_rate": (ns - inv - not_ok) / ns if ns else float("nan"),
         "invalid_share": inv / ns if ns else float("nan"),
         "result_not_ok_share": not_ok / ns if ns else float("nan"),
         "repeat_share": rep / ns if ns else float("nan"),
         **{f"mix[{k}]": mix.get(k, 0) / ns if ns else float("nan") for k in KINDS + ["other"]},
         "mix[status net of invalid]": (mix.get("status", 0) - inv) / ns if ns else float("nan"),
         "reached_accusation": mean([float(e.get("accused") is not None) for e in eps]),
         "accuracy": mean([float(bool(e.get("correct"))) for e in eps]),
         "mean_score": mean(scores), "score_ci95": ci_half(scores),
         "mean_final_day": mean([e.get("final_day", 0) for e in eps]),
         "end_reasons": dict(Counter(e.get("end_reason") for e in eps))}
    if solver_agree:
        try:
            a = [solver_agreement(e) for e in eps]
            tot = sum(x[1] for x in a)
            r["solver_tool_agreement"] = sum(x[0] for x in a) / tot if tot else float("nan")
        except Exception as exc:  # noqa: BLE001
            r["solver_tool_agreement"] = f"skipped ({type(exc).__name__}: {exc})"[:80]
    return r


def _f(v):
    if isinstance(v, float):
        return "nan" if v != v else f"{v:.3f}"
    if isinstance(v, dict):
        return ", ".join(f"{k}:{c}" for k, c in sorted(v.items(), key=str))
    return str(v)


def report(runs: list[tuple[str, dict, list[dict]]], solver_agree: bool = True) -> str:
    out = ["# J4 proxy metrics (held-out eval)", "",
           "**Descriptive only.** Episode counts are tiny; no significance is claimed. "
           "Invalid outputs are counted from meta.invalid_calls (eval_hf maps them to `status`).", ""]
    tiers = sorted({e["tier"] for _, _, eps in runs for e in eps})
    for scope in ["all"] + tiers:
        cols = [(name, summarize([e for e in eps if scope == "all" or e["tier"] == scope], solver_agree))
                for name, _, eps in runs]
        cols = [(n, c) for n, c in cols if c["n_episodes"]]
        if not cols:
            continue
        keys = list(cols[0][1].keys())
        out += [f"## {scope} " + "(" + "; ".join(f"{n}: n = {c['n_episodes']} episodes, {c['n_steps']} steps"
                                                for n, c in cols) + ")", "",
                "| metric | " + " | ".join(n for n, _ in cols) + " |", "|---|" + "---|" * len(cols)]
        out += [f"| {k} | " + " | ".join(_f(c.get(k)) for _, c in cols) + " |" for k in keys]
        out.append("")
    out += ["## Runs", ""] + [f"- {n}: {json.dumps({k: m.get(k) for k in ('agent', 'model', 'git_sha', 'tiers', 'seeds', 'n')})}"
                              for n, m, _ in runs]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="J4 proxy metrics")
    ap.add_argument("runs", nargs="+"); ap.add_argument("--out"); ap.add_argument("--no-solver-agree", action="store_true")
    a = ap.parse_args(argv)
    runs = []
    for r in a.runs:
        for d in find_runs(Path(r)):
            meta, eps = load_run(d)
            name = Path(r).name if d == Path(r) else f"{Path(r).name}/{d.name}"
            runs.append((name, meta, eps))
    md = report(runs, not a.no_solver_agree)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(md)
    print(md)


if __name__ == "__main__":
    main()
