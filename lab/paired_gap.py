"""Paired-by-day gap: reference days.jsonl vs frontier row JSONs (or another days.jsonl).
Day-clustered bootstrap CI of mean(ref - frontier_mean_over_trials) on the common day ids.
usage: python -m lab.paired_gap --ref <days.jsonl> --agent <glob-or-days.jsonl> [--label NAME] [--boot 20000]"""
import argparse, glob, json, math, random


def load(spec):
    rows = []
    for p in sorted(glob.glob(spec)):
        if p.endswith(".jsonl"):
            rows += [json.loads(l) for l in open(p) if l.strip()]
        elif not p.endswith(".state.json.gz") and "summary" not in p:
            r = json.load(open(p))
            if r.get("invalid"):
                continue
            sc = r.get("scores") or r.get("result") or {}
            rows.append({"seed": r["seed"], "trial": r.get("trial", 0), "reward": sc.get("reward", 0)})
    by = {}
    for r in rows:
        by.setdefault(int(r["seed"]), []).append(float(r["reward"]))
    return by


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - w) / d), min(1.0, (c + w) / d))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--label", default="agent")
    ap.add_argument("--boot", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    ref, ag = load(a.ref), load(a.agent)
    days = sorted(set(ref) & set(ag))
    if not days:
        raise SystemExit("no common day ids")
    diffs = [sum(ref[d]) / len(ref[d]) - sum(ag[d]) / len(ag[d]) for d in days]
    rnd = random.Random(a.seed)
    ms = sorted(sum(rnd.choice(diffs) for _ in diffs) / len(diffs) for _ in range(a.boot))
    lo, hi = ms[int(0.025 * a.boot)], ms[int(0.975 * a.boot) - 1]
    kr, nr = sum(sum(ref[d]) for d in days), sum(len(ref[d]) for d in days)
    ka, na = sum(sum(ag[d]) for d in days), sum(len(ag[d]) for d in days)
    passk = sum(all(x == 1 for x in ag[d]) for d in days) / len(days)
    out = {"label": a.label, "days": len(days), "ref_mean": kr / nr, "ref_wilson": wilson(kr, nr), "agent_mean": ka / na, "agent_n": na,
           "agent_wilson": wilson(ka, na), "agent_pass^k": passk, "paired_mean_diff": sum(diffs) / len(diffs), "paired_95ci": [lo, hi],
           "days_agent_below_ref": sum(x > 0 for x in diffs), "days_agent_above_ref": sum(x < 0 for x in diffs),
           "verdict": "GAP (CI excludes 0)" if lo > 0 else "inconclusive"}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
