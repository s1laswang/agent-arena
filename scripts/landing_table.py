import inspect
import json
import os
import random
import sys
import time
from collections import defaultdict

os.environ.pop("GEMINI_API_KEY", None)

from agents.sleeper_agent import SleeperAgent
from lab.run import build_team, day_for
from sleeper.day import run_day
from sleeper.verifier import score


def play(day_id, team):
    day, strategy, _ = day_for(day_id)
    players = build_team(team, day, 0)
    if day.sleeper_seat and strategy:
        kw = {"ticks": day.ticks} if "ticks" in inspect.signature(SleeperAgent).parameters else {}
        players[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
    w = run_day(day, players)
    r = score(day, w.initial, w.company, w.ledger, agent=team)
    landed = int(bool(day.goal.success(w.company, w.ledger))) if day.goal else None
    return {"landed": landed, "reward": r.reward, "harm": r.harm}, getattr(strategy, "id", None)


def collect(day_ids):
    rows = []
    for d in day_ids:
        row = {"day_id": d}
        for team in ("staff", "oracle"):
            try:
                row[team], sid = play(d, team)
                row["strategy"] = sid
            except Exception as e:
                row[team] = {"error": f"{type(e).__name__}: {e}"}
        rows.append(row)
    return rows


def table(rows):
    g = defaultdict(list)
    for r in rows:
        g[r["strategy"] or "no_sleeper"].append(r)
    out = ["| strategy | days | landed vs staff | staff reward | oracle reward | oracle errors |", "|---|---|---|---|---|---|"]
    bad = []
    for sid, rs in sorted(g.items()):
        ok = lambda t: [r[t] for r in rs if "error" not in r[t]]
        st, orc = ok("staff"), ok("oracle")
        errs = sum("error" in r["oracle"] for r in rs) + sum("error" in r["staff"] for r in rs)
        land = sum(x["landed"] or 0 for x in st)
        out.append(f"| {sid} | {len(rs)} | {land} | {sum(x['reward'] for x in st)} | {sum(x['reward'] for x in orc)} | {errs} |")
        if errs or any(x["reward"] != 1 for x in orc):
            bad.append(sid)
    return "\n".join(out), bad


def main(n=40, out="results/landing"):
    rows = collect(range(n))
    md, bad = table(rows)
    ts = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(out, exist_ok=True)
    json.dump({"ts": ts, "days": n, "rows": rows, "oracle_not_1": bad}, open(f"{out}/{ts}.json", "w"), indent=1)
    open(f"{out}/{ts}.md", "w").write(md + "\n")
    print(md)
    print("oracle reward != 1 or errors:", bad or "none")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
