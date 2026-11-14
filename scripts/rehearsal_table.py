"""Summarise a Harbor judge rehearsal: per-task rewards per job, each job's mean vs the oracle, run-to-run spread.

    python scripts/rehearsal_table.py results/harbor/rehearsal [--out results/harbor/rehearsal/TABLE.md]

Every job directory under the folder is one column. The reward is the verifier's (the HMAC-checked server ledger);
the ledger copy in artifacts/ gives the accused id, the day and whether the accusation was correct.

Infrastructure failures are not scores. A trial is `infra` when its episode never finished (the server ledger is not
`done`: no accusation, no horizon) AND the cause is outside the agent's play: Harbor's AgentSetupTimeoutError or
ApiRateLimitError, or a CLI error event (`{"type":"error"}`, e.g. a provider 429 or a rejected thought_signature) in
the agent's OpenCode transcript. An agent that simply stops without accusing and without an error keeps its 0.
Infra trials are left out of the headline mean (as in docs/reports/gap.md) and counted in an "infra as 0" column.

A job named `<job>-infra-rerun` re-runs only the infra tasks of `<job>` (same build, same worlds). Its trials fill
those tasks, and only those, marked with † in the table; a task that was valid in `<job>` is never replaced.

Harbor reports NonZeroAgentExitCodeError on most OpenCode trials because OpenCode exits non-zero after the game has
ended; when the ledger is done, that trial is a valid result.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
from pathlib import Path

ORDER = ["oracle", "opencode-1", "opencode-2", "opencode-3", "opencode", "do_nothing", "stop_early"]
INFRA_EXC = {"AgentSetupTimeoutError", "ApiRateLimitError"}
RERUN = "-infra-rerun"


def _cli_error(trial: Path) -> str | None:
    f = trial / "agent/opencode.txt"
    if not f.exists():
        return None
    for line in f.read_text(errors="replace").splitlines():
        if '"type":"error"' in line.replace(" ", ""):
            low = line.lower()
            if "thought_signature" in low:
                return "thought_signature rejected"
            if "quota" in low or "429" in low or "resource_exhausted" in low or "rate" in low:
                return "provider rate limit"
            m = re.search(r'"message":"([^"]{0,60})', line)
            return "CLI error: " + (m.group(1) if m else "?")
    return None


def trials(job: Path) -> dict[str, dict]:
    out = {}
    for rf in sorted(job.glob("canary-*/result.json")):
        r = json.loads(rf.read_text())
        task = r.get("task_name", rf.parent.name).split("/")[-1]
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        led = rf.parent / "artifacts/ledger.json"
        lj = json.loads(led.read_text()) if led.exists() else {}
        exc = r.get("exception_info")
        exc_t = exc.get("exception_type") if isinstance(exc, dict) else (str(exc)[:60] if exc else None)
        why = None
        if not lj.get("done"):
            if exc_t in INFRA_EXC:
                why = {"ApiRateLimitError": "provider rate limit", "AgentSetupTimeoutError": "agent setup timeout"}[exc_t]
            else:
                why = _cli_error(rf.parent)
        if rew is None and why is None:
            why = f"no verifier reward ({exc_t})"
        out[task] = {"reward": None if rew is None else float(rew), "accused": lj.get("accused"),
                     "correct": lj.get("correct"), "day": lj.get("final_day"), "done": bool(lj.get("done")),
                     "exc": exc_t, "infra": why, "rerun": False}
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
    if not vals:
        return float("nan"), float("nan")
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def load(folder: Path) -> dict[str, dict]:
    raw = {p.name: trials(p) for p in sorted(folder.iterdir()) if p.is_dir() and list(p.glob("canary-*/result.json"))}
    jobs = {n: dict(j) for n, j in raw.items() if not n.endswith(RERUN)}
    for n, j in raw.items():
        if not n.endswith(RERUN) or n[: -len(RERUN)] not in jobs:
            continue
        base = jobs[n[: -len(RERUN)]]
        for t, x in j.items():
            if t in base and base[t]["infra"]:
                base[t] = {**x, "rerun": True, "first": base[t]["infra"]}
    return jobs


def valid(x) -> bool:
    return x is not None and not x["infra"] and x["reward"] is not None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    jobs = load(a.folder)
    names = sorted(jobs, key=lambda n: (ORDER.index(n) if n in ORDER else 99, n))
    tasks = sorted({t for j in jobs.values() for t in j})
    L = ["| task | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
    for t in tasks:
        cells = []
        for n in names:
            x = jobs[n].get(t)
            if x is None:
                cells.append("–")
            elif x["infra"]:
                cells.append(f"infra ({x['infra']})" + (" †" if x["rerun"] else ""))
            else:
                mark = "" if x["accused"] is None else (" ✓" if x["correct"] else " ✗")
                day = f" d{x['day']}" if x["accused"] is not None else ""
                cells.append(f"{x['reward']:+.2f}{mark}{day}" + (" †" if x["rerun"] else ""))
        L.append(f"| {t} | " + " | ".join(cells) + " |")
    L.append("| **mean (valid trials)** | " + " | ".join(
        f"**{mean([x['reward'] for x in jobs[n].values() if valid(x)]):+.3f}**" for n in names) + " |")
    o = jobs.get("oracle", {})
    L += ["", "| run | n valid | infra (excluded) | correct / accused | mean | oracle, same tasks | "
          "run / oracle [95% paired bootstrap CI] | diff | mean, infra as 0 |",
          "|---|---:|---:|---|---:|---:|---|---:|---:|"]
    agent_means = []
    for n in names:
        if n == "oracle":
            continue
        j = jobs[n]
        both = [t for t in tasks if valid(j.get(t)) and valid(o.get(t))]
        ra, rb = [j[t]["reward"] for t in both], [o[t]["reward"] for t in both]
        ninfra = sum(1 for x in j.values() if x["infra"])
        acc = [x for x in j.values() if valid(x) and x["accused"] is not None]
        ok = bool(both) and mean(rb) > 0
        ratio = mean(ra) / mean(rb) if ok else float("nan")
        ci = boot_ratio(ra, rb) if ok else (float("nan"), float("nan"))
        as0 = mean([0.0 if x["infra"] or x["reward"] is None else x["reward"] for x in j.values()])
        if n.startswith("opencode"):
            agent_means.append(mean(ra))
        L.append(f"| {n} | {len(both)} | {ninfra} | {sum(1 for x in acc if x['correct'])} / {len(acc)} | "
                 f"{mean(ra):+.3f} | {mean(rb):+.3f} | {ratio:.0%} [{ci[0]:.0%}, {ci[1]:.0%}] | "
                 f"{mean(ra) - mean(rb):+.3f} | {as0:+.3f} |")
    reruns = [(n, t, x["first"]) for n in names for t, x in jobs[n].items() if x.get("rerun")]
    if reruns:
        L += ["", "† re-run in `<job>-infra-rerun` because the first attempt was an infrastructure failure: "
              + "; ".join(f"{n} {t} ({w})" for n, t, w in reruns) + "."]
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
