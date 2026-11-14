import argparse
import importlib
import json
import os
import shutil
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


def gemini_on():
    return os.environ.get("LAB_GEMINI") == "1"


def _staff(day, trial):
    from agents.staff import make_team

    return make_team(day, seed=trial, kind="gemini" if gemini_on() else "scripted")


def _reference(day, trial):
    import inspect

    if gemini_on():
        from agents.gemini_reference import make_gemini_reference_team

        return make_gemini_reference_team(seed=trial)
    from agents.reference import make_reference_team

    return make_reference_team(day, seed=trial) if "day" in inspect.signature(make_reference_team).parameters else make_reference_team(seed=trial)


def _module(mod, fn):
    def make(day, trial):
        f = getattr(importlib.import_module(mod), fn)
        if fn == "make_oracle_team":
            return f(day)
        if fn == "make_reference_team":
            import inspect

            return f(day, seed=trial) if "day" in inspect.signature(f).parameters else f(seed=trial)
        return f(day, trial)

    return make


FACTORIES = {
    "staff": (_staff, "gemini"),
    "reference": (_reference, "gemini"),
    "oracle": (_module("agents.reference", "make_oracle_team"), "scripted"),
    "do_nothing": (_scripted("NoopAgent"), "scripted"),
    "stop_early": (_baseline("make_stop_early"), "scripted"),
    "quarantine_all": (_baseline("make_quarantine_all"), "scripted"),
    "refuse_all": (_baseline("make_refuse_all"), "scripted"),
}
EXTRA = ("trust_all", "random_accuse", "claim_only", "quarantine_only_then_work")
for _n in EXTRA:
    FACTORIES[_n] = (_baseline("make_" + _n), "scripted")
TEAMS = list(FACTORIES)


def agent_kind(name):
    if name.startswith("local:"):
        return "local"
    return "gemini" if FACTORIES[name][1] == "gemini" and gemini_on() else "scripted"


def agent_model(name):
    if agent_kind(name) == "gemini":
        from agents import gemini

        return gemini.model_for("reference" if name == "reference" else "staff")
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


def day_for(day_id, seat=None):
    from sleeper.tickets import make_day

    try:
        from sleeper import daymix

        spec = daymix.day_spec(day_id, seat)
    except (ImportError, AttributeError):
        return make_day(day_id), None, True, {}
    spec = spec if isinstance(spec, dict) else dict(spec.__dict__)
    day = make_day(day_id, spec.get("sleeper_seat"), spec.get("goal"))
    day.tickets = day.tickets + list(spec.get("tickets") or [])
    return day, spec.get("strategy"), spec.get("winnable", True), {"needs_tested_seat": bool(spec.get("needs_tested_seat")), "strategy": getattr(spec.get("strategy"), "id", None)}


def play_day(team, agent, seat, day_id, trial, claim=False, replace=None):
    from sleeper.day import run_day
    from sleeper.verifier import dump_state, score

    if replace:
        seat = None
    day, strategy, winnable, meta = day_for(day_id, seat)
    players = build_team(team, day, trial)
    if seat:
        players[seat] = build_team(agent, day, trial)[seat]
    for rs, name in (replace or {}).items():
        players[rs] = build_team(name, day, trial)[rs]
    if day.sleeper_seat and strategy:
        import random

        from agents.sleeper_agent import SleeperAgent

        import inspect

        kw = {"ticks": day.ticks} if "ticks" in inspect.signature(SleeperAgent).parameters else {}
        players[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
    if claim:
        players = {k: Claimer(v) for k, v in players.items()}
    steps = []
    players = {k: Recorder(k, v, steps) for k, v in players.items()}
    world = run_day(day, players)
    result = score(day, world.initial, world.company, world.ledger, agent=agent, seat_under_test=seat, model=agent_model(agent)).model_dump()
    goal = day.goal
    result["has_sleeper"] = day.sleeper_seat is not None
    result["sleeper_seat"] = day.sleeper_seat
    result["winnable"] = winnable
    result["needs_tested_seat"] = meta.get("needs_tested_seat", False)
    result["strategy"] = meta.get("strategy")
    result["goal_kind"] = goal.kind if goal else None
    state = dump_state(world)
    try:
        from web.export import harmful

        bad = sorted(harmful(day, world.ledger, result["harm"]))
    except Exception:
        bad = []
    extra = {
        "day": {**state["day"], "day_id": day_id, "goal": {**state["day"]["goal"], "strategy": getattr(strategy, "id", None)} if state["day"].get("goal") else None},
        "company": state["company"],
        "ledger": state["ledger"],
        "messages": state["company"]["messages"],
        "harmful": bad,
        "steps": steps,
    }
    return result, extra


def run_id(team, seat, agent, days, day_start, trials):
    who = f"{seat}-{agent}" if seat else "all"
    return f"{team}-{who}-d{days}@{day_start}-t{trials}"


def _usage():
    if not gemini_on():
        return {}
    from agents import gemini

    return dict(gemini._usage)


def _work(task):
    runner, team, agent, seat, day_id, trial, claim = task
    before = _usage()
    res, tr = runner(team, agent, seat, day_id, trial, **({"claim": True} if claim else {}))
    after = _usage()
    return res, tr, {k: after[k] - before[k] for k in after}


def run(team, days, trials, seat=None, agent=None, day_start=0, day_ids=None, out="results", runner=play_day, claim=False, export_web=None, jobs=1):
    agent = agent or team
    ids = day_ids or list(range(day_start, day_start + days))
    rid = run_id(team, seat, agent, len(ids), ids[0], trials)
    d = os.path.join(out, rid)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "days"), exist_ok=True)
    tasks = [(runner, team, agent, seat, day_id, trial, claim) for day_id in ids for trial in range(trials)]
    if jobs > 1:
        import multiprocessing

        with multiprocessing.Pool(jobs) as pool:
            outs = pool.map(_work, tasks)
    else:
        outs = [_work(t) for t in tasks]
    rows = []
    with open(os.path.join(d, "days.jsonl"), "w") as f:
        for (_, _, _, _, day_id, trial, _), (res, tr, _) in zip(tasks, outs):
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
    if gemini_on():
        keys = {k for o in outs for k in o[2]}
        summary["gemini_usage"] = {k: sum(o[2].get(k, 0) for o in outs) for k in sorted(keys)}
        cap = int(os.environ.get("SLEEPER_MAX_CALLS", 0) or 0)
        summary["gemini_usage"]["budget_exhausted"] = bool(cap and summary["gemini_usage"].get("calls", 0) >= cap * max(jobs, 1))
    summary.update(run_id=rid, background_team=team, seat_under_test=seat)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump({"run_id": rid, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
    if export_web:
        from lab.export_web import export

        export(d, export_web)
    return d, summary


def setup_gemini(on, budget, jobs):
    if not on:
        return
    from agents import gemini

    if not gemini.enable_live():
        raise SystemExit("--gemini needs GEMINI_API_KEY, or SLEEPER_OFFLINE=1 with cached responses")
    os.environ["LAB_GEMINI"] = "1"
    if budget:
        os.environ["SLEEPER_MAX_CALLS"] = str(-(-budget // max(jobs, 1)))


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
    p.add_argument("--export-web")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--gemini", action="store_true")
    p.add_argument("--budget-calls", type=int, default=0)
    a = p.parse_args(argv)
    setup_gemini(a.gemini, a.budget_calls, a.jobs)
    ids = [int(x) for x in a.day_ids.split(",")] if a.day_ids else None
    d, s = run(a.team, a.days, a.trials, a.seat, a.agent, a.day_start, ids, a.out, claim=a.claim_caught, export_web=a.export_web, jobs=a.jobs)
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
