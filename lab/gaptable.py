import argparse
import glob
import json
import os
import random
from collections import Counter
from math import sqrt

from lab.results import load_days, pass_hat_k, summarise

MODELS = ["Gemini 4 Carbon", "Gemini 3.5 Flash", "Gemini 3.1 Pro", "Claude Sonnet 5.5", "Claude Opus 5.5", "Codex"]
FIXED = ["fair reference", "oracle", "trust_all", "do_nothing", "quarantine_all", "stop_early", "refuse_all"]
ALIAS = {"reference": "fair reference"}
HEAD = ["row", "provenance", "mode", "day source", "sleeper", "team", "capped", "invalid", "n days", "trials", "pass^1", "pass^3 (95% Wilson)", "sleeper success", "false accusation", "gap vs reference", "gap vs oracle", "model id", "commit", "calls/cost", "cache"]


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


NAMES = [("gemini-4-carbon", "Gemini 4 Carbon"), ("gemini-3.5-flash", "Gemini 3.5 Flash"), ("gemini-3.1-pro", "Gemini 3.1 Pro"), ("sonnet", "Claude Sonnet 5.5"), ("opus", "Claude Opus 5.5"), ("codex", "Codex")]


def display(model):
    return next((n for k, n in NAMES if k in str(model).lower()), str(model))


def is_capped(r):
    return bool(r.get("capped") or r.get("hit_cap") or r.get("scores", {}).get("capped"))


def is_invalid(r):
    return bool(r.get("invalid") or r.get("scores", {}).get("invalid"))


def aggregate(runs):
    inv = sum(is_invalid(r) for r in runs)
    runs = [r for r in runs if not is_invalid(r)]
    by = {}
    for r in runs:
        by.setdefault(r["seed"], []).append(r["scores"]["reward"])
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    out = {"invalid": inv, "capped": sum(is_capped(r) for r in runs), "n_days": len(by), "n_runs": len(runs), "reward_mean": mean([r["scores"]["reward"] for r in runs])}
    for k in (1, 3):
        out[f"pass^{k}"] = mean([pass_hat_k(len(v), sum(v), k) for v in by.values()]) if all(len(v) >= k for v in by.values()) and by else None
    out["pass^1_uncapped"], out["pass^3_uncapped"] = (aggregate([r for r in runs if not is_capped(r)])[k] if out["capped"] and len(runs) > out["capped"] else out[k] for k in ("pass^1", "pass^3"))
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
        groups.setdefault((("fair reference" if r.get("role") == "reference" else r["model"]), r.get("mode", "seat"), r.get("seat"), r.get("commit"), r.get("day_source") or "unknown", r.get("sleeper") or "unknown", r.get("team") or "unknown"), []).append(r)
    out = []
    for (model, mode, seat, commit, *ds), runs in groups.items():
        s = aggregate(runs)
        s["model"] = model
        extra = {"commit": commit, "calls": sum(x.get("calls") or 0 for x in runs) or None, "cost": round(sum(x.get("cost") or 0 for x in runs), 4) or None, "cache_path": os.path.dirname(runs[0]["_path"]), "files": [x["_path"] for x in runs], "provenance": "scripted" if runs[0].get("agent") == "scripted" else "real", "agent": runs[0].get("agent"), "day_source": ds[0], "sleeper": ds[1], "bg_team": ds[2]}
        out.append((model if model == "fair reference" else display(model), f"{seat} seat" if mode == "seat" else "all-8", s, None, extra))
    return out


def per_seed(files, run_dir):
    by = {}
    if files:
        for f in files:
            r = json.load(open(f))
            if not is_invalid(r):
                by.setdefault(r["seed"], []).append(r["scores"]["reward"])
    elif run_dir and os.path.exists(os.path.join(run_dir, "days.jsonl")):
        for r in load_days(os.path.join(run_dir, "days.jsonl")):
            by.setdefault(r["seed"], []).append(r["reward"])
    return {str(k): sum(v) / len(v) for k, v in by.items()}


def regret(files, run_dir):
    from lab import analyse

    days = []
    try:
        if files:
            for f in files:
                r = json.load(open(f))
                t = r.get("transcript")
                if t and r["scores"]["reward"] == 0 and not is_capped(r) and not is_invalid(r):
                    days.append(json.load(open(t if os.path.exists(t) else os.path.join(os.path.dirname(f), t))))
        elif run_dir and os.path.isdir(os.path.join(run_dir, "days")):
            days = [d for d in analyse.load(run_dir) if d["result"].get("reward", 1) == 0]
        c = Counter(x["label"] for d in days for x in analyse.label(analyse.norm(d)))
    except Exception:
        return None
    return dict(c) if days or not files else None


def boot_ci(xs, n=2000):
    rng = random.Random(0)
    m = sorted(sum(rng.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return m[int(0.025 * n)], m[int(0.975 * n) - 1]


def pair(rows):
    src = lambda r: (r["day_source"], r["sleeper"], r["team"])
    by = {(r["row"], r["mode"], src(r)): r for r in rows if not r.get("status")}
    for r in by.values():
        ref = by.get(("fair reference", r["mode"], src(r)))
        base = by.get(("staff", r["mode"], src(r)))
        unk = "unknown" in src(r)
        ps = r["per_seed"]
        r["paired"] = r["luck_adj"] = None
        if ref and not unk and r["row"] != "fair reference":
            seeds = sorted(set(ps) & set(ref["per_seed"]))
            d = [ref["per_seed"][k] - ps[k] for k in seeds]
            if d:
                ci = boot_ci(d)
                r["paired"] = {"seeds": len(d), "mean_diff": sum(d) / len(d), "ci": ci, "verdict": "significant" if ci[0] > 0 or ci[1] < 0 else "inconclusive"}
        if base and not unk:
            seeds = sorted(set(ps) & set(base["per_seed"]))
            if seeds:
                r["luck_adj"] = sum(ps[k] - base["per_seed"][k] for k in seeds) / len(seeds)
    return rows


def paired_md(rows):
    lines = ["| row | mode | paired seeds | mean diff (ref - row) | 95% bootstrap CI | verdict | luck-adjusted vs staff | regret tags (lost days) |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("status") or not r.get("paired"):
            continue
        p = r["paired"]
        tags = ", ".join(f"{k} {v}" for k, v in sorted((r.get("regret") or {}).items(), key=lambda x: -x[1])) or "n/a"
        lines.append(f"| {r['row']} | {r['mode']} | {p['seeds']} | {p['mean_diff']:.3f} | [{p['ci'][0]:.2f}, {p['ci'][1]:.2f}] | {p['verdict']} | {fmt(r['luck_adj'])} | {tags} |")
    return "\n".join(lines) + "\n"


def canon(name):
    return ALIAS.get(name, name)


def build(root):
    rows = {}
    for name, mode, s, run_dir, extra in entries(root) + real_entries(root):
        rows[(canon(name), (mode, (extra.get("day_source") or "day_for", extra.get("sleeper") or "scripted", extra.get("bg_team") or "staff_scripted")))] = (s, run_dir, extra)
    ref = {m: v[0]["reward_mean"] for (n, m), v in rows.items() if n == "fair reference"}
    orc = {m: v[0]["reward_mean"] for (n, m), v in rows.items() if n == "oracle"}
    modes = sorted({m for _, m in rows}) or [("all-8", "day_for")]
    names = MODELS + FIXED + sorted({n for n, _ in rows} - set(MODELS) - set(FIXED))
    out = []
    for n in names:
        found = [m for m in modes if (n, m) in rows]
        if not found:
            out.append({"row": n, "status": "pending"})
        for m in found:
            s, run_dir, x = rows[(n, m)]
            m, ds = m
            m_ = (m, ds)
            unk = "unknown" in ds
            runs = s.get("n_runs", 0)
            trials = runs // s["n_days"] if s.get("n_days") else 0
            p3 = s.get("pass^3")
            ci = wilson(p3, s.get("n_days", 0)) if p3 is not None else None
            out.append({
                "row": n, "mode": m, "day_source": ds[0], "sleeper": ds[1], "team": ds[2], "headline": tuple(ds) == ("day_for", "scripted", "procedure"), "invalid": s.get("invalid", 0), "n_days": s.get("n_days"), "trials": trials, "pass1": s.get("pass^1"), "pass3": p3, "pass3_ci": ci,
                "sleeper_success": s.get("sleeper_success_rate"), "false_accusation": s.get("false_accusation_rate"), "reward": s["reward_mean"],
                "gap_ref": ref[m_] - s["reward_mean"] if m_ in ref and not unk else None, "gap_oracle": orc[m_] - s["reward_mean"] if m_ in orc and not unk else None,
                "model": s.get("model"), "commit": x.get("commit"), "calls": x.get("calls"), "cost": x.get("cost"), "cache": x.get("cache_path"), "run_dir": run_dir, "files": x.get("files"), "per_seed": per_seed(x.get("files"), run_dir), "regret": regret(x.get("files"), run_dir), "provenance": x.get("provenance") or ("scripted" if s.get("agent_kind", "scripted") == "scripted" else "real"), "agent": x.get("agent") or s.get("agent_kind"), "capped": s.get("capped", 0), "pass1_uncapped": s.get("pass^1_uncapped"), "pass3_uncapped": s.get("pass^3_uncapped"),
            })
    return out


def fmt(v, f="{:.3f}"):
    return "n/a" if v is None else f.format(v)


def md(rows):
    head = [r for r in rows if r.get("headline") or r.get("status")]
    rest = [r for r in rows if not r.get("headline") and not r.get("status")]
    return table_md(head) + ("\n## Ablation and other groups (not headline)\n\n" + table_md(rest) if rest else "")


def table_md(rows):
    lines = ["| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    for r in rows:
        if r.get("status"):
            lines.append(f"| {r['row']} | pending |" + " |" * (len(HEAD) - 2))
            continue
        ci = r["pass3_ci"]
        p3 = "n/a" if r["pass3"] is None else f"{r['pass3']:.3f}" + (f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else "")
        cost = " / ".join(str(x) for x in (r["calls"], r["cost"]) if x is not None) or "n/a"
        lines.append("| " + " | ".join([r["row"], r["provenance"], r["mode"], r["day_source"], r["sleeper"], r["team"], str(r["capped"]), str(r["invalid"]), str(r["n_days"]), str(r["trials"]), fmt(r["pass1"]) + (f" ({fmt(r['pass1_uncapped'])} uncapped)" if r["capped"] else ""), p3 + (f" ({fmt(r['pass3_uncapped'])} uncapped)" if r["capped"] else ""), fmt(r["sleeper_success"]), fmt(r["false_accusation"]), fmt(r["gap_ref"]), fmt(r["gap_oracle"]), str(r["model"]), str(r["commit"] or "n/a"), cost, str(r["cache"] or "n/a")]) + " |")
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


def verify(rows, scripted=False):
    from sleeper.verifier import rescore

    cache = {}
    out = []
    for r in rows:
        if r.get("status"):
            out.append(r)
            continue
        d = os.path.dirname(r["files"][0]) if r.get("files") else (r["run_dir"] if scripted else None)
        names = {os.path.basename(f) for f in r["files"]} if r.get("files") else None
        r["verified"] = None
        if d and os.path.isdir(d):
            if d not in cache:
                cache[d] = rescore(d)
            n, bad = cache[d]
            mine = [b for b in bad if names is None or b.split(":")[0] in names]
            hard = [b for b in mine if "no initial state" not in b]
            r["verified"] = False if hard else (None if mine else True)
            r["rescore_failures"] = hard
        if r["verified"] is False:
            print(f"REFUSED {r['row']} [{r['mode']}]: rescore mismatch " + "; ".join(r["rescore_failures"][:3]))
            continue
        out.append(r)
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("root", nargs="?", default="results/frontier")
    p.add_argument("--also", action="append", default=["results/eval", "results/train"])
    p.add_argument("--replay", action="store_true")
    p.add_argument("--out", default="")
    a = p.parse_args(argv)
    rows = verify(build_many([a.root] + a.also), a.replay)
    text = md(rows) + "\n## Paired vs fair reference (same seeds)\n\n" + paired_md(rows)
    for out in [a.out or a.root, "web/results/frontier"] if not a.out else [a.out]:
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "gaptable.md"), "w").write(text)
        json.dump(rows, open(os.path.join(out, "gaptable.json"), "w"), indent=2, sort_keys=True)
    print(text)
    if a.replay:
        bad = replay(rows)
        print("\n".join(f"REPLAY FAIL {b}" for b in bad) or f"REPLAY OK ({sum(1 for r in rows if not r.get('status'))} rows)")
        import subprocess

        if subprocess.run(["make", "-n", "frontier-replay"], capture_output=True).returncode == 0:
            bad += [] if subprocess.run(["make", "frontier-replay"]).returncode == 0 else ["make frontier-replay failed"]
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
                seen[(r["row"], r.get("mode"), r.get("day_source"), r.get("sleeper"), r.get("team"))] = r
    done = {k[0] for k, v in seen.items() if not v.get("status")}
    return pair([v for k, v in seen.items() if not (v.get("status") and k[0] in done)])


if __name__ == "__main__":
    main()
