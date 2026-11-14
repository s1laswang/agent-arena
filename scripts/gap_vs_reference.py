"""Frontier-vs-reference gap, paired by (tier, seed), with a replayed reference agent.

(a) default: for every v1.4 Gemini episode set, collect the valid (tier, seed) pairs, replay
    --ref-agent IN-PROCESS on exactly those seeds (canary.eval.make_env + run_episode, rules v1.4,
    template text provider = the eval/reproduce path), and report the paired ratio
    mean(frontier)/mean(ref) and mean paired difference, each with a paired bootstrap 95% CI.
    With --ref-agent solver the replayed scores are checked against the stored solver
    reference runs (the ones /tmp/gapcalc.py pairs against); mismatches are flagged.
(b) --fresh N --seed0 S --tiers medium,hard: ref-agent vs solver on fresh seeds S..S+N-1.

    uv run --python 3.12 --extra dev python scripts/gap_vs_reference.py --ref-agent solver \
        --staging /tmp/gapjob/staging --fleet /tmp/gapjob/fleet14/data/runs/committed/v1.4
    uv run --python 3.12 --extra dev python scripts/gap_vs_reference.py --ref-agent solver \
        --fresh 400 --seed0 9000 --tiers medium,hard --procs 2
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import statistics as st
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

N_BOOT = 10_000
BOOT_SEED = 20261114
TIERS_VERSION = "v1.4"
REPLAYABLE_MAX_SEED = 899_999  # judge seeds (900000+) are secret-keyed; not replayable here


# --------------------------------------------------------------------------- parsing
def iter_episodes(paths):
    for f in paths:
        with open(f) as fh:
            for line in fh:
                try:
                    yield f, json.loads(line)
                except Exception:
                    continue


def is_invalid(e: dict) -> bool:
    """Same rule as gapcalc.collect."""
    return e.get("valid") is False or e.get("end_reason") == "error" or e.get("score") is None


# Team dedup rule (reproduce-table fix): per (agent, tier, version, seed) keep the NEWEST run by the
# run's own start timestamp in its metadata; fall back to file mtime only when there is none.
# Read order never matters (ties broken by path). With --fleet-git, fleet files without a metadata
# timestamp use the git commit time of that file instead of mtime (archive extraction resets mtime).
TS_KEYS = ("started_at", "start_time", "timestamp")
FLEET_GIT = None  # (repo, ref, fleet_root, prefix_in_repo)


def run_timestamp(path: str) -> tuple[float, str]:
    from datetime import datetime
    meta = Path(path).with_name("meta.json")
    if meta.exists():
        try:
            m = json.loads(meta.read_text())
            for k in TS_KEYS:
                if m.get(k):
                    return datetime.fromisoformat(str(m[k]).replace("Z", "+00:00")).timestamp(), f"meta.{k}"
        except Exception:
            pass
    if FLEET_GIT and str(path).startswith(FLEET_GIT[2]):
        rel = FLEET_GIT[3] + str(path)[len(FLEET_GIT[2]):]
        t = sh("git", "-C", FLEET_GIT[0], "log", "-1", "--format=%ct", FLEET_GIT[1], "--", rel)
        if t:
            return float(t), "git-commit"
    return os.path.getmtime(path), "mtime"


def collect(paths, version: str = TIERS_VERSION):
    """(tier, seed) -> newest valid episode (team rule, order-independent).

    Sets collect.duplicates = {(tier, seed): [dropped {path, ts, ts_src, score, agent}, ...]}.
    """
    cand, invalid = {}, 0
    ts_cache = {}
    for f, e in iter_episodes(paths):
        if is_invalid(e):
            invalid += 1
            continue
        if f not in ts_cache:
            ts_cache[f] = run_timestamp(f)
        ts, src = ts_cache[f]
        k = (e.get("agent"), e["tier"], e.get("tiers_version", version), int(e["seed"]))
        cand.setdefault(k, []).append((ts, f, src, e))
    d, dups = {}, {}
    for (agent, tier, ver, seed), lst in cand.items():
        lst.sort(key=lambda x: (x[0], x[1]))
        keep = lst[-1]
        pk = (tier, seed)
        if pk in d:  # same seed under another agent string in one set: still keep the newest
            prev = d[pk]
            if (prev[0], prev[1]) > (keep[0], keep[1]):
                lst, keep = lst + [keep], prev
            else:
                lst = lst + [prev]
        d[pk] = keep
        dropped = [x for x in lst if x is not keep]
        if dropped:
            dups[pk] = dups.get(pk, []) + [{"path": x[1], "ts": x[0], "ts_src": x[2], "score": x[3]["score"],
                                            "agent": x[3].get("agent")} for x in dropped]
            dups[pk] = [x for x in dups[pk] if x["path"] != keep[1]]
    collect.duplicates = dups
    return {k: v[3] for k, v in d.items()}, invalid


def stored_refs(fleet: str, agent: str = "solver"):
    refs = {}
    for _, e in iter_episodes(glob.glob(f"{fleet}/reference/{agent}-*/episodes.jsonl")):
        refs[(e["tier"], int(e["seed"]))] = e["score"]
    return refs


def frontier_sets(staging: str, fleet: str) -> dict[str, list[str]]:
    sets = {
        "carbon OpenCode (ours+fleet)":
            glob.glob(staging + "/opencode/**/episodes.jsonl", recursive=True)
            + glob.glob(fleet + "/opencode-gemini-4-carbon/*/episodes.jsonl"),
        "carbon in-process (ours+fleet)":
            glob.glob(staging + "/inproc/**/episodes.jsonl", recursive=True)
            + glob.glob(fleet + "/inproc-gemini-4-carbon/*/episodes.jsonl"),
        "3.5-flash OpenCode (fleet)": glob.glob(fleet + "/opencode-gemini-3.5-flash/*/episodes.jsonl"),
    }
    known = {"reference", "opencode-gemini-4-carbon", "inproc-gemini-4-carbon", "opencode-gemini-3.5-flash"}
    for d in sorted(glob.glob(fleet + "/*/")):  # any other v1.4 frontier set in the fleet archive
        name = Path(d).name
        if name not in known:
            sets[f"{name} (fleet)"] = glob.glob(d + "**/episodes.jsonl", recursive=True)
    for d in sorted(glob.glob(staging + "/*/")):
        name = Path(d).name
        if name not in {"opencode", "inproc", "invalid", "logs"}:
            sets[f"staging/{name}"] = glob.glob(d + "**/episodes.jsonl", recursive=True)
    return {k: v for k, v in sets.items() if v}


def pair_keys(frontier: dict, tier: str):
    return sorted(k for k in frontier if k[0] == tier and 0 <= k[1] <= REPLAYABLE_MAX_SEED)


# --------------------------------------------------------------------------- statistics
def paired_bootstrap(a, b, n_boot: int = N_BOOT, seed: int = BOOT_SEED):
    """Resample seed indices jointly. Returns dict with ratio/diff point estimates and 95% CIs."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = len(a)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    sa, sb = a[idx].sum(1), b[idx].sum(1)
    ok = sb > 0
    ratios = np.sort(sa[ok] / sb[ok])
    diffs = np.sort((sa - sb) / n)
    q = lambda x, p: float(np.quantile(x, p)) if len(x) else float("nan")
    return {
        "n": n,
        "mean_a": float(a.mean()), "mean_b": float(b.mean()),
        "ratio": float(a.mean() / b.mean()) if b.mean() > 0 else float("nan"),
        "ratio_ci": [q(ratios, .025), q(ratios, .975)],
        "diff": float((a - b).mean()), "diff_ci": [q(diffs, .025), q(diffs, .975)],
        "n_boot": n_boot, "boot_seed": seed, "n_boot_ratio_valid": int(ok.sum()),
    }


def mean_ci(x, n_boot: int = N_BOOT, seed: int = BOOT_SEED):
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    m = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(1)
    return float(x.mean()), [float(np.quantile(m, .025)), float(np.quantile(m, .975))]


# --------------------------------------------------------------------------- replay
def _policy(agent: str, seed: int):
    try:
        from canary.eval import make_policy_factory, AgentUnavailable
        try:
            return make_policy_factory(agent)(seed)
        except AgentUnavailable:
            pass
    except ImportError:
        pass
    from canary.solver.bench import make_policy
    return make_policy(agent, seed)


def replay_one(job):
    agent, tier, seed = job
    from canary import rules
    assert rules.TIERS_VERSION == TIERS_VERSION, rules.TIERS_VERSION
    from canary.eval import make_env, run_episode
    r = run_episode(make_env(tier, seed), _policy(agent, seed))
    return {"agent": agent, "tier": tier, "seed": seed, "score": r.score, "correct": bool(r.correct),
            "accused": r.end_reason == "accused", "end_reason": r.end_reason,
            "invalid": r.meta.get("valid") is False or r.end_reason == "error"}


def replay(agent, keys, procs):
    jobs = [(agent, t, s) for t, s in sorted(set(keys))]
    if procs <= 1:
        res = [replay_one(j) for j in jobs]
    else:
        with Pool(min(procs, 2)) as p:
            res = p.map(replay_one, jobs, chunksize=4)
    return {(r["tier"], r["seed"]): r for r in res}


# --------------------------------------------------------------------------- provenance
def sh(*cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def manifest(paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.encode()); h.update(Path(p).read_bytes())
    return h.hexdigest()[:16]


def pct(x):
    return f"{x:.0%}" if x == x else "nan"


# --------------------------------------------------------------------------- main
def run_gap(args):
    sets = frontier_sets(args.staging, args.fleet)
    stored = stored_refs(args.fleet, "solver")
    tiers = args.tiers.split(",")
    frontier = {}
    need = set()
    for name, paths in sets.items():
        g, inv = collect(paths)
        frontier[name] = (g, inv, paths, dict(collect.duplicates))
        for t in tiers:
            need.update(pair_keys(g, t))
    t0 = time.time()
    ref = replay(args.ref_agent, need, args.procs)
    replay_s = time.time() - t0
    # reproduction check against the stored solver reference
    check = {"agent": args.ref_agent, "compared": 0, "mismatches": [], "missing_stored": []}
    if args.ref_agent == "solver" or args.check_solver:
        sol = ref if args.ref_agent == "solver" else replay("solver", need, args.procs)
        for k in sorted(need):
            if k not in stored:
                check["missing_stored"].append(list(k)); continue
            check["compared"] += 1
            if abs(sol[k]["score"] - stored[k]) > 1e-9:
                check["mismatches"].append({"tier": k[0], "seed": k[1], "stored": stored[k], "replayed": sol[k]["score"]})
    rows = []
    inv_dir = glob.glob(args.staging + "/invalid/**/episodes.jsonl", recursive=True)
    for name, (g, inv, paths, dups) in frontier.items():
        for t in tiers:
            ks = [k for k in pair_keys(g, t) if not ref[k]["invalid"]]
            if len(ks) < 3:
                continue
            a = [g[k]["score"] for k in ks]
            b = [ref[k]["score"] for k in ks]
            bs = paired_bootstrap(a, b)
            inv_t = sum(1 for _, e in iter_episodes(paths) if e.get("tier") == t and is_invalid(e))
            rows.append({"set": name, "tier": t, **bs, "seeds": [k[1] for k in ks],
                         "invalid_dropped": inv_t,
                         "frontier_wrong": sum(1 for k in ks if g[k].get("accused") and not g[k].get("correct")),
                         "frontier_abstain": sum(1 for k in ks if not g[k].get("accused")),
                         "duplicates": sum(1 for k in dups if k[0] == t),
                         "dropped_duplicates": [{"seed": k[1], **x} for k, v in sorted(dups.items()) if k[0] == t for x in v],
                         "n_files": len(paths)})
    return {"mode": "gap", "ref_agent": args.ref_agent, "rows": rows,
            "staging_invalid_dir_files": len(inv_dir), "repro_check": check,
            "replay_seconds": round(replay_s, 1), "n_replayed": len(need)}


def run_fresh(args):
    tiers = args.tiers.split(",")
    seeds = list(range(args.seed0, args.seed0 + args.fresh))
    keys = [(t, s) for t in tiers for s in seeds]
    ref = replay(args.ref_agent, keys, args.procs)
    sol = ref if args.ref_agent == "solver" else replay("solver", keys, args.procs)
    rows = []
    for t in tiers:
        ks = [k for k in keys if k[0] == t]
        a = [ref[k]["score"] for k in ks]; b = [sol[k]["score"] for k in ks]
        bs = paired_bootstrap(a, b)
        def stats(d):
            acc = [d[k] for k in ks if d[k]["accused"]]
            return {"mean_ci": mean_ci([d[k]["score"] for k in ks]),
                    "acc_when_accusing": (sum(r["correct"] for r in acc) / len(acc)) if acc else float("nan"),
                    "abstain_rate": 1 - len(acc) / len(ks)}
        rows.append({"tier": t, "n": len(ks), "ref": stats(ref), "solver": stats(sol),
                     "diff": bs["diff"], "diff_ci": bs["diff_ci"], "ratio": bs["ratio"], "ratio_ci": bs["ratio_ci"]})
    return {"mode": "fresh", "ref_agent": args.ref_agent, "seeds": [args.seed0, args.seed0 + args.fresh - 1], "rows": rows}


def provenance(args):
    files_s = glob.glob(args.staging + "/**/episodes.jsonl", recursive=True)
    files_f = glob.glob(args.fleet + "/**/episodes.jsonl", recursive=True)
    return {
        "command": "uv run --python 3.12 --extra dev python " + " ".join(sys.argv),
        "repo_commit": sh("git", "rev-parse", "HEAD", cwd=ROOT),
        "repo_dirty": bool(sh("git", "status", "--porcelain", "--", "canary", cwd=ROOT)),
        "staging": args.staging, "staging_files": len(files_s), "staging_sha": manifest(files_s),
        "staging_origin": args.staging_origin,
        "fleet": args.fleet, "fleet_files": len(files_f), "fleet_sha": manifest(files_f),
        "fleet_origin": args.fleet_origin,
        "tiers_version": TIERS_VERSION, "n_boot": N_BOOT, "boot_seed": BOOT_SEED,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }


def to_md(out):
    p = out["provenance"]
    L = [f"# Gap vs reference `{out['ref_agent']}` (rules {TIERS_VERSION})", "",
         f"Generated {p['timestamp']} at repo commit `{p['repo_commit'][:10]}`"
         f"{' (canary/ dirty)' if p['repo_dirty'] else ''}.", "",
         "Command:", "", f"```\n{p['command']}\n```", "",
         "Inputs:", "",
         f"- staging: `{p['staging']}` ({p['staging_files']} episodes.jsonl, sha {p['staging_sha']}); origin {p['staging_origin']}",
         f"- fleet: `{p['fleet']}` ({p['fleet_files']} episodes.jsonl, sha {p['fleet_sha']}); origin {p['fleet_origin']}",
         f"- bootstrap: {p['n_boot']} paired resamples of seeds, numpy default_rng({p['boot_seed']}), percentile 95% CI", ""]
    g = out.get("gap")
    if g:
        c = g["repro_check"]
        L += ["## (a) Frontier / reference, paired on the frontier's own seeds", "",
              f"Reference replayed in-process on {g['n_replayed']} (tier, seed) pairs in {g['replay_seconds']} s "
              "(canary.eval.make_env template provider + run_episode; judge seeds excluded).", ""]
        if c["compared"] or c["missing_stored"]:
            L += [f"Solver reproduction check: {c['compared']} pairs compared with stored `reference/solver-*` runs, "
                  f"**{len(c['mismatches'])} mismatches**, {len(c['missing_stored'])} with no stored score.", ""]
            for m in c["mismatches"][:20]:
                L.append(f"- MISMATCH {m['tier']} seed {m['seed']}: stored {m['stored']} replayed {m['replayed']}")
            L.append("")
        L += [f"Invalid (infra) episodes: dropped by gapcalc's rule (valid is False, end_reason error, or score None) "
              f"in the 'invalid dropped' column; plus {g['staging_invalid_dir_files']} episode files the gemini runner "
              "had already moved to staging/invalid/ (never globbed, same as gapcalc). 'dup' = seeds with more than one "
              "valid episode; team rule keeps the NEWEST run per (agent, tier, version, seed) by metadata start "
              "timestamp, else git commit time (fleet, --fleet-git), else file mtime; read order never matters. "
              "gapcalc instead keeps the last file in glob order, which can differ (see dropped list below).", ""]
        L += ["| set | tier | n | seeds | frontier | ref | ratio [95% CI] | Δ frontier−ref [95% CI] | invalid dropped | dup | wrong | abstain |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in g["rows"]:
            L.append(f"| {r['set']} | {r['tier']} | {r['n']} | {min(r['seeds'])}–{max(r['seeds'])} | {r['mean_a']:+.3f} | {r['mean_b']:+.3f} | "
                     f"{pct(r['ratio'])} [{pct(r['ratio_ci'][0])}, {pct(r['ratio_ci'][1])}] | "
                     f"{r['diff']:+.3f} [{r['diff_ci'][0]:+.3f}, {r['diff_ci'][1]:+.3f}] | {r['invalid_dropped']} | {r['duplicates']} | "
                     f"{r['frontier_wrong']} | {r['frontier_abstain']} |")
        L.append("")
        L += ["### Dropped duplicates", ""]
        for r in g["rows"]:
            for x in r["dropped_duplicates"]:
                L.append(f"- {r['set']} {r['tier']} seed {x['seed']}: dropped score {x['score']} "
                         f"({x['ts_src']} {time.strftime('%H:%M:%S', time.localtime(x['ts']))}) `{x['path']}`")
        L.append("")
    f = out.get("fresh")
    if f:
        L += [f"## (b) `{f['ref_agent']}` vs solver on fresh seeds {f['seeds'][0]}–{f['seeds'][1]}", "",
              "| tier | n | ref mean [CI] | solver mean [CI] | Δ ref−solver [CI] | ratio [CI] | ref acc / abstain | solver acc / abstain |",
              "|---|---|---|---|---|---|---|---|"]
        for r in f["rows"]:
            a, b = r["ref"], r["solver"]
            L.append(f"| {r['tier']} | {r['n']} | {a['mean_ci'][0]:+.3f} [{a['mean_ci'][1][0]:+.3f}, {a['mean_ci'][1][1]:+.3f}] | "
                     f"{b['mean_ci'][0]:+.3f} [{b['mean_ci'][1][0]:+.3f}, {b['mean_ci'][1][1]:+.3f}] | "
                     f"{r['diff']:+.3f} [{r['diff_ci'][0]:+.3f}, {r['diff_ci'][1]:+.3f}] | {pct(r['ratio'])} [{pct(r['ratio_ci'][0])}, {pct(r['ratio_ci'][1])}] | "
                     f"{pct(a['acc_when_accusing'])} / {pct(a['abstain_rate'])} | {pct(b['acc_when_accusing'])} / {pct(b['abstain_rate'])} |")
        L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-agent", default="solver")
    ap.add_argument("--staging", default="/tmp/gapjob/staging")
    ap.add_argument("--fleet", default="/tmp/gapjob/fleet14/data/runs/committed/v1.4")
    ap.add_argument("--staging-origin", default="copy of ~/junction-aimo-team/wt/justSilas-gemini/data/runs/staging-gemini-v1.4 @ e8a6fdf (clean), copied with cp -Rp (mtimes kept)")
    ap.add_argument("--fleet-origin", default="copy of /tmp/fleet14 = git-archive of origin/fr8/afterquery/v14-runs @ 91d57ff (all 46 episodes.jsonl byte-identical)")
    ap.add_argument("--tiers", default="medium,hard")
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--fresh", type=int, default=0)
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--skip-gap", action="store_true", help="only run (b)")
    ap.add_argument("--check-solver", action="store_true", help="also replay solver and check it vs stored runs")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fleet-git", default="~/junction-aimo-team/agent-arena:origin/fr8/afterquery/v14-runs",
                    help="REPO:REF the fleet archive came from (commit time = run time fallback); '' to disable")
    args = ap.parse_args(argv)
    args.procs = max(1, min(args.procs, 2))
    global FLEET_GIT
    if args.fleet_git:
        repo, ref = args.fleet_git.rsplit(":", 1)
        FLEET_GIT = (os.path.expanduser(repo), ref, args.fleet.rstrip("/"), "data/runs/committed/v1.4")
    out = {"ref_agent": args.ref_agent, "provenance": provenance(args)}
    if not args.skip_gap:
        out["gap"] = run_gap(args)
    if args.fresh:
        out["fresh"] = run_fresh(args)
    stem = args.out or str(ROOT / f"results/gap_vs_{args.ref_agent}_{TIERS_VERSION}")
    Path(stem).parent.mkdir(parents=True, exist_ok=True)
    Path(stem + ".json").write_text(json.dumps(out, indent=1))
    md = to_md(out)
    Path(stem + ".md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
