import argparse
import json
import os

from lab.run import run

ORDER = ["oracle", "reference", "staff", "do_nothing", "stop_early", "quarantine_all", "refuse_all"]
SEAT_AGENTS = ["staff", "reference", "oracle", "do_nothing"]
HEAD = ["| team | kind | model | reward | pass^1 | sleeper success | false accusation | tickets | gap vs reference |", "|---|---|---|---|---|---|---|---|---|"]


def row(name, s, ref):
    if s is None:
        return f"| {name} | NOT FOUND | | | | | | | |"
    gap = "" if ref is None else f"{ref - s['reward_mean']:.3f}"
    return f"| {name} | {s['agent_kind']} | {s['model']} | {s['reward_mean']:.3f} | {s.get('pass^1', 0):.3f} | {s['sleeper_success_rate']:.3f} | {s['false_accusation_rate']:.3f} | {s['ticket_completion']:.3f} | {gap} |"


def table(summaries):
    ref = (summaries.get("reference") or {}).get("reward_mean")
    return "\n".join(HEAD + [row(t, s, ref) for t, s in summaries.items()]) + "\n"


def attempt(*a, **kw):
    try:
        return run(*a, **kw)[1]
    except Exception:
        return None


def main(argv=None, runner=None):
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=20)
    p.add_argument("--day-start", type=int, default=1000)
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--seat", default="controller")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--out", default="results")
    p.add_argument("--web-out", default="web/results/eval")
    a = p.parse_args(argv)
    kw = {"runner": runner} if runner else {}
    kw["jobs"] = a.jobs
    runs = os.path.join(a.out, "runs")
    summaries = {t: attempt(t, a.days, a.trials, day_start=a.day_start, out=runs, **kw) for t in ORDER}
    seat = {g: attempt("staff", a.days, a.trials, a.seat, g, a.day_start, out=runs, **kw) for g in SEAT_AGENTS}
    d = os.path.join(a.out, "eval")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump({"all_seats": summaries, "seat": {a.seat: seat}}, f, indent=2, sort_keys=True)
    md = "## Team plays all 8 seats\n\n" + table(summaries) + f"\n## Staff background, {a.seat} seat swapped\n\n" + table(seat)
    with open(os.path.join(d, "gap.md"), "w") as f:
        f.write(md)
    if a.web_out:
        os.makedirs(a.web_out, exist_ok=True)
        flat = {t: v for t, v in summaries.items() if v}
        flat.update({f"{a.seat}:{g}": v for g, v in seat.items() if v})
        with open(os.path.join(a.web_out, "summary.json"), "w") as f:
            json.dump(flat, f, indent=2, sort_keys=True)
        with open(os.path.join(a.web_out, "gap.md"), "w") as f:
            f.write(md)
    print(md)
    return summaries, seat


if __name__ == "__main__":
    main()
