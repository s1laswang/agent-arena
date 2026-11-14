"""Resumable driver for the Gemini frontier measurement (one episode per process), adapted from budget_runner.py.

    python scripts/gemini_runner.py --tiers-version v1.3 [--seeds 0-9] [--slots 3] [--harnesses opencode,inproc]
                                    [--model gemini-4-carbon] [--dry-run]

Jobs: OpenCode + Gemini over MCP (judges' harness shape; canary.agents.frontier.opencode_run, one MCP server per
episode on its own port) and the in-process LLMPolicy (canary.agents.play --agent gemini:<model>, full history,
thought-signature replay) on dev seeds x {medium, hard}, interleaved so both harnesses progress together.

All state lives on disk under --staging (default data/runs/staging-gemini-<tiers-version>), so the driver can be
killed and restarted at any time:
  <staging>/<harness>/<tier>/<seed>/episodes.jsonl   finished episode (valid)
  <staging>/<harness>/<tier>/<seed>/RUNNING.json     {pid, cmd, started}: in flight while that pid is alive
  <staging>/invalid/<harness>-<tier>-<seed>-<ts>/    infra-failed attempts (API/network errors, CLI error events,
                                                     timeouts), moved aside with INVALID.txt and re-queued (max
                                                     --max-attempts per job); never scored
  <staging>/spend_ledger.jsonl                       one line per finished attempt (cost estimate, cumulative)
Children run in their own session (start_new_session) and are tracked by PID only (never pkill by pattern).

Rate limits: the in-process client retries 429/5xx with exponential backoff (CANARY_LLM_MAX_RETRIES=12, capped at
60 s per wait); OpenCode retries provider errors itself. If an attempt still fails on a rate limit, the driver
pauses new launches (60 s doubling to 15 min) and drops one parallel slot (min 1) until an attempt succeeds.
There is no spend cap (Gemini spend approved without limit); spend is still logged at list prices.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

UV = ["uv", "run", "--python", "3.12", "--extra", "llm", "--extra", "dev", "python", "-W", "ignore"]
RATE = re.compile(r"RESOURCE_EXHAUSTED|\b429\b|rate.?limit|Quota exceeded", re.I)
INPROC_INFRA = re.compile(r"ClientError|ServerError|APIError|RESOURCE_EXHAUSTED|UNAVAILABLE|INTERNAL|\b5\d\d\b|\b429\b|"
                          r"ConnectError|ConnectTimeout|ReadTimeout|ReadError|RemoteProtocolError|Server disconnected|"
                          r"Connection|Timeout|SSLError|ssl", re.I)


def read_eps(d: Path) -> list[dict]:
    f = d / "episodes.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def ep_cost(ep: dict) -> tuple[float, float]:
    u = (ep.get("meta") or {}).get("usage") or {}
    est = u.get("cost_usd_est", u.get("cost_usd", 0.0)) or 0.0
    upper = u.get("cost_usd_upper", u.get("cost_usd", est)) or est
    return float(est), float(upper)


def pid_alive(pid: int, needle: str) -> bool:
    try:
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    except Exception:  # noqa: BLE001
        return False
    return needle in cmd.split()


def infra_reason(harness: str, d: Path, ep: dict) -> str | None:
    """Non-None if this attempt failed for infrastructure reasons (not because of the agent's decisions).
    Only these are retried: empty model replies that end an OpenCode run, provider/network errors, a dead MCP
    server. Every other ending (wrong accusation, no accusation, our-side timeout, tool-call cap) counts as played."""
    m = ep.get("meta") or {}
    if ep.get("end_reason") == "accused":
        return None
    if m.get("valid") is False or (harness == "opencode" and m.get("error")):
        return f"invalid: {str(m.get('error', ''))[:200]}"
    tr = d / "transcripts" / f"{ep.get('seed')}.txt"
    if harness == "opencode" and tr.exists() and empty_final_response(tr.read_text(errors="replace")):
        from canary.agents.frontier.common import final_step
        fs = final_step(tr.read_text(errors="replace")) or {}
        t = fs.get("tokens") or {}
        return (f"infra:empty_model_response (final reply had no text and no tool call: finish={fs.get('reason')}, "
                f"output_tokens={t.get('output')}, reasoning_tokens={t.get('reasoning')}; opencode exited)")
    if ep.get("end_reason") != "error":
        return None
    err = str(m.get("error") or "")
    if harness == "inproc":
        # any exception out of the in-process loop comes from the API client, not from an agent decision
        return f"api: {err[:200]}" if err else None
    return None   # OpenCode: the agent ended its turn without accusing (non-empty reply) -> played, score 0


def empty_final_response(stdout: str) -> bool:
    from canary.agents.frontier.common import empty_final_response as f
    return f(stdout)


class Job:
    def __init__(self, harness: str, tier: str, seed: int, staging: Path, model: str, timeout: int):
        self.harness, self.tier, self.seed, self.staging, self.model, self.timeout = harness, tier, seed, staging, model, timeout
        self.dir = staging / harness / tier / str(seed)

    @property
    def key(self) -> str:
        return f"{self.harness}/{self.tier}/{self.seed}"

    def cmd(self) -> list[str]:
        if self.harness == "opencode":
            return UV + ["-m", "canary.agents.frontier.opencode_run", "--model", f"google/{self.model}",
                         "--tier", self.tier, "--seeds", str(self.seed), "--jobs", "1", "--retries", "0",
                         "--timeout", str(self.timeout), "--out", str(self.dir)]
        return UV + ["-m", "canary.agents.play", "--agent", f"gemini:{self.model}", "--tier", self.tier,
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers-version", required=True, help="recorded in the ledger; must match canary.env TIERS_VERSION")
    ap.add_argument("--staging", default=None)
    ap.add_argument("--model", default="gemini-4-carbon")
    ap.add_argument("--slots", type=int, default=3, help="parallel episodes across both harnesses")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--tiers", default="medium,hard")
    ap.add_argument("--harnesses", default="opencode,inproc")
    ap.add_argument("--max-attempts", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=3600, help="seconds per OpenCode episode")
    ap.add_argument("--harness-first", action="store_true",
                    help="queue every job of the first harness before the second (prioritise the headline path)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from canary.rules import TIERS_VERSION
    if TIERS_VERSION != a.tiers_version:
        print(f"refusing: canary.env TIERS_VERSION={TIERS_VERSION!r} != --tiers-version {a.tiers_version!r}")
        return 2
    lo, hi = (int(x) for x in a.seeds.split("-"))
    seeds = list(range(lo, hi + 1))
    staging = Path(a.staging or f"data/runs/staging-gemini-{a.tiers_version}")
    (staging / "logs").mkdir(parents=True, exist_ok=True)
    ledger = staging / "spend_ledger.jsonl"
    hs = [h for h in ("opencode", "inproc") if h in a.harnesses.split(",")]
    tiers = a.tiers.split(",")
    # interleave: seed-major, then tier, then harness -> both harnesses and tiers progress together
    alljobs = [Job(h, t, s, staging, a.model, a.timeout) for s in seeds for t in tiers for h in hs]
    if a.harness_first:
        alljobs.sort(key=lambda j: hs.index(j.harness))  # stable: seed/tier order kept within a harness

    def log(msg: str) -> None:
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    def spend() -> tuple[float, float]:
        est = up = 0.0
        for f in staging.rglob("episodes.jsonl"):
            for ep in read_eps(f.parent):
                e, u = ep_cost(ep)
                est, up = est + e, up + u
        return est, up

    def move_invalid(j: Job, reason: str) -> Path:
        dst = staging / "invalid" / f"{j.harness}-{j.tier}-{j.seed}-{time.strftime('%H%M%S')}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(j.dir), str(dst))
        (dst / "INVALID.txt").write_text(reason + "\n")
        return dst

    backoff = {"until": 0.0, "delay": 60.0, "penalty": 0}

    def reap() -> None:
        for j in alljobs:
            rf = j.dir / "RUNNING.json"
            if not rf.exists() or j.running():
                continue
            r = json.loads(rf.read_text())
            eps = read_eps(j.dir)
            ep = eps[-1] if eps else None
            reason = infra_reason(j.harness, j.dir, ep) if ep else "no episode written"
            if not ep:
                lf = staging / "logs" / f"{j.harness}-{j.tier}-{j.seed}.log"
                tail = lf.read_text(errors="replace")[-600:] if lf.exists() else ""
                reason += f" | log tail: {tail}"
            rf.unlink()
            if reason:
                move_invalid(j, reason)
                if RATE.search(reason):
                    backoff["until"] = time.time() + backoff["delay"]
                    backoff["penalty"] = min(backoff["penalty"] + 1, a.slots - 1)
                    log(f"RATE LIMIT: pausing launches {backoff['delay']:.0f}s, slots -> {a.slots - backoff['penalty']}")
                    backoff["delay"] = min(backoff["delay"] * 2, 900.0)
            else:
                backoff["delay"], backoff["penalty"] = 60.0, max(0, backoff["penalty"] - 1)
            est, up = spend()
            e, u = ep_cost(ep) if ep else (0.0, 0.0)
            log(f"DONE {j.key} score={ep.get('score') if ep else None} correct={ep.get('correct') if ep else None} "
                f"end={ep.get('end_reason') if ep else None} day={ep.get('final_day') if ep else None} "
                f"cost_est=${e:.2f} wall={time.time() - r.get('started', time.time()):.0f}s"
                f"{' INFRA-INVALID (' + reason[:160] + '), re-queued' if reason else ''} | cumulative est ${est:.2f}")
            with ledger.open("a") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job": j.key, "infra_invalid": reason,
                                    "score": ep.get("score") if ep else None, "cost_est": round(e, 4),
                                    "cost_upper": round(u, 4), "cumulative_est": round(est, 4),
                                    "cumulative_upper": round(up, 4)}) + "\n")

    # startup sweep: finished without a RUNNING marker but infra-failed
    for j in alljobs:
        if (j.dir / "RUNNING.json").exists():
            continue
        eps = read_eps(j.dir)
        if eps:
            reason = infra_reason(j.harness, j.dir, eps[-1])
            if reason:
                log(f"SWEEP {j.key}: infra-invalid ({reason[:120]}); moved to {move_invalid(j, reason)}, re-queued")
    est, _ = spend()
    log(f"START {a.tiers_version} model={a.model} seeds={a.seeds} tiers={tiers} harnesses={hs} slots={a.slots}; "
        f"spent est ${est:.2f}; in flight {[j.key for j in alljobs if j.running()]}")

    while True:
        reap()
        running = [j for j in alljobs if j.running()]
        queue = [j for j in alljobs if not j.running() and not read_eps(j.dir) and j.attempts() < a.max_attempts]
        slots = max(1, a.slots - backoff["penalty"])
        while queue and len(running) < slots and time.time() >= backoff["until"]:
            j = queue.pop(0)
            if a.dry_run:
                log(f"DRY {j.key}: {' '.join(j.cmd())}")
                running.append(j)
                continue
            j.dir.mkdir(parents=True, exist_ok=True)
            out = (staging / "logs" / f"{j.harness}-{j.tier}-{j.seed}.log").open("a")
            env = dict(os.environ, CANARY_LLM_MAX_RETRIES=os.environ.get("CANARY_LLM_MAX_RETRIES", "12"), CANARY_PROGRESS="1")
            p = subprocess.Popen(j.cmd(), stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            (j.dir / "RUNNING.json").write_text(json.dumps({"pid": p.pid, "started": time.time(), "cmd": j.cmd()}))
            running.append(j)
            log(f"LAUNCH {j.key} pid={p.pid} (running {len(running)}/{slots})")
            time.sleep(5)  # stagger starts
        if a.dry_run:
            break
        if not running and not queue:
            reap()
            break
        time.sleep(10)
    est, up = spend()
    valid = {h: sum(1 for j in alljobs if j.harness == h and read_eps(j.dir)) for h in hs}
    failed = [j.key for j in alljobs if not read_eps(j.dir)]
    log(f"ALL DONE: valid episodes {valid}; gave up on {failed}; total est ${est:.2f} (upper ${up:.2f})")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
