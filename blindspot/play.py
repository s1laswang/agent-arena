"""Play one day step by step from a shell (one tool call per command).

Used to let an outside agent (e.g. a fresh Claude / Gemini CLI session with no
access to the source) play the AP seat exactly as it would over MCP, and to let
a human try a day.

  python -m blindspot.play new  --session runs/play/a.json --seed 7 [--difficulty hard]
  python -m blindspot.play tools
  python -m blindspot.play call --session runs/play/a.json read_ticket '{"ticket_id": "T-101"}'
  python -m blindspot.play score --session runs/play/a.json        (after end_day; grader only)

The session file stores only the seed and the list of calls made so far, never
the answer key: each command rebuilds the world from the seed and replays the
calls (the environment is deterministic), then runs the new call.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .env import TOOL_SPECS, Env


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rebuild(sess: dict) -> Env:
    plan = {} if sess.get("difficulty", "standard") == "standard" else {
        "difficulty": sess["difficulty"]}
    env = Env(int(sess["seed"]), **plan)
    for c in sess["calls"]:
        env.call(c["tool"], c["args"])
    return env


def cmd_new(a) -> dict:
    p = Path(a.session)
    if p.exists() and not a.force:
        raise SystemExit(f"session {p} exists (use --force to overwrite)")
    p.parent.mkdir(parents=True, exist_ok=True)
    sess = {"seed": a.seed, "difficulty": a.difficulty, "calls": []}
    p.write_text(json.dumps(sess, indent=1), encoding="utf-8")
    return {"ok": True, "result": "new working day started; call list_tickets / read_policy"}


def cmd_call(a) -> dict:
    sess = _load(a.session)
    try:
        args = json.loads(a.args) if a.args else {}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"arguments must be a JSON object: {e}"}
    if not isinstance(args, dict):
        return {"ok": False, "error": "arguments must be a JSON object"}
    env = _rebuild(sess)
    out = env.call(a.tool, args)
    sess["calls"].append({"tool": a.tool, "args": args})
    Path(a.session).write_text(json.dumps(sess, indent=1), encoding="utf-8")
    return out


def cmd_score(a) -> dict:
    from .verify import score
    env = _rebuild(_load(a.session))
    s = score(env.state())
    return {"reward": s["reward"], "tickets_ok": s["tickets_ok"],
            "tickets_total": s["tickets_total"], "hazards_caught": s["hazards_caught"],
            "hazards_total": s["hazards_total"], "eur_lost": s["eur_lost"],
            "ended": env.world["ended"], "steps": env.steps,
            "failed": {tid: {"family": t["family"], "hazard": t["hazard"], "reasons": t["reasons"]}
                       for tid, t in s["tickets"].items() if not t["ok"]},
            "harms": s["harms"]}


def summarise(paths: list[str], out_dir: str) -> str:
    """Score finished sessions, copy them (calls only) to out_dir, write summary.md."""
    import shutil
    out = Path(out_dir)
    (out / "sessions").mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(paths):
        sess = _load(p)
        s = cmd_score(type("A", (), {"session": p})())
        shutil.copy(p, out / "sessions" / Path(p).name)
        rows.append((Path(p).stem, sess["seed"], sess.get("difficulty", "standard"), s))
    lines = ["| run | seed | difficulty | reward | tickets | hazards caught | EUR lost | steps | failed |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, seed, diff, s in rows:
        failed = ", ".join(f"{v['family']}{' (hazard)' if v['hazard'] else ' (benign)'}"
                           for v in s["failed"].values()) or "-"
        lines.append(f"| {name} | {seed} | {diff} | {s['reward']} | {s['tickets_ok']}/{s['tickets_total']} "
                     f"| {s['hazards_caught']}/{s['hazards_total']} | {s['eur_lost']:,.0f} | {s['steps']} | {failed} |")
    text = "\n".join(lines) + "\n"
    (out / "summary.md").write_text(text, encoding="utf-8")
    (out / "scores.json").write_text(json.dumps({r[0]: r[3] for r in rows}, indent=1, default=str),
                                     encoding="utf-8")
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m blindspot.play")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--session", required=True)
    n.add_argument("--seed", type=int, required=True)
    n.add_argument("--difficulty", default="standard", choices=["standard", "hard", "expert"])
    n.add_argument("--force", action="store_true")
    sub.add_parser("tools")
    c = sub.add_parser("call")
    c.add_argument("--session", required=True)
    c.add_argument("tool")
    c.add_argument("args", nargs="?", default="")
    s = sub.add_parser("score")
    s.add_argument("--session", required=True)
    sm = sub.add_parser("summarise")
    sm.add_argument("sessions", nargs="+")
    sm.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "summarise":
        print(summarise(a.sessions, a.out))
        return
    if a.cmd == "new":
        out = cmd_new(a)
    elif a.cmd == "tools":
        out = {name: {"description": d, "params": p} for name, (d, p) in TOOL_SPECS.items()}
    elif a.cmd == "call":
        out = cmd_call(a)
    else:
        out = cmd_score(a)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
