import argparse
import json
import os

from lab.run import run

ORDER = ["oracle", "reference", "staff", "do_nothing", "stop_early", "quarantine_all", "refuse_all"]


def table(summaries):
    ref = summaries.get("reference", {}).get("reward_mean")
    lines = ["| team | kind | model | reward | pass^1 | sleeper success | false accusation | tickets | gap vs reference |", "|---|---|---|---|---|---|---|---|---|"]
    for t, s in summaries.items():
        gap = "" if ref is None else f"{ref - s['reward_mean']:.3f}"
        lines.append(f"| {t} | {s['agent_kind']} | {s['model']} | {s['reward_mean']:.3f} | {s.get('pass^1', 0):.3f} | {s['sleeper_success_rate']:.3f} | {s['false_accusation_rate']:.3f} | {s['ticket_completion']:.3f} | {gap} |")
    return "\n".join(lines) + "\n"


def main(argv=None, runner=None):
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=20)
    p.add_argument("--day-start", type=int, default=1000)
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--out", default="results")
    a = p.parse_args(argv)
    kw = {"runner": runner} if runner else {}
    summaries = {}
    for t in ORDER:
        _, summaries[t] = run(t, a.days, a.trials, day_start=a.day_start, out=os.path.join(a.out, "runs"), **kw)
    d = os.path.join(a.out, "eval")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump(summaries, f, indent=2, sort_keys=True)
    with open(os.path.join(d, "gap.md"), "w") as f:
        f.write(table(summaries))
    print(table(summaries))
    return summaries


if __name__ == "__main__":
    main()
