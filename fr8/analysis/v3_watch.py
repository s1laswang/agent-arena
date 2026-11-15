"""v3 early-kill check (CEO rule): is the VALID-only signal moving by step ~100?

    python -m fr8.analysis.v3_watch RUN/curve.jsonl [--at 100] [--window 25]
Compares the first and last --window steps up to --at on: gain_vs_solver_valid (valid reward minus the solver's own
score at the same states), reward_valid, action_entropy, accuse/continue mix, valid rate.
Verdict FLAT if the valid-only gain moved < 1 pooled SE, COLLAPSED if action entropy < 0.15 nats (8 samples).
Prints a verdict; the FR8 head decides (kill only our own job ids from OURS.txt).
"""
import argparse
import json
import math


def ms(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return float("nan"), float("nan")
    m = sum(xs) / len(xs)
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1) / len(xs))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("curve")
    ap.add_argument("--at", type=int, default=100)
    ap.add_argument("--window", type=int, default=25)
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.curve)]
    recs = [r for r in recs if r["step"] < a.at]
    if len(recs) < 2 * a.window:
        print(f"only {len(recs)} steps < {2 * a.window}: too early"); return
    early, late = recs[:a.window], recs[-a.window:]
    out = {}
    for k in ("gain_vs_solver_valid", "reward_valid", "reward", "valid", "action_entropy", "accuse_frac", "continue_frac"):
        (m0, s0), (m1, s1) = ms([r.get(k) for r in early]), ms([r.get(k) for r in late])
        out[k] = (round(m0, 4), round(m1, 4), round(m1 - m0, 4), round(math.sqrt(s0 ** 2 + s1 ** 2), 4))
        print(f"{k:22s} early {m0:+.4f}  late {m1:+.4f}  delta {m1 - m0:+.4f}  (pooled SE {math.sqrt(s0**2 + s1**2):.4f})")
    g = out["gain_vs_solver_valid"]
    verdict = "COLLAPSED" if out["action_entropy"][1] < 0.15 else ("FLAT" if abs(g[2]) < g[3] else
                                                                  ("IMPROVING" if g[2] > 0 else "WORSENING"))
    print("VERDICT", verdict, f"(steps {recs[0]['step']}-{recs[-1]['step']})")


if __name__ == "__main__":
    main()
