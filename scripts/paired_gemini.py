"""Paired Gemini-vs-solver table for one tiers version (no API cost). Same method as scripts/paired_v13.py.

    python scripts/paired_gemini.py --version v1.3 [--seeds 0-9] [--out-md ...] [--out-json ...]

Rows: OpenCode + Gemini over MCP (judges' shape) and the in-process Gemini loop from
data/runs/committed/<version>/{opencode,inproc}-<model>/, the earlier gpt-5.5 rows for context (v1.3 only), the
reference solver and baselines from data/runs/committed/<version>/reference/. Each row is restricted to the seeds it
shares with the solver: frontier/solver = mean_F / mean_S with a paired bootstrap 95% CI over seeds (10,000
resamples), the paired difference, the solver posterior P(accused) at the accusation and the luck-adjusted score.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from canary.analysis.gap import load_runs, mean_ci  # noqa: E402
from paired_v13 import _f, boot_ratio, p_acc, post_expected  # noqa: E402


def groups(version: str, model: str) -> list[tuple[str, str, str]]:
    g = [(f"OpenCode + {model} over MCP (judges' shape)", f"{version}/opencode-{model}", f"opencode:google/{model}"),
         (f"in-process {model} (full history, thought-signature replay)", f"{version}/inproc-{model}", f"gemini:{model}")]
    if version == "v1.3":
        g += [("Codex gpt-5.5 over MCP (earlier official run)", "v1.3/codex-gpt-5.5-full", "codex:gpt-5.5"),
              ("in-process gpt-5.5, fixed loop (earlier official run)", "v1.3/gpt-5.5-full", "openai:gpt-5.5")]
    g += [("reference solver", f"{version}/reference", "solver"), ("heuristic", f"{version}/reference", "heuristic"),
          ("do_nothing", f"{version}/reference", "do_nothing"), ("stop_early", f"{version}/reference", "stop_early")]
    return g


def rows_for(root: Path, version: str, model: str, seeds: set[int]) -> list[dict]:
    solver = {(e["tier"], e["seed"]): e for e in load_runs(root / version / "reference") if e["agent"] == "solver"}
    out = []
    for label, sub, agent in groups(version, model):
        d = root / sub
        if not d.exists():
            continue
        eps = [e for e in load_runs(d) if e["agent"] == agent and e["seed"] in seeds
               and (e.get("meta") or {}).get("valid") is not False]
        for tier in ("medium", "hard"):
            es = sorted((e for e in eps if e["tier"] == tier), key=lambda e: e["seed"])
            if not es:
                continue
            paired = [e for e in es if (tier, e["seed"]) in solver]
            f = [e["score"] for e in paired]
            s = [solver[(tier, e["seed"])]["score"] for e in paired]
            m, h = mean_ci([e["score"] for e in es])
            ms = sum(s) / len(s) if s else float("nan")
            dm, dh = mean_ci([x - y for x, y in zip(f, s)]) if f else (float("nan"), float("nan"))
            ps = [x for x in (p_acc(e) for e in es if e.get("accused")) if x is not None]
            pe = [post_expected(e) for e in paired]
            pe_s = [post_expected(solver[(tier, e["seed"])]) for e in paired]
            pe_ratio = (sum(pe) / sum(pe_s)) if pe and None not in pe + pe_s and sum(pe_s) > 0 else float("nan")
            lo, hi = boot_ratio(f, s) if len(f) > 1 and agent != "solver" else (float("nan"), float("nan"))
            out.append(dict(label=label, group=sub, agent=agent, tier=tier, n=len(es), seeds=[e["seed"] for e in es],
                            mean=m, ci=h, accuracy=sum(bool(e["correct"]) for e in es) / len(es),
                            accused_rate=sum(1 for e in es if e.get("accused")) / len(es),
                            p_accused=(sum(ps) / len(ps)) if ps else float("nan"), n_p=len(ps),
                            accuse_day=(sum(e["final_day"] for e in es if e.get("accused")) /
                                        max(1, sum(1 for e in es if e.get("accused")))),
                            solver_same_seeds=ms, ratio=(sum(f) / len(f) / ms) if f and ms > 0 else float("nan"),
                            ratio_lo=lo, ratio_hi=hi, diff=dm, diff_ci=dh,
                            post_expected=(sum(pe) / len(pe)) if pe and None not in pe else float("nan"),
                            post_expected_ratio=pe_ratio))
    return out


def to_md(rows: list[dict], version: str, model: str) -> str:
    order = [g[1] + "|" + g[2] for g in groups(version, model)]
    out = ["| tier | run | n | score ± 95% CI | accuracy | accused | mean accuse day | mean P(accused) at accusation | "
           "solver, same seeds | **frontier / solver [95% CI]** | paired diff ± CI | luck-adjusted score | luck-adj. / solver |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["tier"] != "medium", order.index(r["group"] + "|" + r["agent"]))):
        solver = r["agent"] == "solver"
        if solver or r["ratio"] != r["ratio"]:
            ratio = "–"
        elif r["ratio_lo"] != r["ratio_lo"]:
            ratio = f"{r['ratio']:.0%}"
        else:
            ratio = f"{r['ratio']:.0%} [{r['ratio_lo']:.0%}, {r['ratio_hi']:.0%}]"
        out.append(f"| {r['tier']} | {r['label']} | {r['n']} | {_f(r['mean'])} ± {_f(r['ci'])} | {r['accuracy']:.2f} | "
                   f"{r['accused_rate']:.2f} | {r['accuse_day']:.1f} | {_f(r['p_accused'], 2)} | {_f(r['solver_same_seeds'])} | "
                   f"{ratio} | {'–' if solver else _f(r['diff']) + ' ± ' + _f(r['diff_ci'])} | {_f(r['post_expected'])} | "
                   f"{'–' if solver or r['post_expected_ratio'] != r['post_expected_ratio'] else format(r['post_expected_ratio'], '.0%')} |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/runs/committed")
    ap.add_argument("--version", default="v1.3")
    ap.add_argument("--model", default="gemini-4-carbon")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--out-json", default=None)
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split("-"))
    rows = rows_for(Path(a.root), a.version, a.model, set(range(lo, hi + 1)))
    md = to_md(rows, a.version, a.model)
    print(md)
    if a.out_md:
        Path(a.out_md).write_text(md + "\n")
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
