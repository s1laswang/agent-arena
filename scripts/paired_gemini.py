"""Paired Gemini-vs-solver table for one tiers version (no API cost). Same method as scripts/paired_v13.py.

    python scripts/paired_gemini.py --version v1.3 [--seeds 0-9] [--out-md ...] [--out-json ...]

Rows: OpenCode + Gemini over MCP (judges' shape) and the in-process Gemini loop from
data/runs/committed/<version>/{opencode,inproc}-<model>/, the earlier gpt-5.5 rows for context (v1.3 only), the
reference solver and baselines from data/runs/committed/<version>/reference/. Each row is restricted to the seeds it
shares with the solver: frontier/solver = mean_F / mean_S with a paired bootstrap 95% CI over seeds (10,000
resamples), the paired difference, the solver posterior P(accused) at the accusation and the luck-adjusted score:
each accusation scored as P*V - (1-P) under the solver's exact posterior at that step (0 without an accusation),
paired with the solver's own luck-adjusted score on the same seeds (ratio with a paired bootstrap 95% CI).
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


ALT_LABEL = ("OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply "
             "counted as 0 instead of retried")


def empty_reply_seeds(run_dir: Path, tier: str) -> set[int]:
    """Seeds with an excluded attempt that ended on an empty model reply (from merge_staging's meta.json)."""
    f = run_dir / tier / "meta.json"
    if not f.exists():
        return set()
    out = set()
    for entry in json.loads(f.read_text()).get("infra_invalid_attempts_excluded") or []:
        name, _, why = entry.partition(":")
        if "empty_model_response" in why:
            out.add(int(name.split("-")[2]))   # opencode-<tier>-<seed>-<hhmmss>
    return out


def groups(version: str, model: str) -> list[tuple[str, str, str]]:
    g = [(f"OpenCode + {model} over MCP (judges' shape)", f"{version}/opencode-{model}", f"opencode:google/{model}"),
         (f"OpenCode + {model} over MCP, extension (seeds 30-59)", f"{version}/opencode-{model}-ext",
          f"opencode:google/{model}"),
         (f"OpenCode + {model} over MCP, pooled (primary + extension)",
          f"{version}/opencode-{model}+{version}/opencode-{model}-ext", f"opencode:google/{model}"),
         (ALT_LABEL, f"{version}/opencode-{model}", f"opencode:google/{model}"),
         (f"in-process {model} (full history, thought-signature replay)", f"{version}/inproc-{model}", f"gemini:{model}")]
    if version == "v1.4":
        g += [("OpenCode + gemini-3.5-flash over MCP (second Gemini family; the API reports modelVersion "
               "gemini-3.6-flash for this id)", "v1.4/opencode-gemini-3.5-flash", "opencode:google/gemini-3.5-flash")]
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
        dirs = [root / p for p in sub.split("+")]
        if not all(d.exists() for d in dirs):
            continue
        by_dir = [[e for e in load_runs(d) if e["agent"] == agent and e["seed"] in seeds
                   and (e.get("meta") or {}).get("valid") is not False] for d in dirs]
        for tier in ("medium", "hard"):
            if len(dirs) > 1 and not all(any(e["tier"] == tier for e in eps) for eps in by_dir):
                continue
            es = sorted((e for eps in by_dir for e in eps if e["tier"] == tier), key=lambda e: e["seed"])
            if label == ALT_LABEL:
                zero = set().union(*(empty_reply_seeds(d, tier) for d in dirs))
                if not zero:
                    continue
                es = [dict(e, score=0.0, correct=False, accused=None) if e["seed"] in zero else e for e in es]
                have = {e["seed"] for e in es}
                es += [{"tier": tier, "seed": z, "agent": agent, "score": 0.0, "correct": False, "accused": None,
                        "final_day": 0, "steps": [], "meta": {}} for z in sorted(zero - have) if z in seeds]
                es.sort(key=lambda e: e["seed"])
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
            pe_ok = bool(pe) and None not in pe + pe_s
            pe_ratio = (sum(pe) / sum(pe_s)) if pe_ok and sum(pe_s) > 0 else float("nan")
            pe_lo, pe_hi = (boot_ratio(pe, pe_s) if pe_ok and len(pe) > 1 and agent != "solver"
                            else (float("nan"), float("nan")))
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
                            post_expected_ratio=pe_ratio, post_expected_lo=pe_lo, post_expected_hi=pe_hi,
                            solver_post_expected=(sum(pe_s) / len(pe_s)) if pe_ok else float("nan")))
    return out


def _luck(r: dict) -> str:
    if r["agent"] == "solver" or r["post_expected_ratio"] != r["post_expected_ratio"]:
        return "–"
    if r["post_expected_lo"] != r["post_expected_lo"]:
        return f"{r['post_expected_ratio']:.0%}"
    return f"**{r['post_expected_ratio']:.0%} [{r['post_expected_lo']:.0%}, {r['post_expected_hi']:.0%}]**"


def to_md(rows: list[dict], version: str, model: str) -> str:
    order = [g[0] for g in groups(version, model)]
    out = ["| tier | run | n | score ± 95% CI | accuracy | accused | mean accuse day | mean P(accused) at accusation | "
           "solver, same seeds | **frontier / solver [95% CI]** | paired diff ± CI | luck-adjusted score | **luck-adj. / solver's luck-adj. [95% CI]** |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["tier"] != "medium", order.index(r["label"]))):
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
                   f"{_luck(r)} |")
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
