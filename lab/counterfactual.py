import sys
from collections import Counter

from lab import analyse
from lab import run as lrun


AUDITORS = ("controller", "it_admin", "legal")


def swap(team, day_id, trial, seats):
    seats = [seats] if isinstance(seats, str) else list(seats)
    return lrun.play_day(team, team, None, day_id, trial, replace={s: "oracle" for s in seats})[0]["reward"]


def decisive_seats(day, fls):
    ss = day.get("sleeper_seat")
    seats = {}
    for x in fls:
        if x["seat"] and x["seat"] != ss:
            seats.setdefault(x["seat"], x["action_seq"] or 0)
    for a in day["ledger"]:
        if a["tool"] in ("quarantine", "report_insider") and a["seat"] != ss and (a["args"].get("target") or a["args"].get("suspect")) in day["result"].get("false_quarantine", []):
            seats.setdefault(a["seat"], a["seq"])
    bad = {pp[1] for pp in (analyse.parse_harm(h) for h in day["result"].get("harm", [])) if pp and pp[0] in analyse.PAYMENT}
    for a in day["ledger"]:
        if a["ok"] and a["seat"] != ss and a["tool"] == "approve_payment" and (a["args"].get("id") or a["args"].get("payment_id")) in bad:
            seats.setdefault(a["seat"], a["seq"])
    return sorted(seats, key=seats.get)


def counterfactual(run_dir, team="staff", where=None):
    rows = {}
    losses = one = two = audit = 0
    for day in analyse.load(run_dir):
        r = day["result"]
        if r["reward"] != 0 or (where and not where(day)):
            continue
        losses += 1
        did, trial = int(str(r["day_id"]).lstrip("d")), r.get("trial", 0)
        fls = analyse.label(day)
        seats = decisive_seats(day, fls)
        ss = day.get("sleeper_seat")
        f1 = any(swap(team, did, trial, s) for s in seats)
        f2 = not f1 and len(seats) >= 2 and bool(swap(team, did, trial, seats[:2]))
        f3 = not (f1 or f2) and any(x["label"] in ("missed_slow_burn", "undetected_sleeper_action") for x in fls) and any(swap(team, did, trial, s) for s in AUDITORS if s != ss)
        one += f1
        two += f2
        audit += f3
        for lab in {x["label"] for x in fls}:
            row = rows.setdefault(lab, [0, 0, 0, 0])
            row[0] += 1
            row[1] += f1
            row[2] += f2
            row[3] += f3
    return {"losses": losses, "fixed": one, "fixed_two": two, "fixed_audit": audit, "labels": dict(sorted(rows.items()))}


def table(c):
    lines = ["| label | lost days | fixed by one seat | extra fixed by two seats | extra fixed by an auditor reading the audit log |", "|---|---|---|---|---|"]
    lines += [f"| {k} | {n} | {a} | {b} | {d} |" for k, (n, a, b, d) in c["labels"].items()]
    lines += ["", f"{c['fixed']} of {c['losses']} lost days flip with one careful seat, {c['fixed_two']} more with two, {c['fixed_audit']} more with an auditor who reads the audit log. A lost day appears under every label it carries."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(table(counterfactual(sys.argv[1])))
