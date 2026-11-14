"""Cheat corpus (port of Momin's redteam/cheat_corpus.py + cheat_eval.py `Inject` onto Canary).

Mine: every distinct (tool, arg-shape) call that FAILED (ok=false) in a committed frontier-agent transcript,
plus Momin's real Gemini tricks from his Sleeper env (foreign tools, e.g. report_insider) -> data/redteam/corpus.jsonl.
Eval: inject each row into the solver's episode at its midpoint (Momin's Inject at ticks//2). A failed call must
change nothing, so the solver's score must be EXACTLY unchanged ("lift" or "harm" both fail).

    uv run python -m canary.redteam.corpus mine [--momin FILE]
    uv run python -m canary.redteam.corpus eval [--seeds N] [--tiers medium,hard]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data/redteam/corpus.jsonl"


def shape(v):
    if isinstance(v, dict):
        return {k: shape(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [shape(x) for x in v]
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return "<N>"
    s = str(v)
    if re.fullmatch(r"e\d+", s):
        return "<ID>"
    return "<TEXT>" if len(s) > 12 else s


_PROBE_ENV = None


def _always_invalid(tool, args) -> bool:
    """True if the call is rejected in ANY state: unknown tool or args that fail the schema check. Calls that
    failed only because of state (daily limit, already restricted, ...) are excluded: injected later they may
    legitimately succeed."""
    global _PROBE_ENV
    from ..env import _SPECS, Env
    if not isinstance(tool, str) or tool not in _SPECS:
        return True
    if _PROBE_ENV is None:
        _PROBE_ENV = Env("hard", 0)
    return not _PROBE_ENV._check_args(tool, args)


def mine(momin_file: Path | None = None) -> list[dict]:
    from ..reproduce import committed_files
    seen: dict[str, dict] = {}
    for f in committed_files(ROOT):
        if "/reference/" in str(f):
            continue
        for line in f.read_text().splitlines():
            e = json.loads(line)
            for st in e.get("steps", []):
                if (st.get("result") or {}).get("ok", True) or not _always_invalid(st["tool"], st["args"]):
                    continue
                key = json.dumps([st["tool"], shape(st["args"])], sort_keys=True)
                row = seen.setdefault(key, {"tool": st["tool"], "args": st["args"], "pattern": key,
                                            "source": e.get("agent"), "error": st["result"].get("error"), "count": 0})
                row["count"] += 1
    if momin_file and momin_file.is_file():
        for line in momin_file.read_text().splitlines():
            r = json.loads(line)
            key = json.dumps([r["tool"], shape(r.get("args") or {})], sort_keys=True)
            seen.setdefault(key, {"tool": r["tool"], "args": r.get("args") or {}, "pattern": key,
                                  "source": f"momin:{r.get('model')}", "error": "foreign tool", "count": r.get("count", 1)})
    return sorted(seen.values(), key=lambda r: (-r["count"], r["pattern"]))


def load() -> list[dict]:
    return [json.loads(l) for l in CORPUS.read_text().splitlines() if l.strip()] if CORPUS.is_file() else []


def inject_run(tier: str, seed: int, row: dict):
    """Solver episode with `row` injected once at the solver's own midpoint."""
    from ..eval import make_env, make_policy_factory
    from .anticheat import solver_actions
    actions, base = solver_actions(tier, seed)
    mid = len(actions) // 2
    env = make_env(tier, seed)
    pol = make_policy_factory("solver")(seed)
    pol.reset(env.tools_spec(), env.instruction())
    injected = None
    n = 0
    while not env.done and n < 2000:
        if n == mid and injected is None:
            injected = env.call(row["tool"], row["args"])
        else:
            tool, args = pol.act(list(env.history))
            env.call(tool, args)
        n += 1
    return base, env.score(), injected


def evaluate(tiers, seeds, rows=None) -> dict:
    rows = load() if rows is None else rows
    out = {"rows": len(rows), "runs": 0, "changed": [], "accepted": []}
    for tier in tiers:
        for seed in seeds:
            for r in rows:
                base, got, inj = inject_run(tier, seed, r)
                out["runs"] += 1
                if inj is not None and inj.ok:
                    out["accepted"].append({"tier": tier, "seed": seed, "pattern": r["pattern"]})
                if abs(got - base) > 1e-9:
                    out["changed"].append({"tier": tier, "seed": seed, "pattern": r["pattern"], "base": base, "got": got})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["mine", "eval"])
    ap.add_argument("--momin", type=Path, default=None)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--tiers", default="medium,hard")
    a = ap.parse_args(argv)
    if a.cmd == "mine":
        rows = mine(a.momin)
        CORPUS.parent.mkdir(parents=True, exist_ok=True)
        CORPUS.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        print(f"{len(rows)} distinct failed/foreign calls -> {CORPUS.relative_to(ROOT)}")
        return 0
    res = evaluate(a.tiers.split(","), list(range(a.seeds)))
    print(json.dumps({k: (v if isinstance(v, int) else v[:10]) for k, v in res.items()}, indent=1))
    print(f"runs={res['runs']} changed={len(res['changed'])} accepted={len(res['accepted'])}")
    return 1 if res["changed"] or res["accepted"] else 0


if __name__ == "__main__":
    sys.exit(main())
