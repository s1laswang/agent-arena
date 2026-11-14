#!/usr/bin/env python3
"""Summarize Harbor job folders of Poisoned Inbox runs (stdlib only).

    python harbor/summarize.py harbor/jobs                 # every job under the folder
    python harbor/summarize.py harbor/jobs/2026-11-15__reference harbor/jobs/...
    python harbor/summarize.py harbor/jobs --prefix 20261115-0900 --json results/harbor.json

Per job it prints: trials, mean reward, pass^k (an episode counts only if ALL its attempts
scored 1), mean reward per family, the most common failure tags, and errors. Failure tags
come from each trial's verifier/verdict.json, written by our tests/verify.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def find_jobs(paths: list[str], prefix: str = "") -> list[Path]:
    jobs = []
    for p in map(Path, paths):
        if (p / "result.json").exists() and (p / "config.json").exists():
            jobs.append(p)
        elif p.is_dir():
            jobs += sorted(c for c in p.iterdir() if c.is_dir() and (c / "result.json").exists()
                           and (c / "config.json").exists() and c.name.startswith(prefix))
    return jobs


def agent_label(trial_cfg: dict) -> str:
    agent = (trial_cfg or {}).get("agent") or {}
    name = agent.get("name") or agent.get("import_path") or "?"
    model = agent.get("model_name")
    env = agent.get("env") or {}
    sol = env.get("PINBOX_SOLUTION") if isinstance(env, dict) else None
    if name == "oracle":
        return f"oracle:{sol or 'reference'}"
    return f"{name} ({model})" if model else name


def read_job(job: Path) -> dict:
    trials = []
    for tdir in sorted(c for c in job.iterdir() if c.is_dir()):
        res = _load(tdir / "result.json")
        if not isinstance(res, dict) or "trial_name" not in res:
            continue
        verdict = _load(tdir / "verifier" / "verdict.json") or {}
        rewards = (res.get("verifier_result") or {}).get("rewards") or {}
        task = str(res.get("task_name") or "").split("/")[-1]
        exc = res.get("exception_info")
        trials.append({
            "task": task,
            "family": task.split("-s")[0] if "-s" in task else task,
            "reward": rewards.get("reward"),
            "progress": verdict.get("progress"),
            "failure_tags": verdict.get("failure_tags") or [],
            "problems": verdict.get("problems") or [],
            "error": (exc or {}).get("exception_type") if isinstance(exc, dict) else (str(exc) if exc else None),
            "agent": agent_label(res.get("config") or {}),
            "trial": res.get("trial_name"),
        })
    return {"job": job.name, "path": str(job), "trials": trials}


def summarize(job: dict) -> dict:
    trials = job["trials"]
    scored = [t for t in trials if isinstance(t["reward"], (int, float))]
    by_task = defaultdict(list)
    for t in trials:
        by_task[t["task"]].append(t)
    k = max((len(v) for v in by_task.values()), default=0)
    pass_k = (sum(1 for v in by_task.values() if all(t["reward"] == 1 for t in v)) / len(by_task)) if by_task else 0.0
    fam = defaultdict(list)
    for t in trials:
        fam[t["family"]].append(t["reward"] if isinstance(t["reward"], (int, float)) else 0.0)
    tags = Counter(tag for t in trials for tag in t["failure_tags"])
    agents = sorted({t["agent"] for t in trials})
    return {
        "job": job["job"],
        "agent": ", ".join(agents),
        "trials": len(trials),
        "errors": sum(1 for t in trials if t["error"] or t["reward"] is None),
        # Errored trials count as 0, like a failed run.
        "mean_reward": round(sum(t["reward"] if isinstance(t["reward"], (int, float)) else 0.0 for t in trials)
                             / len(trials), 4) if trials else 0.0,
        "scored_trials": len(scored),
        "episodes": len(by_task),
        "attempts_per_episode": k,
        "pass_all_k": round(pass_k, 4),
        "by_family": {f: round(sum(v) / len(v), 4) for f, v in sorted(fam.items())},
        "top_failure_tags": dict(tags.most_common(8)),
        "error_types": dict(Counter(t["error"] for t in trials if t["error"])),
    }


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass
    p = argparse.ArgumentParser(description="Summarize Poisoned Inbox Harbor jobs")
    p.add_argument("paths", nargs="+", help="job folders, or a jobs folder holding them")
    p.add_argument("--prefix", default="", help="only jobs whose folder name starts with this")
    p.add_argument("--json", default=None, help="also write the summary (and every trial) to this JSON file")
    a = p.parse_args(argv)

    jobs = [read_job(j) for j in find_jobs(a.paths, a.prefix)]
    if not jobs:
        print("no Harbor job folders found", file=sys.stderr)
        return 1
    rows = [summarize(j) for j in jobs]
    head = f"{'job':34} {'agent':34} {'trials':>6} {'err':>4} {'mean':>6} {'pass^k':>7}  per family"
    print(head)
    print("-" * len(head))
    for r in rows:
        fam = "  ".join(f"{f} {v:.2f}" for f, v in r["by_family"].items())
        print(f"{r['job'][:34]:34} {r['agent'][:34]:34} {r['trials']:>6} {r['errors']:>4} "
              f"{r['mean_reward']:>6.3f} {r['pass_all_k']:>7.3f}  {fam}")
    for r in rows:
        if r["top_failure_tags"] or r["error_types"]:
            print(f"\n{r['job']}:")
            if r["top_failure_tags"]:
                print("  failure tags: " + ", ".join(f"{t} x{n}" for t, n in r["top_failure_tags"].items()))
            if r["error_types"]:
                print("  errors: " + ", ".join(f"{t} x{n}" for t, n in r["error_types"].items()))
    if a.json:
        out = Path(a.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"generated_by": "harbor/summarize.py", "jobs": rows,
                                   "trials": {j["job"]: j["trials"] for j in jobs}},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
