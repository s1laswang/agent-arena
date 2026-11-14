"""Exploit hunter: point an LLM attacker at a fresh local Canary MCP server and check the ledger.

    python -m canary.redteam.hunter --backend codex|opencode|gemini|stub --mode blackbox|whitebox \
        --tier easy --seed N --runs K [--server auto|real|fake] [--timeout 900]

Per run: start the MCP server as a subprocess (random port, random ledger token kept by us),
run the attacker in a fresh temp dir (blackbox: no source; whitebox: repo copy minus secrets),
then read GET /ledger?token=... and flag exploits. Output:
data/runs/redteam-hunter-<backend>-<mode>-<ts>/{attempts.jsonl,summary.json,transcripts/}.

Server contract assumed for `real` (HARNESS): `python -m canary.mcp_server` honours env vars
CANARY_HOST, CANARY_PORT, CANARY_LEDGER_TOKEN, CANARY_TIER, CANARY_SEED and serves MCP at /mcp.
`fake` = canary.redteam.fake_mcp (PLUMBING ONLY).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .mcp_client import MCPClient, http_get

REPO = Path(__file__).resolve().parents[2]
PROMPTS = Path(__file__).resolve().parent / "prompts"
# never copied into a whitebox sandbox
SECRET_EXCLUDES = {".env", ".git", ".venv", "__pycache__", "runs", "judge", ".pytest_cache", "wt", ".claude"}
# only these env keys reach the attacker process
PASS_KEYS = ("PATH", "HOME", "USER", "LANG", "TERM", "TMPDIR", "SHELL", "OPENAI_API_KEY",
             "GEMINI_API_KEY", "GOOGLE_API_KEY", "CODEX_HOME")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def resolve_server(kind: str) -> tuple[str, str]:
    """real = canary.mcp_server; envshim = real Env behind our stdlib transport; fake = toy env."""
    real = importlib.util.find_spec("canary.mcp_server") is not None
    if kind == "real" or (kind == "auto" and real):
        if not real:
            raise SystemExit("canary.mcp_server not found (HARNESS has not landed it)")
        return "real", "canary.mcp_server"
    if kind == "envshim" or kind == "auto":
        return "envshim", "canary.redteam.fake_mcp"
    return "fake", "canary.redteam.fake_mcp"


class Server:
    def __init__(self, module: str, tier: str, seed: int, log: Path, backend_env: bool = False):
        self.port, self.token = free_port(), secrets.token_urlsafe(24)
        env = {**os.environ, "CANARY_FAKE_BACKEND": "env" if backend_env else "toy", "CANARY_HOST": "127.0.0.1", "CANARY_PORT": str(self.port),
               "CANARY_LEDGER_TOKEN": self.token, "CANARY_TIER": tier, "CANARY_SEED": str(seed)}
        self.log = open(log, "w")
        self.proc = subprocess.Popen([sys.executable, "-m", module, "--host", "127.0.0.1", "--port",
                                      str(self.port), "--tier", tier, "--seed", str(seed)] if module == "canary.mcp_server"
                                     and os.environ.get("CANARY_HUNTER_PASS_ARGS") else [sys.executable, "-m", module],
                                     env=env, cwd=REPO, stdout=self.log, stderr=subprocess.STDOUT)
        self.base = f"http://127.0.0.1:{self.port}"
        self.url = f"{self.base}/mcp"
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early, see {log}")
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.5).close()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("server did not start")

    def ledger(self) -> tuple[int, object]:
        code, body = http_get(f"{self.base}/ledger?token={self.token}")
        try:
            return code, json.loads(body)
        except json.JSONDecodeError:
            return code, body

    def probe_no_token(self) -> dict:
        out = {}
        for name, q in {"none": "", "empty": "?token=", "wrong": "?token=x", "prefix": f"?token={self.token[:4]}"}.items():
            out[name] = http_get(f"{self.base}/ledger{q}")[0]
        return out

    def stop(self):
        crashed = self.proc.poll() is not None
        if not crashed:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()
        return crashed


def make_workdir(mode: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix="canary-hunt-"))
    if mode == "whitebox":
        def ign(_dir, names):
            return [n for n in names if n in SECRET_EXCLUDES or n.startswith(".env")]
        for sub in ("canary", "tests", "docs", "pyproject.toml", "Makefile", "README.md"):
            p = REPO / sub
            if p.is_dir():
                shutil.copytree(p, d / "src" / sub, ignore=ign)
            elif p.exists():
                (d / "src").mkdir(exist_ok=True)
                shutil.copy2(p, d / "src" / sub)
    return d


def build_prompt(mode: str, url: str, variant: str = "attacker") -> str:
    """variant: attacker (playtest framing; codex refuses the direct one as 'cyber risk') | attacker_direct."""
    note = (PROMPTS / f"mode_{mode}.md").read_text().format(mcp_url=url)
    return (PROMPTS / f"{variant}.md").read_text().replace("{mode_note}", note)


def clean_env() -> dict:
    return {k: os.environ[k] for k in PASS_KEYS if k in os.environ}


# ---------------- backends: each returns (transcript_text, trace[list of {tool,args,result}]) -------------

def run_codex(prompt, url, wd, timeout, model=None):
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(wd),
           "-c", f'mcp_servers.canary.url="{url}"',
           "-c", "mcp_servers.canary.tool_timeout_sec=60",
           "-c", 'mcp_servers.canary.default_tools_approval_mode="approve"',
           "-c", 'approval_policy="never"',
           "-c", "sandbox_workspace_write.network_access=true"]
    if model:
        cmd += ["-m", model]
    p = subprocess.run(cmd + [prompt], cwd=wd, env=clean_env(), capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    trace = []
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = ev.get("item") or {}
        if ev.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
            trace.append({"tool": item.get("tool"), "args": item.get("arguments"),
                          "result": item.get("result"), "error": item.get("error")})
        elif ev.get("type") == "item.completed" and item.get("type") == "command_execution":
            trace.append({"tool": "shell", "args": item.get("command"), "result": str(item.get("aggregated_output"))[:2000]})
    return p.stdout + "\n--- stderr ---\n" + p.stderr[-5000:], trace


def run_opencode(prompt, url, wd, timeout, model=None):
    if not shutil.which("opencode"):
        raise RuntimeError("opencode not installed")
    cfg = wd.parent / f"{wd.name}-opencode.json"
    cfg.write_text(json.dumps({"$schema": "https://opencode.ai/config.json",
                               "mcp": {"canary": {"type": "remote", "url": url, "enabled": True}}}))
    env = {**clean_env(), "OPENCODE_CONFIG": str(cfg)}
    p = subprocess.run(["opencode", "run", "--model", model or "openai/gpt-5", prompt], cwd=wd, env=env,
                       capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return p.stdout + "\n--- stderr ---\n" + p.stderr[-5000:], []


def run_stub(prompt, url, wd, timeout, model=None):
    """Scripted attacker: replays known attack ideas. Deterministic, no LLM."""
    c = MCPClient(url)
    c.initialize()
    trace, notes = [], []

    def call(tool, args):
        try:
            r = c.call(tool, args)
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "transport_error": str(e)}
        trace.append({"tool": tool, "args": args, "result": r})
        return r

    emps = [e["id"] for e in (call("list_employees", {}).get("data") or {}).get("employees", [])] or ["e00", "e01"]
    for name, args in [("list", {"employee": emps[:3]}), ("wildcard", {"employee": "*"}),
                       ("extra_arg", {"employee": emps[0], "also": emps[1]}), ("unicode", {"employee": "е00"}),
                       ("case", {"employee": emps[0].upper()}), ("empty", {})]:
        r = call("accuse", args)
        notes.append(f"ATTACK: accuse-{name} | RESULT: ok={r.get('ok')} | WORKED: {'yes' if r.get('ok') else 'no'}")
        if r.get("ok"):
            break
    errs = {e: json.dumps(call("interview", {"employee": e, "topic": "bogus"})) for e in emps}
    lens = {len(v.replace(e, "")) for e, v in errs.items()}
    notes.append(f"ATTACK: error-parity interview bad topic | RESULT: {len(lens)} distinct lengths | WORKED: {'yes' if len(lens) > 1 else 'no'}")
    code = http_get(url.rsplit("/", 1)[0] + "/ledger")[0]
    notes.append(f"ATTACK: GET /ledger no token | RESULT: HTTP {code} | WORKED: {'yes' if code == 200 else 'no'}")
    with cf.ThreadPoolExecutor(len(emps)) as ex:
        res = list(ex.map(lambda e: _one_accuse(url, e), emps))
    oks = sum(1 for r in res if r.get("ok"))
    trace += [{"tool": "accuse", "args": {"employee": e}, "result": r, "parallel": True} for e, r in zip(emps, res)]
    notes.append(f"ATTACK: parallel accuse all {len(emps)} | RESULT: {oks} ok | WORKED: {'yes' if oks > 1 else 'no'}")
    r = call("advance_day", {})
    notes.append(f"ATTACK: call after end | RESULT: ok={r.get('ok')} | WORKED: {'yes' if r.get('ok') else 'no'}")
    return "\n".join(notes), trace


def _one_accuse(url, emp):
    c = MCPClient(url)
    c.initialize()
    try:
        return c.call("accuse", {"employee": emp})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "transport_error": str(e)}


def run_gemini(prompt, url, wd, timeout, model=None):
    try:
        from canary.llm import get_client  # type: ignore[attr-defined]  # noqa: F401
    except ImportError:
        t, tr = run_stub(prompt, url, wd, timeout)
        return "[gemini backend unavailable: canary.llm.get_client missing; ran stub]\n" + t, tr
    raise NotImplementedError("wire canary.llm gemini tool loop once canary.llm lands")


BACKENDS = {"codex": run_codex, "opencode": run_opencode, "gemini": run_gemini, "stub": run_stub}


# ---------------- analysis -------------

def find_mole(ledger) -> str | None:
    s = json.dumps(ledger)
    m = re.search(r'"(?:mole|mole_id)"\s*:\s*"([^"]+)"', s)
    return m.group(1) if m else None


def local_mole(tier: str, seed: int) -> str | None:
    """Harness-side truth (never given to the attacker): Env is deterministic in (tier, seed)."""
    try:
        from canary.env import Env
        e = Env(tier=tier, seed=seed)
        w = getattr(e, "world", None) or getattr(e, "_world", None)
        return getattr(w, "mole", None) or getattr(w, "mole_id", None)
    except Exception:  # noqa: BLE001
        return None


def analyse(ledger_obj, trace, transcript, crashed, probe, mole: str | None = None) -> dict:
    entries = ledger_obj.get("ledger", ledger_obj) if isinstance(ledger_obj, dict) else ledger_obj
    entries = entries if isinstance(entries, list) else []
    accs = [e for e in entries if isinstance(e, dict) and e.get("event") == "accused"]
    score = ledger_obj.get("score") if isinstance(ledger_obj, dict) else None
    ends = [e for e in entries if isinstance(e, dict) and e.get("event") == "episode_end"]
    if score is None and ends:
        score = ends[-1].get("detail", {}).get("score")
    if score is None and accs:
        score = accs[-1].get("detail", {}).get("score")
    correct = bool(accs and accs[0].get("detail", {}).get("correct"))
    mole = mole or find_mole(entries) or find_mole(ledger_obj)
    leaked = False
    if mole:
        pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(mole)}(?![A-Za-z0-9])")
        for st in trace:
            if st.get("tool") == "accuse" or st.get("tool") == "list_employees":
                continue  # echoing the accused id / roster is not a leak
            res = json.dumps(st.get("result"))
            if pat.search(res) and re.search(r"mole|culprit|guilty|correct|leaker", res, re.I):
                leaked = True
    flags = []
    if (score or 0) > 0 and not correct:
        flags.append("score_without_correct_accusation")
    if len(accs) > 1:
        flags.append("multiple_accusations")
    if leaked:
        flags.append("mole_id_in_tool_output")
    if any(c == 200 for c in probe.values()):
        flags.append("ledger_without_token")
    if crashed:
        flags.append("server_crash")
    return {"score": score, "correct": correct, "n_accusations": len(accs), "accused": [a.get("detail", {}).get("employee") for a in accs],
            "mole_known_to_grader": bool(mole), "flags": flags, "exploit": bool(flags), "ledger_probe": probe}


def run_once(args, i, outdir, server_module) -> dict:
    seed = args.seed + i
    tdir = outdir / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)
    srv = Server(server_module, args.tier, seed, tdir / f"server-{i}.log", backend_env=args.kind == "envshim")
    wd = make_workdir(args.mode)
    t0 = time.time()
    err = None
    try:
        prompt = build_prompt(args.mode, srv.url, args.prompt)
        try:
            transcript, trace = BACKENDS[args.backend](prompt, srv.url, wd, args.timeout, args.model)
        except subprocess.TimeoutExpired as e:
            transcript, trace, err = str(e.stdout or "")[-20000:], [], "timeout"
        except Exception as e:  # noqa: BLE001
            transcript, trace, err = "", [], f"{type(e).__name__}: {e}"
        probe = srv.probe_no_token()
        code, led = srv.ledger()
    finally:
        crashed = srv.stop()
        shutil.rmtree(wd, ignore_errors=True)
    (tdir / f"attacker-{i}.txt").write_text(transcript)
    res = analyse(led if code == 200 else {}, trace, transcript, crashed, probe,
                  None if args.kind == "fake" else local_mole(args.tier, seed))
    attacks = sorted({a.strip().rstrip('"}') for a in re.findall(r"ATTACK:[^\n]*", transcript.replace("\\n", "\n"))})
    return {"run": i, "seed": seed, "tier": args.tier, "backend": args.backend, "mode": args.mode,
            "server": {"real": "real", "envshim": "envshim(real Env, stub transport)"}.get(args.kind, "fake(plumbing-only)"),
            "secs": round(time.time() - t0, 1), "error": err, "ledger_http": code, **res,
            "attack_lines": attacks, "n_tool_calls": len(trace), "trace": trace}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=list(BACKENDS), default="stub")
    ap.add_argument("--mode", choices=["blackbox", "whitebox"], default="blackbox")
    ap.add_argument("--tier", default="easy")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--server", choices=["auto", "real", "envshim", "fake"], default="auto")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--prompt", default="attacker", choices=["attacker", "attacker_direct"])
    a = ap.parse_args(argv)
    kind, module = resolve_server(a.server)
    a.kind = kind
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(a.out or REPO / "data" / "runs" / f"redteam-hunter-{a.backend}-{a.mode}-{ts}")
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(outdir / "attempts.jsonl", "w") as f:
        for i in range(a.runs):
            r = run_once(a, i, outdir, module)
            rows.append(r)
            f.write(json.dumps(r) + "\n")
            f.flush()
            print(f"run {i} seed={r['seed']} score={r['score']} correct={r['correct']} flags={r['flags']} err={r['error']}")
    summary = {"backend": a.backend, "mode": a.mode, "tier": a.tier, "server": kind,
               "plumbing_only": kind == "fake", "transport_is_real": kind == "real", "runs": len(rows),
               "exploits": sum(r["exploit"] for r in rows),
               "flags": sorted({fl for r in rows for fl in r["flags"]}),
               "mean_score": sum((r["score"] or 0) for r in rows) / max(1, len(rows)),
               "attack_lines": [ln for r in rows for ln in r["attack_lines"]]}
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
