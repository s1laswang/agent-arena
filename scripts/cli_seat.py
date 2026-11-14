import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

from harbor.opencode.instruction import seat_instruction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def commit():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def server_argv(seat, seed, out):
    return [PY, "-m", "sleeper.mcp_server", "--seat", seat, "--day", str(seed), "--team", "procedure", "--out", out]


def score_state(out, seat, model):
    env = {**os.environ, "SLEEPER_SEAT": seat}
    r = subprocess.run([PY, "-m", "sleeper.verifier", "--state", out], cwd=ROOT, capture_output=True, text=True, env=env)
    d = json.loads(r.stdout.strip().splitlines()[-1])
    return {"reward": d["reward"], "harm": d["harm"], "false_quarantines": d["false_quarantine"],
            "sleeper_caught": d["sleeper_caught"], "tickets_done": d["tickets_done"], "tickets_total": d["tickets_total"]}


def parse_claude(lines):
    calls, pend = [], {}
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b["name"].startswith("mcp__sleeper__"):
                c = {"tool": b["name"][14:], "args": b["input"], "result": None}
                pend[b["id"]] = c
                calls.append(c)
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in pend:
                t = b["content"]
                pend[b["tool_use_id"]]["result"] = t if isinstance(t, str) else "".join(x.get("text", "") for x in t)
    return calls


def parse_codex(lines):
    calls = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        i = e.get("item") or {}
        if e.get("type") == "item.completed" and i.get("type") == "mcp_tool_call" and i.get("server") == "sleeper":
            r = i.get("result") or {}
            txt = "".join(x.get("text", "") for x in r.get("content", [])) if isinstance(r, dict) else str(r)
            calls.append({"tool": i["tool"], "args": i.get("arguments") or {}, "result": txt})
    return calls


def strat(seat, seed):
    from scripts.frontier_day import build_day
    return getattr(build_day(seat, seed)[2], "id", None)


def run_seat(agent, model, seat, seed, days=1, max_turns=60):
    tmp = tempfile.mkdtemp(prefix="cliseat_")
    out = os.path.join(tmp, "state.json")
    argv = server_argv(seat, seed, out)
    prompt = seat_instruction(seat)
    env = {**os.environ, "PYTHONPATH": ROOT}
    if agent == "claude":
        cfg = os.path.join(tmp, "mcp.json")
        json.dump({"mcpServers": {"sleeper": {"command": argv[0], "args": argv[1:], "env": {"PYTHONPATH": ROOT}}}}, open(cfg, "w"))
        cmd = ["claude", "-p", prompt, "--mcp-config", cfg, "--strict-mcp-config", "--model", model,
               "--allowedTools", "mcp__sleeper__*", "--tools", "", "--output-format", "stream-json", "--verbose",
               "--max-turns", str(max_turns), "--permission-mode", "dontAsk"]
    else:
        home = os.path.join(tmp, "codex_home")
        os.makedirs(home)
        src = os.path.expanduser("~/.codex/auth.json")
        if os.path.exists(src):
            os.symlink(src, os.path.join(home, "auth.json"))
        env["CODEX_HOME"] = home
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-s", "read-only", "-C", tmp, "-m", model,
               "-c", f"mcp_servers.sleeper.command={json.dumps(argv[0])}",
               "-c", f"mcp_servers.sleeper.args={json.dumps(argv[1:])}",
               "-c", f'mcp_servers.sleeper.env={{PYTHONPATH={json.dumps(ROOT)}}}',
               "-c", 'mcp_servers.sleeper.default_tools_approval_mode="approve"',
               prompt + "\nUse only the sleeper MCP tools. Do not run shell commands."]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=ROOT if agent == "claude" else tmp, capture_output=True, text=True, env=env, timeout=1800)
    wall = time.time() - t0
    lines = p.stdout.splitlines()
    calls = (parse_claude if agent == "claude" else parse_codex)(lines)
    os.path.exists(out) and os.remove(out)
    asyncio.run(_finish(calls, seat, seed, out))
    return {"model": model, "commit": commit(), "agent": agent, "seat": seat, "seed": seed, "trial": 0, "mode": "seat", "day_source": "day_for", "strategy": strat(seat, seed),
            "scores": score_state(out, seat, model), "calls": len(calls), "wall_s": round(wall, 1),
            "mcp_calls": calls, "transcript": lines, "stderr": p.stderr[-2000:]}


async def _replay(calls, seat, seed, out, src="oracle"):
    from sleeper.company import World
    from sleeper.mcp_server import build_server
    from sleeper.scripted import OracleAgent, make_team
    from sleeper.tickets import make_day
    if src == "day_for":
        from scripts.frontier_day import build_day
        w, bg, _ = build_day(seat, seed)
    elif src == "procedure":
        from agents.procedure import make_procedure_team
        w = World(make_day(seed))
        bg = make_procedure_team(w.day, seed)
    else:
        w = World(make_day(seed))
        bg = make_team(OracleAgent)
    srv = build_server(w, seat, bg, out)
    for c in calls:
        try:
            await srv.call_tool(c["tool"], c["args"] or {})
        except Exception:
            pass
    srv.finish()


async def _finish(calls, seat, seed, out):
    await _replay(calls, seat, seed, out, "day_for")


def rescore(rec):
    out = tempfile.mkdtemp(prefix="replay_") + "/state.json"
    asyncio.run(_replay(rec["mcp_calls"], rec["seat"], rec["seed"], out, rec.get("day_source") or ("procedure" if rec.get("agent") == "gemini" else "oracle")))
    return score_state(out, rec["seat"], rec["model"])


def save(rec):
    d = os.path.join(ROOT, "results", "frontier", rec["model"], rec["commit"])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{rec['seat']}-s{rec['seed']}.json")
    json.dump(rec, open(p, "w"), indent=1)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", choices=["claude", "codex"])
    ap.add_argument("--model")
    ap.add_argument("--seat", default="finance_ap")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--rescore")
    a = ap.parse_args()
    if a.rescore:
        rec = json.load(open(a.rescore))
        print(json.dumps(rescore(rec)), "saved:", json.dumps(rec["scores"]))
        return
    rec = run_seat(a.agent, a.model, a.seat, a.seed, a.days, a.max_turns)
    s = rec["scores"]
    print(f"{a.model} {a.seat} s{a.seed} reward={s['reward']} harm={s['harm']} fq={s['false_quarantines']} calls={rec['calls']} wall={rec['wall_s']}s -> {save(rec)}")


if __name__ == "__main__":
    main()
