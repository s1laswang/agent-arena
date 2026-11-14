"""Budget-guarded driver for the official v1.3 frontier measurement (one episode per process).

    python scripts/budget_runner.py --budget-stop 90 --staging data/runs/staging-v1.3 [--dry-run]

Jobs: Codex gpt-5.5 over MCP (priority, 2 slots) on dev seeds 0-9 x {medium, hard}, and the in-process
LLMPolicy (full history, Responses API) on the same seeds, interleaved medium/hard seed by seed (2 slots).
Each episode runs in its own staging dir (own MCP server / port for Codex); merge_staging() assembles the
final run dirs. Spend after every episode = sum of per-episode cost estimates at gpt-5.5 list prices
(input $5, cached input $0.50, output $30 per 1M; verified on developers.openai.com/api/docs/pricing).

Launch rule: launch a job only if  spent + reserve(in-flight) + E(job) [+ reserve(pending Codex) for
in-process jobs] <= budget_stop, where E = expected cost per episode of that harness. In-flight
episodes are always allowed to finish. Processes are tracked by PID (never pkill by pattern).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

UV = ["uv", "run", "--python", "3.12", "--extra", "llm", "--extra", "dev", "python"]
PRIOR = {"codex": 2.2, "inproc": 3.0}


def ep_cost(ep: dict) -> tuple[float, float]:
    """(estimate with cached input at the cached price, upper bound with all input at full price)."""
    u = (ep.get("meta") or {}).get("usage") or {}
    est = u.get("cost_usd_est", u.get("cost_usd", 0.0)) or 0.0
    upper = u.get("cost_usd_upper", u.get("cost_usd", est)) or est
    return float(est), float(upper)


def read_eps(d: Path) -> list[dict]:
    f = d / "episodes.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


class Job:
    def __init__(self, harness: str, tier: str, seed: int, staging: Path):
        self.harness, self.tier, self.seed = harness, tier, seed
        self.dir = staging / harness / tier / str(seed)
        self.proc: subprocess.Popen | None = None
        self.t0 = 0.0

    @property
    def key(self) -> str:
        return f"{self.harness}/{self.tier}/{self.seed}"

    def cmd(self) -> list[str]:
        if self.harness == "codex":
            return UV + ["-m", "canary.agents.frontier.codex_run", "--model", "gpt-5.5", "--tier", self.tier,
                         "--seeds", str(self.seed), "--jobs", "1", "--out", str(self.dir)]
        return UV + ["-m", "canary.agents.play", "--agent", "openai:gpt-5.5", "--tier", self.tier,
                     "--seeds", str(self.seed), "--out", str(self.dir)]

    def done(self) -> bool:
        return bool(read_eps(self.dir))


def expected(costs: list[float], harness: str) -> float:
    if not costs:
        return PRIOR[harness]
    m = statistics.mean(costs)
    sd = statistics.stdev(costs) if len(costs) > 1 else 0.5 * m
    return max(m + 0.5 * sd, 0.5)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", default="data/runs/staging-v1.3")
    ap.add_argument("--budget-stop", type=float, default=90.0)
    ap.add_argument("--already-spent", type=float, default=0.0, help="spend outside staging (smoke runs)")
    ap.add_argument("--codex-slots", type=int, default=2)
    ap.add_argument("--inproc-slots", type=int, default=2)
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--skip", default="", help="comma list of harness/tier/seed already covered (e.g. inproc/medium/0)")
    ap.add_argument("--ledger", default="data/runs/staging-v1.3/spend_ledger.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split("-"))
    seeds = list(range(lo, hi + 1))
    staging = Path(a.staging)
    skip = {s for s in a.skip.split(",") if s}
    codex = [Job("codex", t, s, staging) for s in seeds for t in ("medium", "hard")]
    inproc = [Job("inproc", t, s, staging) for s in seeds for t in ("medium", "hard")]
    queue = {"codex": [j for j in codex if j.key not in skip and not j.done()],
             "inproc": [j for j in inproc if j.key not in skip and not j.done()]}
    slots = {"codex": a.codex_slots, "inproc": a.inproc_slots}
    running: list[Job] = []
    finished: list[Job] = [j for j in codex + inproc if j.done()]
    stopped = False
    ledger = Path(a.ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    logs = staging / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    def spend() -> tuple[float, float, dict[str, list[float]]]:
        est = up = 0.0
        per: dict[str, list[float]] = {"codex": [], "inproc": []}
        for j in finished:
            for ep in read_eps(j.dir):
                e, u = ep_cost(ep)
                est, up = est + e, up + u
                per[j.harness].append(e)
        return est + a.already_spent, up + a.already_spent, per

    def log(msg: str) -> None:
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    while queue["codex"] or queue["inproc"] or running:
        for j in list(running):
            if j.proc.poll() is not None:
                running.remove(j)
                finished.append(j)
                eps = read_eps(j.dir)
                est, up, per = spend()
                if eps:
                    ep = eps[-1]
                    e, u = ep_cost(ep)
                    log(f"DONE {j.key} rc={j.proc.returncode} score={ep.get('score')} correct={ep.get('correct')} "
                        f"end={ep.get('end_reason')} cost_est=${e:.2f} (upper ${u:.2f}) wall={time.time()-j.t0:.0f}s "
                        f"| cumulative est ${est:.2f} (upper ${up:.2f})")
                else:
                    log(f"DONE {j.key} rc={j.proc.returncode} NO EPISODE WRITTEN | cumulative est ${est:.2f}")
                with ledger.open("a") as f:
                    f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job": j.key, "rc": j.proc.returncode,
                                        "cost_est": ep_cost(eps[-1])[0] if eps else None,
                                        "cost_upper": ep_cost(eps[-1])[1] if eps else None,
                                        "cumulative_est": round(est, 4), "cumulative_upper": round(up, 4)}) + "\n")
        if not stopped:
            for h in ("codex", "inproc"):
                while queue[h] and sum(1 for r in running if r.harness == h) < slots[h]:
                    est, _, per = spend()
                    E = {k: expected(per[k], k) for k in per}
                    reserve = sum(E[r.harness] for r in running)
                    need = E[h] + (len(queue["codex"]) * E["codex"] if h == "inproc" else 0.0)
                    if est + reserve + need > a.budget_stop:
                        if h == "codex" or not queue["codex"]:
                            log(f"BUDGET STOP: spent ${est:.2f} + in-flight reserve ${reserve:.2f} + next ${need:.2f} "
                                f"> ${a.budget_stop}; not launching {[j.key for j in queue['codex'] + queue['inproc']]}")
                            stopped = True
                        break
                    j = queue[h].pop(0)
                    j.dir.mkdir(parents=True, exist_ok=True)
                    if a.dry_run:
                        log(f"DRY {j.key}: {' '.join(j.cmd())}")
                        continue
                    j.t0 = time.time()
                    out = (logs / f"{j.harness}-{j.tier}-{j.seed}.log").open("w")
                    j.proc = subprocess.Popen(j.cmd(), stdout=out, stderr=subprocess.STDOUT, env=dict(os.environ))
                    running.append(j)
                    log(f"LAUNCH {j.key} pid={j.proc.pid} | spent est ${est:.2f}, in-flight reserve ${reserve:.2f}, "
                        f"E={E[h]:.2f}")
                    time.sleep(2)
                if stopped:
                    break
        if stopped:
            queue = {"codex": [], "inproc": []}
        if a.dry_run:
            break
        time.sleep(5)
    est, up, per = spend()
    log(f"ALL DONE: episodes codex={len(per['codex'])} inproc={len(per['inproc'])}; total est ${est:.2f} (upper ${up:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
