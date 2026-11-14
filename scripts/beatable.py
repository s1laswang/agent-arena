import json
import sys
from pathlib import Path

from sleeper import goals
from sleeper.regret import run_day

TEAMS = ("oracle", "reference", "staff", "trust_all")
SEEDS = (1, 2, 3)


def audit(ids=None):
    rows = []
    for sid, st in goals.STRATEGIES.items():
        if ids and sid not in ids:
            continue
        for seat in st.seats:
            r = {t: [run_day(s, t, seat, None, sid)["reward"] for s in SEEDS] for t in TEAMS}
            m = {t: sum(v) / len(v) for t, v in r.items()}
            bad = []
            if m["oracle"] < 1:
                bad.append("oracle<1")
            if m["reference"] <= m["staff"]:
                bad.append("reference<=staff")
            if m["trust_all"] >= 1 and st.kind != "frame":
                bad.append("trust_all wins")
            rows.append({"strategy": sid, "seat": seat, **m, "bad": bad, "kept": not bad})
    return rows


def md(rows):
    out = ["| strategy | seat | oracle | reference | staff | trust_all | verdict |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| %s | %s | %.2f | %.2f | %.2f | %.2f | %s |" % (r["strategy"], r["seat"], r["oracle"], r["reference"], r["staff"], r["trust_all"], ", ".join(r["bad"]) or "kept"))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    rows = audit(sys.argv[1:] or None)
    Path("results/attack").mkdir(parents=True, exist_ok=True)
    Path("results/attack/beatable.json").write_text(json.dumps(rows, indent=1))
    Path("results/attack/beatable.md").write_text(md(rows))
    print(md(rows))
