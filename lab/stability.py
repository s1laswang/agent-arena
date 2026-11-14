import sys
import tempfile

from lab import counterfactual, report
from lab import run as lrun

WINDOWS = (1000, 1020, 1040)
NUM = ("staff_reward", "ref_reward", "named_pct", "one_seat_pct", "two_seat_pct")


def window(start, days=20, trials=3):
    with tempfile.TemporaryDirectory() as tmp:
        for team in ("staff", "reference"):
            lrun.run(team, days, trials, day_start=start, out=tmp)
        rs = report.runs(tmp)
        st = report.pick(rs, "staff")
        f = report.facts(rs, counterfactual.counterfactual(st[0]))
    return {k: f.get(k) for k in NUM} | {f"goal_{g}": v for g, v in f["goal"].items()}


def stability(starts=WINDOWS, **kw):
    ws = [window(s, **kw) for s in starts]
    keys = sorted({k for w in ws for k in w})
    lines = ["| fact | " + " | ".join(f"{s}-{s + 19}" for s in starts) + " | min | max |", "|---|" + "---|" * (len(starts) + 2)]
    for k in keys:
        v = [w.get(k) for w in ws]
        nums = [x for x in v if x is not None]
        lines.append(f"| {k} | " + " | ".join("-" if x is None else f"{x:.2f}" for x in v) + f" | {min(nums):.2f} | {max(nums):.2f} |" if nums else f"| {k} | no data |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(stability() if "--full" in sys.argv else "stability runs its own evals (about 5 min); pass --full")
