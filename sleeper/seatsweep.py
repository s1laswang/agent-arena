import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

os.environ["GEMINI_API_KEY"] = ""
AGENTS = ("oracle", "do_nothing", "trust")


def days_for(seat, per=1, limit=600):
    from sleeper import daymix
    got = {}
    for d in range(limit):
        e = daymix.entry(d, seat)
        if e["strategy"] and len(got.setdefault(e["strategy"], [])) < per:
            got[e["strategy"]].append(d)
    return got


def run(job):
    from lab.run import play_day
    seat, sid, day, agent = job
    name = agent
    if agent == "trust":
        from sleeper.daymix import STRATEGIES
        agent = "quarantine_all" if STRATEGIES[sid].kind == "frame" else "trust_all"
        r, _ = play_day("oracle", agent, seat, day, 0)
    else:
        r, _ = play_day("staff", agent, seat, day, 0)
    return seat, sid, day, name, r["reward"]


def main(per=1, out="results/seat_sweep", jobs=4):
    from sleeper import daymix
    from sleeper.models import SEATS
    todo = []
    for seat in SEATS:
        want = {s.id for s in daymix.gated(seat)}
        for sid, ds in days_for(seat, per).items():
            if sid in want:
                todo += [(seat, sid, d, a) for d in ds for a in AGENTS]
    with Pool(jobs) as p:
        res = p.map(run, todo, chunksize=1)
    rows = {}
    for seat, sid, day, agent, rw in res:
        rows.setdefault((seat, sid, day), {})[agent] = rw
    table = [{"seat": s, "strategy": i, "day": d, **v, "ok": v["oracle"] == 1 and v["do_nothing"] == 0 and v["trust"] == 0} for (s, i, d), v in sorted(rows.items())]
    Path(out).parent.mkdir(exist_ok=True)
    Path(out + ".json").write_text(json.dumps(table, indent=1))
    lines = ["| seat | strategy | day | oracle | do_nothing | trust | ok |", "|---|---|---|---|---|---|---|"]
    lines += ["| %(seat)s | %(strategy)s | %(day)d | %(oracle)s | %(do_nothing)s | %(trust)s | %(ok)s |" % r for r in table]
    Path(out + ".md").write_text("\n".join(lines) + "\n")
    print("\n".join(l for l in lines if "False" in l or l.startswith("|--") or l.startswith("| seat")))
    print(len(table), "rows,", sum(not r["ok"] for r in table), "failing")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
