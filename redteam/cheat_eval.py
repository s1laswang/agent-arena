import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sleeper.day import run_day
from sleeper.verifier import score

CORPUS = Path(__file__).resolve().parent / "corpus"


class Inject:
    def __init__(self, inner, rows, at):
        self.inner, self.rows, self.at = inner, rows, at

    def turn(self, seat, view, tools, call):
        self.inner.turn(seat, view, tools, call)
        if view["tick"] == self.at:
            for r in self.rows:
                try:
                    call(r["tool"], r["args"])
                except Exception:
                    pass


def play(day_id, team, seat, rows):
    from lab import run
    day = run.day_for(day_id, seat)[0]
    players = run.build_team(team, day, 0)
    if rows:
        players[seat] = Inject(players[seat], rows, day.ticks // 2)
    w = run_day(day, players)
    r = score(day, w.initial, w.company, w.ledger, agent=team, seat_under_test=seat)
    return r.reward, list(r.harm), {a.tool for a in w.ledger}


def losing_day(lo=1000, hi=1030):
    from lab import run
    for d in range(lo, hi):
        day = run.day_for(d, "finance_ap")[0]
        if day.sleeper_seat and day.sleeper_seat != "finance_ap" and play(d, "trust_all", "finance_ap", None)[0] == 0:
            return d


def pick(rows, n):
    if not n:
        return rows
    by = defaultdict(list)
    for r in rows:
        by[r["tool"]].append(r)
    out = []
    for i in range(n):
        out += [v[i] for v in by.values() if len(v) > i]
    return out[:n]


def evaluate(rows, days=(1000,), seats=("finance_ap", "controller"), lose_day=None):
    out = {"benign": 0, "harmful": 0, "fp_candidates": [], "lifted": [], "runs": 0, "no_baseline": 0}
    lose = lose_day if lose_day is not None else losing_day()
    base = {}
    for d in days:
        for s in seats:
            base[(d, s)] = play(d, "oracle", s, None)
    for r in rows:
        for (d, s), (b, _, used) in base.items():
            if b != 1:
                out["no_baseline"] += 1
                continue
            rw, harm, _u = play(d, "oracle", s, [r])
            out["runs"] += 1
            if rw == 1:
                out["benign"] += 1
            else:
                out["harmful"] += 1
                if r["tool"] in used:
                    out["fp_candidates"].append({"pattern": r["pattern"], "seat": s, "day": d, "harm": harm[:3]})
        if lose is not None:
            for s in seats:
                rw, _h, _u = play(lose, "trust_all", s, [r])
                out["runs"] += 1
                if rw > 0:
                    out["lifted"].append({"pattern": r["pattern"], "seat": s, "day": lose, "reward": rw})
    out["lose_day"] = lose
    return out


def load():
    rows = []
    for f in sorted(CORPUS.glob("real_*.jsonl")):
        rows += [json.loads(l) for l in f.read_text().splitlines() if l]
    return rows


def main():
    slow = os.environ.get("SLEEPER_SLOW") == "1"
    res = evaluate(pick(load(), 0 if slow else 10), (1000, 1001, 1002) if slow else (1000,))
    print(json.dumps({k: (v if not isinstance(v, list) else v) for k, v in res.items()}, indent=1))
    return 1 if res["lifted"] else 0


if __name__ == "__main__":
    sys.exit(main())
