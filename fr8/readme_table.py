"""README confirmation table: fresh dev seeds 1000-1999 (never used for tuning), default params from code.

  uv run --python 3.12 --extra dev python fr8/readme_table.py [--seeds 1000-1999] [--procs 3] [--out data/fr8/readme_v12]
Writes table.csv, table.md, RUN.txt (code sha + command). One process per (tier, agent) chunk; <=3 processes.
"""
import argparse, csv, math, statistics as st, subprocess, sys
from multiprocessing import Pool
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TIERS = ["easy", "medium", "hard"]
AGENTS = ["solver", "heuristic", "logs_only", "stop_early", "random", "do_nothing", "restrict_all"]
OVERRIDES = {}  # --set hard.fingerprint_accuracy=0.9 (to confirm a co-tune pick before ENV freezes it)


def work(args):
    tier, agent, seeds, overrides, bw = args
    import dataclasses
    from canary import rules
    if overrides.get(tier):
        rules.TIERS[tier] = dataclasses.replace(rules.TIERS[tier], **overrides[tier])
    from canary.env import Env
    from canary.solver.policy import SolverPolicy
    from canary.baselines import BASELINES, CALIBRATION_POLICIES
    from fr8.j1_grid import run
    pols = {**BASELINES, **CALIBRATION_POLICIES}
    out = []
    for s in seeds:
        r = run(Env(tier=tier, seed=s), (SolverPolicy() if bw is None else SolverPolicy(behaviour_weight=bw)) if agent == "solver" else pols[agent](seed=s), agent)
        out.append((s, r.score, int(r.correct), int(r.accused is not None and not r.correct), int(r.accused is None),
                    r.final_day if r.accused is not None else None))
    return tier, agent, out


def ci(x):
    return 1.96 * st.stdev(x) / math.sqrt(len(x))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1000-1999")
    ap.add_argument("--agents", default=",".join(AGENTS))
    ap.add_argument("--refs", default="heuristic", help="paired solver-minus-X gaps, e.g. heuristic,grok_tactics")
    ap.add_argument("--set", action="append", default=[], help="tier.field=value override (json value)")
    ap.add_argument("--bw", type=float, help="solver behaviour_weight (default: code default)")
    ap.add_argument("--title", default="Canary confirmation table (tiers v1.2)")
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "data/fr8/readme_v12"))
    a = ap.parse_args()
    assert a.procs <= 3
    lo, hi = map(int, a.seeds.split("-"))
    assert 0 <= lo and hi < 10_000, "dev seeds only"
    import json
    ov = {}
    for x in a.set:
        k, v = x.split("=", 1); t, f = k.split(".", 1)
        v = json.loads(v); ov.setdefault(t, {})[f] = tuple(v) if isinstance(v, list) else v
    AGENTS = a.agents.split(",") + [r for r in a.refs.split(",") if r not in a.agents.split(",")]
    seeds = list(range(lo, hi + 1))
    chunks = [seeds[i:i + 250] for i in range(0, len(seeds), 250)]
    jobs = [(t, ag, c, ov, a.bw) for t in TIERS for ag in AGENTS for c in chunks]
    res = {}
    with Pool(a.procs) as p:
        for t, ag, rows in p.imap_unordered(work, jobs):
            res.setdefault((t, ag), []).extend(rows)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    table, md = [], []
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    ssha = subprocess.run(["git", "log", "-1", "--format=%h", "--", "canary/solver", "canary/rules.py", "canary/env.py"],
                          cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "canary"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    md += [f"# {a.title}", "", f"Overrides: {ov or 'none'}; solver behaviour_weight: {a.bw if a.bw is not None else 'code default'}.", "",
           f"Fresh dev seeds {lo}-{hi} (n={len(seeds)} per tier x agent), v0.3 scoring (wrong accusation = -1), "
           f"code {sha} (last canary/ change {ssha}{', DIRTY' if dirty else ''}). Solver = default params from code.", ""]
    for t in TIERS:
        md += [f"## {t}", "", "| agent | n | mean ± 95% CI | accuracy | wrong | none | mean accusation day |", "|---|---|---|---|---|---|---|"]
        for ag in AGENTS:
            rows = sorted(res[(t, ag)])
            sc = [r[1] for r in rows]; days = [r[5] for r in rows if r[5] is not None]
            row = {"tier": t, "agent": ag, "n": len(rows), "mean": round(st.mean(sc), 4), "ci95": round(ci(sc), 4),
                   "accuracy": round(st.mean(r[2] for r in rows), 4), "wrong": round(st.mean(r[3] for r in rows), 4),
                   "none": round(st.mean(r[4] for r in rows), 4), "mean_accuse_day": round(st.mean(days), 2) if days else ""}
            table.append(row)
            md.append(f"| {ag} | {row['n']} | {row['mean']:.3f} ± {row['ci95']:.3f} | {row['accuracy']:.3f} | {row['wrong']:.3f} | {row['none']:.3f} | {row['mean_accuse_day']} |")
        s = dict((r[0], r[1]) for r in res[(t, "solver")])
        for ref in a.refs.split(","):
            h = dict((r[0], r[1]) for r in res[(t, ref)])
            d = [s[k] - h[k] for k in s]
            g, gc = st.mean(d), ci(d)
            need = math.ceil((1.96 * st.stdev(d) / (g / 3)) ** 2) if g > 0 else None
            table.append({"tier": t, "agent": f"solver-{ref} (paired)", "n": len(d), "mean": round(g, 4), "ci95": round(gc, 4),
                          "accuracy": "", "wrong": "", "none": "", "mean_accuse_day": "", "seeds_for_ci_gap3": need})
            md += ["", f"**Solver − {ref} (paired):** {g:.3f} ± {gc:.3f}; seeds needed for CI < gap/3: {need}"]
        md += [""]
    keys = list(dict.fromkeys(k for r in table for k in r))
    with open(out / "table.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, keys); w.writeheader(); w.writerows(table)
    (out / "table.md").write_text("\n".join(md) + "\n")
    (out / "RUN.txt").write_text(f"code={sha} canary_last_change={ssha} dirty={bool(dirty)}\nseeds={lo}-{hi}\n"
                                 f"cmd: uv run --python 3.12 --extra dev python {' '.join(sys.argv)}\n")
    print("\n".join(md))
