import sys
from pathlib import Path

from lab import analyse

AVOIDING = ("do_nothing", "stop_early", "quarantine_all", "refuse_all")


def runs(root):
    out = {}
    keep = analyse.listed(root, Path(root).parent / "eval")
    for p in sorted(Path(root).glob("*-all-*")):
        if (p / "days").is_dir() and (keep is None or p.name in keep):
            out[p.name.split("-all-")[0]] = p
    return out


def legit_count_mismatches(days):
    from sleeper import verifier
    from sleeper.models import Day
    fn = getattr(verifier, "legit_tickets", None)
    if fn is None:
        return None
    bad = []
    for d in days:
        day = Day.model_validate({**d["day"], "goal": None})
        if len(fn(day)) != d["result"]["tickets_total"]:
            bad.append(d["result"]["day_id"])
    return bad


def gate(root):
    rs = runs(root)
    lines = []

    def rec(ok, name, detail=""):
        lines.append(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))

    if "oracle" in rs:
        days = analyse.load(rs["oracle"])
        bad = [d["result"]["day_id"] for d in days if d["result"].get("winnable", True) and d["result"]["reward"] != 1]
        rec(not bad, "oracle reward 1 on every winnable day", f"{len(bad)} lost, e.g. {bad[:3]}")
    else:
        rec(False, "oracle run present", "no oracle-all run")
    for t in AVOIDING:
        if t in rs:
            bad = [d["result"]["day_id"] for d in analyse.load(rs[t]) if d["result"]["reward"] != 0]
            rec(not bad, f"{t} reward 0 on every day", f"{len(bad)} wins, e.g. {bad[:3]}")
    for name, p in rs.items():
        days = analyse.load(p)
        bad = [d["result"]["day_id"] for d in days if (d["result"]["reward"] == 0) != bool(analyse.label(d))]
        rec(not bad, f"{name}: every loss labeled and no win labeled", f"{len(bad)} days, e.g. {bad[:3]}")
    if "trust_all" in rs and "staff" in rs:
        m = {k: sum(d["result"]["reward"] for d in analyse.load(rs[k])) / max(len(analyse.load(rs[k])), 1) for k in ("trust_all", "staff")}
        if m["trust_all"] > m["staff"]:
            lines.append(f"WARN trust_all {m['trust_all']:.3f} > staff {m['staff']:.3f}: too easy to just trust everything")
        else:
            lines.append("PASS trust_all <= staff")
    allbad, seen = [], False
    for p in rs.values():
        m = legit_count_mismatches(analyse.load(p))
        if m is None:
            break
        seen = True
        allbad += m
    rec(seen and not allbad, "tickets_total equals sleeper.verifier.legit_tickets", "legit_tickets not exposed yet" if not seen else f"{len(allbad)} days differ")
    return lines


def append(root, gap):
    lines = gate(root)
    gap = Path(gap)
    text = gap.read_text() if gap.exists() else ""
    text = text.split("\n## Self-checks")[0]
    gap.write_text(text.rstrip("\n") + "\n\n## Self-checks\n\n" + "\n".join(f"- {l}" for l in lines) + "\n")
    return lines


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "results/runs"
    lines = append(root, sys.argv[2]) if len(sys.argv) > 2 else gate(root)
    print("\n".join(lines))
    sys.exit(1 if any(l.startswith("FAIL") for l in lines) else 0)
