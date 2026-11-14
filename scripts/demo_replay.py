"""Side-by-side day-by-day replay of two committed episodes on the same seed (demo; no keys, no network).

    python scripts/demo_replay.py                       # hard seed 4: solver vs OpenCode gemini-4-carbon (v1.4)
    python scripts/demo_replay.py --seed 26             # the "Fooled" seed: Gemini accuses the wrong person
    python scripts/demo_replay.py --seed 4 --verify     # also replay both episodes through a fresh Env first

Reads only committed runs under data/runs/committed/v1.4/. For every day it prints, for each agent:
the company value V the agent could see (known V), canaries planted so far, interviews so far, and the
reference solver's exact posterior that the TRUE mole is the mole given everything that agent had seen by the
end of that day (canary.solver.policy.SolverPolicy.belief, the same posterior canary.analysis.accuse uses).
The true mole is taken from a correct episode on the same seed (a correct accusation names the mole).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

R = ROOT / "data/runs/committed/v1.4"
RUNS = {
    "solver": [R / "reference/solver-hard-20261114-121126", R / "reference/solver-hard-seeds20to29"],
    "gemini": [R / "opencode-gemini-4-carbon/hard"],
}
LABEL = {"solver": "reference solver", "gemini": "gemini-4-carbon (OpenCode over MCP, judges' harness)"}


def load(dirs, seed: int) -> dict:
    for d in dirs:
        f = d / "episodes.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                if e["seed"] == seed:
                    e.setdefault("tier", "hard")
                    e["_file"] = str(f.relative_to(ROOT))
                    return e
    raise SystemExit(f"seed {seed} not found in {[str(d) for d in dirs]}")


def per_day(e: dict, mole: str | None) -> dict[int, dict]:
    from canary.analysis.tags import to_result
    from canary.rules import tier_params_for_episode
    from canary.solver.policy import SolverPolicy

    ep = to_result(e)
    sp = SolverPolicy(tier_params_for_episode(ep.tier, ep.steps))
    out: dict[int, dict] = {}
    V, canaries, interviews = 1.0, 0, 0
    for i, st in enumerate(ep.steps):
        res = (st.result or {}).get("data") or {}
        if st.tool in ("status", "advance_day") and isinstance(res, dict) and "V" in res:
            V = res["V"]
        if st.tool == "plant_canary" and (st.result or {}).get("ok"):
            canaries += 1
        if st.tool == "interview":
            interviews += 1
        last_of_day = i + 1 == len(ep.steps) or ep.steps[i + 1].day != st.day
        if st.tool == "accuse":
            last_of_day = True
        if last_of_day:
            for prev in ep.steps[sp.seen:i + 1]:
                if prev.tool != "accuse":
                    sp._ingest(prev)
            sp.seen = i + 1
            post = sp.belief() if sp.obs.employees else {}
            top = max(post, key=post.get) if post else None
            out[st.day] = dict(V=V, canaries=canaries, interviews=interviews, calls=i + 1,
                               p_mole=post.get(mole) if (post and mole) else None,
                               top=top, p_top=post.get(top) if top else None,
                               accused=st.args.get("employee") if st.tool == "accuse" else None)
    return out


def fmt(row: dict | None, ended: str | None) -> str:
    if row is None:
        return f"{'':>4} {ended or '':<38}"
    p = "  -  " if row["p_mole"] is None else f"{row['p_mole']:.2f}"
    acc = f"  ACCUSE {row['accused']}" if row["accused"] else ""
    return f"V={row['V']:.2f} can={row['canaries']:>2} int={row['interviews']:>2} P(mole)={p}{acc}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--verify", action="store_true", help="replay both episodes in a fresh Env and check the score")
    a = ap.parse_args(argv)
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")

    eps = {k: load(v, a.seed) for k, v in RUNS.items()}
    mole = next((e["accused"] for e in eps.values() if e.get("correct")), None)
    if a.verify:
        from scripts.verify_replay import replay_episode
        for k, e in eps.items():
            r = replay_episode(e)
            ok = abs(r["score"] - e["score"]) < 1e-9 and r["accused"] == e["accused"]
            print(f"verify {k:<6} recorded {e['score']:+.2f} replayed {r['score']:+.2f} -> {'MATCH' if ok else 'MISMATCH'}")
            if not ok:
                return 1
    days = {k: per_day(e, mole) for k, e in eps.items()}

    print(f"Canary v1.4, tier hard, dev seed {a.seed}. True mole: {mole or 'unknown (no correct episode)'}")
    for k, e in eps.items():
        verdict = "correct" if e.get("correct") else ("WRONG" if e.get("accused") else "no accusation")
        print(f"  {k:<6} {LABEL[k]}: score {e['score']:+.2f}, accused {e.get('accused')} on day {e['final_day']} "
              f"({verdict}), {len(e['steps'])} tool calls  [{e['_file']}]")
    print()
    print(f"{'day':>3} | {'SOLVER':<52} | GEMINI")
    last = max(max(d) for d in days.values())
    for d in range(1, last + 1):
        cells = []
        for k in ("solver", "gemini"):
            row = days[k].get(d)
            ended = f"(done: day {eps[k]['final_day']}, {eps[k]['score']:+.2f})" if d > eps[k]["final_day"] else None
            cells.append(fmt(row, ended))
        print(f"{d:>3} | {cells[0]:<52} | {cells[1]}")
    s, g = eps["solver"], eps["gemini"]
    print()
    if s.get("correct") and g.get("correct") and s["accused"] == g["accused"]:
        print(f"Same answer ({mole}); the solver had it on day {s['final_day']}, Gemini {g['final_day'] - s['final_day']} days "
              f"later. Value kept: solver {s['score']:.2f} vs Gemini {g['score']:.2f} "
              f"({g['score'] / s['score']:.0%} of the solver).")
    else:
        print(f"Solver {s['score']:+.2f} vs Gemini {g['score']:+.2f}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
