import argparse
import json
import os
import time

from lab.results import summarise

TEAMS = ["staff", "reference", "oracle", "do_nothing", "stop_early", "quarantine_all"]


FACTORIES = {
    "staff": ("agents.staff", "make_team"),
    "reference": ("agents.reference", "make_reference_team"),
    "oracle": ("agents.reference", "make_oracle_team"),
    "do_nothing": ("sleeper.baselines", "make_do_nothing"),
    "stop_early": ("sleeper.baselines", "make_stop_early"),
    "quarantine_all": ("sleeper.baselines", "make_quarantine_all"),
}


def build_team(name, day, seed):
    import importlib

    mod, fn = FACTORIES[name]
    return getattr(importlib.import_module(mod), fn)(day, seed)


def play_day(team, day_idx, seed, seat):
    from sleeper.tickets import build_day
    from sleeper.world import run_day
    from sleeper.verifier import score

    day = build_day(day_idx, seed)
    company, ledger, transcript = run_day(day, build_team(team, day, seed), seat)
    result = score(company, ledger, day)
    result = dict(result if isinstance(result, dict) else result.model_dump())
    result.setdefault("has_sleeper", day.sleeper_seat is not None)
    result.setdefault("goal_kind", day.goal.kind if day.goal else None)
    return result, transcript


def run_id(team, seat, days, seeds):
    return f"{team}-{seat}-d{days}-s{seeds}"


def run(team, days, seeds, seat="controller", out="results", runner=play_day):
    rid = run_id(team, seat, days, seeds)
    d = os.path.join(out, rid)
    os.makedirs(os.path.join(d, "transcripts"), exist_ok=True)
    rows = []
    with open(os.path.join(d, "days.jsonl"), "w") as f:
        for day_idx in range(days):
            for seed in range(seeds):
                res, tr = runner(team, day_idx, seed, seat)
                res = dict(res)
                res.setdefault("day_id", day_idx)
                res.setdefault("agent", team)
                res.setdefault("seat_under_test", seat)
                if tr is not None:
                    p = os.path.join(d, "transcripts", f"day{day_idx}-seed{seed}.json")
                    with open(p, "w") as t:
                        json.dump({**tr, "result": res} if isinstance(tr, dict) else {"transcript": tr, "result": res}, t, sort_keys=True)
                    res["transcript_path"] = p
                rows.append(res)
                f.write(json.dumps(res, sort_keys=True) + "\n")
    summary = summarise(rows, team)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump({"run_id": rid, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
    return d, summary


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--team", choices=TEAMS, required=True)
    p.add_argument("--days", type=int, default=20)
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--seat", default="controller")
    p.add_argument("--out", default="results")
    a = p.parse_args(argv)
    d, s = run(a.team, a.days, a.seeds, a.seat, a.out)
    print(d)
    print(json.dumps(s, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
