import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import gemini

STATS = {}
CUR = {"path": None}
STOP = {"cost": False}


def bucket(system):
    from agents.procedure import PROCEDURE_TEXT
    if "Privately you also pursue" in (system or ""):
        return "sleeper"
    if PROCEDURE_TEXT[:40] in (system or ""):
        return "procedure"
    return "staff"


def s(name):
    return STATS.setdefault(name, {"calls": 0, "errors": [], "in": 0, "out": 0})


def install_meter():
    inner = gemini.chat
    cap = float(os.environ.get("SLEEPER_MAX_COST", 0) or 0)

    def meter(model, system, messages, tools=None, temperature=0, seed=None):
        st = s(bucket(system))
        if STOP["cost"]:
            raise gemini.GeminiUnavailable("max cost reached")
        u0 = dict(gemini._usage)
        try:
            out = inner(model, system, messages, tools, temperature, seed)
        except Exception as e:
            st["errors"].append("%s: %s" % (type(e).__name__, str(e)[:120]))
            raise
        st["calls"] += 1
        st["in"] += gemini._usage["in_tokens"] - u0["in_tokens"]
        st["out"] += gemini._usage["out_tokens"] - u0["out_tokens"]
        if cap and gemini.usage()["cost"] >= cap:
            STOP["cost"] = True
        return out

    gemini.chat = meter
    return inner


def smoke():
    tool = {"name": "get_number", "description": "returns a number", "parameters": {"type": "object", "properties": {}}}
    st = s("smoke")
    try:
        r = gemini.chat(gemini.model_for("staff"), "Use the tool.", [{"role": "user", "text": "Call get_number."}], [tool], seed=0)
        st["calls"] += 1
        if not r["tool_calls"]:
            st["errors"].append("no tool call returned")
    except Exception as e:
        st["errors"].append("%s: %s" % (type(e).__name__, str(e)[:120]))


def make_day(seed):
    from sleeper import goals
    from sleeper.company import seed_company
    from sleeper.tickets import make_day as md
    st = goals.STRATEGIES["fraud.bank_swap"]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    st = st.model_copy(update={"steps": [x.model_copy(update={"tick": max(0, x.tick - 8)}) for x in st.steps]})
    day = md(seed, "finance_ap").model_copy(update={"goal": goal, "ticks": 10})
    return day, st, goal


def play(seed, kind):
    from agents.gemini_reference import make_gemini_procedure_team
    from agents.sleeper_agent import SleeperAgent
    from agents.staff import make_team
    from sleeper.day import run_day
    from sleeper.verifier import score
    day, st, goal = make_day(seed)
    team = make_gemini_procedure_team(day, seed) if kind == "procedure" else make_team(day, seed, "gemini")
    team["finance_ap"] = SleeperAgent("finance_ap", goal, st, random.Random(seed), ticks=day.ticks)
    w = run_day(day, team)
    r = score(day, w.initial, w.company, w.ledger, agent=kind)
    return r, bool(goal.success(w.company, w.ledger)), team


def main(seed=1):
    os.environ.setdefault("SLEEPER_MAX_CALLS", "600")
    if not gemini.enabled() or os.environ.get("SLEEPER_OFFLINE") == "1":
        print("key-check needs GEMINI_API_KEY and SLEEPER_OFFLINE unset")
        return 2
    gemini.reset_usage()
    install_meter()
    t = time.time()
    smoke()
    results = {}
    for kind in ("staff", "procedure"):
        try:
            r, landed, team = play(seed, kind)
            results[kind] = {"reward": r.reward, "harm": len(r.harm), "landed": landed}
            if kind == "procedure":
                results[kind]["scripted_seats"] = [x for x, a in team.items() if getattr(a, "agent_kind", "gemini") == "scripted"]
        except Exception as e:
            s(kind)["errors"].append("day crashed: %s: %s" % (type(e).__name__, str(e)[:120]))
    pin = os.environ.get("SLEEPER_PRICE_IN_PER_M")
    pout = os.environ.get("SLEEPER_PRICE_OUT_PER_M")
    bad = []
    print("%-10s %-4s %-7s %6s %9s %8s %-10s %s" % ("path", "ok", "kind", "calls", "in_tok", "out_tok", "cost", "result"))
    for name in ("smoke", "staff", "sleeper", "procedure"):
        st = s(name)
        fell = bool(st["errors"]) or st["calls"] == 0 or bool(results.get(name, {}).get("scripted_seats"))
        if name in results and not results[name]:
            fell = True
        if fell:
            bad.append(name)
        cost = "%.4f" % ((st["in"] * float(pin) + st["out"] * float(pout)) / 1e6) if pin and pout else "NOT FOUND"
        res = results.get(name, {})
        print("%-10s %-4s %-7s %6d %9d %8d %-10s %s" % (name, "FAIL" if fell else "ok", "scripted" if fell else "gemini", st["calls"], st["in"], st["out"], cost, res or "-"))
        for e in st["errors"][:3]:
            print("    " + e)
    if STOP["cost"]:
        print("stopped: SLEEPER_MAX_COST reached")
    print("total live calls %d, cap %s, %.0fs" % (gemini._usage["calls"], os.environ["SLEEPER_MAX_CALLS"], time.time() - t))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
