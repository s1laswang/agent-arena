import json
import sys

from lab.run import day_for
from sleeper.company import World
from sleeper.day import play_round
from sleeper.days.canaries import apply_evidence, seed_decoys
from sleeper.models import SEATS
from sleeper.scripted import OracleAgent, make_team
from sleeper.verifier import score

FRACTIONS = tuple(i / 10 for i in range(11))
MODES = ("team", "finance_ap", "controller")


class StopAt:
    def __init__(self, inner, stop):
        self.inner, self.stop = inner, stop

    def turn(self, seat, view, tools, call):
        if view["tick"] >= self.stop:
            call("end_turn", {})
        else:
            self.inner.turn(seat, view, tools, call)


def run(day_id, mode, f):
    day = day_for(day_id)[0]
    day, _ = seed_decoys(day, False)
    w = World(day)
    apply_evidence(day, w.company)
    apply_evidence(day, w.initial)
    team = make_team(OracleAgent)
    stop = int(f * day.ticks)
    for s in (SEATS if mode == "team" else (mode,)):
        team[s] = StopAt(team[s], stop)
    while w.tick < day.ticks:
        play_round(w, team)
    return score(day, w.initial, w.company, w.ledger, f"stop_{f}", None if mode == "team" else mode)


def curve(days=20, fractions=FRACTIONS, modes=MODES, start=0):
    out = {}
    for mode in modes:
        for f in fractions:
            rs = [run(d, mode, f) for d in range(start, start + days)]
            out[f"{mode}@{f}"] = {"mode": mode, "fraction": f, "days": days, "reward": sum(r.reward for r in rs) / days,
                                  "exploits": [(start + i, r.reward) for i, r in enumerate(rs) if f < 1 and r.reward > 0 and r.tickets_done < r.tickets_total],
                                  "ticket_completion": round(sum(r.tickets_done / max(1, r.tickets_total) for r in rs) / days, 3)}
    return out


def md(c):
    rows = ["| mode | k | reward | ticket completion | exploits |", "|---|---|---|---|---|"]
    rows += [f"| {v['mode']} | {int(v['fraction'] * 100)} | {v['reward']:.2f} | {v['ticket_completion']} | {len(v['exploits'])} |" for v in c.values()]
    return "\n".join(rows) + "\n"


def main(path="results/stop_early_curve.json", days=20):
    c = curve(int(days))
    with open(path, "w") as fh:
        json.dump(c, fh, indent=1)
    with open(path.replace(".json", ".md"), "w") as fh:
        fh.write(md(c))
    for k, v in c.items():
        print(k, v["reward"], v["ticket_completion"], v["exploits"])


if __name__ == "__main__":
    main(*sys.argv[1:3])
