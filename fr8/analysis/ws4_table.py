"""WS4 tiebreaker table: base vs v1 (J4) vs v2 vs v3 on held-out seeds, from eval_hf episodes.jsonl.

Every row is the model playing FULL episodes on its own (train.eval_hf: run_capped(env, policy)); no solver
continuation at eval time. Per model and tier: n, mean score ± 95% CI, accused / correct / abstain rates, valid
tool-call rate, and the paired difference vs each --pair reference (default base) on the seeds both models played
(mean ± 95% CI).

    python -m fr8.analysis.ws4_table base=DIR v1=DIR[,DIR] v2=DIR v3s0=DIR ... [--pair base,v2] [--out OUT.md]
        [--info "v3s0=H100 · 250 GRPO steps" ...]   (per-model GPU / steps label; seeds column is computed)
A DIR is an eval_hf run dir (contains episodes.jsonl); comma-join dirs to pool runs of one model.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ABSTAIN = {"horizon", "tool_cap", "eval_cap"}


def load(dirs: str) -> list[dict]:
    eps, seen = [], set()
    for d in dirs.split(","):
        for line in (Path(d) / "episodes.jsonl").read_text().splitlines():
            e = json.loads(line)
            k = (e["tier"], e["seed"])
            if k not in seen:            # pooled runs: first episode per (tier, seed) wins
                seen.add(k)
                eps.append(e)
    return eps


def mci(xs):
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan")
    m = sum(xs) / n
    if n < 2:
        return m, float("nan")
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def row(eps):
    n = len(eps)
    m, h = mci([e["score"] for e in eps])
    calls = sum(len(e["steps"]) for e in eps)
    inval = sum(e.get("meta", {}).get("invalid_calls", 0) for e in eps)
    return {"n": n, "score": m, "ci": h,
            "accused": sum(e["end_reason"] == "accused" for e in eps) / max(n, 1),
            "correct": sum(bool(e["correct"]) for e in eps) / max(n, 1),
            "abstain": sum(e["end_reason"] in ABSTAIN for e in eps) / max(n, 1),
            "valid": 1 - inval / max(calls, 1)}


def fmt(x, p=3):
    return "–" if x != x else f"{x:.{p}f}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="label=dir[,dir]")
    ap.add_argument("--out", default=None)
    ap.add_argument("--pair", default="base", help="comma list of reference labels for paired Δ columns")
    ap.add_argument("--info", action="append", default=[], help="label=TEXT (GPU, steps) shown per row")
    a = ap.parse_args(argv)
    models = {}
    for spec in a.runs:
        label, dirs = spec.split("=", 1)
        models[label] = load(dirs)
    info = dict(x.split("=", 1) for x in a.info)
    refs = [r for r in a.pair.split(",") if r in models]
    ref_scores = {r: {(e["tier"], e["seed"]): e["score"] for e in models[r]} for r in refs}
    tiers = sorted({e["tier"] for eps in models.values() for e in eps}, key=["easy", "medium", "hard"].index)
    lines = ["| model | run (GPU · steps) | held-out seeds | tier | n | score ± 95% CI | accused | correct | abstain | valid calls | "
             + " | ".join(f"Δ vs {r} (paired n)" for r in refs) + " |",
             "|---|---|---|---|---|---|---|---|---|---|" + "---|" * len(refs)]
    for label, eps in models.items():
        for tier in tiers + ["all"]:
            sub = [e for e in eps if tier == "all" or e["tier"] == tier]
            if not sub:
                continue
            r = row(sub)
            deltas = []
            for ref in refs:
                rs = ref_scores[ref]
                d = [e["score"] - rs[(e["tier"], e["seed"])] for e in sub if (e["tier"], e["seed"]) in rs]
                dm, dh = mci(d)
                deltas.append("–" if label == ref or not d else f"{dm:+.3f} ± {fmt(dh)} ({len(d)})")
            sd = sorted({e["seed"] for e in sub})
            seeds = f"{sd[0]}–{sd[-1]} ({len(sd)})"
            lines.append(f"| {label} | {info.get(label, '–')} | {seeds} | {tier} | {r['n']} | {fmt(r['score'])} ± {fmt(r['ci'])} | {fmt(r['accused'], 2)} | "
                         f"{fmt(r['correct'], 2)} | {fmt(r['abstain'], 2)} | {fmt(r['valid'], 2)} | "
                         + " | ".join(deltas) + " |")
    txt = "\n".join(lines) + ("\n\nEval: each model plays full held-out episodes alone (train.eval_hf, greedy, "
                              "KV reuse, call cap 120). v3 TRAINING used solver rollouts for credit assignment "
                              "(decision-point GRPO); evaluation never does.\n")
    print(txt)
    if a.out:
        Path(a.out).write_text(txt)


if __name__ == "__main__":
    main()
