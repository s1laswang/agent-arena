"""Keyless reproduction of recorded Gemini runs (`make lab-replay`).

    python -m canary.gemini.lab_replay                       # replay every results/gemini/replay*/ store
    python -m canary.gemini.lab_replay --record NAME -- python -m canary.gemini.ladder ... --out {out}

A store is a gateway --record directory with a manifest.json:
    {"name", "cmd": [... "{out}" ...], "recorded_at", "git_sha",
     "episodes": {"<rel path of episodes.jsonl>": [{"seed", "tier", "score", "steps_sha256"}]}}
Replay runs `cmd` behind a --replay gateway (no key, no network) with {out} = a fresh dir under
data/gemini/replay-check/, then checks every recorded episode reproduces (same score, identical step list).
The original showcase store (results/gemini/replay, showcase.json) is replayed too.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "gemini"
CHECK = ROOT / "data" / "gemini" / "replay-check"


def _steps_sha(ep: dict) -> str:
    return hashlib.sha256(json.dumps(ep.get("steps", []), sort_keys=True).encode()).hexdigest()


def summarize(out: Path) -> dict:
    eps: dict[str, list] = {}
    for f in sorted(out.rglob("episodes.jsonl")):
        if "_invalid" in f.parts:
            continue
        rows = []
        for line in f.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                rows.append({"seed": e.get("seed"), "tier": e.get("tier"), "score": e.get("score"),
                             "steps_sha256": _steps_sha(e)})
        eps[str(f.relative_to(out))] = rows
    return eps


def _with_gateway(mode: str, store: Path, cmd: list[str], ledger: Path) -> int:
    return subprocess.call([sys.executable, "-m", "canary.gemini.with_gateway", f"--{mode}", str(store),
                            "--ledger", str(ledger), "--", *cmd], cwd=ROOT)


def record(name: str, cmd: list[str]) -> int:
    store = RESULTS / f"replay-{name}"
    if store.exists():
        print(f"lab_replay: {store} exists; remove it first", file=sys.stderr)
        return 1
    out = ROOT / "data" / "gemini" / "replay-record" / name
    shutil.rmtree(out, ignore_errors=True)
    rc = _with_gateway("record", store, [c.replace("{out}", str(out)) for c in cmd], out.parent / f"{name}-ledger.jsonl")
    if rc != 0:
        return rc
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    man = {"name": name, "cmd": cmd, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": sha,
           "episodes": summarize(out)}
    (store / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    n = sum(len(v) for v in man["episodes"].values())
    print(f"lab_replay: recorded {name}: {n} episodes, {sum(1 for _ in store.rglob('*.json.gz'))} responses -> {store}")
    return 0


def replay_store(store: Path) -> bool:
    man = json.loads((store / "manifest.json").read_text())
    out = CHECK / man["name"]
    shutil.rmtree(out, ignore_errors=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    rc = _with_gateway("replay", store, [c.replace("{out}", str(out)) for c in man["cmd"]],
                       CHECK / f"{man['name']}-ledger.jsonl")
    got = summarize(out) if out.exists() else {}
    ok = rc == 0 and got == man["episodes"]
    n = sum(len(v) for v in man["episodes"].values())
    if ok:
        scores = [e["score"] for v in got.values() for e in v]
        print(f"lab_replay: {man['name']}: REPLAY OK, {n} episodes reproduced step for step "
              f"(scores {scores[:8]}{' ...' if len(scores) > 8 else ''})")
    else:
        missing = sorted(set(man["episodes"]) - set(got))
        diff = [k for k in man["episodes"] if k in got and got[k] != man["episodes"][k]]
        print(f"lab_replay: {man['name']}: MISMATCH rc={rc} missing={missing[:5]} differing={diff[:5]}",
              file=sys.stderr)
    return ok


def replay_all() -> int:
    ok = True
    show = RESULTS / "replay"
    if (show / "showcase.json").exists():
        rc = _with_gateway("replay", show, [sys.executable, "-m", "canary.gemini.showcase", "--check",
                                            str(show / "showcase.json")], CHECK / "showcase-ledger.jsonl")
        ok &= rc == 0
    for store in sorted(RESULTS.glob("replay-*")):
        if (store / "manifest.json").exists():
            ok &= replay_store(store)
    print("lab_replay: ALL OK" if ok else "lab_replay: FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(prog="python -m canary.gemini.lab_replay")
    p.add_argument("--record", metavar="NAME", help="record results/gemini/replay-NAME by running the command after --")
    p.add_argument("--only", metavar="NAME", help="replay only results/gemini/replay-NAME")
    a = p.parse_args(argv)
    if a.record:
        if not cmd:
            p.error("--record needs a command after --, with {out} as its output dir")
        return record(a.record, cmd)
    if a.only:
        return 0 if replay_store(RESULTS / f"replay-{a.only}") else 1
    return replay_all()


if __name__ == "__main__":
    sys.exit(main())
