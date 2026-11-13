import argparse
import importlib
import json
import os
import time

from lab.results import summarise

FACTORIES = {
    "staff": ("agents.staff", "make_team", "gemini"),
    "reference": ("agents.reference", "make_reference_team", "gemini"),
    "oracle": ("agents.reference", "make_oracle_team", "scripted"),
    "do_nothing": ("sleeper.baselines", "make_do_nothing", "scripted"),
    "stop_early": ("sleeper.baselines", "make_stop_early", "scripted"),
    "quarantine_all": ("sleeper.baselines", "make_quarantine_all", "scripted"),
    "refuse_all": ("sleeper.baselines", "make_refuse_all", "scripted"),
}
TEAMS = list(FACTORIES)


def agent_kind(name):
    if name.startswith("local:"):
        return "local"
    kind = FACTORIES[name][2]
    return "gemini" if kind == "gemini" and os.environ.get("GEMINI_API_KEY") else "scripted"


def agent_model(name):
    if agent_kind(name) == "gemini":
        return os.environ.get("SLEEPER_MODEL_REFERENCE" if name == "reference" else "SLEEPER_MODEL_STAFF")
    return None


def build_team(name, day, trial):
    if name.startswith("local:"):
        mod = importlib.import_module("train.agent")
        return mod.make_team(name[6:], day, trial)
    mod, fn, _ = FACTORIES[name]
    return getattr(importlib.import_module(mod), fn)(day, trial)


def score_world(world, day):
    from sleeper.verifier import score

    result = score(world.company, world.ledger, day)
    return dict(result if isinstance(result, dict) else result.model_dump())


def play_day(team, agent, seat, day_id, trial):
    from sleeper.day import run_day
    from sleeper.tickets import build_day

    day = build_day(day_id)
    players = build_team(team, day, trial)
    if seat:
        players[seat] = build_team(agent, day, trial)[seat]
    world = run_day(day, players)
    result = score_world(world, day)
    result["has_sleeper"] = day.sleeper_seat is not None
    result["goal_kind"] = day.goal.kind if day.goal else None
    return result, getattr(world, "transcript", None)


def run_id(team, seat, agent, days, day_start, trials):
    who = f"{seat}-{agent}" if seat else "all"
    return f"{team}-{who}-d{days}@{day_start}-t{trials}"


def run(team, days, trials, seat=None, agent=None, day_start=0, day_ids=None, out="results", runner=play_day):
    agent = agent or team
    ids = day_ids or list(range(day_start, day_start + days))
    rid = run_id(team, seat, agent, len(ids), ids[0], trials)
    d = os.path.join(out, rid)
    os.makedirs(os.path.join(d, "transcripts"), exist_ok=True)
    rows = []
    with open(os.path.join(d, "days.jsonl"), "w") as f:
        for day_id in ids:
            for trial in range(trials):
                res, tr = runner(team, agent, seat, day_id, trial)
                res = dict(res)
                res.update(day_id=day_id, trial=trial, agent=agent, team=team, seat_under_test=seat)
                if tr is not None:
                    p = os.path.join(d, "transcripts", f"day{day_id}-trial{trial}.json")
                    with open(p, "w") as t:
                        json.dump({**tr, "result": res} if isinstance(tr, dict) else {"transcript": tr, "result": res}, t, sort_keys=True)
                    res["transcript_path"] = p
                rows.append(res)
                f.write(json.dumps(res, sort_keys=True) + "\n")
    summary = summarise(rows, agent, agent_kind(agent), agent_model(agent))
    summary.update(run_id=rid, background_team=team, seat_under_test=seat)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump({"run_id": rid, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
    return d, summary


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--team", required=True)
    p.add_argument("--days", type=int, default=20)
    p.add_argument("--day-start", type=int, default=0)
    p.add_argument("--day-ids")
    p.add_argument("--trials", "--seeds", dest="trials", type=int, default=3)
    p.add_argument("--seat")
    p.add_argument("--agent")
    p.add_argument("--out", default="results")
    a = p.parse_args(argv)
    ids = [int(x) for x in a.day_ids.split(",")] if a.day_ids else None
    d, s = run(a.team, a.days, a.trials, a.seat, a.agent, a.day_start, ids, a.out)
    print(d)
    print(json.dumps(s, indent=2, sort_keys=True))


def run_day(seed, team, sleeper_seat=None, goal=None, strategy=None, run=0):
    from sleeper.day import run_day as world_run_day
    from sleeper.tickets import build_day

    day = build_day(seed, sleeper_seat, goal, strategy)
    return score_world(world_run_day(day, build_team(team, day, run)), day)


if __name__ == "__main__":
    main()
