import sys
from collections import Counter

from lab import analyse


def causes(day):
    r = day["result"]
    c = []
    if r["tickets_done"] < r["tickets_total"]:
        c.append("unfinished")
    if r.get("harm"):
        c.append("harm")
    if r.get("false_quarantine"):
        c.append("false accusation")
    return " + ".join(c) or "none"


def decisions_only(day):
    return "unfinished" not in causes(day).split(" + ") and causes(day) != "none"


def shares(run_dir):
    days = analyse.load(run_dir)
    c = Counter(causes(d) for d in days if d["result"]["reward"] == 0)
    return len(days), sum(c.values()), c


def company_of(day):
    from sleeper.models import Company
    c = dict(day["company"])
    for k in ("docs", "vendors", "payments", "accounts", "employees", "contracts"):
        if isinstance(c.get(k), list):
            c[k] = {v["id"]: v for v in c[k]}
    return Company.model_validate(c)


def completion(run_dir):
    from sleeper import verifier
    from sleeper.models import Day, Ticket
    from sleeper.tickets import done
    tot, ok = Counter(), Counter()
    for day in analyse.load(run_dir):
        comp = company_of(day)
        ids = {t.id for t in verifier.legit_tickets(Day.model_validate({**day["day"], "goal": None}))}
        for t in day["day"]["tickets"]:
            if t["id"] in ids:
                tot[t["kind"]] += 1
                try:
                    ok[t["kind"]] += bool(done(Ticket.model_validate(t), comp))
                except Exception:
                    pass
    return tot, ok


def decomposition_table(run_dir):
    n, losses, c = shares(run_dir)
    lines = ["| cause of loss | days | share of losses | share of all days |", "|---|---|---|---|"]
    for k, v in c.most_common():
        lines.append(f"| {k} | {v} | {100 * v / losses:.0f}% | {100 * v / n:.0f}% |")
    lines.append(f"| all losses | {losses} | 100% | {100 * losses / n:.0f}% |" if losses else "| all losses | 0 | - | 0% |")
    return "\n".join(lines)


def completion_table(runs):
    comps = {name: completion(d) for name, d in runs.items()}
    kinds = sorted({k for t, _ in comps.values() for k in t})
    head = "| ticket kind | " + " | ".join(f"{n} done" for n in comps) + " |"
    lines = [head, "|---|" + "---|" * len(comps)]
    for k in kinds:
        lines.append(f"| {k} | " + " | ".join(f"{o[k]}/{t[k]}" for t, o in comps.values()) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(decomposition_table(sys.argv[1]))


def where_gap(run_dir):
    days = analyse.load(run_dir)
    lost = [d for d in days if d["result"]["reward"] == 0]
    if not lost:
        return "No losses, no gap."
    dec = [d for d in lost if decisions_only(d)]
    inc = len(lost) - len(dec)
    c = Counter(l for d in dec for l in {y["label"] for y in analyse.label(d)} if l in analyse.GLOSSARY)
    out = [f"{len(dec)} of {len(lost)} staff losses ({100 * len(dec) // len(lost)}%) are decision-only (harm or false accusation, every ticket done); {inc} ({100 * inc // len(lost)}%) include unfinished tickets, which is incompleteness, not a decision."]
    if c:
        out += ["", "Top decisions among decision-only losses, with the evidence the oracle used:", "", "| decision | lost days | the oracle checked |", "|---|---|---|"]
        out += [f"| {k} | {v} | {analyse.GLOSSARY[k][1]} |" for k, v in c.most_common()]
    return "\n".join(out)
