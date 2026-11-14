"""Clash matrix (arena mode, never the judge path): Gemini detective x Gemini mole on medium.

    python -m canary.gemini.clash --detectives gemini-3.1-flash-lite,gemini-3.8-flash,gemini-4-hydrogen \
        --moles default,gemini-3.1-flash-lite,gemini-3.8-flash,gemini-4-hydrogen --seeds 0-4 --tier medium \
        --out ~/agent-arena-data/gemini/clash/run1 [--concurrency 8] [--report results/gemini]

Detective: the in-process LLMPolicy (full history, as in the ladder) on a ledgered client (feature="clash").
"solver" as a detective is the reference solver (free). Mole: canary.agents.mole_arena.LLMMole on a ledgered client
(feature="clash-mole"), installed through Env(..., mole_strategy=...) ; "default" is the env's own DSL mole.
Both sides run at the model's default thinking level. The LLM mole decides each day from its MoleView only; note
that the env applies an LLM mole's leak without the DSL's p_leak gate (canary.agents.mole_arena docstring), so an
LLM mole can leak more often than the default mole.

Layout: OUT/<detective>/<mole>/<seed>/episodes.jsonl (+ meta.json, transcripts/), resumable; infra failures moved to
OUT/_invalid/. Report: results/gemini/clash.{md,json}.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from canary.gemini.ladder import HOST, TallyClient, check_seeds, parse_seed_spec, read_eps

FEATURE = "clash"


def _client(model: str, feature: str, run_id: str, meta: dict):
    from canary.gemini import lab_client
    return lab_client(f"gemini:{model}", feature=feature, run_id=run_id, meta=meta)


def run_one(out: Path, det: str, mole: str, tier: str, seed: int, client_factory=None) -> dict:
    from canary.agents.llm_policy import LLMPolicy
    from canary.agents.mole_arena import LLMMole
    from canary.env import Env
    from canary.agents.loop import run_episode  # (env, policy, agent_name)
    cf = client_factory or _client
    d = Path(out) / det / mole / str(seed)
    if d.exists():
        shutil.rmtree(d)
    (d / "transcripts").mkdir(parents=True)
    t0 = time.time()
    run_id = f"clash:{Path(out).name}:{det}/{mole}/{tier}/{seed}"
    meta = {"detective": det, "mole": mole, "tier": tier, "seed": seed}
    mole_obj = None if mole == "default" else LLMMole(cf(mole, "clash-mole", run_id, meta))
    env = Env(tier=tier, seed=seed, mole_strategy=mole_obj)
    error = None
    tally = {}
    try:
        if det == "solver":
            from canary.solver.policy import SolverPolicy
            pol = SolverPolicy()
            res = run_episode(env, pol)
        else:
            client = TallyClient(cf(det, FEATURE, run_id, meta))
            pol = LLMPolicy(f"gemini:{det}", context="full", client=client)
            res = run_episode(env, pol, f"gemini:{det}")
            tally = dict(client.tally)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
        res = env.result(det)
        res.end_reason = "error"
    res.agent = f"detective:{det}|mole:{mole}"
    mlog = getattr(mole_obj, "log", []) if mole_obj is not None else []
    res.meta = {**(res.meta or {}), "clash": {**meta, "run_id": run_id, "wall_s": round(time.time() - t0, 1),
                                              "tokens": tally, "mole_days": len(mlog),
                                              "mole_llm_errors": sum(1 for x in mlog if x.get("error")),
                                              "mole_leaks": sum(1 for x in mlog if x["move"].get("leak")),
                                              "mole_frames": sum(1 for x in mlog if x["move"].get("frame"))},
                **({"error": error} if error else {})}
    ep = json.loads(json.dumps(dataclasses.asdict(res), default=str))
    (d / "episodes.jsonl").write_text(json.dumps(ep) + "\n")
    if det != "solver":
        (d / "transcripts" / f"{seed}.json").write_text(json.dumps(pol.transcript, indent=1, default=str))
    (d / "transcripts" / f"{seed}.mole.json").write_text(json.dumps(mlog, indent=1, default=str))
    (d / "meta.json").write_text(json.dumps({"agent": res.agent, "feature": FEATURE, "run_id": run_id, **meta,
                                             "arena_mode": True, "host": HOST}, indent=1))
    if res.end_reason == "error" or (mlog and all(x.get("error") for x in mlog)):
        dst = Path(out) / "_invalid" / f"{det}-{mole}-{seed}-{time.strftime('%H%M%S')}-{os.getpid()}-{threading.get_ident() % 10000}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d), str(dst))
        (dst / "INVALID.txt").write_text((error or "mole: every LLM call failed") + "\n")
        return {"cell": f"{det}/{mole}/{seed}", "invalid": True}
    return {"cell": f"{det}/{mole}/{seed}", "score": res.score, "correct": res.correct}


def run_matrix(out: Path, dets, moles, seeds, tier="medium", concurrency=8, max_attempts=3, client_factory=None,
               log=print) -> list[dict]:
    jobs = [(d, m, s) for s in seeds for d in dets for m in moles]
    lock = threading.Lock()
    rows: list[dict] = []

    def done(d, m, s):
        eps = read_eps(Path(out) / d / m / str(s))
        return bool(eps)

    todo = [j for j in jobs if not done(*j)]
    log(f"clash: {len(jobs)} cells, {len(todo)} to run")

    def worker():
        while True:
            with lock:
                if not todo:
                    return
                j = todo.pop(0)
            for _ in range(max_attempts):
                r = run_one(out, *j[:2], tier, j[2], client_factory)
                if not r.get("invalid"):
                    break
            with lock:
                rows.append(r)
            log(f"DONE {r}")

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, concurrency))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return rows


def report(out: Path, dest: Path) -> dict:
    from canary.agents.runlog import git_sha
    from canary.analysis.gap import mean_ci
    cells: dict = {}
    for f in sorted(Path(out).glob("*/*/*/episodes.jsonl")):
        det, mole, seed = f.parent.relative_to(out).parts
        if det.startswith("_"):
            continue
        for e in read_eps(f.parent):
            cells.setdefault((det, mole), []).append(e)
    dets = sorted({k[0] for k in cells}, key=lambda x: (x != "solver", x))
    moles = sorted({k[1] for k in cells}, key=lambda x: (x != "default", x))
    rows = []
    for (det, mole), es in sorted(cells.items()):
        m, h = mean_ci([e["score"] for e in es])
        c = [(e.get("meta") or {}).get("clash", {}) for e in es]
        rows.append({"detective": det, "mole": mole, "n": len(es), "mean": m, "ci": h,
                     "accuracy": sum(bool(e["correct"]) for e in es) / len(es),
                     "accuse_day": sum(e["final_day"] for e in es) / len(es),
                     "mole_leaks_per_ep": sum(x.get("mole_leaks", 0) for x in c) / len(es),
                     "mole_frames_per_ep": sum(x.get("mole_frames", 0) for x in c) / len(es),
                     "seeds": sorted(e["seed"] for e in es)})
    run_ids = sorted({(e.get("meta") or {}).get("clash", {}).get("run_id") for es in cells.values() for e in es} - {None})
    doc = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": git_sha(), "ledger_run_ids": run_ids,
           "arena_mode": True, "runs": str(out), "rows": rows}
    by = {(r["detective"], r["mole"]): r for r in rows}
    L = ["# Clash matrix: Gemini detective x Gemini mole (arena mode, medium)", "",
         f"Generated {doc['generated_at']} at git `{doc['git_sha'][:10]}`. Cell = detective mean score ± 95% CI "
         "(accuracy; mole leaks per episode). Arena mode only: never the judge path. `default` = the env's DSL mole; "
         "`solver` = the reference solver as detective. LLM moles leak without the DSL's p_leak gate.", "",
         "| detective \\ mole | " + " | ".join(moles) + " |", "|---|" + "---|" * len(moles)]
    for d in dets:
        cellstr = []
        for m in moles:
            r = by.get((d, m))
            cellstr.append("–" if r is None else f"{r['mean']:+.2f} ± {r['ci']:.2f} (acc {r['accuracy']:.0%}; "
                           f"{r['mole_leaks_per_ep']:.1f} leaks; n={r['n']})")
        L.append(f"| {d} | " + " | ".join(cellstr) + " |")
    dest.mkdir(parents=True, exist_ok=True)
    clean = json.loads(json.dumps(doc, default=str).replace("NaN", "null"))
    (dest / "clash.json").write_text(json.dumps(clean, indent=1) + "\n")
    (dest / "clash.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.clash", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detectives", default="gemini-3.1-flash-lite,gemini-3.8-flash,gemini-4-hydrogen")
    ap.add_argument("--moles", default="default,gemini-3.1-flash-lite,gemini-3.8-flash,gemini-4-hydrogen")
    ap.add_argument("--seeds", default="0-4")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--report", default=None, help="write clash.{md,json} here (e.g. results/gemini)")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args(argv)
    out = Path(os.path.expanduser(a.out))
    if not a.report_only:
        seeds = parse_seed_spec(a.seeds)
        check_seeds(seeds)
        prev_retries = os.environ.get("CANARY_LLM_MAX_RETRIES")
        prev_ledger = os.environ.get("CANARY_GEMINI_LEDGER")
        try:
            os.environ.setdefault("CANARY_LLM_MAX_RETRIES", "12")
            os.environ.setdefault("CANARY_GEMINI_LEDGER", str(out / "_ledger" / f"{HOST}-{os.getpid()}.jsonl"))
            run_matrix(out, a.detectives.split(","), a.moles.split(","), seeds, a.tier, a.concurrency,
                       log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
        finally:
            if prev_retries is None:
                os.environ.pop("CANARY_LLM_MAX_RETRIES", None)
            else:
                os.environ["CANARY_LLM_MAX_RETRIES"] = prev_retries
            if prev_ledger is None:
                os.environ.pop("CANARY_GEMINI_LEDGER", None)
            else:
                os.environ["CANARY_GEMINI_LEDGER"] = prev_ledger
    if a.report or a.report_only:
        report(out, Path(a.report or "results/gemini"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
