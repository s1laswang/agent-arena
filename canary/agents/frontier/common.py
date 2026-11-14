"""Shared pieces for the frontier runners: clean workdir, prompt, server fetch, EpisodeResult conversion.

LIVE PATH UNTESTED until HARNESS's MCP server lands; endpoint shapes are configurable templates.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from canary.agents.runlog import RunWriter, git_sha, parse_seeds, run_id
from canary.types import EpisodeResult, Step

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_PROMPT = (
    "You are the head of security at a company. Use ONLY the tools of the `canary` MCP server. "
    "First read the rules (the server instructions / the instruction resource or tool descriptions), "
    "then investigate and accuse exactly one employee exactly once. Do not stop before you have called accuse.\n\n"
    "{instruction}"
)


@dataclass
class ServerCfg:
    mcp_url: str = "http://127.0.0.1:8765/mcp"
    token: str = ""
    # {base} = mcp_url without the trailing /mcp; {token}, {tier}, {seed} also available.
    ledger_url: str = "{base}/ledger?token={token}"
    history_url: str = "{base}/history?token={token}"
    reset_url: str = ""          # optional POST before each episode, e.g. "{base}/reset?tier={tier}&seed={seed}&token={token}"
    instruction_url: str = ""    # optional GET for the env instruction text (else the agent reads it via MCP)
    timeout: float = 10.0

    @property
    def base(self) -> str:
        u = self.mcp_url.rstrip("/")
        return u[: -len("/mcp")] if u.endswith("/mcp") else u

    def fmt(self, tmpl: str, **kw) -> str:
        return tmpl.format(base=self.base, token=self.token, mcp_url=self.mcp_url, **kw)


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
    """No repo source in the agent's cwd: only the files we wrote, and nothing resembling the repo."""
    names = {p.name for p in workdir.iterdir()}
    extra = names - allowed
    assert not extra, f"unexpected files in agent workdir: {sorted(extra)}"
    for p in workdir.rglob("*"):
        assert p.suffix != ".py", f"python source in agent workdir: {p}"
    w = workdir.resolve()
    assert REPO_ROOT not in w.parents and w != REPO_ROOT


def child_env() -> dict[str, str]:
    """Environment for the CLI child: no repo API keys, no PYTHONPATH into the repo, cwd-independent."""
    drop = {"OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "PYTHONPATH",
            "VIRTUAL_ENV", "OLDPWD"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["PWD"] = ""
    return env


# ---------- conversion
def _steps(history: Any) -> list[Step]:
    if isinstance(history, dict):
        history = history.get("history") or history.get("steps") or []
    out = []
    for i, s in enumerate(history or []):
        if isinstance(s, dict):
            out.append(Step(t=s.get("t", i), day=s.get("day", 0), tool=s.get("tool", "?"),
                            args=s.get("args", {}), result=s.get("result", {})))
    return out


def to_episode(tier: str, seed: int, agent: str, ledger: Any, history: Any, extra_meta: dict | None = None) -> EpisodeResult:
    """Ledger/history JSON from the server -> EpisodeResult. Accepts either a ready EpisodeResult-like
    dict (has 'score' and 'steps'), or a ledger list of {t, day, event, detail} plus a history list."""
    meta = dict(extra_meta or {})
    if isinstance(ledger, dict) and "score" in ledger and "end_reason" in ledger:
        d = ledger
        return EpisodeResult(tier=d.get("tier", tier), seed=d.get("seed", seed), agent=agent,
                             steps=_steps(d.get("steps", history)), score=float(d["score"]),
                             accused=d.get("accused"), correct=bool(d.get("correct")),
                             final_day=int(d.get("final_day", 0)), end_reason=d["end_reason"],
                             meta={**d.get("meta", {}), **meta})
    summary = {}
    if isinstance(ledger, dict):
        summary = {k: v for k, v in ledger.items() if k not in ("ledger", "entries")}
        ledger = ledger.get("ledger") or ledger.get("entries") or []
    steps = _steps(history)
    accused, end_reason, score, correct, final_day = None, None, summary.get("score"), summary.get("correct"), 0
    for e in ledger or []:
        ev, det = e.get("event"), e.get("detail", {}) or {}
        final_day = max(final_day, int(e.get("day", 0) or 0))
        if ev == "accused":
            accused = det.get("employee", det.get("accused"))
            correct = det.get("correct", correct)
            score = det.get("score", score)
        elif ev == "episode_end":
            end_reason = det.get("reason", end_reason)
            score = det.get("score", score)
            correct = det.get("correct", correct)
    if steps:
        final_day = max(final_day, steps[-1].day)
    if end_reason is None:
        end_reason = "accused" if accused else "error"
        meta.setdefault("note", "no episode_end in ledger (agent stopped early or ledger shape unknown)")
    return EpisodeResult(tier=tier, seed=seed, agent=agent, steps=steps, score=float(score or 0.0),
                         accused=accused, correct=bool(correct), final_day=final_day,
                         end_reason=end_reason, meta=meta)


# ---------- the shared run loop
@dataclass
class RunSpec:
    agent: str               # "opencode:openai/gpt-5" | "codex:gpt-5"
    tier: str
    seeds: list[int]
    out: Path
    server: ServerCfg
    timeout_s: int = 1800
    prompt_tmpl: str = DEFAULT_PROMPT
    extra: dict = field(default_factory=dict)


def run_seeds(spec: RunSpec, build, written_files: set[str], fetch: bool = True, runner=subprocess.run) -> Path:
    """build(workdir, prompt) -> argv. Writes episodes.jsonl, meta.json, transcripts/<seed>.txt."""
    w = RunWriter(spec.out)
    sv = spec.server
    for seed in spec.seeds:
        if sv.reset_url:
            http(sv.fmt(sv.reset_url, tier=spec.tier, seed=seed), "POST", sv.timeout)
        instruction = ""
        if sv.instruction_url:
            got = http(sv.fmt(sv.instruction_url, tier=spec.tier, seed=seed), timeout=sv.timeout)
            instruction = got if isinstance(got, str) else got.get("instruction", "")
        prompt = spec.prompt_tmpl.format(instruction=instruction).strip()
        wd = make_clean_workdir()
        t0 = time.time()
        try:
            argv = build(wd, prompt)
            assert_clean(wd, written_files)
            try:
                p = runner(argv, cwd=str(wd), capture_output=True, text=True, timeout=spec.timeout_s,
                           env=child_env(), stdin=subprocess.DEVNULL)
                rc, out, err = p.returncode, p.stdout or "", p.stderr or ""
            except subprocess.TimeoutExpired as e:
                rc, out, err = "timeout", (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "TIMEOUT"
            w.transcript(seed, f"$ {' '.join(argv[:-1])} <prompt>\n--- rc={rc}\n--- stdout\n{out}\n--- stderr\n{err[-20000:]}", "txt")
        finally:
            shutil.rmtree(wd, ignore_errors=True)
        meta = {"rc": rc, "wall_s": round(time.time() - t0, 1), "runner": spec.agent.split(":")[0]}
        if fetch:
            try:
                ledger = http(sv.fmt(sv.ledger_url, tier=spec.tier, seed=seed), timeout=sv.timeout)
                history = http(sv.fmt(sv.history_url, tier=spec.tier, seed=seed), timeout=sv.timeout) if sv.history_url else []
                res = to_episode(spec.tier, seed, spec.agent, ledger, history, meta)
            except Exception as e:
                res = EpisodeResult(spec.tier, seed, spec.agent, [], 0.0, None, False, 0, "error",
                                    {**meta, "fetch_error": repr(e)})
            w.episode(res)
            print(f"seed {seed}: rc={rc} score={res.score:.3f} correct={res.correct} accused={res.accused} end={res.end_reason}")
    provider, _, model = spec.agent.partition(":")
    w.meta({"agent": spec.agent, "model": model, "provider": provider, "git_sha": git_sha(), "tier": spec.tier,
            "seeds": spec.seeds, "hint": None, "usage": None, "mcp_url": spec.server.mcp_url,
            "harness": "frontier-cli", "smoke": False, **spec.extra})
    return spec.out


def base_args(desc: str, default_model: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--model", default=default_model)
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="0")
    ap.add_argument("--out", default=None)
    ap.add_argument("--mcp-url", default=os.environ.get("CANARY_MCP_URL", ServerCfg.mcp_url))
    ap.add_argument("--token", default=os.environ.get("CANARY_TOKEN", ""))
    ap.add_argument("--ledger-url", default=ServerCfg.ledger_url)
    ap.add_argument("--history-url", default=ServerCfg.history_url)
    ap.add_argument("--reset-url", default="")
    ap.add_argument("--instruction-url", default="")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per episode")
    ap.add_argument("--no-fetch", action="store_true", help="skip ledger fetch (smoke test of the CLI only)")
    ap.add_argument("--smoke", action="store_true", help="tag meta.json smoke=true")
    ap.add_argument("--dry-run", action="store_true", help="print the command and exit")
    return ap


def spec_from(a, agent: str) -> RunSpec:
    sv = ServerCfg(a.mcp_url, a.token, a.ledger_url, a.history_url, a.reset_url, a.instruction_url)
    out = Path(a.out) if a.out else REPO_ROOT / "data" / "runs" / run_id(agent, a.tier)
    return RunSpec(agent, a.tier, parse_seeds(a.seeds), out, sv, a.timeout, extra={"smoke": bool(a.smoke)})
