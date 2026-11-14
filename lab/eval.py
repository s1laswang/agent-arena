import argparse
import json
import os

from lab.results import load_days, summarise
from lab.run import run

ORDER = ["oracle", "reference", "staff", "do_nothing", "stop_early", "quarantine_all", "refuse_all"]
SEAT_AGENTS = ["staff", "reference", "oracle", "do_nothing"]
HEAD = ["| team | kind | model | n winnable days | reward | pass^1 | pass^k | sleeper success | false accusation | tickets | gap vs reference |", "|---|---|---|---|---|---|---|---|---|---|---|"]


def row(name, s, ref):
    if s is None:
        return f"| {name} | NOT FOUND | | | | | | | | | |"
    gap = "" if ref is None else f"{ref - s['reward_mean']:.3f}"
    return f"| {name} | {s['agent_kind']} | {s['model']} | {s['n_winnable_days']} | {s['reward_mean']:.3f} | {s.get('pass^1', 0):.3f} | {passk(s)} | {s['sleeper_success_rate']:.3f} | {s['false_accusation_rate']:.3f} | {s['ticket_completion']:.3f} | {gap} |"


def passk(s):
    if s["deterministic"]:
        return "= pass^1 (deterministic)"
    ks = sorted((k for k in s if k.startswith("pass^") and k != "pass^1"), key=lambda k: int(k[5:]))
    return ", ".join(f"{k} {s[k]:.3f}" for k in ks) or "n/a"


def group(k):
    return k.split("[", 1)[1] if "[" in k else ""


def table(summaries):
    refs = {group(k): v["reward_mean"] for k, v in summaries.items() if k.startswith("reference") and v}
    return "\n".join(HEAD + [row(t, s, refs.get(group(t))) for t, s in summaries.items()]) + "\n"


def attempt(*a, **kw):
    try:
        return run(*a, **kw)
    except Exception:
        return None


def subset(res, pred):
    if res is None:
        return None
    rows = [r for r in load_days(os.path.join(res[0], "days.jsonl")) if pred(r)]
    if not rows:
        return None
    return summarise(rows, res[1]["team"], res[1]["agent_kind"], res[1]["model"])


def warn(label, s):
    if s and s["reward_mean"] < 1.0:
        return f"WARNING: oracle reward {s['reward_mean']:.3f} < 1.0 on winnable days ({label}, n_days {s['n_days']})\n"
    return ""


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
    wins = lambda r: r.get("winnable", True)
    full = {t: attempt(t, a.days, a.trials, day_start=a.day_start, out=runs, **kw) for t in ORDER}
    seatruns = {g: attempt("staff", a.days, a.trials, a.seat, g, a.day_start, out=runs, **kw) for g in SEAT_AGENTS}
    summaries = {t: (v[1] if v else None) for t, v in full.items()}
    need = {g: subset(v, lambda r: r.get("needs_tested_seat")) for g, v in seatruns.items()}
    alld = {g: (v[1] if v else None) for g, v in seatruns.items()}
    seat = {f"{g} [needs {a.seat}, n={need[g]['n_days']}]" if need[g] else f"{g} [needs {a.seat}, n=0]": need[g] for g in SEAT_AGENTS}
    seat.update({f"{g} [all days, n={alld[g]['n_days']}]" if alld[g] else f"{g} [all days]": alld[g] for g in SEAT_AGENTS})
    warns = warn("all 8 seats", subset(full["oracle"], wins)) + warn(f"{a.seat} seat, all days", subset(seatruns["oracle"], wins)) + warn(f"{a.seat} seat, needs tested seat", subset(seatruns["oracle"], lambda r: wins(r) and r.get("needs_tested_seat")))
    d = os.path.join(a.out, "eval")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump({"all_seats": summaries, "seat": {a.seat: seat}}, f, indent=2, sort_keys=True)
    md = warns + ("\n" if warns else "") + "## Team plays all 8 seats\n\n" + table(summaries) + f"\n## Staff background, {a.seat} seat swapped\n\n" + table(seat)
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
