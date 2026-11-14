"""Budget-guarded, RESUMABLE driver for the official v1.3 frontier measurement (one episode per process).

    python scripts/budget_runner.py --budget-stop 90 --already-spent <smoke $> [--seeds 0-9] [--no-codex-reserve] [--dry-run]

Jobs: Codex gpt-5.5 over MCP (priority, 2 slots; each episode = its own codex_run process with its own MCP
server on its own port) on dev seeds x {medium, hard}, and the in-process LLMPolicy (full history,
Responses API) on the same seeds, interleaved medium/hard seed by seed (2 slots).

All state lives on disk under --staging, so the driver can be killed and restarted at any time:
  <staging>/<harness>/<tier>/<seed>/episodes.jsonl   finished episode (valid or not)
  <staging>/<harness>/<tier>/<seed>/RUNNING.json     {pid, cmd, started}: in flight while that pid is alive
  <staging>/invalid/<harness>-<tier>-<seed>-<ts>/    infra-failed attempts (network/API errors), moved aside
                                                     and re-queued (max --max-attempts per job); their
                                                     cost still counts
  <staging>/spend_ledger.jsonl                       one line per finished attempt with cumulative spend
Children run in their own session (start_new_session) so they survive the driver; they are tracked by PID
only (never pkill by pattern).

Spend = sum over every episodes.jsonl under <staging> (valid + invalid) of the per-episode estimate at
gpt-5.5 list prices (input $5, cached input $0.50, output $30 per 1M; verified on
developers.openai.com/api/docs/pricing) + --already-spent.
Launch rule: launch only if  spent + reserve(in-flight) + E(job) [+ reserve(queued Codex) for in-process
jobs unless --no-codex-reserve] <= --budget-stop, where E = expected cost per episode of that harness
(mean + 0.5 sd of its valid episodes so far). In-flight episodes are always allowed to finish.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

UV = ["uv", "run", "--python", "3.12", "--extra", "llm", "--extra", "dev", "python"]
PRIOR = {"codex": 2.2, "inproc": 3.0}
INPROC_INFRA = re.compile(r"APIConnectionError|APITimeoutError|RateLimitError|InternalServerError|"
                          r"ServiceUnavailable|Connection error|ENOTFOUND")
CODEX_INFRA = re.compile(r"stream disconnected|error sending request|ENOTFOUND|dns error|failed to lookup address|"
                         r"Connection refused|connection error|network error|Reconnecting\.\.\. \d/\d", re.I)


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


def pid_alive(pid: int, needle: str) -> bool:
    try:
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    except Exception:  # noqa: BLE001
        return False
    return needle in cmd.split()


def infra_reason(harness: str, d: Path, ep: dict) -> str | None:
    """Non-None if this episode failed for infrastructure reasons (not the agent's decisions)."""
    m = ep.get("meta") or {}
    if m.get("valid") is False:
        return f"invalid: {str(m.get('error', ''))[:160]}"
    if ep.get("end_reason") != "error":
        return None
    err = str(m.get("error") or "")
    if harness == "inproc":
        return f"api: {err[:160]}" if INPROC_INFRA.search(err) else None
    tr = d / "transcripts" / f"{ep['seed']}.txt"
    blob = tr.read_text(errors="replace") if tr.exists() else ""
    hit = CODEX_INFRA.search(blob)
    return f"codex network: {hit.group(0)}" if hit else None


class Job:
    def __init__(self, harness: str, tier: str, seed: int, staging: Path):
        self.harness, self.tier, self.seed, self.staging = harness, tier, seed, staging
        self.dir = staging / harness / tier / str(seed)

    @property
    def key(self) -> str:
        return f"{self.harness}/{self.tier}/{self.seed}"

    def cmd(self) -> list[str]:
        if self.harness == "codex":
            return UV + ["-m", "canary.agents.frontier.codex_run", "--model", "gpt-5.5", "--tier", self.tier,
                         "--seeds", str(self.seed), "--jobs", "1", "--retries", "0", "--out", str(self.dir)]
        return UV + ["-m", "canary.agents.play", "--agent", "openai:gpt-5.5", "--tier", self.tier,
                     "--seeds", str(self.seed), "--out", str(self.dir)]

    def running(self) -> bool:
        f = self.dir / "RUNNING.json"
        if not f.exists():
            return False
        r = json.loads(f.read_text())
        return pid_alive(int(r["pid"]), str(self.dir))

    def attempts(self) -> int:
        inv = self.staging / "invalid"
        n_inv = len(list(inv.glob(f"{self.harness}-{self.tier}-{self.seed}-*"))) if inv.exists() else 0
        return n_inv + (1 if read_eps(self.dir) else 0)


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
    ap.add_argument("--harnesses", default="codex,inproc")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--no-codex-reserve", action="store_true",
                    help="in-process launches do not reserve budget for queued Codex jobs (extension phase: shared pool)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split("-"))
    seeds = list(range(lo, hi + 1))
    staging = Path(a.staging)
    (staging / "logs").mkdir(parents=True, exist_ok=True)
    ledger = staging / "spend_ledger.jsonl"
    hs = [h for h in ("codex", "inproc") if h in a.harnesses.split(",")]
    jobs = {h: [Job(h, t, s, staging) for s in seeds for t in ("medium", "hard")] for h in hs}
    slots = {"codex": a.codex_slots, "inproc": a.inproc_slots}
    alljobs = [j for h in hs for j in jobs[h]]
    # in-flight jobs from ANY seed range (e.g. a previous phase) still occupy slots and budget reserve
    allstaged = [Job(h, t, int(p.name), staging) for h in ("codex", "inproc") for t in ("medium", "hard")
                 if (staging / h / t).exists() for p in (staging / h / t).iterdir() if p.name.isdigit()]

    def log(msg: str) -> None:
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    def spend() -> tuple[float, float, dict[str, list[float]]]:
        est = up = 0.0
        per: dict[str, list[float]] = {"codex": [], "inproc": []}
        for f in staging.rglob("episodes.jsonl"):
            rel = f.relative_to(staging).parts
            harness = "codex" if (rel[0] == "codex" or (rel[0] == "invalid" and rel[1].startswith("codex-"))) else "inproc"
            valid = rel[0] != "invalid"
            for ep in read_eps(f.parent):
                e, u = ep_cost(ep)
                est, up = est + e, up + u
                if valid:
                    per[harness].append(e)
        return est + a.already_spent, up + a.already_spent, per

    def move_invalid(j: Job, reason: str) -> Path:
        dst = staging / "invalid" / f"{j.harness}-{j.tier}-{j.seed}-{time.strftime('%H%M%S')}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(j.dir), str(dst))
        (dst / "INVALID.txt").write_text(reason + "\n")
        return dst

    def reap() -> None:
        """Finished attempts: write the ledger line, move infra failures aside (re-queued)."""
        for j in allstaged + [x for x in alljobs if x.key not in {y.key for y in allstaged}]:
            rf = j.dir / "RUNNING.json"
            if not rf.exists() or j.running():
                continue
            r = json.loads(rf.read_text())
            eps = read_eps(j.dir)
            ep = eps[-1] if eps else None
            reason = infra_reason(j.harness, j.dir, ep) if ep else "no episode written"
            rf.unlink()
            if reason:
                move_invalid(j, reason)
            est, up, _ = spend()
            e, u = ep_cost(ep) if ep else (0.0, 0.0)
            log(f"DONE {j.key} score={ep.get('score') if ep else None} correct={ep.get('correct') if ep else None} "
                f"end={ep.get('end_reason') if ep else None} cost_est=${e:.2f} (upper ${u:.2f}) "
                f"wall={time.time() - r.get('started', time.time()):.0f}s"
                f"{' INFRA-INVALID (' + reason + '), re-queued' if reason else ''} "
                f"| cumulative est ${est:.2f} (upper ${up:.2f})")
            with ledger.open("a") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job": j.key, "infra_invalid": reason,
                                    "score": ep.get("score") if ep else None, "cost_est": round(e, 4),
                                    "cost_upper": round(u, 4), "cumulative_est": round(est, 4),
                                    "cumulative_upper": round(up, 4)}) + "\n")

    # startup sweep: episodes finished without a RUNNING marker (earlier driver) that failed on infra
    for j in alljobs:
        if (j.dir / "RUNNING.json").exists():
            continue
        eps = read_eps(j.dir)
        if eps:
            reason = infra_reason(j.harness, j.dir, eps[-1])
            if reason:
                dst = move_invalid(j, reason)
                log(f"SWEEP {j.key}: infra-invalid ({reason}); moved to {dst}, re-queued")
    est, up, _ = spend()
    log(f"START seeds {a.seeds} harnesses {hs}: spent est ${est:.2f} (upper ${up:.2f}); in flight "
        f"{[j.key for j in allstaged if j.running()]}")

    stopped = False
    while True:
        reap()
        running = [j for j in allstaged + alljobs if j.running()]
        running = list({j.key: j for j in running}.values())
        queue = {h: [j for j in jobs[h] if not j.running() and not read_eps(j.dir)
                     and j.attempts() < a.max_attempts] for h in hs}
        for h in hs:
            if stopped:
                break
            while queue[h] and sum(1 for r in running if r.harness == h) < slots[h]:
                est, _, per = spend()
                E = {k: expected(per[k], k) for k in per}
                reserve = sum(E[r.harness] for r in running)
                need = E[h] + (len(queue.get("codex", [])) * E["codex"]
                               if h == "inproc" and not a.no_codex_reserve else 0.0)
                if est + reserve + need > a.budget_stop:
                    if h == "codex" or not queue.get("codex") or a.no_codex_reserve:
                        log(f"BUDGET STOP: spent ${est:.2f} + in-flight reserve ${reserve:.2f} + next ${need:.2f} "
                            f"> ${a.budget_stop}; not launching {[j.key for hh in hs for j in queue[hh]]}")
                        stopped = True
                    break
                j = queue[h].pop(0)
                if a.dry_run:
                    log(f"DRY {j.key}: {' '.join(j.cmd())}")
                    running.append(j)
                    continue
                j.dir.mkdir(parents=True, exist_ok=True)
                out = (staging / "logs" / f"{j.harness}-{j.tier}-{j.seed}.log").open("a")
                env = dict(os.environ, CANARY_LLM_MAX_RETRIES=os.environ.get("CANARY_LLM_MAX_RETRIES", "12"))
                p = subprocess.Popen(j.cmd(), stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=True)
                (j.dir / "RUNNING.json").write_text(json.dumps({"pid": p.pid, "started": time.time(), "cmd": j.cmd()}))
                running.append(j)
                if j.key not in {y.key for y in allstaged}:
                    allstaged.append(j)
                log(f"LAUNCH {j.key} pid={p.pid} | spent est ${est:.2f}, in-flight reserve ${reserve:.2f}, E={E[h]:.2f}")
                time.sleep(2)
        if a.dry_run:
            break
        running = [j for j in allstaged + alljobs if j.running()]
        pending = sum(len(q) for q in queue.values())
        if not running and (stopped or pending == 0):
            reap()
            break
        time.sleep(10)
    est, up, per = spend()
    log(f"ALL DONE: valid episodes codex={len(per['codex'])} inproc={len(per['inproc'])}; "
        f"total est ${est:.2f} (upper ${up:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
