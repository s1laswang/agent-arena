"""Failure analysis, rules v1.4 hard: OpenCode + gemini-4-carbon over MCP vs the reference solver, seeds 0-29.

    uv run python scripts/failure_analysis_v14.py            # writes the report + JSON (no API keys, ~1-2 min)
    uv run python scripts/failure_analysis_v14.py --check    # recompute and fail if the committed JSON differs

Every number in docs/reports/failure_analysis_v1.4.md is produced here, from the committed episodes only:
  data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl      (the judges' harness)
  data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl        (context row only)
  data/runs/committed/v1.4/reference/solver-hard-{20261114-121126,seeds20to29}/episodes.jsonl

Method (all deterministic):
  * Each episode is replayed in a fresh Env (the Env is deterministic in tier, seed and action sequence; the replay
    must reproduce the recorded score, else the script aborts). The replay gives the ground truth the agent never
    sees: the mole, every leak, the true V, and whether a leaked canary label was a fingerprint flip.
  * "Solver posterior" = canary.solver.SolverPolicy's exact Bayesian posterior over the agent's OWN observations
    (only the tool results the agent actually received), as in canary/analysis/accuse.py. It is evaluated at
    every end of day (just before advance_day) and at the accusation.
  * "Solver rule" = the solver's own accusation rule applied to that posterior: accuse the argmax when
    P(top) >= 0.85 and EV = P*E[true V] - (1-P) > 0, or on the last day when EV > 0.
  * Counterfactual "accuse at the first decisive moment": replay the agent's steps up to the first end of day where
    the solver rule fires on the agent's own evidence, then accuse the argmax. Exact score from the Env.
  * Luck-adjusted score = P*V - (1-P) at the accusation (scripts/paired_v13.py:post_expected), 0 if no accusation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary.env import Env  # noqa: E402
from canary.rules import tier_params_for_episode  # noqa: E402
from canary.solver.policy import SolverPolicy, accuse_value  # noqa: E402
from canary.types import Step  # noqa: E402

V14 = ROOT / "data/runs/committed/v1.4"
RUNS = {
    "opencode": [V14 / "opencode-gemini-4-carbon/hard/episodes.jsonl"],
    "inproc": [V14 / "inproc-gemini-4-carbon/hard/episodes.jsonl"],
    "solver": [V14 / "reference/solver-hard-20261114-121126/episodes.jsonl",
               V14 / "reference/solver-hard-seeds20to29/episodes.jsonl"],
}
# Causal hint test (gap.md, pre-registered): same harness + model with `--hint gather`; analysed on the seeds it
# completed (fixed order 0->29, stopped at 06:00), paired with the solver and the unhinted run on those seeds.
HINT_RUN = V14 / "opencode-gemini-4-carbon-hint-gather/hard/episodes.jsonl"
TIER = "hard"
SEEDS = list(range(30))
OUT_JSON = ROOT / "results/failure_analysis_v1.4.json"
OUT_MD = ROOT / "docs/reports/failure_analysis_v1.4.md"
EXAMPLE_SEEDS = (15, 4)  # annotated in the report (chosen after looking at the table: one wrong, one slow-correct)


# ----------------------------------------------------------------------------- loading + replay
def load(paths: list[Path]) -> dict[int, dict]:
    out = {}
    for f in paths:
        for line in f.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                if e["tier"] == TIER and (e.get("meta") or {}).get("valid") is not False:
                    out[e["seed"]] = e
    return out


def steps_of(e: dict) -> list[Step]:
    return [Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")}) for s in e.get("steps") or []]


def replay(seed: int, steps: list[Step], upto: int | None = None, accuse: str | None = None) -> Env:
    env = Env(TIER, seed)
    for s in steps[:upto] if upto is not None else steps:
        if env.done:
            break
        env.call(s.tool, s.args or {})
    if accuse is not None and not env.done:
        env.call("accuse", {"employee": accuse})
    return env


def ok(s: Step) -> bool:
    return bool((s.result or {}).get("ok"))


# ----------------------------------------------------------------------------- per-episode facts
def canary_facts(steps: list[Step], acc_idx: int | None) -> dict:
    cans = [s for s in steps if s.tool == "plant_canary" and ok(s)]
    before = [s for s in cans if acc_idx is None or s.t < steps[acc_idx].t]
    days = {s.day for s in cans}
    covered = set().union(*[set(s.args["assignment"]) for s in cans]) if cans else set()
    return {
        "n": len(before),
        "n_total": len(cans),
        "days_with_canary": len({s.day for s in before}),
        "two_on_a_day": sum(1 for d in days if sum(1 for s in cans if s.day == d) >= 2),
        "recipients_mean": (sum(len(s.args["assignment"]) for s in cans) / len(cans)) if cans else 0.0,
        "labels_mean": (sum(len(set(s.args["assignment"].values())) for s in cans) / len(cans)) if cans else 0.0,
        "staff_covered": len(covered),
        "first_day": min(days) if days else None,
        "failed_calls": sum(1 for s in steps if s.tool == "plant_canary" and not ok(s)),
    }


def assignments(steps: list[Step]) -> dict[str, dict[str, str]]:
    return {(s.result.get("data") or {}).get("canary_id"): dict(s.args["assignment"])
            for s in steps if s.tool == "plant_canary" and ok(s)}


def last_feed(steps: list[Step], upto: int) -> list[dict]:
    feed = []
    for s in steps[:upto]:
        if s.tool == "check_leak_feed" and ok(s):
            feed = list((s.result.get("data") or {}).get("items") or [])
    return feed


def canary_hits(steps: list[Step], upto: int, who: str) -> dict:
    """What the agent's own last leak-feed read said about `who` before step index `upto`."""
    asg = assignments(steps[:upto])
    hits, against, sizes = 0, 0, []
    for it in last_feed(steps, upto):
        a = asg.get(it.get("doc_id"))
        if not a or it.get("variant") is None:
            continue
        if a.get(who) == it["variant"]:
            hits += 1
            sizes.append(sum(1 for v in a.values() if v == it["variant"]))
        elif who in a:
            against += 1
    return {"hits": hits, "against": against, "hit_group_sizes": sizes}


def consistent_set(env: Env, steps: list[Step], upto: int) -> list[str]:
    """Employees consistent with EVERY leak in the agent's last feed read before `upto`, read strictly: held each
    leaked regular document (recipients are public via the free list_documents) and got the shown label of each
    leaked canary. Size 1 = the leaks alone isolate one person (up to the 5% fingerprint noise)."""
    asg = assignments(steps[:upto])
    docs = env._doc_by_id  # noqa: SLF001
    cand = set(env._ids)  # noqa: SLF001
    for it in last_feed(steps, upto):
        if it.get("variant") is not None and it["doc_id"] in asg:
            cand &= {e for e, lab in asg[it["doc_id"]].items() if lab == it["variant"]}
        elif it["doc_id"] in docs:
            cand &= set(docs[it["doc_id"]].get("recipients") or [])
    return sorted(cand)


def daily(steps: list[Step]) -> list[dict]:
    from canary.types import INVESTIGATIVE_TOOLS
    days: dict[int, dict] = {}
    for s in steps:
        d = days.setdefault(s.day, {"day": s.day, "actions": 0, "canaries": 0, "interviews": 0, "limit_hit": False})
        if s.tool in INVESTIGATIVE_TOOLS and ok(s):
            d["actions"] += 1
        if s.tool == "plant_canary" and ok(s):
            d["canaries"] += 1
        if s.tool == "interview" and ok(s):
            d["interviews"] += 1
        if "daily action limit" in str((s.result or {}).get("error") or ""):
            d["limit_hit"] = True
    return [days[k] for k in sorted(days)]


def feed_lag(steps: list[Step], upto: int | None) -> dict:
    """Days between a leak surfacing and the agent's first check_leak_feed that shows it (before `upto`)."""
    first: dict[str, int] = {}
    surf: dict[str, int] = {}
    for s in steps[:upto] if upto is not None else steps:
        if s.tool == "check_leak_feed" and ok(s):
            for it in (s.result.get("data") or {}).get("items") or []:
                surf[it["doc_id"]] = int(it["surfaced_day"])
                first.setdefault(it["doc_id"], s.day)
    lags = [first[k] - surf[k] for k in first]
    return {"seen": len(lags), "lag_sum": sum(lags), "lagged": sum(1 for x in lags if x > 0)}


def flips(env: Env) -> list[dict]:
    """Canary leaks whose shown label is NOT the mole's (hard: fingerprint_accuracy 0.95)."""
    out = []
    docs = env._doc_by_id  # noqa: SLF001
    for it in env._feed:  # noqa: SLF001 (offline ground truth)
        d = docs.get(it["doc_id"])
        if d and d.get("is_canary") and "variant" in it:
            true_v = next(k for k, v in d["variants"].items() if env._world.mole in v)  # noqa: SLF001
            if it["variant"] != true_v:
                out.append({"doc_id": it["doc_id"], "shown": it["variant"], "true": true_v,
                            "surfaced_day": it["surfaced_day"]})
    return out


def belief_trace(e: dict, steps: list[Step]) -> list[dict]:
    """Solver posterior over the agent's own observations at every end of day and at the accusation."""
    sp = SolverPolicy(tier_params_for_episode(TIER, steps))
    out, seen = [], 0
    n_days = sp.P.n_days
    for i, s in enumerate(steps):
        if s.tool not in ("advance_day", "accuse"):
            continue
        for prev in steps[seen:i]:
            sp._ingest(prev)  # noqa: SLF001
        seen = i
        if not sp.obs.employees:
            continue
        post = sp.belief()
        top = max(post, key=post.get)
        ev = accuse_value(post[top], sp.expected_true_V(), sp.P)
        last = s.day >= n_days
        row = {"idx": i, "t": s.t, "day": s.day, "kind": s.tool, "top": top, "p_top": post[top], "ev": ev,
               "fires": bool(ev > 0 and (post[top] >= 0.85 or last))}
        if s.tool == "accuse":
            acc = (s.args or {}).get("employee")
            row.update(accused=acc, p_accused=post.get(acc, 0.0),
                       ev_accused=accuse_value(post.get(acc, 0.0), sp.expected_true_V(), sp.P),
                       exp_true_V=sp.expected_true_V())
        out.append(row)
    return out


def episode(e: dict, with_trace: bool) -> dict:
    steps = steps_of(e)
    env = replay(e["seed"], steps)
    if abs(env.score() - e["score"]) > 1e-9 or env._accused != e.get("accused"):  # noqa: SLF001
        raise SystemExit(f"replay mismatch: {e['agent']} seed {e['seed']}: {env.score()} vs {e['score']}")
    acc_idx = next((i for i, s in enumerate(steps) if s.tool == "accuse" and ok(s)), None)
    led = env.ledger()
    t_acc = steps[acc_idx].t if acc_idx is not None else 10**9
    leaks = [x for x in led if x.event == "leak" and x.t <= t_acc]
    tools = {}
    for s in steps:
        tools[s.tool] = tools.get(s.tool, 0) + 1
    r = {
        "seed": e["seed"], "agent": e["agent"], "score": e["score"], "accused": e.get("accused"),
        "correct": bool(e.get("correct")), "mole": env._world.mole, "decoy": env._world.decoy,  # noqa: SLF001
        "end_reason": e["end_reason"], "final_day": e["final_day"],
        "accuse_day": steps[acc_idx].day if acc_idx is not None else None,
        "true_V_end": env.V, "leaks": len(leaks),
        "canary": canary_facts(steps, acc_idx), "tools": tools, "n_calls": len(steps),
        "invalid_calls": sum(1 for s in steps if not ok(s)),
        "flips": flips(env),
        "daily": daily(steps),
        "feed_lag": feed_lag(steps, acc_idx),
        "restrict_calls": tools.get("restrict_access", 0),
    }
    if acc_idx is not None:
        r["evidence_on_accused"] = canary_hits(steps, acc_idx, e["accused"])
        r["evidence_on_mole"] = canary_hits(steps, acc_idx, r["mole"])
        r["surfaced_canary_leaks_at_accusation"] = sum(
            1 for x in led if x.event == "leak_surfaced" and x.t <= t_acc and str(x.detail.get("doc_id", "")).startswith("c"))
        r["consistent_at_accusation"] = consistent_set(env, steps, acc_idx)
        r["seen_canary_leaks_at_accusation"] = sum(1 for it in last_feed(steps, acc_idx) if it.get("variant") is not None)
    if with_trace:
        tr = belief_trace(e, steps)
        for x in tr:
            x["n_consistent"] = len(consistent_set(env, steps, x["idx"]))
            x["top_is_mole"] = x["top"] == env._world.mole  # noqa: SLF001
        r["trace"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} for x in tr]
        acc = next((x for x in tr if x["kind"] == "accuse"), None)
        if acc:
            r["p_accused"], r["ev_accused"], r["p_top_at_accusation"] = acc["p_accused"], acc["ev_accused"], acc["p_top"]
            r["luck_adjusted"] = acc["p_accused"] * env.V - (1 - acc["p_accused"])
        else:
            r["p_accused"] = r["ev_accused"] = None
            r["luck_adjusted"] = 0.0
        fire = next((x for x in tr if x["fires"] and x["kind"] == "advance_day"), None)
        if fire and (acc_idx is None or fire["idx"] < acc_idx):
            cf = replay(e["seed"], steps, upto=fire["idx"], accuse=fire["top"])
            r["decisive"] = {"day": fire["day"], "top": fire["top"], "p_top": round(fire["p_top"], 4),
                             "top_is_mole": fire["top"] == r["mole"], "cf_score": cf.score(),
                             "days_early": (r["accuse_day"] or r["final_day"]) - fire["day"]}
        else:
            r["decisive"] = None
    return r


# ----------------------------------------------------------------------------- aggregates
def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def ci95(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return 1.96 * math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n)


def poisson_binomial_tail(ps: list[float], k: int) -> float:
    """P(at least k successes) for independent Bernoulli(p_i)."""
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for i, q in enumerate(dist):
            nxt[i] += q * (1 - p)
            nxt[i + 1] += q * p
        dist = nxt
    return sum(dist[k:])


def compute() -> dict:
    eps = {k: load(v) for k, v in RUNS.items()}
    for k in eps:
        missing = [s for s in SEEDS if s not in eps[k]]
        if missing:
            raise SystemExit(f"{k}: missing seeds {missing}")
    G = {s: episode(eps["opencode"][s], with_trace=True) for s in SEEDS}
    S = {s: episode(eps["solver"][s], with_trace=True) for s in SEEDS}
    I = {s: episode(eps["inproc"][s], with_trace=True) for s in SEEDS}
    data = {"G": G, "S": S, "I": I}
    if HINT_RUN.exists():
        h = load([HINT_RUN])
        data["H"] = {s: episode(h[s], with_trace=True) for s in sorted(h) if s in SEEDS}
    data["summary"] = summarize(data)
    if data.get("H"):
        mf = HINT_RUN.parent / "meta.json"
        exc = json.loads(mf.read_text()).get("infra_invalid_attempts_excluded", []) if mf.exists() else []
        per: dict[str, int] = {}
        reasons: dict[str, int] = {}
        for x in exc:   # "opencode-hard-<seed>-<HHMMSS>: <reason>"
            sd = x.split(":", 1)[0].split("-")[2]
            per[sd] = per.get(sd, 0) + 1
            r = "provider_quota" if "quota" in x else "empty_model_response" if "empty_model" in x else \
                "cli_error_event" if "cli_error" in x else "provider_unavailable" if "unavailable" in x else "other"
            reasons[r] = reasons.get(r, 0) + 1
        data["summary"]["hint"]["infra_invalid"] = {"total": len(exc), "per_seed": dict(sorted(per.items(), key=lambda kv: int(kv[0]))),
                                                    "by_reason": dict(sorted(reasons.items()))}
    return data


# ----------------------------------------------------------------------------- summary (every report number)
LEAK, CANARY = 0.05, 0.01  # hard tier leak_damage, canary_cost (canary/rules.py)


def acct(r: dict) -> dict | None:
    """Exact V accounting at the accusation: V = 1 - 0.05*leaks - 0.01*canaries - restrictions."""
    if not r["accused"]:
        return None
    V, L, C = r["true_V_end"], r["leaks"], r["canary"]["n"]
    p = r["p_accused"]
    pen = (1 - p) * (1 + V)
    return {"V": V, "L": L, "C": C, "R": 1 - V - LEAK * L - CANARY * C, "pen": pen, "la": V - pen,
            "raw": r["score"]}


def agent_summary(X: dict, seeds: list[int] = SEEDS) -> dict:
    eps = [X[str(s)] if str(s) in X else X[s] for s in seeds]
    acc = [r for r in eps if r["accused"]]
    wrong = [r for r in acc if not r["correct"]]
    played = [r["accuse_day"] or r["final_day"] for r in eps]
    can = [r["canary"]["n"] for r in eps]
    ps = [r["p_accused"] for r in acc]
    days = [d for r in eps for d in r["daily"]]
    hits = [r["evidence_on_accused"]["hits"] for r in acc]
    lag = [r["feed_lag"] for r in eps]
    return {
        "n": len(eps), "score": mean([r["score"] for r in eps]), "score_ci": ci95([r["score"] for r in eps]),
        "luck_adjusted": mean([r["luck_adjusted"] for r in eps]),
        "accused": len(acc), "wrong": len(wrong), "abstain": len(eps) - len(acc),
        "accuse_day": mean([r["accuse_day"] for r in acc]), "accuse_day_horizon21": mean(played),
        "canaries": mean(can), "canaries_ci": ci95(can),
        "canary_rate": sum(can) / sum(played), "capacity_used": sum(can) / (2 * sum(played)),
        "days_with_canary_share": sum(r["canary"]["days_with_canary"] for r in eps) / sum(played),
        "recipients_mean": mean([r["canary"]["recipients_mean"] for r in eps if r["canary"]["n_total"]]),
        "labels_mean": mean([r["canary"]["labels_mean"] for r in eps if r["canary"]["n_total"]]),
        "staff_covered": mean([r["canary"]["staff_covered"] for r in eps]),
        "first_canary_day": mean([r["canary"]["first_day"] for r in eps]),
        "interviews": mean([r["tools"].get("interview", 0) for r in eps]),
        "feed_reads": mean([r["tools"].get("check_leak_feed", 0) for r in eps]),
        "log_reads": mean([r["tools"].get("read_access_logs", 0) for r in eps]),
        "calls": mean([r["n_calls"] for r in eps]), "invalid_calls": mean([r["invalid_calls"] for r in eps]),
        "days": len(days), "days_lt2_canaries": sum(1 for d in days if d["canaries"] < 2),
        "days_lt2_full": sum(1 for d in days if d["canaries"] < 2 and d["actions"] >= 8),
        "interviews_on_lt2_full": sum(d["interviews"] for d in days if d["canaries"] < 2 and d["actions"] >= 8),
        "feed_lag_mean": sum(x["lag_sum"] for x in lag) / max(1, sum(x["seen"] for x in lag)),
        "feed_lagged_share": sum(x["lagged"] for x in lag) / max(1, sum(x["seen"] for x in lag)),
        "p_mean": mean(ps), "p_median": sorted(ps)[len(ps) // 2] if ps else None,
        "p_buckets": {"ge95": sum(p >= 0.95 for p in ps), "85_95": sum(0.85 <= p < 0.95 for p in ps),
                      "60_85": sum(0.6 <= p < 0.85 for p in ps), "lt60": sum(p < 0.6 for p in ps)},
        "ev_negative": [r["seed"] for r in acc if r["ev_accused"] < 0],
        "hits": {str(h): hits.count(h) for h in sorted(set(hits))},
        "isolated": sum(1 for r in acc if len(r["consistent_at_accusation"]) == 1),
        "not_isolated": [r["seed"] for r in acc if len(r["consistent_at_accusation"]) > 1],
        "expected_wrong": sum(1 - p for p in ps),
        "p_ge_observed_wrong": poisson_binomial_tail([1 - p for p in ps], len(wrong)),
        "leaks_at_accusation": mean([r["leaks"] for r in acc]),
        "single_hit_group_mean": mean([r["evidence_on_accused"]["hit_group_sizes"][0] for r in acc
                                       if r["evidence_on_accused"]["hits"] == 1]),
        "consistent_mean": mean([len(r["consistent_at_accusation"]) for r in acc]),
    }


def summarize(data: dict) -> dict:
    G, S = data["G"], data["S"]
    g = {s: G[s] for s in SEEDS}
    sv = {s: S[s] for s in SEEDS}
    out = {"opencode": agent_summary(g), "solver": agent_summary(sv), "inproc": agent_summary(data["I"])}
    if data.get("H"):
        out["hint"] = hint_summary(data["H"], g, sv)
    # exact additive decomposition of the luck-adjusted gap (solver - Gemini), summed over the 30 seeds
    comp = {"leak": 0.0, "canary": 0.0, "restrict": 0.0, "penalty": 0.0, "penalty_ev_negative": 0.0, "penalty_not_isolated": 0.0,
            "abstain": 0.0, "abstain_seeds": []}
    luck_g = luck_s = 0.0
    both_correct = []
    for s in SEEDS:
        a, b = acct(g[s]), acct(sv[s])
        luck_s += b["raw"] - b["la"]
        if a is None:
            comp["abstain"] += b["la"]
            comp["abstain_seeds"].append(s)
            continue
        luck_g += a["raw"] - a["la"]
        comp["leak"] += LEAK * (a["L"] - b["L"])
        comp["canary"] += CANARY * (a["C"] - b["C"])
        comp["restrict"] += a["R"] - b["R"]
        comp["penalty"] += a["pen"] - b["pen"]
        if g[s]["ev_accused"] < 0:
            comp["penalty_ev_negative"] += a["pen"] - b["pen"]
        if len(g[s]["consistent_at_accusation"]) > 1:
            comp["penalty_not_isolated"] += a["pen"] - b["pen"]
        if g[s]["correct"] and sv[s]["correct"]:
            both_correct.append(s)
    raw_gap = sum(sv[s]["score"] - g[s]["score"] for s in SEEDS)
    la_gap = sum(sv[s]["luck_adjusted"] - g[s]["luck_adjusted"] for s in SEEDS)
    comp.update(raw_gap=raw_gap, la_gap=la_gap, luck_gemini=luck_g, luck_solver=luck_s, luck=luck_s - luck_g)
    assert abs(la_gap - (comp["leak"] + comp["canary"] + comp["restrict"] + comp["penalty"] + comp["abstain"])) < 1e-9
    assert abs(raw_gap - la_gap - comp["luck"]) < 1e-9
    # raw gap by episode outcome (what a reader of the score table sees)
    wrong = [s for s in SEEDS if g[s]["accused"] and not g[s]["correct"]]
    comp["raw_by_outcome"] = {
        "wrong": sum(sv[s]["score"] - g[s]["score"] for s in wrong),
        "abstain": sum(sv[s]["score"] - g[s]["score"] for s in comp["abstain_seeds"]),
        "gemini_correct": sum(sv[s]["score"] - g[s]["score"] for s in SEEDS if g[s]["correct"]),
    }
    bc = both_correct
    comp["both_correct"] = {
        "n": len(bc), "gemini_score": mean([g[s]["score"] for s in bc]), "solver_score": mean([sv[s]["score"] for s in bc]),
        "gemini_day": mean([g[s]["accuse_day"] for s in bc]), "solver_day": mean([sv[s]["accuse_day"] for s in bc]),
        "gemini_leaks": mean([g[s]["leaks"] for s in bc]), "solver_leaks": mean([sv[s]["leaks"] for s in bc]),
        "gemini_canaries": mean([g[s]["canary"]["n"] for s in bc]), "solver_canaries": mean([sv[s]["canary"]["n"] for s in bc]),
        "gemini_later": sum(1 for s in bc if g[s]["accuse_day"] > sv[s]["accuse_day"]),
    }
    dec = [(s, g[s]["decisive"]) for s in SEEDS if g[s]["decisive"]]
    comp["hesitation"] = {"seeds": [s for s, _ in dec], "days_early": mean([d["days_early"] for _, d in dec]),
                          "gain": sum(d["cf_score"] - g[s]["score"] for s, d in dec),
                          "all_top_is_mole": all(d["top_is_mole"] for _, d in dec)}
    out["gap"] = comp
    out["wrong_detail"] = [{
        "seed": s, "day": g[s]["accuse_day"], "accused": g[s]["accused"], "mole": g[s]["mole"],
        "p": g[s]["p_accused"], "ev": g[s]["ev_accused"], "V": g[s]["true_V_end"],
        "flip": bool(g[s]["flips"]) and any(f["surfaced_day"] <= g[s]["accuse_day"] for f in g[s]["flips"]),
        "consistent": g[s]["consistent_at_accusation"],
        "mole_in_consistent": g[s]["mole"] in g[s]["consistent_at_accusation"],
        "solver_score": sv[s]["score"], "solver_correct": sv[s]["correct"], "solver_flip": bool(sv[s]["flips"]),
        "days_left": 21 - g[s]["accuse_day"],
    } for s in wrong]
    return out


def boot_ratio(f: list[float], s: list[float], B: int = 10000, rng_seed: int = 0) -> list[float]:
    """Paired bootstrap 95% CI of mean(f)/mean(s) over seeds (same method as scripts/paired_v13.py)."""
    rng = random.Random(rng_seed)
    n, vals = len(f), []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        ms = sum(s[i] for i in idx) / n
        if ms > 0:
            vals.append(sum(f[i] for i in idx) / n / ms)
    vals.sort()
    return [vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]]


def hint_summary(H: dict, G: dict, S: dict) -> dict:
    """Hinted Gemini vs the solver and vs the unhinted Gemini run, on the seeds the hinted run completed."""
    seeds = sorted(H)
    arms = {"hint": agent_summary(H, seeds), "unhinted": agent_summary(G, seeds), "solver": agent_summary(S, seeds)}
    X = {"hint": H, "unhinted": G, "solver": S}
    out: dict = {"seeds": seeds, "n": len(seeds)}
    for k, a in arms.items():
        acc = a["accused"]
        out[k] = {key: a[key] for key in ("score", "score_ci", "luck_adjusted", "accused", "wrong", "abstain",
                                          "accuse_day_horizon21", "canaries", "canaries_ci", "capacity_used",
                                          "days_with_canary_share", "first_canary_day", "interviews", "isolated",
                                          "not_isolated", "ev_negative", "expected_wrong", "leaks_at_accusation")}
        out[k]["premature_rate"] = len(a["not_isolated"]) / acc if acc else None
        if k != "solver":
            f = [X[k][s]["score"] for s in seeds]
            fl = [X[k][s]["luck_adjusted"] for s in seeds]
            sr = [S[s]["score"] for s in seeds]
            sl = [S[s]["luck_adjusted"] for s in seeds]
            out[k]["pct_solver"] = mean(f) / mean(sr)
            out[k]["pct_solver_ci"] = boot_ratio(f, sr)
            out[k]["la_pct_solver"] = mean(fl) / mean(sl)
            out[k]["la_pct_solver_ci"] = boot_ratio(fl, sl)
    for key, fn in (("score", lambda r: r["score"]), ("luck_adjusted", lambda r: r["luck_adjusted"]),
                    ("canaries", lambda r: r["canary"]["n"]),
                    ("accuse_day", lambda r: r["accuse_day"] or r["final_day"])):
        d = [fn(H[s]) - fn(G[s]) for s in seeds]
        out[f"diff_{key}"] = {"mean": mean(d), "ci": ci95(d)}
    out["per_seed"] = [{"seed": s, "hint": H[s]["score"], "unhinted": G[s]["score"], "solver": S[s]["score"],
                        "hint_canaries": H[s]["canary"]["n"], "unhinted_canaries": G[s]["canary"]["n"],
                        "hint_consistent": len(H[s].get("consistent_at_accusation") or []) if H[s]["accused"] else None,
                        "hint_correct": H[s]["correct"], "hint_accused": bool(H[s]["accused"]),
                        "hint_day": H[s]["accuse_day"] or H[s]["final_day"]} for s in seeds]
    return out


def approx_equal(a, b, tol: float = 1e-9) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args(argv)
    data = compute()
    blob = json.dumps(data, indent=1, sort_keys=True, default=str)
    if a.check:
        from failure_analysis_v14_report import render  # noqa: E402
        old = OUT_JSON.read_text() if OUT_JSON.exists() else ""
        fresh = json.loads(blob)
        if not approx_equal(json.loads(old or "{}"), fresh):
            print("results/failure_analysis_v1.4.json differs from a fresh run")
            return 1
        if (OUT_MD.read_text() if OUT_MD.exists() else "") != render(fresh):
            print("docs/reports/failure_analysis_v1.4.md differs from a fresh render")
            return 1
        print("failure analysis reproduces")
        return 0
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(blob + "\n")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    if not a.json_only:
        from failure_analysis_v14_report import render  # noqa: E402
        OUT_MD.write_text(render(data))
        print(f"wrote {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
