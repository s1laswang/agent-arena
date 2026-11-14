import argparse
import glob
import json
import os
from math import sqrt

from lab.results import load_days, pass_hat_k, summarise

MODELS = ["Gemini 4 Carbon", "Gemini 3.5 Flash", "Claude Sonnet 5.5", "Claude Opus 5.5", "Codex"]
FIXED = ["fair reference", "oracle", "trust_all", "do_nothing", "quarantine_all", "stop_early", "refuse_all"]
ALIAS = {"reference": "fair reference"}
HEAD = ["row", "provenance", "mode", "n days", "trials", "pass^1", "pass^3 (95% Wilson)", "sleeper success", "false accusation", "gap vs reference", "gap vs oracle", "model id", "commit", "calls/cost", "cache"]


def wilson(p, n, z=1.96):
    if not n:
        return None
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def entries(root):
    out = []
    for path in sorted(glob.glob(os.path.join(root, "**", "summary.json"), recursive=True)):
        d = json.load(open(path))
        base = os.path.dirname(path)
        if "all_seats" in d:
            for team, s in d["all_seats"].items():
                if s:
                    out.append((team, "all-8", s, os.path.join(os.path.dirname(base), "runs", s.get("run_id", "")), {}))
            for seat, rows in d.get("seat", {}).items():
                for k, s in rows.items():
                    if s and k.endswith("all days]") or s and "all days," in k:
                        out.append((s["team"], f"{seat} seat", s, os.path.join(os.path.dirname(base), "runs", s.get("run_id", "")), {}))
        elif "reward_mean" in d:
            seat = d.get("seat") or d.get("seat_under_test")
            out.append((d.get("label") or d.get("team"), d.get("mode") or (f"{seat} seat" if seat else "all-8"), d, base, d))
    return out


NAMES = [("gemini-4-carbon", "Gemini 4 Carbon"), ("gemini-3.5-flash", "Gemini 3.5 Flash"), ("sonnet", "Claude Sonnet 5.5"), ("opus", "Claude Opus 5.5"), ("codex", "Codex")]


def display(model):
    return next((n for k, n in NAMES if k in str(model).lower()), str(model))


def aggregate(runs):
    by = {}
    for r in runs:
        by.setdefault(r["seed"], []).append(r["scores"]["reward"])
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    out = {"n_days": len(by), "n_runs": len(runs), "reward_mean": mean([r["scores"]["reward"] for r in runs])}
    for k in (1, 3):
        out[f"pass^{k}"] = mean([pass_hat_k(len(v), sum(v), k) for v in by.values()]) if all(len(v) >= k for v in by.values()) and by else None
    out["sleeper_success_rate"] = mean([1.0 if r["scores"]["harm"] else 0.0 for r in runs])
    out["false_accusation_rate"] = mean([1.0 if r["scores"]["false_quarantines"] else 0.0 for r in runs])
    return out


def run_files(root):
    out = []
    for path in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
        if os.path.basename(path) in ("summary.json", "gaptable.json"):
            continue
        d = json.load(open(path))
        if isinstance(d, dict) and "scores" in d and "seed" in d:
            d["_path"] = path
            out.append(d)
    return out


def real_entries(root):
    groups = {}
    for r in run_files(root):
        groups.setdefault((r["model"], r.get("mode", "seat"), r.get("seat"), r.get("commit")), []).append(r)
    out = []
    for (model, mode, seat, commit), runs in groups.items():
        s = aggregate(runs)
        s["model"] = model
        extra = {"commit": commit, "calls": sum(x.get("calls") or 0 for x in runs) or None, "cost": round(sum(x.get("cost") or 0 for x in runs), 4) or None, "cache_path": os.path.dirname(runs[0]["_path"]), "files": [x["_path"] for x in runs], "provenance": "scripted" if runs[0].get("agent") == "scripted" else "real"}
        out.append((display(model), f"{seat} seat" if mode == "seat" else "all-8", s, None, extra))
    return out


def canon(name):
    return ALIAS.get(name, name)


def build(root):
    rows = {}
    for name, mode, s, run_dir, extra in entries(root) + real_entries(root):
        rows[(canon(name), mode)] = (s, run_dir, extra)
    ref = {m: v[0]["reward_mean"] for (n, m), v in rows.items() if n == "fair reference"}
    orc = {m: v[0]["reward_mean"] for (n, m), v in rows.items() if n == "oracle"}
    modes = sorted({m for _, m in rows}) or ["all-8"]
    names = MODELS + FIXED + sorted({n for n, _ in rows} - set(MODELS) - set(FIXED))
    out = []
    for n in names:
        found = [m for m in modes if (n, m) in rows]
        if not found:
            out.append({"row": n, "status": "pending"})
        for m in found:
            s, run_dir, x = rows[(n, m)]
            runs = s.get("n_runs", 0)
            trials = runs // s["n_days"] if s.get("n_days") else 0
            p3 = s.get("pass^3")
            ci = wilson(p3, s.get("n_days", 0)) if p3 is not None else None
            out.append({
                "row": n, "mode": m, "n_days": s.get("n_days"), "trials": trials, "pass1": s.get("pass^1"), "pass3": p3, "pass3_ci": ci,
                "sleeper_success": s.get("sleeper_success_rate"), "false_accusation": s.get("false_accusation_rate"), "reward": s["reward_mean"],
                "gap_ref": ref[m] - s["reward_mean"] if m in ref else None, "gap_oracle": orc[m] - s["reward_mean"] if m in orc else None,
                "model": s.get("model"), "commit": x.get("commit"), "calls": x.get("calls"), "cost": x.get("cost"), "cache": x.get("cache_path"), "run_dir": run_dir, "files": x.get("files"), "provenance": x.get("provenance", "scripted"),
            })
    return out


def fmt(v, f="{:.3f}"):
    return "n/a" if v is None else f.format(v)


def md(rows):
    lines = ["| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    for r in rows:
        if r.get("status"):
            lines.append(f"| {r['row']} | pending |" + " |" * (len(HEAD) - 2))
            continue
        ci = r["pass3_ci"]
        p3 = "n/a" if r["pass3"] is None else f"{r['pass3']:.3f}" + (f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else "")
        cost = " / ".join(str(x) for x in (r["calls"], r["cost"]) if x is not None) or "n/a"
        lines.append("| " + " | ".join([r["row"], r["provenance"], r["mode"], str(r["n_days"]), str(r["trials"]), fmt(r["pass1"]), p3, fmt(r["sleeper_success"]), fmt(r["false_accusation"]), fmt(r["gap_ref"]), fmt(r["gap_oracle"]), str(r["model"]), str(r["commit"] or "n/a"), cost, str(r["cache"] or "n/a")]) + " |")
    return "\n".join(lines) + "\n"


def replay(rows):
    bad = []
    for r in rows:
        if r.get("status"):
            continue
        if r.get("files"):
            runs = [json.load(open(f)) for f in r["files"]]
            s = aggregate(runs)
            for k, v in (("reward_mean", r["reward"]), ("pass^1", r["pass1"]), ("sleeper_success_rate", r["sleeper_success"]), ("false_accusation_rate", r["false_accusation"]), ("pass^3", r["pass3"])):
                if v is not None and abs((s.get(k) or 0.0) - v) > 1e-9:
                    bad.append(f"{r['row']} [{r['mode']}]: {k} table {v:.4f} replay {s.get(k):.4f}")
            bad += [f"{r['row']}: missing transcript {x['transcript']}" for x in runs if x.get("transcript") and not os.path.exists(x["transcript"]) and not os.path.exists(os.path.join(os.path.dirname(r["cache"]), x["transcript"]))]
            continue
        path = os.path.join(r["run_dir"], "days.jsonl")
        if not os.path.exists(path):
            bad.append(f"{r['row']} [{r['mode']}]: no days.jsonl at {r['run_dir']}")
            continue
        s = summarise(load_days(path))
        for k, v in (("reward_mean", r["reward"]), ("pass^1", r["pass1"]), ("sleeper_success_rate", r["sleeper_success"]), ("false_accusation_rate", r["false_accusation"]), ("pass^3", r["pass3"])):
            if v is not None and abs(s.get(k, 0.0) - v) > 1e-9:
                bad.append(f"{r['row']} [{r['mode']}]: {k} table {v:.4f} replay {s.get(k, 0.0):.4f}")
    return bad


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("root", nargs="?", default="results/frontier")
    p.add_argument("--also", action="append", default=["results/eval"])
    p.add_argument("--replay", action="store_true")
    p.add_argument("--out", default="")
    a = p.parse_args(argv)
    rows = build_many([a.root] + a.also)
    text = md(rows)
    for out in [a.out or a.root, "web/results/frontier"] if not a.out else [a.out]:
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "gaptable.md"), "w").write(text)
        json.dump(rows, open(os.path.join(out, "gaptable.json"), "w"), indent=2, sort_keys=True)
    print(text)
    if a.replay:
        bad = replay(rows)
        print("\n".join(f"REPLAY FAIL {b}" for b in bad) or f"REPLAY OK ({sum(1 for r in rows if not r.get('status'))} rows)")
        if bad:
            raise SystemExit(1)
    return rows


def build_many(roots):
    seen = {}
    for root in roots:
        if os.path.isdir(root):
            for r in build(root):
                if r.get("status") and r["row"] in {x["row"] for x in seen.values()}:
                    continue
                seen[(r["row"], r.get("mode"))] = r
    done = {k[0] for k, v in seen.items() if not v.get("status")}
    return [v for k, v in seen.items() if not (v.get("status") and k[0] in done)]


if __name__ == "__main__":
    main()
