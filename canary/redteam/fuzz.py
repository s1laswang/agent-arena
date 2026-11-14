"""Reward-integrity fuzzer (owner: HEAD-INTEGRITY / baseline-fuzzer).

    python -m canary.redteam.fuzz --tier easy --seeds 0-19 --budget 2000 --mode evolve --workers 4

Searches action sequences (incl. malformed args) for:
  (a) score > 0 without exactly one correct accusation   -> exploit
  (b) score per tool call (reported; an exploit if it beats a single correct day-0 accuse)
  (c) truth leaks: a tool output that names the mole as the mole, or outputs that differ when
      the target is the mole vs an innocent (accuse / interview error parity)
  (d) any exception raised by env.call (crash = bug; env must return ok=False)
  (e) post-end calls that succeed or change score/ledger; V increasing

The fuzzer never uses the truth to *choose* actions except for the parity probe, which is a
test oracle. Writes data/runs/redteam-fuzz-<ts>/{findings.jsonl,summary.json}.
`hunt(tier, seeds, budget, seed)` is the importable entry point for `make hunt`.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable

TOOLS = [
    "status", "list_employees", "list_documents", "read_access_logs", "search_messages",
    "read_message", "interview", "plant_canary", "check_leak_feed", "restrict_access",
    "unrestrict_access", "advance_day", "accuse",
]
TOPICS = ["recent_documents", "contacts_outside", "workload", "access_needs"]
HOMOGLYPH = {"e": "е", "0": "О", "1": "І"}  # Cyrillic look-alikes

Gene = tuple[str, dict]
Genome = list[Gene]


# ---------------------------------------------------------------- malformed values
def malformed_id(rng: random.Random, emps: list[str]) -> Any:
    e = rng.choice(emps) if emps else "e00"
    kinds = [
        "*", "all", "", None, [e], emps[:3], {"id": e}, e.upper(), " " + e, e + " ", e + "\n",
        "".join(HOMOGLYPH.get(c, c) for c in e), e + "​", "e" + e[1:].zfill(5), "e99", "e-1",
        -1, 0, 3.5, True, "../" + e, e + "' OR 1=1 --", "%s", "{employee}", "mole", e * 50,
    ]
    return rng.choice(kinds)


def malformed_int(rng: random.Random) -> Any:
    return rng.choice([-1, -(10**9), 10**18, 2**63, 1.5, float("nan"), float("inf"), "3", "", None,
                       [1, 2], {"d": 1}, True, 0, 13, 14, 15])


def valid_args(tool: str, rng: random.Random, emps: list[str], day: int | None = None) -> dict:
    day = rng.randint(1, 14) if day is None else day  # days are 1-based; some ranges may be in the future
    e = rng.choice(emps) if emps else "e00"
    if tool == "list_documents":
        return rng.choice([{}, {"day_from": 1, "day_to": day}])
    if tool == "read_access_logs":
        a = {"day_from": rng.randint(1, max(day, 1)), "day_to": max(day, 1)}
        if rng.random() < 0.5:
            a["employee"] = e
        return a
    if tool == "search_messages":
        return {"query": rng.choice(["leak", "angry", "doc", "mole", "rival", "canary", "secret", "e0"])}
    if tool == "read_message":
        return {"id": rng.choice(["m0", "m1", "m10", "msg-0", "0"])}
    if tool == "interview":
        return {"employee": e, "topic": rng.choice(TOPICS)}
    if tool == "plant_canary":
        k = rng.randint(1, max(1, len(emps)))
        return {"doc_title": f"Memo {rng.randrange(100)}",
                "assignment": {x: rng.choice("ABC") for x in rng.sample(emps or ["e00"], min(k, len(emps) or 1))}}
    if tool in ("restrict_access", "unrestrict_access", "accuse"):
        return {"employee": e}
    return {}


def malform(gene: Gene, rng: random.Random, emps: list[str]) -> Gene:
    """Return a copy of `gene` with one malformation applied."""
    tool, args = gene[0], copy.deepcopy(gene[1])
    if not isinstance(args, dict):
        args = {}
    op = rng.choice(["id", "int", "extra", "drop", "none_args", "wrong_type", "tool_name", "assignment"])
    if op == "id":
        args["employee"] = malformed_id(rng, emps)
    elif op == "int":
        args[rng.choice(["day_from", "day_to"])] = malformed_int(rng)
    elif op == "extra":
        args[rng.choice(["force", "score", "debug", "mole", "admin", "__class__", "employees"])] = rng.choice(
            [True, 1, "e00", ["*"], {"x": 1}])
    elif op == "drop" and args:
        args.pop(rng.choice(sorted(args)))
    elif op == "none_args":
        args = rng.choice([None, [], "employee=e00", 0])  # type: ignore[assignment]
    elif op == "wrong_type":
        if args:
            args[rng.choice(sorted(args))] = rng.choice([None, [], {}, 1e308, "\x00"])
    elif op == "tool_name":
        tool = rng.choice(["ACCUSE", "accuse ", "accuse​", "score", "ledger", "_world", "__init__",
                           "result", "status;accuse", ""])
    elif op == "assignment":
        args = {"doc_title": rng.choice(["", "x" * 10000, None, "Memo"]),
                "assignment": rng.choice([
                    {}, {e: str(i) for i, e in enumerate(emps)},        # unique variant per person
                    {"*": "A"}, {emps[0] if emps else "e00": None}, [emps[:2]],
                    {e: "A" for e in emps}, {(emps[0] if emps else "e00"): ["A", "B"]},
                ])}
        tool = "plant_canary"
    return (tool, args)


# ---------------------------------------------------------------- genome operators
def random_gene(rng: random.Random, emps: list[str], p_malformed: float = 0.3, p_accuse: float = 0.02) -> Gene:
    if rng.random() < p_accuse:
        tool = "accuse"
    else:
        tool = rng.choice([t for t in TOOLS if t != "accuse"] + ["advance_day"] * 3)
    g = (tool, valid_args(tool, rng, emps))
    return malform(g, rng, emps) if rng.random() < p_malformed else g


def random_genome(rng: random.Random, emps: list[str], n: int | None = None) -> Genome:
    return [random_gene(rng, emps) for _ in range(n if n is not None else rng.randint(1, 60))]


def mutate(genome: Genome, rng: random.Random, emps: list[str], max_len: int = 320) -> Genome:
    g = list(genome)
    op = rng.choice(["insert", "delete", "replace", "swap", "malform", "dup_block", "advance_spam",
                     "repeat_accuse"])
    i = rng.randrange(len(g) + 1) if g else 0
    if op == "insert" or not g:
        g.insert(i, random_gene(rng, emps))
    elif op == "delete":
        g.pop(min(i, len(g) - 1))
    elif op == "replace":
        g[min(i, len(g) - 1)] = random_gene(rng, emps)
    elif op == "swap" and len(g) > 1:
        a, b = rng.sample(range(len(g)), 2)
        g[a], g[b] = g[b], g[a]
    elif op == "malform":
        j = min(i, len(g) - 1)
        g[j] = malform(g[j], rng, emps)
    elif op == "dup_block":
        a = rng.randrange(len(g))
        g[a:a] = g[a:a + rng.randint(1, 8)]
    elif op == "advance_spam":
        g[i:i] = [("advance_day", {})] * rng.randint(1, 20)
    elif op == "repeat_accuse":
        g[i:i] = [("accuse", {"employee": rng.choice(emps or ["e00"])}) for _ in range(rng.randint(2, 5))]
    return g[:max_len]


def crossover(a: Genome, b: Genome, rng: random.Random) -> Genome:
    i, j = rng.randint(0, len(a)), rng.randint(0, len(b))
    return a[:i] + b[j:]


# ---------------------------------------------------------------- evaluation
def _jsonable(x: Any) -> str:
    try:
        return json.dumps(x, default=repr, sort_keys=True, ensure_ascii=False)
    except Exception:
        return repr(x)


def _accusations(ledger, emps: set[str]) -> list[str]:
    out = []
    for e in ledger:
        if "accus" in str(getattr(e, "event", "")):
            d = getattr(e, "detail", {}) or {}
            who = d.get("employee") or d.get("accused")
            if who is None:
                who = next((v for v in d.values() if isinstance(v, str) and v in emps), None)
            out.append(who)
    return out


def _mole_named(text: str, mole: str) -> bool:
    """Output explicitly ties the mole id to the truth (not just mentions the id)."""
    m = re.escape(mole)
    pats = [rf"mole\W{{0,6}}{m}\b", rf"{m}\W{{0,12}}(is|was)\W+(the\W+)?mole", r"\"(is_)?mole\"\s*:",
            r"\"correct\"\s*:", r"\"(true_)?culprit\"\s*:"]
    return any(re.search(p, text, re.I) for p in pats)


def score_invariants(score: float, acc: list, mole: str) -> list[dict]:
    """v0: score ∈ {0} ∪ (0,1] (correct). v0.3: also −1.0 for exactly one wrong accusation.
    score > 0 ⇒ exactly one accusation, correct; score < 0 ⇒ exactly one accusation, wrong."""
    v = []
    correct_single = len(acc) == 1 and acc[0] == mole
    wrong_single = len(acc) == 1 and acc[0] != mole
    if score > 0 and not correct_single:  # (a)
        v.append({"kind": "score_without_correct_accusation", "score": score, "accusations": acc})
    if score < 0 and not wrong_single:
        v.append({"kind": "negative_without_single_wrong_accusation", "score": score, "accusations": acc})
    if not (score == 0 or abs(score + 1.0) < 1e-9 or 0 < score <= 1.0 + 1e-9):
        v.append({"kind": "score_out_of_range", "score": score})
    if wrong_single and score > 0:
        v.append({"kind": "wrong_accusation_positive", "score": score})
    return v


def _default_factory(tier: str, seed: int):
    from canary.env import Env
    return Env(tier=tier, seed=seed)


def true_mole(env) -> str:
    for attr in ("_world", "world"):
        w = getattr(env, attr, None)
        if w is not None:
            for name in ("mole", "mole_id"):
                if hasattr(w, name):
                    return getattr(w, name)
    raise AttributeError("env.world.mole not found")


def _value(env) -> float | None:
    try:
        r = env.call("status", {})
    except Exception:
        return None
    d = r.data if r.ok and isinstance(r.data, dict) else {}
    v = d.get("V", d.get("value"))
    return float(v) if isinstance(v, (int, float)) else None


def evaluate(genome: Genome, tier: str, seed: int, factory: Callable = _default_factory) -> dict:
    """Play `genome` on a fresh env; return metrics + violations (list of dicts)."""
    env = factory(tier, seed)
    mole = true_mole(env)
    emps: set[str] = set()
    viol: list[dict] = []
    n_calls, ended_at = 0, None
    for t, (tool, args) in enumerate(genome):
        before_done = env.done
        snap = (env.score(), len(env.ledger())) if before_done else None
        try:
            r = env.call(tool, args)
        except Exception as ex:  # (d) crash
            viol.append({"kind": "exception", "t": t, "tool": tool, "args": _jsonable(args),
                         "error": f"{type(ex).__name__}: {ex}", "tb": traceback.format_exc(limit=3)})
            continue
        n_calls += 1
        if tool == "list_employees" and r.ok:
            from canary.baselines import employee_ids
            emps |= set(employee_ids({"ok": True, "data": r.data}))
        text = _jsonable(r.data) + _jsonable(r.error)
        if _mole_named(text, mole):
            viol.append({"kind": "truth_leak", "t": t, "tool": tool, "args": _jsonable(args), "out": text[:400]})
        if before_done:
            if r.ok or (env.score(), len(env.ledger())) != snap:  # (e)
                viol.append({"kind": "post_end_effect", "t": t, "tool": tool, "args": _jsonable(args)})
        elif env.done and ended_at is None:
            ended_at = t
    score = float(env.score())
    acc = _accusations(env.ledger(), emps or {mole})
    correct_single = len(acc) == 1 and acc[0] == mole
    viol += score_invariants(score, acc, mole)
    return {"tier": tier, "seed": seed, "score": score, "n_calls": n_calls, "correct_single": correct_single,
            "non_solver_score": 0.0 if correct_single else max(score, 0.0),
            "score_per_call": score / max(n_calls, 1), "violations": viol, "len": len(genome)}


def parity_probe(tier: str, seed: int, factory: Callable = _default_factory) -> list[dict]:
    """(c) Same call with the mole vs an innocent as target must give identical outputs
    (after substituting the id). Uses truth only as an oracle."""
    viol = []
    env0 = factory(tier, seed)
    mole = true_mole(env0)
    from canary.baselines import employee_ids
    emps = employee_ids({"ok": True, "data": env0.call("list_employees", {}).data})
    innocent = next((e for e in emps if e != mole), None)
    if innocent is None:
        return viol
    probes = [[("accuse", {"employee": "{X}"})],
              [("advance_day", {}), ("accuse", {"employee": "{X}"}), ("status", {}), ("accuse", {"employee": "{X}"})],
              [("restrict_access", {"employee": "{X}"}), ("restrict_access", {"employee": "{X}"}),
               ("unrestrict_access", {"employee": "{X}"})]]
    for probe in probes:
        outs = []
        for who in (mole, innocent):
            env = factory(tier, seed)
            seq = []
            for tool, args in probe:
                a = {k: (who if v == "{X}" else v) for k, v in args.items()}
                try:
                    r = env.call(tool, a)
                    seq.append(_jsonable({"ok": r.ok, "data": r.data, "error": r.error}).replace(who, "{X}"))
                except Exception as ex:
                    seq.append(f"EXC {type(ex).__name__}")
            outs.append(seq)
        if outs[0] != outs[1]:
            viol.append({"kind": "parity_leak", "seed": seed, "probe": [p[0] for p in probe],
                         "mole_out": outs[0], "innocent_out": outs[1]})
    return viol


# ---------------------------------------------------------------- search drivers
def _emps_for(tier: str, seed: int, factory: Callable) -> list[str]:
    from canary.baselines import employee_ids
    env = factory(tier, seed)
    return employee_ids({"ok": True, "data": env.call("list_employees", {}).data})


def fitness(m: dict) -> float:
    return 1000 * len(m["violations"]) + 10 * m["non_solver_score"] + m["score_per_call"]


def search(tier: str, seeds: list[int], budget: int, mode: str, rng_seed: int = 0,
           factory: Callable = _default_factory) -> tuple[list[dict], dict]:
    rng = random.Random(rng_seed)
    emps = {s: _emps_for(tier, s, factory) for s in seeds}
    findings: list[dict] = []
    best = {"non_solver_score": 0.0, "score_per_call": 0.0}
    pop: list[tuple[float, Genome, dict]] = []

    def run(g: Genome) -> dict:
        s = rng.choice(seeds)
        m = evaluate(g, tier, s, factory)
        best["non_solver_score"] = max(best["non_solver_score"], m["non_solver_score"])
        best["score_per_call"] = max(best["score_per_call"], m["score_per_call"])
        for v in m["violations"]:
            findings.append({**v, "seed": s, "mode": mode, "genome": _jsonable(g)[:4000]})
        return m

    for i in range(budget):
        s0 = seeds[i % len(seeds)]
        if mode == "malformed":
            g = [malform((t, valid_args(t, rng, emps[s0])), rng, emps[s0]) for t in rng.choices(TOOLS, k=30)]
        elif mode == "random" or len(pop) < 8:
            g = random_genome(rng, emps[s0])
        else:  # evolve: tournament + mutation/crossover
            a, b = (max(rng.sample(pop, 3), key=lambda x: x[0]) for _ in range(2))
            g = crossover(a[1], b[1], rng) if rng.random() < 0.3 else a[1]
            for _ in range(rng.randint(1, 3)):
                g = mutate(g, rng, emps[s0])
        m = run(g)
        if mode == "evolve":
            pop.append((fitness(m), g, m))
            pop = sorted(pop, key=lambda x: -x[0])[:32]
    for s in seeds[: min(len(seeds), 5)]:
        for v in parity_probe(tier, s, factory):
            findings.append({**v, "mode": "parity"})
    return findings, best


def parallel_accuse(tier: str, seeds: list[int], factory: Callable = _default_factory, n_threads: int = 8) -> list[dict]:
    """N threads accuse different ids on one env at once: exactly one accusation may be recorded."""
    import threading
    viol = []
    for s in seeds:
        env = factory(tier, s)
        from canary.baselines import employee_ids
        emps = employee_ids({"ok": True, "data": env.call("list_employees", {}).data})
        barrier = threading.Barrier(min(n_threads, len(emps)))
        oks: list[bool] = []

        def go(e):
            barrier.wait()
            try:
                oks.append(env.call("accuse", {"employee": e}).ok)
            except Exception as ex:
                viol.append({"kind": "exception", "seed": s, "tool": "accuse(parallel)", "error": repr(ex)})
        th = [threading.Thread(target=go, args=(e,)) for e in emps[: barrier.parties]]
        [t.start() for t in th]
        [t.join() for t in th]
        acc = _accusations(env.ledger(), set(emps))
        if sum(oks) != 1 or len(acc) != 1:
            viol.append({"kind": "parallel_accuse_race", "seed": s, "ok_count": sum(oks), "accusations": acc})
    return viol


def _worker(args) -> tuple[list[dict], dict]:
    tier, seeds, budget, mode, rng_seed = args
    return search(tier, seeds, budget, mode, rng_seed)


def hunt(tier: str = "easy", seeds: list[int] | range = range(0, 10), budget: int = 300, seed: int = 0,
         mode: str = "evolve", workers: int = 1, factory: Callable = _default_factory) -> dict:
    seeds = list(seeds)
    if mode == "all":
        per = {}
        for m in ("random", "malformed", "evolve", "parallel_accuse"):
            per[m] = hunt(tier, seeds, budget // 3, seed, m, workers, factory)
        allv = [v for r in per.values() for v in r["invariant_violations"]]
        return {"tier": tier, "seeds": [seeds[0], seeds[-1]], "budget": budget, "mode": "all",
                "best_non_solver_score": max(r["best_non_solver_score"] for r in per.values()),
                "best_score_per_call": max(r["best_score_per_call"] for r in per.values()),
                "invariant_violations": allv, "violation_kinds": sorted({v["kind"] for v in allv}),
                "per_mode": {m: {k: v for k, v in r.items() if k != "invariant_violations"}
                             | {"n_violations": len(r["invariant_violations"])} for m, r in per.items()}}
    if mode == "parallel_accuse":
        v = parallel_accuse(tier, seeds, factory)
        return {"tier": tier, "seeds": [seeds[0], seeds[-1]], "budget": 0, "mode": mode,
                "races": len(seeds), "threads_per_race": 8,  # budget unused: one N-thread race per seed
                "best_non_solver_score": 0.0, "best_score_per_call": 0.0, "invariant_violations": v,
                "violation_kinds": sorted({x["kind"] for x in v})}
    if workers > 1 and factory is _default_factory:
        chunks = [(tier, seeds, budget // workers, mode, seed * 1000 + k) for k in range(workers)]
        with ProcessPoolExecutor(workers) as ex:
            res = list(ex.map(_worker, chunks))
    else:
        res = [search(tier, seeds, budget, mode, seed, factory)]
    findings = [f for r in res for f in r[0]]
    return {"tier": tier, "seeds": [seeds[0], seeds[-1]], "budget": budget, "mode": mode,
            "best_non_solver_score": max(r[1]["non_solver_score"] for r in res),
            "best_score_per_call": max(r[1]["score_per_call"] for r in res),
            "invariant_violations": findings,
            "violation_kinds": sorted({f["kind"] for f in findings})}


def solver_mean(tier: str, seeds: list[int]) -> str:
    """Mean solver score if canary.solver exposes a Policy; 'n/a' otherwise."""
    try:
        from canary import solver as S
        from canary.baselines import play
        cls = getattr(S, "Solver", None) or getattr(S, "SolverPolicy")
        xs = [play(_default_factory(tier, s), cls()) for s in seeds]
        return f"{sum(xs) / len(xs):.3f}"
    except Exception:
        return "n/a"


def _parse_seeds(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", default="easy")
    ap.add_argument("--seeds", default="0-19")
    ap.add_argument("--budget", type=int, default=500)
    ap.add_argument("--mode", choices=["random", "evolve", "malformed", "parallel_accuse", "all"], default="evolve")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--rng", type=int, default=0)
    ap.add_argument("--out", default="data/runs")
    ap.add_argument("--report", action="store_true", help="print a short human table")
    ap.add_argument("--tiers-version", default=None, help="e.g. v1.5-candidate (rules.TIERS_HISTORY); in-process, workers=1")
    a = ap.parse_args(argv)
    if a.tiers_version:
        from .. import rules
        with rules.tiers_version(a.tiers_version):
            return _main(a)
    return _main(a)


def _main(a) -> int:
    t0 = time.time()
    res = hunt(a.tier, _parse_seeds(a.seeds), a.budget, a.rng, a.mode, a.workers)
    out = Path(a.out) / f"redteam-fuzz-{time.strftime('%Y%m%d-%H%M%S')}-{a.tier}-{a.mode}"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "findings.jsonl", "w") as f:
        for v in res["invariant_violations"]:
            f.write(_jsonable(v) + "\n")
    summary = {k: v for k, v in res.items() if k != "invariant_violations"}
    summary.update(n_findings=len(res["invariant_violations"]), seconds=round(time.time() - t0, 1))
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    if a.report:
        sm = solver_mean(a.tier, _parse_seeds(a.seeds))
        rows = res.get("per_mode") or {a.mode: {**summary, "n_violations": summary["n_findings"]}}
        for m, r in rows.items():
            print(f"[{m:15s}] best non-solver score found: {r['best_non_solver_score']:.3f} | "
                  f"solver mean: {sm} | invariant violations: {r['n_violations']}")
    else:
        print(json.dumps(summary, indent=2))
    print(f"-> {out}")
    return 1 if res["invariant_violations"] or res["best_non_solver_score"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
