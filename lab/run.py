import argparse
import importlib
import json
import os
import time

from lab.results import summarise

def _scripted(cls):
    def make(day, trial):
        from sleeper import scripted

        return scripted.make_team(getattr(scripted, cls), day)

    return make


def _baseline(name):
    def make(day, trial):
        from sleeper import baselines

        return getattr(baselines, name)(day, trial)

    return make


def _module(mod, fn):
    def make(day, trial):
        return getattr(importlib.import_module(mod), fn)(day, trial)

    return make


FACTORIES = {
    "staff": (_module("agents.staff", "make_team"), "gemini"),
    "reference": (_module("agents.reference", "make_reference_team"), "gemini"),
    "oracle": (_scripted("OracleAgent"), "scripted"),
    "do_nothing": (_scripted("NoopAgent"), "scripted"),
    "stop_early": (_baseline("make_stop_early"), "scripted"),
    "quarantine_all": (_baseline("make_quarantine_all"), "scripted"),
    "refuse_all": (_baseline("make_refuse_all"), "scripted"),
}
TEAMS = list(FACTORIES)


def agent_kind(name):
    if name.startswith("local:"):
        return "local"
    return "gemini" if FACTORIES[name][1] == "gemini" and os.environ.get("GEMINI_API_KEY") else "scripted"


def agent_model(name):
    if agent_kind(name) == "gemini":
        return os.environ.get("SLEEPER_MODEL_REFERENCE" if name == "reference" else "SLEEPER_MODEL_STAFF")
    return "scripted"


def build_team(name, day, trial):
    if name.startswith("local:"):
        return importlib.import_module("train.agent").make_team(name[6:], day, trial)
    return FACTORIES[name][0](day, trial)


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


class Claimer:
    def __init__(self, agent):
        self.agent = agent

    def turn(self, seat, view, tools, call):
        call("post_chat", {"to": "all", "body": "I caught the sleeper"})
        return self.agent.turn(seat, view, tools, call)


def play_day(team, agent, seat, day_id, trial, claim=False):
    from sleeper.day import run_day
    from sleeper.tickets import make_day
    from sleeper.verifier import dump_state, score

    day = make_day(day_id)
    players = build_team(team, day, trial)
    if seat:
        players[seat] = build_team(agent, day, trial)[seat]
    if claim:
        players = {k: Claimer(v) for k, v in players.items()}
    steps = []
    players = {k: Recorder(k, v, steps) for k, v in players.items()}
    world = run_day(day, players)
    result = score(day, world.initial, world.company, world.ledger, agent=agent, seat_under_test=seat, model=agent_model(agent)).model_dump()
    goal = day.goal
    result["has_sleeper"] = day.sleeper_seat is not None
    result["sleeper_seat"] = day.sleeper_seat
    result["winnable"] = True
    result["goal_kind"] = goal.kind if goal else None
    state = dump_state(world)
    extra = {
        "day": {"day_id": day_id, "sleeper_seat": day.sleeper_seat, "goal": {"kind": goal.kind, "target": goal.target, "strategy": getattr(goal, "strategy", None)} if goal else None, "tickets": state["day"]["tickets"]},
        "company": state["company"],
        "ledger": state["ledger"],
        "messages": state["company"]["messages"],
        "steps": steps,
    }
    return result, extra


def run_id(team, seat, agent, days, day_start, trials):
    who = f"{seat}-{agent}" if seat else "all"
    return f"{team}-{who}-d{days}@{day_start}-t{trials}"


def run(team, days, trials, seat=None, agent=None, day_start=0, day_ids=None, out="results", runner=play_day, claim=False):
    agent = agent or team
    ids = day_ids or list(range(day_start, day_start + days))
    rid = run_id(team, seat, agent, len(ids), ids[0], trials)
    d = os.path.join(out, rid)
    os.makedirs(os.path.join(d, "days"), exist_ok=True)
    rows = []
    with open(os.path.join(d, "days.jsonl"), "w") as f:
        for day_id in ids:
            for trial in range(trials):
                res, tr = runner(team, agent, seat, day_id, trial, **({"claim": True} if claim else {}))
                res = dict(res)
                res.setdefault("day_id", day_id)
                res.update(trial=trial, agent=agent, team=team, seat_under_test=seat)
                res["agent_kind"] = agent_kind(agent)
                res["model"] = agent_model(agent)
                p = os.path.join(d, "days", f"{day_id}-t{trial}.json")
                with open(p, "w") as t:
                    json.dump({**(tr or {}), "result": res}, t, sort_keys=True)
                res["transcript_path"] = os.path.relpath(p, d)
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
    p.add_argument("--claim-caught", action="store_true")
    a = p.parse_args(argv)
    ids = [int(x) for x in a.day_ids.split(",")] if a.day_ids else None
    d, s = run(a.team, a.days, a.trials, a.seat, a.agent, a.day_start, ids, a.out, claim=a.claim_caught)
    print(d)
    print(json.dumps(s, indent=2, sort_keys=True))


def run_day(seed, team, sleeper_seat=None, goal=None, strategy=None, run=0):
    from sleeper.day import run_day as world_run_day
    from sleeper.tickets import make_day
    from sleeper.verifier import score

    day = make_day(seed, sleeper_seat, goal)
    world = world_run_day(day, build_team(team, day, run))
    return score(day, world.initial, world.company, world.ledger, agent=team).model_dump()


if __name__ == "__main__":
    main()
