import argparse
import hashlib
import json
import time
from pathlib import Path


def plain(x):
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    if hasattr(x, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(x)
    return x


def ident(x):
    if x is None or isinstance(x, (str, int)):
        return x
    return getattr(x, "id", None) or hashlib.sha1(json.dumps(plain(x), sort_keys=True, default=str).encode()).hexdigest()[:8]


def kind(goal):
    return "none" if goal is None else getattr(goal, "kind", None) or str(ident(goal))


def cid(c):
    body = json.dumps(plain(c["strategy"]), sort_keys=True, default=str) if c["strategy"] is not None and not isinstance(c["strategy"], str) else str(c["strategy"])
    key = json.dumps([c["seed"], c["sleeper_seat"], ident(c["goal"]), ident(c["strategy"]), hashlib.sha1(body.encode()).hexdigest()[:6]])
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def reward(r):
    return r["reward"] if isinstance(r, dict) else r


def play(run_day, c, team, k):
    return [reward(run_day(c["seed"], team, c["sleeper_seat"], c["goal"], c["strategy"], run=i)) for i in range(k)]


def evaluate(c, run_day, k=3):
    base = {"id": cid(c), **c, "goal_kind": kind(c["goal"]), "k": k}
    oracle = play(run_day, c, "oracle", 1)[0]
    base["oracle"] = oracle
    if c["sleeper_seat"] is None:
        ok = oracle == 1
        return {**base, "type": "no_sleeper", "verdict": "kept" if ok else "dropped", "reason": "" if ok else "unbeatable"}
    trust = play(run_day, c, "trust_all", 1)[0]
    ref = play(run_day, c, "reference", k)
    staff = play(run_day, c, "staff", k)
    ref_m, staff_m = sum(ref) / k, sum(staff) / k
    out = {**base, "type": "sleeper", "reference": ref_m, "staff": staff_m, "staff_fails": staff.count(0), "regret": ref_m - staff_m, "trust_all": trust}
    if oracle != 1:
        reason = "unbeatable"
    elif trust == 1 and base["goal_kind"] != "frame":
        reason = "blind_diligence_wins"
    elif 0 not in staff:
        reason = "no_gap"
    elif ref_m <= staff_m:
        reason = "reference_not_better"
    else:
        reason = ""
    return {**out, "verdict": "kept" if not reason else "dropped", "reason": reason}


def filter_candidates(cands, run_day, k=3):
    kept, dropped = [], []
    for c in cands:
        e = evaluate(c, run_day, k)
        (kept if e["verdict"] == "kept" else dropped).append(e)
    return kept, [(e, e["reason"]) for e in dropped]


def mutate_round(kept, run_day, mutate, k=3, variants=1):
    cands = []
    for e in kept:
        if e["type"] != "sleeper":
            continue
        for v in range(variants):
            cands.append({"seed": e["seed"], "sleeper_seat": e["sleeper_seat"], "goal": e["goal"], "strategy": mutate(e["strategy"], e["seed"] + v)})
    seen = {e["id"] for e in kept}
    cands = [c for c in cands if cid(c) not in seen]
    return filter_candidates(cands, run_day, k)


def summary(kept, dropped):
    s = {"sleeper": {}, "no_sleeper": {"kept": 0, "dropped": 0}}
    for e in kept + [d for d, _ in dropped]:
        if e["type"] == "no_sleeper":
            s["no_sleeper"]["kept" if e["verdict"] == "kept" else "dropped"] += 1
            continue
        g = s["sleeper"].setdefault(e["goal_kind"], {"kept": 0, "dropped": 0, "regret_sum": 0.0, "reasons": {}})
        if e["verdict"] == "kept":
            g["kept"] += 1
            g["regret_sum"] += e["regret"]
        else:
            g["dropped"] += 1
            g["reasons"][e["reason"]] = g["reasons"].get(e["reason"], 0) + 1
    for g in s["sleeper"].values():
        g["mean_regret"] = g.pop("regret_sum") / g["kept"] if g["kept"] else None
    return s


def dump(path, k, kept, dropped, extra=None):
    d = {"k": k, "summary": summary(kept, dropped), "kept": kept, "dropped": [e for e, _ in dropped], **(extra or {})}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(d, indent=1, default=lambda o: plain(o) if plain(o) is not o else str(o)))


def run_day(seed, team, sleeper_seat=None, goal=None, strategy=None, run=0):
    import random
    from agents.sleeper_agent import SleeperAgent
    from lab.run import build_team
    from sleeper import goals
    from sleeper.company import seed_company
    from sleeper.day import run_day as world_run_day
    from sleeper.tickets import make_day
    from sleeper.verifier import score
    st = goals.STRATEGIES[strategy] if isinstance(strategy, str) else strategy
    g = goals.make_goal(st.kind, random.Random(seed), seed_company(seed), sleeper_seat=sleeper_seat) if st else None
    day = make_day(seed, sleeper_seat, g)
    if st:
        day.tickets = day.tickets + st.render_tickets(g.target)
    players = build_team(team, day, run)
    if st:
        players[sleeper_seat] = SleeperAgent(sleeper_seat, g, st, random.Random(seed), ticks=day.ticks)
    w = world_run_day(day, players)
    return score(day, w.initial, w.company, w.ledger, agent=team).model_dump()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=20)
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--out", default="results/regret")
    p.add_argument("--mutate", type=int, default=0)
    a = p.parse_args()
    from sleeper.goals import candidates
    kept, dropped = filter_candidates(candidates(a.seeds), run_day, a.k)
    mutated = []
    if a.mutate:
        from agents.sleeper_agent import mutate_strategy
        for _ in range(a.mutate):
            mk, md = mutate_round([e for e in kept if e not in mutated], run_day, mutate_strategy, a.k)
            kept += mk
            mutated += mk
            dropped += md
    f = Path(a.out) / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    dump(f, a.k, kept, dropped, {"mutated_ids": [e["id"] for e in mutated]})
    print(f"kept {len(kept)} dropped {len(dropped)} -> {f}")


if __name__ == "__main__":
    main()
