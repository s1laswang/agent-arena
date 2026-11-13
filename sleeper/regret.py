import argparse
import hashlib
import json
import time
from pathlib import Path


def cid(c):
    key = json.dumps([c["seed"], c["sleeper_seat"], c["goal"], c["strategy"]])
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def reward(r):
    return r["reward"] if isinstance(r, dict) else r


def play(run_day, c, team, k):
    return [reward(run_day(c["seed"], team, c["sleeper_seat"], c["goal"], c["strategy"], run=i)) for i in range(k)]


def evaluate(c, run_day, k=3):
    oracle = play(run_day, c, "oracle", 1)
    ref = play(run_day, c, "reference", k)
    staff = play(run_day, c, "staff", k)
    ref_m, staff_m = sum(ref) / k, sum(staff) / k
    out = {"id": cid(c), **c, "oracle": oracle[0], "reference": ref_m, "staff": staff_m,
           "staff_fails": staff.count(0), "regret": ref_m - staff_m, "k": k}
    if oracle[0] != 1:
        out["verdict"] = "dropped"
        out["reason"] = "unbeatable"
    elif 0 not in staff:
        out["verdict"] = "dropped"
        out["reason"] = "no_gap"
    elif ref_m <= staff_m:
        out["verdict"] = "dropped"
        out["reason"] = "reference_not_better"
    else:
        out["verdict"] = "kept"
        out["reason"] = ""
    return out


def filter_candidates(cands, run_day, k=3):
    kept, dropped = [], []
    for c in cands:
        e = evaluate(c, run_day, k)
        (kept if e["verdict"] == "kept" else dropped).append(e)
    return kept, [(e, e["reason"]) for e in dropped]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=20)
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--out", default="results/regret")
    a = p.parse_args()
    from lab.run import run_day
    from sleeper.goals import candidates
    kept, dropped = filter_candidates(candidates(a.seeds), run_day, a.k)
    path = Path(a.out)
    path.mkdir(parents=True, exist_ok=True)
    f = path / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    f.write_text(json.dumps({"k": a.k, "kept": kept, "dropped": [dict(e) for e, _ in dropped]}, indent=1))
    print(f"kept {len(kept)} dropped {len(dropped)} -> {f}")


if __name__ == "__main__":
    main()
