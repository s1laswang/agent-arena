"""Summarise a Harbor judge rehearsal: per-task rewards per job, each job's mean vs the oracle, run-to-run spread.

    python scripts/rehearsal_table.py results/harbor/rehearsal [--out results/harbor/rehearsal/TABLE.md]

Every job directory under the folder is one column. The reward is the verifier's (the HMAC-checked server ledger);
the ledger copy in artifacts/ gives the accused id, the day and whether the accusation was correct. A trial with no
verifier reward is an infrastructure failure and is shown as `exc`, never as 0.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

ORDER = ["oracle", "opencode-1", "opencode-2", "opencode-3", "opencode", "do_nothing", "stop_early"]


def trials(job: Path) -> dict[str, dict]:
    out = {}
    for rf in sorted(job.glob("canary-*/result.json")):
        r = json.loads(rf.read_text())
        task = r.get("task_name", rf.parent.name).split("/")[-1]
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        led = rf.parent / "artifacts/ledger.json"
        lj = json.loads(led.read_text()) if led.exists() else {}
        exc = r.get("exception_info")
        out[task] = {"reward": None if rew is None else float(rew), "accused": lj.get("accused"),
                     "correct": lj.get("correct"), "day": lj.get("final_day"), "end": lj.get("end_reason"),
                     "exc": (exc or {}).get("exception_type") if isinstance(exc, dict) else (str(exc)[:60] if exc else None)}
    return out


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def boot_ratio(a: list[float], b: list[float], n=10000, seed=0):
    """Paired bootstrap 95% CI of mean(a)/mean(b) over tasks."""
    rng = random.Random(seed)
    k, vals = len(a), []
    for _ in range(n):
        idx = [rng.randrange(k) for _ in range(k)]
        mb = mean([b[i] for i in idx])
        if mb > 0:
            vals.append(mean([a[i] for i in idx]) / mb)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    jobs = {p.name: trials(p) for p in sorted(a.folder.iterdir()) if p.is_dir() and list(p.glob("canary-*/result.json"))}
    names = sorted(jobs, key=lambda n: (ORDER.index(n) if n in ORDER else 99, n))
    tasks = sorted({t for j in jobs.values() for t in j})
    L = [f"| task | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
    for t in tasks:
        cells = []
        for n in names:
            x = jobs[n].get(t)
            if x is None:
                cells.append("–")
            elif x["reward"] is None:
                cells.append(f"exc ({x['exc']})")
            else:
                mark = "" if x["accused"] is None else (" ✓" if x["correct"] else " ✗")
                day = f" d{x['day']}" if x["accused"] is not None else ""
                cells.append(f"{x['reward']:+.2f}{mark}{day}")
        L.append(f"| {t} | " + " | ".join(cells) + " |")
    o = jobs.get("oracle", {})
    L.append("| **mean** | " + " | ".join(
        f"**{mean([x['reward'] for x in jobs[n].values() if x['reward'] is not None]):+.3f}**" for n in names) + " |")
    L += ["", "| run | n valid | exceptions (Harbor) | infra (no reward) | correct / accused | mean | oracle, same tasks | run / oracle [95% paired bootstrap CI] | diff |",
          "|---|---:|---:|---:|---|---:|---:|---|---:|"]
    agent_means = []
    for n in names:
        if n == "oracle":
            continue
        j = jobs[n]
        both = [t for t in tasks if t in j and j[t]["reward"] is not None and t in o and o[t]["reward"] is not None]
        ra, rb = [j[t]["reward"] for t in both], [o[t]["reward"] for t in both]
        nexc = sum(1 for x in j.values() if x["exc"])
        ninfra = sum(1 for x in j.values() if x["reward"] is None)
        acc = [x for x in j.values() if x["accused"] is not None]
        ratio = mean(ra) / mean(rb) if both and mean(rb) > 0 else float("nan")
        ci = boot_ratio(ra, rb) if both and mean(rb) > 0 else (float("nan"), float("nan"))
        if n.startswith("opencode"):
            agent_means.append(mean(ra))
        L.append(f"| {n} | {len(both)} | {nexc} | {ninfra} | {sum(1 for x in acc if x['correct'])} / {len(acc)} | "
                 f"{mean(ra):+.3f} | {mean(rb):+.3f} | {ratio:.0%} [{ci[0]:.0%}, {ci[1]:.0%}] | {mean(ra) - mean(rb):+.3f} |")
    if len(agent_means) >= 2:
        m = mean(agent_means)
        sd = math.sqrt(sum((x - m) ** 2 for x in agent_means) / (len(agent_means) - 1))
        L += ["", f"Run-to-run spread over {len(agent_means)} OpenCode runs: run means "
              + ", ".join(f"{x:+.3f}" for x in agent_means)
              + f"; mean of means {m:+.3f}, SD {sd:.3f}, range {max(agent_means) - min(agent_means):.3f}."]
    txt = "\n".join(L) + "\n"
    print(txt)
    if a.out:
        a.out.write_text(txt)


if __name__ == "__main__":
    main()
