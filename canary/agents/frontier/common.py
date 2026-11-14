"""Shared pieces for the frontier runners (judges' harness shape).

Per seed: start one HARNESS MCP server (python -m canary.mcp_server) on a free port with a random
ledger token -> run the CLI agent from a fresh temp dir outside the repo (MCP-only, keys stripped,
token never shown to the agent) -> GET /ledger?token= -> EpisodeResult -> kill the server.

The server has no step-history endpoint. `steps` are rebuilt best-effort from the CLI's JSON event
stream (meta.steps_source = "agent_transcript"); score/accused/correct/end_reason/final_day come
from the server ledger only.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from canary.agents.llm_policy import build_system_prompt
from canary.agents.runlog import RunWriter, git_sha, parse_seeds, run_id
from canary.types import EpisodeResult, Step

REPO_ROOT = Path(__file__).resolve().parents[3]


def episode_prompt(tier: str, seed: int) -> str:
    """Identical to LLMPolicy's system prompt without hints: Env instruction verbatim + the generic line."""
    from canary.env import Env
    return build_system_prompt(Env(tier, seed).instruction())


# ---------- server lifecycle
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Server:
    tier: str
    seed: int
    port: int = 0
    token: str = ""
    proc: Any = None
    log_path: Path | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    port_file: Path | None = None

    def start(self, timeout: float = 60.0, log_dir: Path | None = None, port_dir: Path | None = None) -> "Server":
        self.port = self.port or free_port()  # bind-tested free port, unique per server
        self.token = secrets.token_hex(16)
        from canary.mcp_server import clean_launch_env, write_secret_files
        # INTEGRITY item 2: the seed and ledger token go in 0600 files, never in the server's environment.
        env = dict(clean_launch_env(), **write_secret_files(self.tier, self.seed, self.token),
                   CANARY_ALLOW_DEV="1", CANARY_PORT=str(self.port), CANARY_HOST="127.0.0.1")
        log = subprocess.DEVNULL
        if log_dir:
            self.log_path = Path(log_dir) / f"server-{self.tier}-{self.seed}.log"
            log = self.log_path.open("w")
        # Own session: avoids process-group signals reaching the server. Plainly visible as canary.mcp_server.
        self.proc = subprocess.Popen([sys.executable, "-m", "canary.mcp_server"], cwd=str(REPO_ROOT), env=env,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        if port_dir:
            Path(port_dir).mkdir(parents=True, exist_ok=True)
            self.port_file = Path(port_dir) / f"{self.tier}-{self.seed}.port"
            self.port_file.write_text(json.dumps({"port": self.port, "pid": self.proc.pid}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(f"MCP server exited rc={self.proc.returncode} (see {self.log_path})")
            try:
                http(f"{self.base}/healthz", timeout=2)
                return self
            except Exception:
                time.sleep(0.3)
        self.stop()
        raise TimeoutError("MCP server did not come up")

    def ledger(self) -> dict:
        if self.proc is not None and self.proc.poll() is not None:
            raise RuntimeError(f"MCP server died during the episode (rc={self.proc.returncode}; see {self.log_path})")
        return http(f"{self.base}/ledger?token={self.token}", timeout=10)

    def stop(self) -> None:
        """Stops only our own recorded child (by its pid via the Popen handle); never by name/pattern."""
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.port_file:
            self.port_file.unlink(missing_ok=True)


def http(url: str, method: str = "GET", timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


# ---------- workdir hygiene
def make_clean_workdir(prefix: str = "canary-frontier-") -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    assert REPO_ROOT not in d.parents and d != REPO_ROOT, "workdir must be outside the repo"
    return d


def assert_clean(workdir: Path, allowed: set[str]) -> None:
    names = {p.name for p in workdir.iterdir()}
    extra = names - allowed
    assert not extra, f"unexpected files in agent workdir: {sorted(extra)}"
    for p in workdir.rglob("*"):
        assert p.suffix != ".py", f"python source in agent workdir: {p}"
    w = workdir.resolve()
    assert REPO_ROOT not in w.parents and w != REPO_ROOT


def child_env() -> dict[str, str]:
    """CLI child env: no API keys, no ledger token, no repo paths."""
    drop = {"OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "PYTHONPATH", "VIRTUAL_ENV",
            "OLDPWD", "CANARY_LEDGER_TOKEN", "CANARY_ADMIN_TOKEN", "CANARY_WORLD_SECRET", "CANARY_TOKEN", "OPENCODE_CONFIG"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["PWD"] = ""
    return env


# ---------- steps from the agent's own event stream (best effort)
def _strip(name: str) -> str:
    for pre in ("canary_", "canary__", "mcp__canary__", "canary."):
        if name.startswith(pre):
            return name[len(pre):]
    return name


def _parse_result(out: Any) -> dict:
    if isinstance(out, dict):
        if "content" in out and isinstance(out["content"], list) and out["content"]:
            out = out["content"][0].get("text", "")
        elif "structured_content" in out or "structuredContent" in out:
            return out.get("structured_content") or out.get("structuredContent")
        else:
            return out
    if isinstance(out, str):
        try:
            v = json.loads(out)
            return v if isinstance(v, dict) else {"raw": out}
        except json.JSONDecodeError:
            return {"raw": out[:2000]}
    return {"raw": str(out)[:2000]}


def steps_from_events(stdout: str) -> list[Step]:
    """OpenCode --format json (part.type == "tool") and Codex --json (item.type == "mcp_tool_call")."""
    steps: list[Step] = []
    day = 1
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        tool, args, res = None, None, None
        part = ev.get("part") if isinstance(ev, dict) else None
        if isinstance(part, dict) and part.get("type") == "tool":
            st = part.get("state") or {}
            if st.get("status") not in ("completed", "error"):
                continue
            tool, args = part.get("tool", ""), st.get("input") or {}
            res = st.get("output") if st.get("status") == "completed" else {"ok": False, "error": st.get("error")}
        item = ev.get("item") if isinstance(ev, dict) else None
        if isinstance(item, dict) and item.get("type") == "mcp_tool_call" and ev.get("type") == "item.completed":
            tool, args = item.get("tool", ""), item.get("arguments") or {}
            res = item.get("result") if item.get("result") is not None else {"ok": False, "error": item.get("error")}
        if tool is None:
            continue
        tool = _strip(tool)
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        result = _parse_result(res)
        steps.append(Step(t=len(steps), day=day, tool=tool, args=args, result=result))
        if tool == "advance_day" and result.get("ok"):
            day = (result.get("data") or {}).get("day", day + 1)
    return steps


# ---------- infra failure classification (not the agent's fault; excluded / retried)
INFRA_PATTERNS = {
    "provider_quota": ("usage limit has been reached", "credits_depleted", '"statusCode":429',
                       "hit your usage limit", "usage_limit_reached", "429 Too Many Requests"),
    "opencode_db_locked": ("database is locked",),
}


def classify_infra(stdout: str, stderr: str) -> str | None:
    blob = (stdout or "") + "\n" + (stderr or "")
    for kind, pats in INFRA_PATTERNS.items():
        if any(p in blob for p in pats):
            return kind
    return None


def usage_from_events(stdout: str, model: str) -> dict:
    """Token usage from Codex `turn.completed` events -> ESTIMATED cost at canary.llm.pricing list prices.
    cost_usd_est bills cached input at 10% of the input price; cost_usd_upper bills all input at full price."""
    tin = cached = tout = 0
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(ev, dict) and ev.get("type") == "turn.completed":
            u = ev.get("usage") or {}
            tin += u.get("input_tokens", 0) or 0
            cached += u.get("cached_input_tokens", 0) or 0
            tout += u.get("output_tokens", 0) or 0
    if not (tin or tout):
        return {"cost_unknown": True}
    from canary.llm.pricing import PRICES
    pin, pout = PRICES.get(model.split("/")[-1], (None, None))
    out = {"in": tin, "cached_in": cached, "out": tout}
    if pin is None:
        return {**out, "cost_unknown": True}
    out["cost_usd_est"] = round(((tin - cached) * pin + cached * pin * 0.1 + tout * pout) / 1e6, 4)
    out["cost_usd_upper"] = round((tin * pin + tout * pout) / 1e6, 4)
    out["cost_note"] = "estimate from codex turn.completed usage at canary.llm.pricing list prices"
    return out


# ---------- conversion
def to_episode(tier: str, seed: int, agent: str, ledger: dict, steps: list[Step], extra_meta: dict | None = None) -> EpisodeResult:
    meta = dict(extra_meta or {})
    meta["ledger_events"] = ledger.get("ledger", [])
    meta["V_final"] = ledger.get("V")
    end = ledger.get("end_reason")
    if not ledger.get("done"):
        end = "error"
        meta["note"] = "agent stopped without ending the episode (no accusation)"
    return EpisodeResult(tier=ledger.get("tier", tier), seed=seed, agent=agent, steps=steps,
                         score=float(ledger.get("score") or 0.0), accused=ledger.get("accused"),
                         correct=bool(ledger.get("accused_correct")), final_day=int(ledger.get("final_day") or 0),
                         end_reason=end or "error", meta=meta)


# ---------- the run loop
@dataclass
class RunSpec:
    agent: str               # exact label: "opencode:openai/gpt-5.6-sol" | "codex:gpt-5.5"
    tier: str
    seeds: list[int]
    out: Path
    timeout_s: int = 2400
    jobs: int = 1
    retries: int = 1
    extra: dict = field(default_factory=dict)


def run_one(spec: RunSpec, seed: int, build: Callable[[Path, str, str], list[str]], files: set[str],
            w: RunWriter, lock: threading.Lock, runner=subprocess.run, server_factory=Server,
            write: bool = True) -> EpisodeResult:
    t0 = time.time()
    srv = server_factory(spec.tier, seed)
    wd = None
    try:
        srv.start(log_dir=spec.out / "transcripts", port_dir=spec.out / "servers")
        prompt = episode_prompt(spec.tier, seed)
        wd = make_clean_workdir()
        argv = build(wd, prompt, srv.url)
        assert_clean(wd, files)
        assert srv.token not in " ".join(argv) and srv.token not in prompt
        try:
            p = runner(argv, cwd=str(wd), capture_output=True, text=True, timeout=spec.timeout_s,
                       env=child_env(), stdin=subprocess.DEVNULL)
            rc, out, err = p.returncode, p.stdout or "", p.stderr or ""
        except subprocess.TimeoutExpired as e:
            rc = "timeout"
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = "TIMEOUT"
        ledger = srv.ledger()
        steps = steps_from_events(out)
        meta = {"rc": rc, "wall_s": round(time.time() - t0, 1), "steps_source": "agent_transcript",
                "n_ledger_tool_calls": None}
        meta["usage"] = usage_from_events(out, spec.agent.partition(":")[2])
        infra = classify_infra(out, err)
        if infra and not ledger.get("done"):
            meta["error"] = f"infra:{infra}"
        res = to_episode(spec.tier, seed, spec.agent, ledger, steps, meta)
        with lock:
            w.transcript(seed, f"$ {' '.join(argv[:-1])} <prompt>\n--- rc={rc}\n--- stdout\n{out}\n--- stderr\n{err[-20000:]}", "txt")
    except Exception as e:
        res = EpisodeResult(spec.tier, seed, spec.agent, [], 0.0, None, False, 0, "error",
                            {"error": repr(e), "wall_s": round(time.time() - t0, 1)})
    finally:
        srv.stop()
        if wd:
            shutil.rmtree(wd, ignore_errors=True)
    with lock:
        if write:
            w.episode(res)
        print(f"[{spec.agent} {spec.tier}] seed {seed}: score={res.score:+.3f} correct={res.correct} accused={res.accused} "
              f"end={res.end_reason} day={res.final_day} steps={len(res.steps)} wall={res.meta.get('wall_s')}s", flush=True)
    return res


def run_seeds(spec: RunSpec, build, files: set[str], runner=subprocess.run, server_factory=Server) -> list[EpisodeResult]:
    """Infra errors (server died / unreachable before a ledger was read) are retried up to spec.retries times;
    only the final attempt per seed is written to episodes.jsonl."""
    w = RunWriter(spec.out)
    lock = threading.Lock()

    quota_hit = threading.Event()

    def one(seed: int) -> EpisodeResult:
        if quota_hit.is_set():  # stop on provider quota: do not burn more seeds
            res = EpisodeResult(spec.tier, seed, spec.agent, [], 0.0, None, False, 0, "error",
                                {"error": "infra:not_run_after_provider_quota", "valid": False})
            with lock:
                w.episode(res)
            print(f"seed {seed}: skipped (provider quota hit earlier)", flush=True)
            return res
        time.sleep(3.0 * (spec.seeds.index(seed) % max(1, spec.jobs)))  # stagger CLI starts (opencode db lock)
        for attempt in range(spec.retries + 1):
            if attempt:
                time.sleep(5.0)
            res = run_one(spec, seed, build, files, w, lock, runner, server_factory, write=False)
            if "error" not in (res.meta or {}) or attempt == spec.retries or res.meta["error"] == "infra:provider_quota":
                break
            print(f"seed {seed}: infra error ({res.meta['error'][:120]}); retry {attempt + 1}/{spec.retries}", flush=True)
        res.meta["attempts"] = attempt + 1
        res.meta["valid"] = "error" not in res.meta
        if res.meta.get("error") == "infra:provider_quota":
            quota_hit.set()
        with lock:
            w.episode(res)
        return res

    with ThreadPoolExecutor(max_workers=max(1, spec.jobs)) as ex:
        results = list(ex.map(one, spec.seeds))
    provider, _, model = spec.agent.partition(":")
    w.meta({"agent": spec.agent, "model": model, "provider": provider, "git_sha": git_sha(), "tier": spec.tier,
            "seeds": spec.seeds, "hint": None, "usage": None, "harness": "frontier-cli+mcp_server",
            "steps_source": "agent_transcript", "smoke": False, **spec.extra})
    return results


def base_args(desc: str, default_model: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--model", default=default_model)
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="0")
    ap.add_argument("--root", default="data/runs_v1", help="parent dir for run dirs")
    ap.add_argument("--out", default=None)
    ap.add_argument("--jobs", type=int, default=1, help="parallel episodes (one server each)")
    ap.add_argument("--timeout", type=int, default=2400, help="seconds per episode")
    ap.add_argument("--retries", type=int, default=1, help="retries per seed on infra errors (server died)")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    return ap


def spec_from(a, agent: str) -> RunSpec:
    out = Path(a.out) if a.out else REPO_ROOT / a.root / run_id(agent, a.tier)
    return RunSpec(agent, a.tier, parse_seeds(a.seeds), out, a.timeout, a.jobs, a.retries, extra={"smoke": bool(a.smoke)})
