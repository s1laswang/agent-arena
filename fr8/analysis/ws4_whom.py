"""WS4 'whom' accuracy: does the model pick the right mole when it accuses?

Two measures per run:
  train  forced_accuse_correct from curve.jsonl (guided-exploration samples forced to start an accuse call; the model
         chooses whom), mean ± 95% CI over the first and last --window steps. Chance is ~1/(#suspects).
  eval   held-out correct / accused from eval_hf episodes.jsonl (Wilson 95% CI), i.e. precision of its accusations.

    python -m fr8.analysis.ws4_whom LABEL=CURVE_JSONL_OR_- [EVAL_DIR[,EVAL_DIR]] ... [--window 100]
    e.g. v3-4k-s0=data/fr8/verda/run-verda-s0/curve.jsonl:data/fr8/verda/h100-3bb7/runs/v3-verda-s0
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def mci(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n < 2:
        return (xs[0] if xs else float("nan")), float("nan"), n
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n), n


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="label=curve.jsonl[:evaldir[,evaldir]] (curve may be '-')")
    ap.add_argument("--window", type=int, default=100)
    a = ap.parse_args(argv)
    out = ["| run | train steps | forced-accuse whom-acc, first W | last W | held-out accused | correct/accused (95% CI) |",
           "|---|---|---|---|---|---|"]
    for spec in a.runs:
        label, rest = spec.split("=", 1)
        curve, _, evals = rest.partition(":")
        first = last = "–"
        steps = "–"
        if curve != "-" and Path(curve).exists():
            recs = [json.loads(l) for l in open(curve) if l.strip()]
            steps = str(len(recs))
            w = min(a.window, len(recs) // 2) or 1
            f = mci([r.get("forced_accuse_correct") for r in recs[:w]])
            l = mci([r.get("forced_accuse_correct") for r in recs[-w:]])
            first = f"{f[0]:.3f} ± {f[1]:.3f} (W={w})"
            last = f"{l[0]:.3f} ± {l[1]:.3f} (W={w})"
        acc = prec = "–"
        if evals:
            seen, eps = set(), []
            for d in evals.split(","):
                p = Path(d) / "episodes.jsonl"
                if not p.exists():
                    continue
                for line in p.read_text().splitlines():
                    e = json.loads(line)
                    if (e["tier"], e["seed"]) not in seen:
                        seen.add((e["tier"], e["seed"]))
                        eps.append(e)
            accused = [e for e in eps if e["end_reason"] == "accused"]
            k = sum(bool(e["correct"]) for e in accused)
            p, lo, hi = wilson(k, len(accused))
            acc = f"{len(accused)}/{len(eps)}"
            prec = f"{k}/{len(accused)} = {p:.2f} ({lo:.2f}–{hi:.2f})" if accused else "no accusations"
        out.append(f"| {label} | {steps} | {first} | {last} | {acc} | {prec} |")
    print("\n".join(out))


if __name__ == "__main__":
    main()
