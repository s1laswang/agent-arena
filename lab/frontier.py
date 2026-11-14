import hashlib
import json
import os
import subprocess
import time

MAX_DAYS = 5


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip() or "?"
    except Exception:
        return "?"


def prompt_hash(seat):
    from sleeper.company import tools_for

    return hashlib.sha256(json.dumps(tools_for(seat), sort_keys=True, default=str).encode()).hexdigest()[:12]


def key(model, day, seat, trial, ph):
    return hashlib.sha256(f"{model}|{day}|{seat}|{trial}|{ph}".encode()).hexdigest()[:16]


def default_runner():
    from scripts.cli_seat import run_seat

    return run_seat


def run_frontier(agent, model, seat, days, trials, out="results/frontier", max_turns=60, max_seconds=900, max_total_seconds=3600, i_know=False, run_seat=None, replay_only=False):
    if len(days) > MAX_DAYS and not i_know:
        raise SystemExit(f"{len(days)} days on a personal plan: refusing, pass --i-know")
    base = os.path.join(out, model.replace("/", "_"))
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    ph = prompt_hash(seat)
    commit = sh("git", "rev-parse", "--short", "HEAD")
    rows, live, t0 = [], 0, time.time()
    for day in days:
        for trial in range(trials):
            p = os.path.join(cache, key(model, day, seat, trial, ph) + ".json")
            if os.path.exists(p):
                r = json.load(open(p))
                r["mode"] = "replay"
            elif replay_only or time.time() - t0 > max_total_seconds:
                r = {"error": "no cache" if replay_only else "total wall-clock cap hit", "mode": "skipped"}
            else:
                run_seat = run_seat or default_runner()
                s = time.time()
                try:
                    r = dict(run_seat(agent, model, seat, day, 1, {"max_turns": max_turns, "max_seconds": max_seconds}))
                except Exception as e:
                    r = {"error": f"{type(e).__name__}: {e}"}
                r.update(mode="live", seconds=round(time.time() - s, 1))
                live += 1
                if "error" not in r:
                    json.dump({**r, "mode": "live"}, open(p, "w"), indent=2, sort_keys=True)
            r.update(trial=trial, day=day, seat=seat, model=model, agent=agent)
            rows.append(r)
    ok = [r for r in rows if "error" not in r]
    cli = sh({"claude": "claude", "codex": "codex"}.get(agent, "true"), "--version")
    summary = {"model": model, "agent": agent, "commit": commit, "cli_version": cli, "seat": seat, "days": days, "trials": trials,
               "prompt_hash": ph, "caps": {"max_turns": max_turns, "max_seconds": max_seconds, "max_total_seconds": max_total_seconds},
               "live_runs": live, "n_ok": len(ok), "n_err": len(rows) - len(ok), "total_seconds": round(time.time() - t0, 1),
               "reward_mean": sum(r.get("score", r.get("reward", 0)) for r in ok) / len(ok) if ok else None, "rows": rows}
    json.dump(summary, open(os.path.join(base, f"summary-{commit}.json"), "w"), indent=2, sort_keys=True)
    return summary
