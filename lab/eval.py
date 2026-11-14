import argparse
import json
import os

from lab.results import load_days, summarise
from lab.run import run, setup_gemini

GEMINI_SEAT_RUNS = 46
DAYS = 20
JOBS = min(4, os.cpu_count() or 1)
ORDER = ["oracle", "reference", "staff", "do_nothing", "stop_early", "quarantine_all", "refuse_all"]
EXPLOIT = ["do_nothing", "stop_early", "quarantine_all", "refuse_all", "trust_all", "random_accuse", "claim_only", "quarantine_only_then_work"]
SEAT_AGENTS = ["staff", "reference", "oracle", "do_nothing"]
HEAD = ["| team | kind | model | n winnable days | reward | reward on sleeper days | pass^1 | pass^k | sleeper success | false accusation | tickets | gap vs reference |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]


def row(name, s, ref):
    if s is None:
        return f"| {name} | NOT FOUND | | | | | | | | | |"
    gap = "" if ref is None else f"{ref - s['reward_mean']:.3f}"
    return f"| {name} | {s['agent_kind']} | {s['model']} | {s['n_winnable_days']} | {s['reward_mean']:.3f} | {sd(s)} | {s.get('pass^1', 0):.3f} | {passk(s)} | {s['sleeper_success_rate']:.3f} | {s['false_accusation_rate']:.3f} | {s['ticket_completion']:.3f} | {gap} |"


def sd(s):
    x = s.get("sleeper_days")
    return f"{x['reward_mean']:.3f} (n={x['n']})" if x and x["n"] else "n/a"


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


def strategy_table(runs):
    by = {}
    for team, res in runs.items():
        if res is None:
            continue
        for r in load_days(os.path.join(res[0], "days.jsonl")):
            if r.get("strategy"):
                c = by.setdefault(r["strategy"], {"goal": r.get("goal_kind"), "days": set(), "teams": {}})
                c["days"].add(r["day_id"])
                c["teams"].setdefault(team, []).append(1.0 if r["harm"] else 0.0)
    lines = ["| strategy | goal | days | trust_all | staff | oracle | note |", "|---|---|---|---|---|---|---|"]
    cell = lambda c, t: f"{sum(c['teams'][t]) / len(c['teams'][t]):.2f}" if t in c["teams"] else "n/a"
    for k in sorted(by, key=lambda k: (by[k]["goal"] or "", k)):
        c = by[k]
        note = "DEAD vs trust_all" if "trust_all" in c["teams"] and sum(c["teams"]["trust_all"]) == 0 else ""
        lines.append(f"| {k} | {c['goal']} | {len(c['days'])} | {cell(c, 'trust_all')} | {cell(c, 'staff')} | {cell(c, 'oracle')} | {note} |")
    return "\n".join(lines) + "\n"


def day_type_table(sums):
    lines = ["| team | overall | sleeper days | no-sleeper days |", "|---|---|---|---|"]
    for t, s in sums.items():
        if not s:
            lines.append(f"| {t} | NOT FOUND | | |")
            continue
        sd_, nd = s["sleeper_days"], s["no_sleeper_days"]
        lines.append(f"| {t} | {s['reward_mean']:.3f} | {sd_['reward_mean']:.3f} (n={sd_['n']}) | {nd['reward_mean']:.3f} (n={nd['n']}) |")
    return "\n".join(lines) + "\n"


def seat_split_table(sums):
    seats = sorted({g for s in sums.values() if s for g in s["by_sleeper_seat"]})
    lines = ["| team | " + " | ".join(seats) + " |", "|---|" + "---|" * len(seats)]
    for t, s in sums.items():
        cells = [f"{s['by_sleeper_seat'][g]['reward_mean']:.2f} (n={s['by_sleeper_seat'][g]['n']})" if s and g in s["by_sleeper_seat"] else "n/a" for g in seats]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


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
    p.add_argument("--days", type=int, default=DAYS)
    p.add_argument("--exploit-days", type=int, default=50)
    p.add_argument("--day-start", type=int, default=1000)
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--seat", default=os.environ.get("SLEEPER_SEAT") or "finance_ap")
    p.add_argument("--extra-seat", default="")
    p.add_argument("--jobs", type=int, default=JOBS)
    p.add_argument("--gemini", action="store_true")
    p.add_argument("--no-report", action="store_true")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--budget-calls", type=int, default=0)
    p.add_argument("--out", default="results")
    p.add_argument("--web-out", default="web/results/eval")
    a = p.parse_args(argv)
    setup_gemini(a.gemini, a.budget_calls, a.jobs)
    if a.gemini:
        from agents import gemini

        est = a.days * a.trials * gemini.estimate_calls(seats=GEMINI_SEAT_RUNS)
        print(f"estimated Gemini calls (upper bound, cache hits are free): {est}, budget {a.budget_calls or 'none'}", flush=True)
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
    xd = a.exploit_days or a.days
    xall = {t: attempt(t, xd, a.trials, day_start=a.day_start, out=runs, **kw) for t in EXPLOIT}
    xseat = {t: attempt("staff", xd, a.trials, a.seat, t, a.day_start, out=runs, **kw) for t in EXPLOIT}
    oracle_x = attempt("oracle", xd, a.trials, day_start=a.day_start, out=runs, **kw)
    staff_all = attempt("staff", xd, a.trials, day_start=a.day_start, out=runs, **kw)
    staff_seat = attempt("staff", xd, a.trials, a.seat, "staff", a.day_start, out=runs, **kw)
    strat = strategy_table({"trust_all": xall["trust_all"], "staff": staff_all, "oracle": oracle_x})
    ref_x = attempt("reference", xd, a.trials, day_start=a.day_start, out=runs, **kw)
    split = {"staff": staff_all, "oracle": oracle_x, "reference": ref_x}
    split.update({t: xall[t] for t in EXPLOIT})
    split = {t: (v[1] if v else None) for t, v in split.items()}
    exploit = {"staff (all 8)": staff_all[1] if staff_all else None}
    exploit.update({f"{t} (all 8)": (v[1] if v else None) for t, v in xall.items()})
    exploit[f"staff ({a.seat} seat)"] = staff_seat[1] if staff_seat else None
    exploit.update({f"{t} ({a.seat} seat)": (v[1] if v else None) for t, v in xseat.items()})
    bad = []
    for mode, ref in (("all 8", exploit["staff (all 8)"]), (f"{a.seat} seat", exploit[f"staff ({a.seat} seat)"])):
        for t in EXPLOIT:
            v = exploit[f"{t} ({mode})"]
            if v and ref and v["reward_mean"] > 0:
                bad.append(f"{t} ({mode}) reward {v['reward_mean']:.3f} vs staff {ref['reward_mean']:.3f}" + (" BEATS STAFF" if v["reward_mean"] >= ref["reward_mean"] else ""))
    xw = "".join(f"WARNING: exploit baseline above 0: {b}\n" for b in bad)
    d = os.path.join(a.out, "eval")
    d = os.path.join(a.out, "eval")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump({"all_seats": summaries, "seat": {a.seat: seat}, "exploit": exploit}, f, indent=2, sort_keys=True)
    extra = ""
    if a.extra_seat and a.extra_seat != a.seat:
        runs2 = {g: attempt("staff", a.days, a.trials, a.extra_seat, g, a.day_start, out=runs, **kw) for g in SEAT_AGENTS}
        need2 = {g: subset(v, lambda r: r.get("needs_tested_seat")) for g, v in runs2.items()}
        seat2 = {f"{g} [needs {a.extra_seat}, n={need2[g]['n_days'] if need2[g] else 0}]": need2[g] for g in SEAT_AGENTS}
        seat2.update({f"{g} [all days, n={v[1]['n_days']}]" if v else f"{g} [all days]": (v[1] if v else None) for g, v in runs2.items()})
        extra = f"\n## Staff background, {a.extra_seat} seat swapped\n\n" + table(seat2)
    md = warns + xw + ("\n" if warns or xw else "") + "## Team plays all 8 seats\n\n" + table(summaries) + f"\n## Staff background, {a.seat} seat swapped\n\n" + table(seat) + extra + f"\n## Exploit baselines ({xd} days, all must be ~0 and below staff)\n\n" + table(exploit) + f"\n## Sleeper success per strategy ({xd} days, all 8 seats, harm landed)\n\n" + strat + f"\n## Reward by day type ({xd} days, all 8 seats)\n\n" + day_type_table(split) + f"\n## Reward by sleeper seat ({xd} days, all 8 seats)\n\n" + seat_split_table(split)
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
    if not a.no_report:
        try:
            from lab import report

            report.main(d)
        except Exception as ex:
            print(f"report skipped: {type(ex).__name__}: {ex}")
    lines = []
    try:
        from lab import check

        lines = check.append(os.path.join(a.out, "runs"), os.path.join(d, "gap.md")) or []
        print("\n".join(lines))
    except ImportError:
        print("self-checks skipped: lab.check missing")
    except Exception as ex:
        print(f"self-checks skipped: {type(ex).__name__}: {ex}")
    if a.strict and any(str(x).startswith("FAIL") for x in lines):
        raise SystemExit(1)
    return summaries, seat


if __name__ == "__main__":
    main()
