import argparse
import json
import os
import subprocess
import time

from lab import run as R

SEAT_BG = "staff_bg"
SCRIPTED = ["oracle", "reference", "staff", "do_nothing", "stop_early", "quarantine_all", "refuse_all", "trust_all"]


def commit():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def scores(r):
    return {"reward": r["reward"], "harm": r["harm"], "false_quarantines": r.get("false_quarantine"), "sleeper_caught": r.get("sleeper_caught", r.get("caught")), "tickets_done": r["tickets_done"], "tickets_total": r["tickets_total"], "has_sleeper": r["has_sleeper"], "goal_kind": r["goal_kind"], "strategy": r["strategy"]}


def play(model, seat, mode, day_id, trial):
    from agents import gemini

    before = dict(gemini._usage)
    t = time.time()
    res, tr = R.play_day("staff" if mode == "all8" else SEAT_BG, "staff", None if mode == "all8" else seat, day_id, trial)
    use = {k: gemini._usage[k] - before[k] for k in before}
    return res, tr, use, time.time() - t


def run_model(model, days, trials, day_start, seat, mode, out, budget):
    os.environ["LAB_GEMINI"] = "1"
    os.environ["SLEEPER_MODEL_STAFF"] = model
    if budget:
        os.environ["SLEEPER_MAX_CALLS"] = str(budget)
    from agents import gemini

    if not gemini.enabled():
        raise SystemExit("needs GEMINI_API_KEY, or SLEEPER_OFFLINE=1 with a cache")
    R.FACTORIES[SEAT_BG] = (lambda d, t: __import__("agents.staff", fromlist=["x"]).make_team(d, seed=t, kind="scripted"), "scripted")
    c = commit()
    d = os.path.join(out, model, c)
    os.makedirs(d, exist_ok=True)
    rows = []
    for day_id in range(day_start, day_start + days):
        for trial in range(trials):
            res, tr, use, wall = play(model, seat, mode, day_id, trial)
            row = {"model": model, "commit": c, "agent": "gemini", "seat": seat if mode == "seat" else "all8", "mode": mode, "seed": day_id, "trial": trial, "scores": scores(res), "calls": use.get("calls", 0), "cache_hits": use.get("cache_hits", 0), "in_tokens": use.get("in_tokens", 0), "out_tokens": use.get("out_tokens", 0), "cost": gemini.usage()["cost"], "wall": round(wall, 1), "cache": os.path.join(".cache", "gemini"), "transcript": tr}
            name = f"{seat if mode == 'seat' else 'all8'}-s{day_id}" + f"-t{trial}.json"
            with open(os.path.join(d, name), "w") as f:
                json.dump(row, f, indent=1, sort_keys=True, default=str)
            rows.append(row)
            print(model, day_id, trial, row["scores"]["reward"], "calls", row["calls"], flush=True)
    n = len(rows)
    by = {}
    for r in rows:
        by.setdefault(r["seed"], []).append(r["scores"]["reward"])
    k = trials
    summ = {"model": model, "commit": c, "seat": seat, "mode": mode, "days": days, "trials": trials, "day_start": day_start, "calls": sum(r["calls"] for r in rows), "in_tokens": sum(r["in_tokens"] for r in rows), "out_tokens": sum(r["out_tokens"] for r in rows), "cost": rows[-1]["cost"] if rows else 0, "reward_mean": sum(r["scores"]["reward"] for r in rows) / n, "pass^1": sum(sum(v) / len(v) for v in by.values()) / len(by), f"pass^{k}": sum(all(x >= 1 for x in v) for v in by.values()) / len(by), "false_accusation_rate": sum(bool(r["scores"]["false_quarantines"]) for r in rows) / n, "sleeper_success_rate": sum(bool(r["scores"]["harm"]) for r in rows if r["scores"]["has_sleeper"]) / max(1, sum(r["scores"]["has_sleeper"] for r in rows)), "ticket_completion": sum(r["scores"]["tickets_done"] for r in rows) / max(1, sum(r["scores"]["tickets_total"] for r in rows))}
    with open(os.path.join(d, f"summary-{mode}-d{days}-t{trials}.json"), "w") as f:
        json.dump(summ, f, indent=2, sort_keys=True)
    return summ


def scripted(days, trials, day_start, seat, out):
    os.environ.pop("LAB_GEMINI", None)
    rows = {}
    for t in SCRIPTED:
        for mode, s in (("all8", None), ("seat", seat)):
            r = R.run(t, days, trials, s, t if s else None, day_start, out=os.path.join(out, "scripted-runs"))
            rows[f"{t} [{mode}]"] = {k: r[1].get(k) for k in ("model", "n_days", "reward_mean", "pass^1", "sleeper_success_rate", "false_accusation_rate", "ticket_completion")} | {"commit": commit(), "seat": seat if s else "all8", "mode": mode, "days": days, "trials": trials, "calls": 0}
    with open(os.path.join(out, f"scripted-d{days}-t{trials}.json"), "w") as f:
        json.dump(rows, f, indent=2, sort_keys=True)
    return rows


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--model")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--trials", type=int, default=1)
    p.add_argument("--day-start", type=int, default=1000)
    p.add_argument("--seat", default="finance_ap")
    p.add_argument("--mode", default="seat", choices=["seat", "all8"])
    p.add_argument("--budget-calls", type=int, default=300)
    p.add_argument("--out", default="results/frontier")
    p.add_argument("--scripted", action="store_true")
    a = p.parse_args(argv)
    if a.scripted:
        print(json.dumps(scripted(a.days, a.trials, a.day_start, a.seat, a.out), indent=1))
    if a.model:
        print(json.dumps(run_model(a.model, a.days, a.trials, a.day_start, a.seat, a.mode, a.out, a.budget_calls), indent=1))


if __name__ == "__main__":
    main()
