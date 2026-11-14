import collections
import glob
import json
import os
import sys


def episode(d, seat):
    t = d["transcript"] if "transcript" in d else d
    day, c = t["day"], t["company"]
    closed = {x["id"] if isinstance(x, dict) else x for x in c["closed_tickets"]}
    steps = [s for s in t["steps"] if s["seat"] == seat]
    mine = [x for x in day["tickets"] if seat in (x.get("needs") or []) or x.get("seat") == seat]
    seen = " ".join(json.dumps(s["effect"]) for s in steps if s["tool"] in ("my_tickets", "read_chat", "read_email", "read_doc", "search_docs"))
    undone = [x for x in mine if x["id"] not in closed]
    per_tick = collections.Counter(s["tick"] for s in steps)
    return {
        "tickets_total": len(day["tickets"]), "tickets_closed": len(closed), "seat_tickets": len(mine), "seat_closed": len(mine) - len(undone),
        "undone": [{"id": x["id"], "kind": x["kind"], "legit": x.get("legit"), "needs": x.get("needs"), "hidden": bool(x.get("hidden")), "read": x["id"] in seen, "tick": x.get("tick")} for x in undone],
        "steps": len(steps), "closes": sum(s["tool"] == "close_ticket" for s in steps), "end_turns": sum(s["tool"] == "end_turn" for s in steps),
        "ticks": day.get("ticks"), "last_tick": max((s["tick"] or 0 for s in t["steps"]), default=0), "max_steps_in_tick": max(per_tick.values(), default=0),
        "tools": collections.Counter(s["tool"] for s in steps).most_common(8),
    }


def load(paths, seat):
    out = {}
    for p in paths:
        d = json.load(open(p))
        if d.get("invalid") or not (d.get("transcript") or d).get("steps"):
            continue
        out[os.path.basename(p)] = episode(d, seat)
    return out


def table(rows):
    lines = ["| episode | tickets closed/total | seat tickets closed | undone legit/should-refuse | undone never read | undone needs other seat | seat steps | close_ticket calls | last tick/ticks | max steps in one tick |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, e in rows.items():
        u = e["undone"]
        lines.append(f"| {k} | {e['tickets_closed']}/{e['tickets_total']} | {e['seat_closed']}/{e['seat_tickets']} | {sum(bool(x['legit']) for x in u)}/{sum(not x['legit'] for x in u)} | {sum(not x['read'] for x in u)} | {sum(len(x['needs'] or []) > 1 or (x['needs'] or [None])[0] != 'finance_ap' for x in u)} | {e['steps']} | {e['closes']} | {e['last_tick']}/{e['ticks']} | {e['max_steps_in_tick']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    seat = sys.argv[2] if len(sys.argv) > 2 else "finance_ap"
    print(table(load(sorted(glob.glob(sys.argv[1])), seat)))
