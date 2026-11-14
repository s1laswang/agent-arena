import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.procedure import make_procedure_team
from lab import run as labrun

labrun.FACTORIES["procedure"] = (lambda day, trial: make_procedure_team(day, seed=trial), "scripted")


def main(days):
    tot = 0
    for d in days:
        try:
            r, _ = labrun.play_day("procedure", "procedure", None, d, 0)
            row = (d, r["reward"], r["goal_kind"], r["strategy"], r["sleeper_seat"], r["false_quarantine"], r["harm"][:2])
        except Exception as e:
            r, row = {"reward": 0}, (d, "ERR", repr(e)[:80])
        tot += r["reward"] or 0
        print(*row)
    print("mean", round(tot / len(days), 3))


if __name__ == "__main__":
    a = sys.argv[1:] or ["1", "20"]
    main(list(range(int(a[0]), int(a[1]) + 1)))
