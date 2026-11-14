"""Human playtest CLI: make play TIER=medium NAME=alice SEED=3000

Friendly commands map 1:1 onto Env.call; unknown input never touches the env (no cap use).
The result is saved as one EpisodeResult JSON line (same format as eval's episodes.jsonl) to
data/runs/human/<name>-<tier>-<seed>.jsonl. Correctness is hidden unless --reveal.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shlex
from dataclasses import asdict
from typing import Iterable, Iterator

from .env import Env
from .rules import DEV_SEEDS

TOPICS = {"docs": "recent_documents", "documents": "recent_documents", "recent_documents": "recent_documents",
          "contacts": "contacts_outside", "contacts_outside": "contacts_outside",
          "workload": "workload", "work": "workload", "access": "access_needs", "access_needs": "access_needs"}
EMP = re.compile(r"^e\d{2}$")
RANGE = re.compile(r"^(\d+)-(\d+)$")

HELP = """commands:
  status | staff | docs [d1-d2] | logs d1-d2 [eXX] | search <query> [d1-d2] | read <msg_id>
  interview eXX docs|contacts|workload|access
  canary "title" e01,e02=A e03=B   | feed | restrict eXX | unrestrict eXX
  next | accuse eXX | rules | help | quit"""


def _range(tok: str) -> dict | None:
    m = RANGE.match(tok)
    return {"day_from": int(m[1]), "day_to": int(m[2])} if m else None


def parse(line: str) -> tuple[str, dict] | None:
    """Map one input line to (tool, args); None if it is not a valid env command."""
    try:
        t = shlex.split(line.strip())
    except ValueError:
        return None
    if not t:
        return None
    c, a = t[0].lower(), t[1:]
    if c == "status" and not a:
        return "status", {}
    if c in ("staff", "employees") and not a:
        return "list_employees", {}
    if c == "docs" and len(a) <= 1:
        if not a:
            return "list_documents", {}
        r = _range(a[0])
        return ("list_documents", r) if r else None
    if c == "logs" and 1 <= len(a) <= 2:
        r = _range(a[0])
        if not r or (len(a) == 2 and not EMP.match(a[1])):
            return None
        return "read_access_logs", r | ({"employee": a[1]} if len(a) == 2 else {})
    if c == "search" and a:
        r = _range(a[-1]) if len(a) > 1 else None
        q = " ".join(a[:-1] if r else a)
        return "search_messages", {"query": q} | (r or {})
    if c == "read" and len(a) == 1:
        return "read_message", {"id": a[0]}
    if c == "interview" and len(a) == 2 and EMP.match(a[0]) and a[1].lower() in TOPICS:
        return "interview", {"employee": a[0], "topic": TOPICS[a[1].lower()]}
    if c == "canary" and len(a) >= 2:
        asg = {}
        for grp in a[1:]:
            if grp.count("=") != 1:
                return None
            ids, lab = grp.split("=")
            if not lab:
                return None
            for e in ids.split(","):
                if not EMP.match(e):
                    return None
                asg[e] = lab
        return "plant_canary", {"doc_title": a[0], "assignment": asg}
    if c == "feed" and not a:
        return "check_leak_feed", {}
    if c in ("restrict", "unrestrict") and len(a) == 1 and EMP.match(a[0]):
        return f"{c}_access", {"employee": a[0]}
    if c in ("next", "advance") and not a:
        return "advance_day", {}
    if c == "accuse" and len(a) == 1 and EMP.match(a[0]):
        return "accuse", {"employee": a[0]}
    return None


def table(rows: list[dict]) -> str:
    if not rows:
        return "(none)"
    cols = list(dict.fromkeys(k for r in rows for k in r))
    cell = lambda v: json.dumps(v) if isinstance(v, (list, dict)) else str(v)
    w = {c: max(len(c), *(len(cell(r.get(c, ""))) for r in rows)) for c in cols}
    w = {c: min(v, 60) for c, v in w.items()}
    line = lambda vals: "  ".join(cell(v)[:w[c]].ljust(w[c]) for c, v in zip(cols, vals))
    return "\n".join([line(cols), line(["-" * w[c] for c in cols])] + [line([r.get(c, "") for c in cols]) for r in rows])


def render(data: dict) -> str:
    out = []
    for k, v in data.items():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            out.append(f"{k}:\n{table(v)}")
        elif isinstance(v, str) and "\n" in v:
            out.append(f"{k}:\n{v}")
        else:
            out.append(f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}")
    return "\n".join(out)


def save(env: Env, name: str, tier: str, seed: int, out_dir: str = "data/runs/human") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}-{tier}-{seed}.jsonl")
    with open(path, "a") as fh:
        fh.write(json.dumps(asdict(env.result(f"human:{name}")), sort_keys=True) + "\n")
    return path


def session(env: Env, lines: Iterable[str], name: str, tier: str, seed: int, out=print,
            reveal: bool = False, out_dir: str = "data/runs/human") -> str:
    it: Iterator[str] = iter(lines)
    for line in it:
        s = line.strip()
        low = s.lower()
        if low in ("quit", "exit", "q"):
            break
        if low in ("help", "?"):
            out(HELP); continue
        if low == "rules":
            out(env.instruction()); continue
        cmd = parse(s)
        if cmd is None:
            if s:
                out("unknown command (no action used)\n" + HELP)
            continue
        tool, args = cmd
        if tool == "accuse":
            out(f"accuse {args['employee']}? this ends the episode [y/n]")
            if next(it, "n").strip().lower() not in ("y", "yes"):
                out("cancelled"); continue
        r = env.call(tool, args)
        out(render(r.data) if r.ok else f"error: {r.error}")
        if not env.done:
            st = env.peek_status()  # local peek, not an env.call: never uses the cap
            out(f"[day {st.get('day')}  V={st.get('V')}  actions_left_today={st.get('actions_left_today')}]")
        if env.done:
            break
    path = save(env, name, tier, seed, out_dir)
    out("episode over; score is recorded" + (f" -> {path}" if path else ""))
    if reveal:
        res = env.result(f"human:{name}")
        out(f"correct={res.correct} score={res.score} accused={res.accused}")
    return path


def _stdin_lines():
    while True:
        try:
            yield input("canary> ")
        except EOFError:
            return


def main(argv=None):
    ap = argparse.ArgumentParser(description="Canary human playtest")
    ap.add_argument("--tier", default="medium", choices=("easy", "medium", "hard"))
    ap.add_argument("--name", default="human")
    ap.add_argument("--seed", default="")
    ap.add_argument("--reveal", action="store_true")
    a = ap.parse_args(argv)
    # non-numeric (e.g. the Makefile default SEEDS=dev20 leaking in) -> random dev seed 3000-3999
    seed = int(a.seed) if str(a.seed).strip().isdigit() else random.randint(3000, 3999)
    if not (seed >= 3000 and seed in DEV_SEEDS):
        ap.error(f"seed must be a dev seed in 3000..{DEV_SEEDS.stop - 1} (judge seeds only via the server)")
    if not re.fullmatch(r"[\w.-]{1,40}", a.name):
        ap.error("name: letters/digits/._- only")
    env = Env(a.tier, seed)
    print(env.instruction())
    print(f"\n{a.tier} tier, seed {seed}. Type 'help' for commands.\n")
    session(env, _stdin_lines(), a.name, a.tier, seed, reveal=a.reveal)


if __name__ == "__main__":
    main()
