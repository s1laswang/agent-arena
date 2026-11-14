import json
import sys
from collections import defaultdict
from pathlib import Path

from lab.run import play_day
from sleeper import baselines

AGENTS = ("oracle", "reference", "staff", "trust_all", "do_nothing")
baselines.register()


def accusations(ex, sleeper):
    out = []
    for a in ex["ledger"]:
        if a["tool"] in ("quarantine", "report_insider") and a.get("ok", True):
            t = a["args"].get("target") or a["args"].get("suspect")
            if t != sleeper:
                out.append((a["seat"], a["tool"], t, a["seq"], a["args"].get("evidence", "")))
    return out


def run(seat, days=20, trials=1):
    rows = []
    for d in range(days):
        for ag in AGENTS:
            for t in range(trials):
                r, ex = play_day("staff", ag, seat, d, t)
                rows.append({"day": d, "agent": ag, "reward": r["reward"], "strategy": r["strategy"], "sleeper": r["sleeper_seat"], "harm": r["harm"],
                             "fa": accusations(ex, r["sleeper_seat"]) if ag == "staff" else []})
    return rows


def md(seat, rows):
    out = ["## seat %s\n" % seat, "| agent | mean reward | sleeper days | no-sleeper days |", "|---|---|---|---|"]
    for ag in AGENTS:
        r = [x for x in rows if x["agent"] == ag]
        s = [x["reward"] for x in r if x["sleeper"]]
        n = [x["reward"] for x in r if not x["sleeper"]]
        f = lambda v: "%.2f (n=%d)" % (sum(v) / len(v), len(v)) if v else "n/a"
        out.append("| %s | %.2f | %s | %s |" % (ag, sum(x["reward"] for x in r) / len(r), f(s), f(n)))
    st = [x for x in rows if x["agent"] == "staff"]
    out += ["", "staff false accusations per day: %.2f" % (sum(len(x["fa"]) for x in st) / len(st)), "", "| day | strategy | sleeper | staff reward | trust_all reward | false accusations (seat, tool, target, seq) |", "|---|---|---|---|---|---|"]
    ta = {x["day"]: x["reward"] for x in rows if x["agent"] == "trust_all"}
    for x in st:
        out.append("| %d | %s | %s | %s | %s | %s |" % (x["day"], x["strategy"] or "none", x["sleeper"] or "none", x["reward"], ta[x["day"]], "; ".join("%s %s %s @%s" % a[:4] for a in x["fa"]) or "-"))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    allrows = {s: run(s) for s in (sys.argv[1:] or ("finance_ap", "controller"))}
    Path("results/attack").mkdir(parents=True, exist_ok=True)
    Path("results/attack/seatmode.json").write_text(json.dumps(allrows, indent=1))
    Path("results/attack/seatmode.md").write_text("# Seat mode, 20 daymix days, 1 trial\n\n" + "\n".join(md(s, r) for s, r in allrows.items()))
