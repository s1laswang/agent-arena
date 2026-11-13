"""Eval runner: play many days with many policies and write a results table.

  python -m blindspot.eval                        # scripted policies, seeds 0-29
  python -m blindspot.eval --agents oracle,autopilot,gemini_staff,gemini_reference --seeds 0-9 --repeats 3

Writes results/<run>/episodes.jsonl, summary.json and summary.md.
Gemini agents are skipped (with a note) when no API key or cache is available.
"""
from __future__ import annotations

import argparse
import collections
import json
import time
from pathlib import Path

from . import world
from .agents import GeminiAgent, NoKey
from .baselines import POLICIES
from .env import Env
from .verify import score

DEFAULT_AGENTS = ["oracle", "autopilot", "do_nothing", "stop_early", "refuse_all", "escalate_all",
                  "claim_in_chat"]


def parse_seeds(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def make_policy(name: str, sample: int, model: str | None):
    if name in POLICIES:
        return POLICIES[name]
    if name.startswith("gemini_"):
        return GeminiAgent(mode=name.split("_", 1)[1], model=model, sample=sample)
    raise SystemExit(f"unknown agent {name}")


def run(agents, seeds, repeats=1, out_dir="results/latest", model=None, quiet=False):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    eps = []
    skipped = {}
    for name in agents:
        reps = repeats if name.startswith("gemini_") else 1
        for seed in seeds:
            for k in range(reps):
                pol = make_policy(name, k, model)
                env = Env(seed)
                t0 = time.time()
                try:
                    pol(env)
                except NoKey as e:
                    skipped[name] = str(e)
                    break
                s = score(env.state())
                ep = {"agent": name, "seed": seed, "sample": k, "reward": s["reward"],
                      "tickets_ok": s["tickets_ok"], "tickets_total": s["tickets_total"],
                      "hazards_caught": s["hazards_caught"], "hazards_total": s["hazards_total"],
                      "benign_ok": s["benign_ok"], "benign_total": s["benign_total"],
                      "eur_lost": s["eur_lost"], "harms": s["harms"], "steps": env.steps,
                      "secs": round(time.time() - t0, 2), "planted": env.hidden["planted"],
                      "failed": {tid: {"family": t["family"], "hazard": t["hazard"],
                                       "reasons": t["reasons"]}
                                 for tid, t in s["tickets"].items() if not t["ok"]}}
                if hasattr(pol, "usage"):
                    ep["usage"] = dict(pol.usage)
                    (out / "transcripts").mkdir(exist_ok=True)
                    (out / "transcripts" / f"{name}_s{seed}_k{k}.json").write_text(
                        json.dumps(pol.transcript, default=str, indent=1), encoding="utf-8")
                eps.append(ep)
                if not quiet:
                    print(f"{name:16s} seed={seed:3d} k={k} reward={s['reward']} "
                          f"tickets={s['tickets_ok']}/{s['tickets_total']} "
                          f"hazards={s['hazards_caught']}/{s['hazards_total']} lost={s['eur_lost']:,.0f}")
            if name in skipped:
                break
    with open(out / "episodes.jsonl", "w", encoding="utf-8") as f:
        for e in eps:
            f.write(json.dumps(e) + "\n")
    summ = summarise(eps, skipped)
    (out / "summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    (out / "summary.md").write_text(to_markdown(summ, seeds, repeats), encoding="utf-8")
    return summ


def summarise(eps, skipped):
    by = collections.defaultdict(list)
    for e in eps:
        by[e["agent"]].append(e)
    rows = {}
    for a, es in by.items():
        fam_tot, fam_ok = collections.Counter(), collections.Counter()
        for e in es:
            for f in e["planted"]:
                fam_tot[f] += 1
            failed_haz = {v["family"] for v in e["failed"].values() if v["hazard"]}
            for f in e["planted"]:
                if f not in failed_haz:
                    fam_ok[f] += 1
        # pass^k: a seed counts only if every repeat on it scored 1
        seeds = collections.defaultdict(list)
        for e in es:
            seeds[e["seed"]].append(e["reward"])
        rows[a] = {
            "episodes": len(es),
            "mean_reward": round(sum(e["reward"] for e in es) / len(es), 3),
            "pass_all_repeats": round(sum(all(v) for v in seeds.values()) / len(seeds), 3),
            "tickets_ok_rate": round(sum(e["tickets_ok"] for e in es) /
                                     max(1, sum(e["tickets_total"] for e in es)), 3),
            "hazard_catch_rate": round(sum(e["hazards_caught"] for e in es) /
                                       max(1, sum(e["hazards_total"] for e in es)), 3),
            "benign_done_rate": round(sum(e["benign_ok"] for e in es) /
                                      max(1, sum(e["benign_total"] for e in es)), 3),
            "eur_lost_total": round(sum(e["eur_lost"] for e in es), 2),
            "by_family": {f: f"{fam_ok[f]}/{fam_tot[f]}" for f in sorted(fam_tot)},
        }
    return {"agents": rows, "skipped": skipped}


def to_markdown(summ, seeds, repeats):
    lines = [f"Seeds {seeds[0]}-{seeds[-1]} ({len(seeds)} days), LLM repeats {repeats}.", "",
             "| Agent | Mean reward | pass^k | Tickets OK | Hazards caught | Valid work done | EUR lost |",
             "|---|---|---|---|---|---|---|"]
    for a, r in summ["agents"].items():
        lines.append(f"| {a} | {r['mean_reward']:.2f} | {r['pass_all_repeats']:.2f} | "
                     f"{r['tickets_ok_rate']:.0%} | {r['hazard_catch_rate']:.0%} | "
                     f"{r['benign_done_rate']:.0%} | {r['eur_lost_total']:,.0f} |")
    fams = sorted({f for r in summ["agents"].values() for f in r["by_family"]})
    if fams:
        lines += ["", "Hazards caught per family:", "",
                  "| Agent | " + " | ".join(fams) + " |", "|---|" + "---|" * len(fams)]
        for a, r in summ["agents"].items():
            lines.append(f"| {a} | " + " | ".join(r["by_family"].get(f, "-") for f in fams) + " |")
    for a, why in summ["skipped"].items():
        lines.append(f"\nSkipped {a}: {why}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", default=",".join(DEFAULT_AGENTS))
    ap.add_argument("--seeds", default="0-29")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default="results/latest")
    ap.add_argument("--model", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    summ = run(a.agents.split(","), parse_seeds(a.seeds), a.repeats, a.out, a.model, a.quiet)
    print(Path(a.out, "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
