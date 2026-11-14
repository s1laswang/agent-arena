import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from lab import eval as lab_eval
from lab import frontier_replay


def force_offline():
    os.environ["SLEEPER_OFFLINE"] = "1"
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["LAB_GEMINI"] = "0"
    os.environ.pop("SLEEPER_SALT", None)


def group_tag(key):
    return key.split("[", 1)[1] if "[" in key else ""


def render_eval_table(items, refs):
    lines = [
        "| team | kind | reward | sleeper success | false accusation | tickets | gap vs reference |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in items:
        if not s:
            lines.append(f"| {name} | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        ref = refs.get(group_tag(name))
        gap = "n/a" if ref is None else f"{ref - s['reward_mean']:.3f}"
        lines.append(
            f"| {name} | {s['agent_kind']} | {s['reward_mean']:.3f} | "
            f"{s['sleeper_success_rate']:.3f} | {s['false_accusation_rate']:.3f} | "
            f"{s['ticket_completion']:.3f} | {gap} |"
        )
    return "\n".join(lines)


def build_summary_block(summary_path, day_start, days, trials, seat, frontier_md):
    data = json.loads(Path(summary_path).read_text())
    all_seats = data.get("all_seats") or {}
    ordered_all = [t for t in lab_eval.ORDER if t in all_seats] + [
        t for t in sorted(all_seats) if t not in lab_eval.ORDER
    ]
    all_items = [(t, all_seats[t]) for t in ordered_all]
    ref_all = (all_seats.get("reference") or {}).get("reward_mean")
    all_refs = {"": ref_all}

    seat_map = (data.get("seat") or {}).get(seat) or {}
    seat_rank = ["oracle", "reference", "staff", "do_nothing"]

    def skey(k):
        ag = k.split(" [", 1)[0]
        grp = 0 if "[needs " in k else 1
        idx = seat_rank.index(ag) if ag in seat_rank else 99
        return (grp, idx, k)

    seat_items = [(k, seat_map[k]) for k in sorted(seat_map, key=skey)]
    seat_refs = {
        group_tag(k): v["reward_mean"]
        for k, v in seat_map.items()
        if k.startswith("reference") and v
    }

    end_day = day_start + max(days, 1) - 1
    parts = [
        "==== SLEEPER REPRODUCE TABLE ====",
        "",
        f"### All 8 seats (days {day_start}..{end_day}, {trials} trials)",
        "",
        render_eval_table(all_items, all_refs),
        "",
        f"### Judge seat ({seat}, procedure background)",
        "",
        render_eval_table(seat_items, seat_refs),
        "",
        frontier_md.rstrip(),
    ]
    return "\n".join(parts) + "\n"


def main(argv=None):
    force_offline()
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=20)
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--day-start", type=int, default=1000)
    p.add_argument("--seat", default="finance_ap")
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument("--out", default="results")
    p.add_argument("--frontier-root", default="results/frontier")
    p.add_argument("--cache-archive", default="data/gemini_cache.tar.gz")
    p.add_argument("--skip-probes", action="store_true")
    p.add_argument("--skip-gaptable", action="store_true")
    p.add_argument("--skip-cache-rerun", action="store_true")
    a = p.parse_args(argv)

    if a.cache_archive and os.path.isfile(a.cache_archive):
        from scripts import gemini_cache

        gemini_cache.unpack(a.cache_archive)

    eval_argv = [
        "--days",
        str(a.days),
        "--trials",
        str(a.trials),
        "--day-start",
        str(a.day_start),
        "--seat",
        a.seat,
        "--out",
        a.out,
        "--web-out",
        "",
        "--strict",
    ]
    if a.jobs is not None:
        eval_argv += ["--jobs", str(a.jobs)]
    lab_eval.main(eval_argv)
    force_offline()

    runs_dir = os.path.join(a.out, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    fr_json = os.path.join(runs_dir, "frontier_replay.json")
    fr_md = os.path.join(runs_dir, "frontier_replay.md")
    fr_argv = [a.frontier_root, "--strict", "--json-out", fr_json, "--md-out", fr_md]
    if a.skip_cache_rerun:
        fr_argv.append("--skip-cache-rerun")
    fr_res = frontier_replay.main(fr_argv)

    if not a.skip_gaptable:
        from lab import gaptable

        gt_extra = [] if a.out == "results" else ["--out", os.path.join(a.out, "frontier")]
        gaptable.main([a.frontier_root, "--replay"] + gt_extra)
        gt_dir = a.frontier_root if a.out == "results" else os.path.join(a.out, "frontier")
        gt_md = Path(gt_dir) / "gaptable.md"
        rep_md = Path(a.out) / "eval" / "REPORT.md"
        if rep_md.is_file() and gt_md.is_file():
            with open(rep_md, "a") as f:
                f.write("\n" + gt_md.read_text())

    if not a.skip_probes and a.out == "results":
        env = dict(os.environ)
        env["SLEEPER_OFFLINE"] = "1"
        env["GEMINI_API_KEY"] = ""
        env["LAB_GEMINI"] = "0"
        env.pop("SLEEPER_SALT", None)
        proc = subprocess.run([sys.executable, "-m", "scripts.probes", "--days", "3"], env=env)
        if proc.returncode != 0:
            raise SystemExit(proc.returncode)

    summary_path = os.path.join(a.out, "eval", "summary.json")
    block = build_summary_block(summary_path, a.day_start, a.days, a.trials, a.seat, fr_res["markdown"])
    print(block, end="", flush=True)
    return {"summary_path": summary_path, "frontier_replay": fr_res, "table": block}


if __name__ == "__main__":
    main()
