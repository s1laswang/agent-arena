import argparse
import glob
import json
import os
import random
import shutil
import tempfile
from pathlib import Path

from lab import frontier_cache, frontier_rows, gaptable
from lab import run as lab_run
from lab.results import pass_hat_k
from scripts import gemini_cache
from sleeper.verifier import rescore


def force_offline():
    os.environ["SLEEPER_OFFLINE"] = "1"
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["LAB_GEMINI"] = "0"
    os.environ.pop("SLEEPER_SALT", None)


def scratch_dir():
    base = "/localscratch" if os.path.isdir("/localscratch") and os.access("/localscratch", os.W_OK) else None
    return tempfile.mkdtemp(dir=base)


def companion_cache(run_path):
    parts = run_path.stem.split("-", 1)
    if len(parts) < 2:
        return None
    return run_path.parent / f"cache-{parts[1]}.tar.gz"


def replay_single(run_file):
    force_offline()
    run_path = Path(run_file)
    if not run_path.is_file():
        raise SystemExit(f"missing run file: {run_path}")
    row = json.loads(run_path.read_text())
    if row.get("invalid"):
        raise SystemExit(f"row is invalid: {row.get('invalid')}")
    tar = companion_cache(run_path)
    if tar is None or not tar.is_file():
        raise SystemExit(f"missing companion cache for {run_path}")
    tmp = scratch_dir()
    try:
        cache_dir = Path(tmp)
        gemini_cache.unpack(str(tar), cache_dir)
        new = frontier_cache.rerun(row, cache_dir)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if new.get("invalid"):
        raise SystemExit(f"replay invalid: {new['invalid']}")
    diff = frontier_cache.same(row, new)
    if diff:
        raise SystemExit("MISMATCH: " + ", ".join(diff))
    if new.get("calls", 0) != 0 or new.get("cache_hits", 0) <= 0:
        raise SystemExit(f"unexpected cache usage: calls={new.get('calls', 0)} cache_hits={new.get('cache_hits', 0)}")
    sc = row["scores"]
    print(
        f"REPLAY OK reward={sc['reward']} tickets={sc['tickets_done']}/{sc['tickets_total']} "
        f"calls_from_cache={new.get('cache_hits', 0)} {run_path}"
    )
    return {"ok": True, "run": str(run_path), "cache_hits": new.get("cache_hits", 0)}


def scan_frontier(root):
    items = []
    if not os.path.isdir(root):
        return items
    for path in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
        if not gaptable.RUN_FILE.match(os.path.basename(path)):
            continue
        with open(path) as f:
            row = json.load(f)
        if not (isinstance(row, dict) and "scores" in row and "seed" in row):
            continue
        if row.get("agent") in (None, "scripted") or row.get("role") == "reference" or row.get("invalid"):
            continue
        p = Path(path)
        st = p.parent / f"{p.stem}.state.json.gz"
        tar = companion_cache(p)
        pb = str(row.get("prompt_budget") or "")
        if not st.is_file():
            kind = "legacy_skipped"
        elif tar is not None and tar.is_file() and pb == "200":
            kind = "cache_replayable"
        else:
            kind = "state_verified"
        items.append({"path": p, "row": row, "state_gz": st, "cache_tar": tar, "prompt_budget": pb, "kind": kind})
    return items


def paired_ci(diffs, boot=20000):
    if len(diffs) < 2:
        val = diffs[0] if diffs else 0.0
        return [val, val]
    rng = random.Random(0)
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(boot))
    return [means[int(0.025 * boot)], means[int(0.975 * boot) - 1]]


def format_markdown(groups, summary_line):
    cols = [
        "model",
        "commit",
        "seat",
        "budget",
        "n days",
        "runs",
        "frontier pass^1",
        "frontier pass^3",
        "reference (same seeds)",
        "paired gap (ref - model)",
        "95% CI",
        "cache replay",
        "verdict",
    ]
    lines = ["## Frontier vs Reference (paired on same seeds)", ""]
    if not groups:
        lines.append("No verified frontier state dumps found under this root.")
    else:
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "---|" * len(cols))
        for g in groups:
            p3 = "n/a" if g["pass3"] is None else f"{g['pass3']:.3f}"
            ci = f"[{g['paired_95ci'][0]:.2f}, {g['paired_95ci'][1]:.2f}]"
            cells = [
                str(g["model"]),
                str(g["commit"]),
                str(g["seat"]),
                str(g["prompt_budget"]),
                str(g["n_days"]),
                str(g["n_runs"]),
                f"{g['pass1']:.3f}",
                p3,
                f"{g['ref_mean']:.3f}",
                f"{g['paired_diff']:.3f}",
                ci,
                str(g["cache_replayed"]),
                str(g["verdict"]),
            ]
            lines.append("| " + " | ".join(cells) + " |")
    lines += ["", summary_line]
    return "\n".join(lines) + "\n"


def evaluate_root(root, skip_cache_rerun=False):
    force_offline()
    items = scan_frontier(root)
    cache_replayable = [x for x in items if x["kind"] == "cache_replayable"]
    state_verified = [x for x in items if x["kind"] == "state_verified"]
    legacy_skipped = [x for x in items if x["kind"] == "legacy_skipped"]
    replay_failures = []
    replayed_ok = set()
    failed_paths = set()

    if not skip_cache_rerun:
        for item in cache_replayable:
            p = item["path"]
            row = item["row"]
            tmp = scratch_dir()
            try:
                cache_dir = Path(tmp)
                gemini_cache.unpack(str(item["cache_tar"]), cache_dir)
                new = frontier_cache.rerun(row, cache_dir)
                if new.get("invalid"):
                    replay_failures.append(f"{p}: replay invalid: {new['invalid']}")
                    failed_paths.add(str(p))
                else:
                    diff = frontier_cache.same(row, new)
                    if diff:
                        replay_failures.append(f"{p}: mismatch {','.join(diff)}")
                        failed_paths.add(str(p))
                    elif new.get("calls", 0) != 0 or new.get("cache_hits", 0) <= 0:
                        replay_failures.append(
                            f"{p}: bad cache stats calls={new.get('calls', 0)} cache_hits={new.get('cache_hits', 0)}"
                        )
                        failed_paths.add(str(p))
                    else:
                        replayed_ok.add(str(p))
            except BaseException as exc:
                if isinstance(exc, KeyboardInterrupt):
                    raise
                replay_failures.append(f"{p}: {exc}")
                failed_paths.add(str(p))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    state_items = cache_replayable + state_verified
    dir_bad = {}
    for d in sorted({str(x["path"].parent) for x in state_items}):
        try:
            _, bad = rescore(d)
            dir_bad[d] = bad
        except Exception as exc:
            dir_bad[d] = [f"*: rescore error {type(exc).__name__}: {exc}"]

    verified_items = []
    for item in state_items:
        p = item["path"]
        d = str(p.parent)
        row = item["row"]
        mine = [b for b in dir_bad.get(d, []) if b.split(":", 1)[0] in (p.name, "*")]
        res_obj = row.get("result")
        if isinstance(res_obj, dict):
            sc_diff = [
                k
                for k in ("reward", "tickets_done", "tickets_total", "harm")
                if row["scores"].get(k) != res_obj.get(k)
            ]
            if sc_diff:
                mine.append(f"{p.name}: scores vs result mismatch {sc_diff}")
        hard = [b for b in mine if "no initial state" not in b]
        if item["prompt_budget"] == "200" and hard:
            for h in hard:
                msg = f"{d}/{h}"
                if msg not in replay_failures:
                    replay_failures.append(msg)
        if not mine and str(p) not in failed_paths:
            verified_items.append(item)

    lab_run.FACTORIES.setdefault(
        frontier_rows.SEAT_BG,
        (lambda d, t: __import__("agents.staff", fromlist=["x"]).make_team(d, seed=t, kind="scripted"), "scripted"),
    )
    ref_memo = {}

    def ref_reward(team, seat, seed):
        key = (team, seat, int(seed))
        if key not in ref_memo:
            force_offline()
            bg = "reference" if seat == "all8" else frontier_rows.bg_for(team)
            seat_arg = None if seat == "all8" else seat
            ref_memo[key] = float(lab_run.play_day(bg, "reference", seat_arg, int(seed), 0)[0]["reward"])
        return ref_memo[key]

    grouped = {}
    for item in verified_items:
        r = item["row"]
        gkey = (
            r["model"],
            r.get("commit") or "n/a",
            r.get("seat") or "finance_ap",
            r.get("team") or "procedure",
            str(r.get("prompt_budget") or "legacy"),
        )
        grouped.setdefault(gkey, []).append(item)

    groups = []
    ordered_keys = sorted(grouped, key=lambda k: (0 if k[4] == "200" else 1, k))
    for model, commit, seat, team, budget in ordered_keys:
        gitems = grouped[(model, commit, seat, team, budget)]
        by_seed = {}
        for x in gitems:
            by_seed.setdefault(int(x["row"]["seed"]), []).append(float(x["row"]["scores"]["reward"]))
        seeds = sorted(by_seed)
        n_days = len(seeds)
        n_runs = len(gitems)
        trials_per_day = min(len(by_seed[s]) for s in seeds)
        model_seed = {s: sum(by_seed[s]) / len(by_seed[s]) for s in seeds}
        frontier_mean = sum(model_seed[s] for s in seeds) / n_days
        pass1 = frontier_mean
        if all(len(by_seed[s]) >= 3 for s in seeds):
            pass3 = sum(pass_hat_k(len(by_seed[s]), sum(int(v >= 1.0) for v in by_seed[s]), 3) for s in seeds) / n_days
        else:
            pass3 = None
        ref_seed = {s: ref_reward(team, seat, s) for s in seeds}
        ref_mean = sum(ref_seed[s] for s in seeds) / n_days
        diffs = [ref_seed[s] - model_seed[s] for s in seeds]
        paired_diff = sum(diffs) / n_days
        ci = paired_ci(diffs, boot=20000)
        count_replayed = sum(1 for x in gitems if str(x["path"]) in replayed_ok)
        if budget != "200":
            verdict = "understated-budget (not headline)"
        elif n_days >= 2 and ci[0] > 0:
            verdict = "GAP (CI excludes 0)"
        elif paired_diff > 0:
            verdict = "below reference (small n)"
        else:
            verdict = "inconclusive"
        groups.append(
            {
                "model": model,
                "commit": commit,
                "seat": seat,
                "team": team,
                "prompt_budget": budget,
                "seeds": seeds,
                "n_days": n_days,
                "n_runs": n_runs,
                "trials_per_day": trials_per_day,
                "frontier_mean": frontier_mean,
                "pass1": pass1,
                "pass3": pass3,
                "ref_mean": ref_mean,
                "paired_diff": paired_diff,
                "paired_95ci": ci,
                "cache_replayed": f"{count_replayed}/{n_runs}",
                "verdict": verdict,
            }
        )

    summary_line = (
        f"frontier_replay: cache_replayed={len(replayed_ok)}/{len(cache_replayable)} "
        f"legacy_skipped={len(legacy_skipped)} failures={len(replay_failures)}"
    )
    md_text = format_markdown(groups, summary_line)
    return {
        "root": root,
        "cache_replayed": f"{len(replayed_ok)}/{len(cache_replayable)}",
        "cache_replayed_count": len(replayed_ok),
        "cache_replayable_count": len(cache_replayable),
        "state_verified_count": len(state_verified),
        "legacy_skipped": len(legacy_skipped),
        "replay_failures": replay_failures,
        "groups": groups,
        "summary_line": summary_line,
        "markdown": md_text,
    }


def main(argv=None):
    force_offline()
    p = argparse.ArgumentParser()
    p.add_argument("root", nargs="?", default="results/frontier")
    p.add_argument("--run", default="")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--skip-cache-rerun", action="store_true")
    p.add_argument("--json-out", default="")
    p.add_argument("--md-out", default="")
    a = p.parse_args(argv)
    if a.run:
        return replay_single(a.run)
    res = evaluate_root(a.root, skip_cache_rerun=a.skip_cache_rerun)
    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        with open(a.json_out, "w") as f:
            json.dump({k: v for k, v in res.items() if k != "markdown"}, f, indent=2, sort_keys=True)
    if a.md_out:
        Path(a.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.md_out).write_text(res["markdown"])
    print(res["markdown"], end="", flush=True)
    if res["replay_failures"]:
        for fail in res["replay_failures"]:
            print(f"REPLAY FAILURE: {fail}", flush=True)
        if a.strict:
            raise SystemExit(1)
    return res


if __name__ == "__main__":
    main()
