"""Replay-verify recorded episodes: re-run each episode's recorded tool calls in a fresh Env and compare with the score.

    python scripts/verify_replay.py <run dir or episodes.jsonl> [...]

The Env is deterministic in (tier, seed, action sequence). For in-process runs the steps are the env's own record;
for OpenCode/Codex runs they are rebuilt from the agent's event stream and the recorded score is the MCP server's
ledger, so a match means the transcript is complete and the ledger agrees with an independent replay.
Exit code 1 if any episode mismatches.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def replay_episode(e: dict) -> dict:
    from canary.env import Env
    env = Env(e["tier"], e["seed"])
    for s in e.get("steps") or []:
        if env.done:
            break
        env.call(s["tool"], s.get("args") or {})
    r = env.result("replay")
    return {"score": r.score, "accused": r.accused, "correct": r.correct, "final_day": r.final_day}


def main(argv=None) -> int:
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    files = [f for p in paths for f in ([p] if p.is_file() else sorted(p.rglob("episodes.jsonl")))]
    bad = n = 0
    for f in files:
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if (e.get("meta") or {}).get("valid") is False:
                continue
            n += 1
            r = replay_episode(e)
            ok = abs(r["score"] - e["score"]) < 1e-9 and r["accused"] == e.get("accused")
            bad += not ok
            print(f"{'OK  ' if ok else 'MISMATCH'} {f.parent.name}/{e['tier']} seed {e['seed']} {e['agent']}: recorded "
                  f"score={e['score']:+.4f} accused={e.get('accused')} day={e.get('final_day')} | replay "
                  f"score={r['score']:+.4f} accused={r['accused']} day={r['final_day']} (steps={len(e.get('steps') or [])})")
    print(f"{n - bad}/{n} episodes replay-verified")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
