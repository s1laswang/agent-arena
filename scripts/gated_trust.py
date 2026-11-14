import json, multiprocessing, os, subprocess, sys

os.environ["GEMINI_API_KEY"] = ""
os.environ["LAB_GEMINI"] = "0"

from lab import run
from sleeper.baselines import SEATS, register

NAMES = ("trust_all", "gullible", "random_accuse")


def one(a):
    name, seat, d = a
    r, _ = run.play_day("oracle", name, seat, d, 0)
    return name, seat, d, None if any(h.startswith("config:") for h in r["harm"]) else r["reward"], r["has_sleeper"]


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    register()
    jobs = [(n, s, d) for n in NAMES for s in SEATS for d in range(1000, 1000 + days)]
    with multiprocessing.get_context("fork").Pool(4) as p:
        res = p.map(one, jobs)
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    out = {}
    for n, s, d, r, hs in res:
        c = out.setdefault(n, {}).setdefault(s, {"graded": 0, "sum": 0, "nonzero_days": []})
        if r is None:
            continue
        c["graded"] += 1
        c["sum"] += r
        if r:
            c["nonzero_days"].append(d)
    ls = ["| baseline | " + " | ".join(SEATS) + " |", "|" + "---|" * (len(SEATS) + 1)]
    for n in NAMES:
        ls.append(f"| {n} | " + " | ".join(f"{out[n][s]['sum']}/{out[n][s]['graded']}" for s in SEATS) + " |")
    md = "\n".join(ls) + f"\n\nwins/graded days 1000-{999 + days}, commit {commit}, offline\n"
    print(md)
    json.dump({"commit": commit, "days": days, "cells": out}, open(os.environ.get("OUT", "results/baselines/gated_trust.json"), "w"), indent=1)
    open(os.environ.get("OUT", "results/baselines/gated_trust.json").replace(".json", ".md"), "w").write(md)


if __name__ == "__main__":
    main()
