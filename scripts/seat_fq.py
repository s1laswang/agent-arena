import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.procedure import make_procedure_team
from lab import run as labrun

labrun.FACTORIES["procedure"] = (lambda day, trial: make_procedure_team(day, seed=trial), "scripted")


def main(days, seat="finance_ap", agent="oracle"):
    bad = 0
    for d in days:
        r, _ = labrun.play_day("procedure", agent, seat, d, 0)
        fq = r["false_quarantine"]
        bad += bool(fq)
        print(d, r["reward"], r["strategy"], fq, r["harm"][:2], flush=True)
    print("days_with_false_quarantine", bad, "of", len(days))
    return bad


if __name__ == "__main__":
    a = sys.argv[1:] or ["1000", "1039"]
    main(range(int(a[0]), int(a[1]) + 1))
