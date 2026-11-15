"""Action-level replay: re-issue a recorded seat's tool calls tick by tick against the
deterministic in-process world, then re-score with the real verifier. No model calls."""
import json, sys, os
from lab import run as R
from lab.frontier_rows import bg_for

class ReplaySeat:
    def __init__(self, calls):
        self.by_tick = {}
        for e in calls:
            self.by_tick.setdefault(e["tick"], []).append(e)
    def turn(self, seat, view, tools, call):
        for e in self.by_tick.get(view.get("tick", 0), []):
            call(e["tool"], e["args"])

def replay(path):
    row = json.load(open(path))
    seat = row["seat"]; tr = row["transcript"]
    calls = [e for e in tr["ledger"] if e["seat"] == seat]
    team = bg_for(row.get("team", "procedure"))
    R.FACTORIES["__replay"] = (lambda d, t, calls=calls, seat=seat: {seat: ReplaySeat(calls)}, "scripted")
    res, _ = R.play_day(team, "__replay", seat, row["seed"], row["trial"])
    old = row["scores"]
    same = all(res[k] == old[k] for k in ("reward", "harm", "tickets_done", "tickets_total"))
    return {"file": os.path.basename(path), "reward": res["reward"], "orig": old["reward"], "harm_same": res["harm"] == old["harm"], "same": same, "harm": res["harm"], "orig_harm": old["harm"], "fq": res.get("false_quarantine"), "orig_fq": old.get("false_quarantines")}

if __name__ == "__main__":
    ok = 0; n = 0
    for p in sys.argv[1:]:
        r = replay(p); n += 1; ok += r["same"]
        print(json.dumps(r))
    print(f"REPLAY MATCH {ok}/{n}")
