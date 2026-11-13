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


def dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, (list, tuple)):
        return [dump(x) for x in obj]
    if isinstance(obj, dict):
        return {k: dump(v) for k, v in obj.items()}
    return obj


class Recorder:
    def __init__(self, seat, agent, steps):
        self.seat, self.agent, self.steps = seat, agent, steps

    def turn(self, seat, view, tools, call):
        def rec(tool, *a, **kw):
            out = call(tool, *a, **kw)
            ok = out.get("ok", True) if isinstance(out, dict) else True
            self.steps.append({"i": len(self.steps), "tick": getattr(view, "tick", None) if not isinstance(view, dict) else view.get("tick"), "seat": seat, "view": dump(view), "tool": tool, "args": dump(a[0] if a and not kw else kw or list(a)), "ok": ok, "effect": dump(out)})
            return out

        return self.agent.turn(seat, view, tools, rec)

    def __getattr__(self, name):
        return getattr(self.agent, name)


def play_day(team, agent, seat, day_id, trial):
    from sleeper.day import run_day
    from sleeper.tickets import build_day

    day = build_day(day_id)
    players = build_team(team, day, trial)
    if seat:
        players[seat] = build_team(agent, day, trial)[seat]
    steps = []
    players = {k: Recorder(k, v, steps) for k, v in players.items()}
    world = run_day(day, players)
    result = score_world(world, day)
    goal = day.goal
    result["has_sleeper"] = day.sleeper_seat is not None
    result["goal_kind"] = goal.kind if goal else None
    extra = {
        "day": {"day_id": day_id, "sleeper_seat": day.sleeper_seat, "goal": {"kind": goal.kind, "target": dump(goal.target), "strategy": getattr(goal, "strategy", None)} if goal else None, "tickets": dump(day.tickets)},
        "company": dump(world.company),
        "ledger": dump(world.ledger),
        "messages": dump(world.company.messages if not isinstance(world.company, dict) else world.company.get("messages", [])),
        "steps": steps,
    }
    return result, extra


def run_id(team, seat, agent, days, day_start, trials):
    who = f"{seat}-{agent}" if seat else "all"
    return f"{team}-{who}-d{days}@{day_start}-t{trials}"


def run(team, days, trials, seat=None, agent=None, day_start=0, day_ids=None, out="results", runner=play_day):
    agent = agent or team
    ids = day_ids or list(range(day_start, day_start + days))
    rid = run_id(team, seat, agent, len(ids), ids[0], trials)
    d = os.path.join(out, rid)
    os.makedirs(os.path.join(d, "days"), exist_ok=True)
    rows = []
    with open(os.path.join(d, "days.jsonl"), "w") as f:
        for day_id in ids:
            for trial in range(trials):
                res, tr = runner(team, agent, seat, day_id, trial)
                res = dict(res)
                res.update(day_id=day_id, trial=trial, agent=agent, team=team, seat_under_test=seat)
                res["agent_kind"] = agent_kind(agent)
                res["model"] = agent_model(agent)
                p = os.path.join(d, "days", f"{day_id}-t{trial}.json")
                with open(p, "w") as t:
                    json.dump({**(tr or {}), "result": res}, t, sort_keys=True)
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
