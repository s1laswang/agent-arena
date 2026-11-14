import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor

from lab.run import build_team, day_for
from sleeper.day import run_day
from sleeper.verifier import score

FRACTIONS = tuple(i / 10 for i in range(11))
MODES = ("team", "finance_ap", "controller")
START = 1000


class StopAt:
    def __init__(self, inner, stop):
        self.inner, self.stop = inner, stop

    def turn(self, seat, view, tools, call):
        if view["tick"] >= self.stop:
            call("end_turn", {})
        else:
            self.inner.turn(seat, view, tools, call)


def run(day_id, mode, f):
    import inspect

    seat = None if mode == "team" else mode
    day, strategy, _, _ = day_for(day_id, seat)
    players = build_team("oracle", day, 0)
    if day.sleeper_seat and strategy:
        from agents.sleeper_agent import SleeperAgent

        kw = {"ticks": day.ticks} if "ticks" in inspect.signature(SleeperAgent).parameters else {}
        players[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
    stop = int(f * day.ticks)
    for s in (players if seat is None else (seat,)):
        if s in players and s != day.sleeper_seat:
            players[s] = StopAt(players[s], stop)
    w = run_day(day, players)
    return score(day, w.initial, w.company, w.ledger, f"stop_{f}", seat)


def cell(a):
    mode, f, days, start = a
    rs = [(start + i, run(start + i, mode, f)) for i in range(days)]
    undone = lambda r: r.tickets_done < r.tickets_total
    return f"{mode}@{f}", {"mode": mode, "fraction": f, "days": days, "reward": sum(r.reward for _, r in rs) / days,
                           "ticket_completion": round(sum(r.tickets_done / max(1, r.tickets_total) for _, r in rs) / days, 3),
                           "exploits": [(i, r.reward) for i, r in rs if r.reward > 0 and undone(r)],
                           "below_one": [(i, r.reward, r.harm, r.tickets_total - r.tickets_done) for i, r in rs if r.reward < 1] if f == 1 else []}


def curve(days=50, fractions=FRACTIONS, modes=MODES, start=START, workers=1):
    jobs = [(m, f, days, start) for m in modes for f in fractions]
    if workers == 1:
        return dict(map(cell, jobs))
    with ProcessPoolExecutor(workers) as ex:
        return dict(ex.map(cell, jobs))


def md(c):
    rows = ["| mode | k | reward | ticket completion | exploits |", "|---|---|---|---|---|"]
    rows += [f"| {v['mode']} | {int(v['fraction'] * 100)} | {v['reward']:.3f} | {v['ticket_completion']} | {len(v['exploits'])} |" for v in c.values()]
    return "\n".join(rows) + "\n"


def main(path="results/stop_early_curve.json", days=50):
    c = curve(int(days), workers=4)
    with open(path, "w") as fh:
        json.dump(c, fh, indent=1)
    with open(path.replace(".json", ".md"), "w") as fh:
        fh.write(md(c))
    for k, v in c.items():
        print(k, round(v["reward"], 3), v["ticket_completion"], v["exploits"], v["below_one"])


if __name__ == "__main__":
    main(*sys.argv[1:3])
