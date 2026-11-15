"""Failure gallery: every lost point, accounted for exactly.

For each episode with a reference-solver run on the same seed and rules version:

    gap = solver_score - agent_score

is decomposed onto the agent's own steps by replaying its exact action sequence in the environment (the replay
reproduces every recorded tool result and the recorded score; fidelity is checked per episode) and doing the same
for the solver's episode. Components (all computed in code, they sum to the gap exactly, a test checks it):

  outcome (the accusation step or the end of the episode)
    wrong_accusation_evidence_backed   wrong accusee, but the solver's own posterior backed it (>= 0.5): luck
    wrong_accusation_decoy             wrong accusee who was the decoy (the loud innocent)
    wrong_accusation_premature         wrong accusee with solver posterior < 0.5
    no_accusation                      ended without accusing: the agent's remaining V was forgone
    infra_error_no_accusation          the run crashed (end_reason=error): infrastructure, not an agent decision
  value spent (agent's true-V drops minus the solver's, by cause)
    slow_commit_leak_damage            leak damage on days after the solver had already accused (advance_day steps)
    leak_timing_variance               the rest of the leak-damage difference (which days leaks happened): luck, +/-
    early_commit_credit                (negative) leak damage the solver took on days after the agent had stopped
    excess_canary_spend                canary cost above the solver's, spread over the agent's canary steps in
                                       proportion to their solver regret (uninformative splits carry it)
    fewer_canaries_credit              (negative) the agent spent less on canaries than the solver
    restriction_cost                   restriction cost above the solver's, on the restrict_access steps that caused it
  solver side
    solver_wrong_on_seed               (negative) the solver itself accused wrongly on this seed
    solver_no_accusation               (negative) the solver did not accuse on this seed

Gemini then names each failure mode, explains it and quotes the agent verbatim (quotes checked in code); the
numbers never come from Gemini.

    python -m canary.gemini.gallery [--runs ...] [--replay] -> results/gemini/failure_gallery.json,
                                                              docs/reports/failure_gallery.md
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .atlas_data import ROOT, Episode, excerpt, find_run_dirs, infer_version, load_corpus, save_snapshot, \
    load_snapshot, step_line
from .atlas_gemini import AtlasOps, ReplayMiss
from .atlas_schema import Verifier, inline_schema, parse

OUT_JSON = ROOT / "results" / "gemini" / "failure_gallery.json"
OUT_MD = ROOT / "docs" / "reports" / "failure_gallery.md"
CACHE = ROOT / "results" / "gemini" / "gallery_cache"
CHARTS = ROOT / "results" / "gemini" / "gallery_charts"
DEFAULT_RUNS = ["data/runs/committed", "data/gemini/scratch/runs/v1.4-gemini",
                str(Path.home() / "agent-arena-data" / "gemini" / "ladder" / "ladder-v14")]
EPS = 1e-9

CATEGORIES = {
    "wrong_accusation_premature": ("Wrong accusation on weak evidence", "outcome"),
    "wrong_accusation_decoy": ("Accused the decoy", "outcome"),
    "wrong_accusation_evidence_backed": ("Wrong accusation the evidence backed (luck)", "luck"),
    "no_accusation": ("Never accused", "outcome"),
    "infra_error_no_accusation": ("Harness/infrastructure error ended the episode", "infrastructure"),
    "slow_commit_leak_damage": ("Kept investigating after the solver would have accused", "timing"),
    "leak_timing_variance": ("Leak timing variance (luck)", "luck"),
    "early_commit_credit": ("Committed earlier than the solver (credit)", "credit"),
    "excess_canary_spend": ("Canary spend above the solver's", "canary"),
    "fewer_canaries_credit": ("Fewer canaries than the solver (credit)", "credit"),
    "restriction_cost": ("Restriction cost", "restriction"),
    "solver_wrong_on_seed": ("The solver itself was wrong on this seed", "luck"),
    "solver_no_accusation": ("The solver did not accuse on this seed", "luck"),
}


# ------------------------------------------------------------------------------------------- env replay

@contextlib.contextmanager
def rules_version(version: str):
    """Env under the rules an episode was played with (v1.2 = v1.3 params with true V shown in status)."""
    from canary import rules
    old = rules.KNOWN_V_MODE
    cm = rules.tiers_version("v1.3") if version in ("v1.3", "v1.2") else contextlib.nullcontext()
    with cm:
        rules.KNOWN_V_MODE = version != "v1.2"
        try:
            yield
        finally:
            rules.KNOWN_V_MODE = old


def same_result(rec: Any, rep: dict) -> bool:
    """Recorded vs replayed tool result. MCP-imported runs (OpenCode) store a failed call's error as the JSON of the
    whole result; that is the same result."""
    if rec == rep:
        return True
    if isinstance(rec, dict) and rec.get("ok") is False and rep.get("ok") is False:
        if (rec.get("error") == rep.get("error") and not rec.get("data")
                and set(rep.get("data") or {}) == {"detail"}):
            return True   # recorded before error details existed (15 Nov): same error, no detail field
        err = rec.get("error")
        try:
            inner = json.loads(err) if isinstance(err, str) and err.startswith("{") else None
        except json.JSONDecodeError:
            inner = None
        if isinstance(inner, dict):
            return inner.get("error") == rep.get("error")
    return False


def harness_artifact(rec: Any) -> bool:
    """A recorded result the harness produced instead of the env's (OpenCode truncated a long output to a 'raw'
    note; a non-Canary tool such as bash was rejected by the harness). The env state is unaffected."""
    if not isinstance(rec, dict):
        return False
    if "raw" in rec and "ok" not in rec:
        return True
    return rec.get("ok") is False and "unavailable tool" in str(rec.get("error", ""))


def replay_accounting(ep_dict: dict, version: str) -> dict:
    """Replay the recorded actions; per step the true-V drop split by cause. Fidelity = every replayed result
    equals the recorded one and the replayed score equals the recorded score."""
    from canary.env import Env
    with rules_version(version):
        env = Env(ep_dict["tier"], int(ep_dict["seed"]))
        p = env.p
        rows, mism, artifacts = [], 0, 0
        restricted_by: dict[str, int] = {}  # employee -> t of the restrict step currently in force
        for k, s in enumerate(ep_dict.get("steps") or []):
            v0, led0 = env.V, len(env.ledger())
            restricted_before = dict(restricted_by)
            r = env.call(s.get("tool"), s.get("args") or {})
            if not same_result(s.get("result"), asdict(r)):
                if harness_artifact(s.get("result")):
                    artifacts += 1
                else:
                    mism += 1
            drop = v0 - env.V
            leak = sum(1 for le in env.ledger()[led0:] if le.event == "leak")
            row = {"t": s.get("t", k), "day": s.get("day"), "tool": s.get("tool"), "drop": drop,
                   "leak": 0.0, "canary": 0.0, "restrict": {}, "V_after": env.V}
            if s.get("tool") == "plant_canary" and r.ok:
                row["canary"] = drop
            elif s.get("tool") == "advance_day" and r.ok:
                want_leak = leak * p.leak_damage
                want_res = p.restrict_cost_per_day * len(restricted_before)
                tot = want_leak + want_res
                scale = drop / tot if tot > 0 else 0.0  # V is floored at 0: scale both causes the same way
                row["leak"] = want_leak * scale
                for e, t_r in restricted_before.items():
                    row["restrict"][t_r] = row["restrict"].get(t_r, 0.0) + p.restrict_cost_per_day * scale
            elif drop > 0:
                row["other"] = drop
            if s.get("tool") == "restrict_access" and r.ok:
                restricted_by[(s.get("args") or {}).get("employee")] = s.get("t", k)
            if s.get("tool") == "unrestrict_access" and r.ok:
                restricted_by.pop((s.get("args") or {}).get("employee"), None)
            rows.append(row)
        score = env.score()
        decoy = getattr(env._world, "decoy", None)
        mole = env._world.mole
    return {"rows": rows, "score": score, "V_end": env.V, "mismatched_results": mism, "harness_artifacts": artifacts,
            "faithful": mism == 0 and abs(score - float(ep_dict.get("score", 0.0))) < 1e-9,
            "final_day": env.day, "decoy": decoy, "mole": mole,
            "accused": env._accused, "correct": bool(env._correct)}


def solver_episodes(paths: list[str | Path]) -> dict[tuple[str, str, int], dict]:
    out: dict[tuple[str, str, int], dict] = {}
    for d in find_run_dirs(paths):
        if not d.name.startswith("solver-"):
            continue
        meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
        v = infer_version(str(d), meta)
        for line in (d / "episodes.jsonl").read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                out.setdefault((v, e["tier"], int(e["seed"])), e)
    return out


def run_solver(version: str, tier: str, seed: int) -> dict | None:
    """Fallback when no committed reference run covers the seed: play the solver now (keyless, seconds)."""
    try:
        from canary.eval import make_env, make_policy_factory, run_episode
        with rules_version(version):
            res = run_episode(make_env(tier, seed), make_policy_factory("solver")(seed))
        return {"tier": tier, "seed": seed, "agent": "solver", "score": res.score, "accused": res.accused,
                "correct": res.correct, "final_day": res.final_day, "end_reason": res.end_reason,
                "steps": [asdict(s) for s in res.steps]}
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------------------------- decomposition

def _spread(total: float, weights: dict[int, float]) -> dict[int, float]:
    """Split `total` over keys in proportion to weights (equal if all zero); exact sum."""
    if not weights:
        return {}
    keys = sorted(weights)
    ws = [max(0.0, weights[k]) for k in keys]
    if sum(ws) <= 0:
        ws = [1.0] * len(keys)
    s = sum(ws)
    parts = {k: total * w / s for k, w in zip(keys, ws)}
    drift = total - sum(parts.values())
    parts[keys[-1]] += drift
    return parts


def decompose(ep: Episode, agent_acc: dict, solver_acc: dict, solver_ep: dict) -> dict:
    """Exact decomposition of gap = solver_score - agent_score into (category, t, value) items."""
    s_a, s_s = float(agent_acc["score"]), float(solver_acc["score"])
    gap = s_s - s_a
    items: list[dict] = []

    def add(cat: str, value: float, t: int | None = None, note: str = ""):
        if abs(value) > EPS:
            items.append({"category": cat, "t": t, "value": value, "note": note})

    v_a = float(agent_acc["V_end"])
    steps_by_t = {s.t: s for s in ep.steps}
    acc_steps = [s for s in ep.steps if s.tool == "accuse"]
    acc_t = acc_steps[-1].t if acc_steps else None
    # 1. outcome: V the agent had at the end vs what it scored
    if agent_acc["accused"] is not None and not agent_acc["correct"]:
        s = steps_by_t.get(acc_t)
        p = s.p_accusee if s is not None and s.p_accusee is not None else 0.0
        if p >= 0.5:
            cat, note = "wrong_accusation_evidence_backed", f"solver P(accused)={p:.2f} at the accusation"
        elif agent_acc.get("decoy") and agent_acc["accused"] == agent_acc["decoy"]:
            cat, note = "wrong_accusation_decoy", f"accused the decoy; solver P(accused)={p:.2f}"
        else:
            cat, note = "wrong_accusation_premature", f"solver P(accused)={p:.2f}, top={s.top if s else '?'}"
        add(cat, v_a - s_a, acc_t, note)
    elif agent_acc["accused"] is None:
        if ep.end_reason == "error":  # the run crashed (harness/provider), not an agent decision
            add("infra_error_no_accusation", v_a - s_a, len(ep.steps), f"end_reason=error after {len(ep.steps)} steps")
        else:
            add("no_accusation", v_a - s_a, len(ep.steps), f"end={ep.end_reason}; remaining V {v_a:.3f} forgone")
    # 2. solver side: what the solver scored vs the V it kept
    v_s = float(solver_acc["V_end"])
    if solver_acc["accused"] is not None and not solver_acc["correct"]:
        add("solver_wrong_on_seed", s_s - v_s, None, "the reference solver accused an innocent on this seed")
    elif solver_acc["accused"] is None:
        add("solver_no_accusation", s_s - v_s, None, "the reference solver did not accuse")
    # 3. value spent: (1 - v_s) vs (1 - v_a) by cause
    ra, rs = agent_acc["rows"], solver_acc["rows"]
    leak_a = sum(r["leak"] for r in ra)
    leak_s = sum(r["leak"] for r in rs)
    can_a = sum(r["canary"] for r in ra)
    can_s = sum(r["canary"] for r in rs)
    res_a: dict[int, float] = defaultdict(float)
    for r in ra:
        for t, c in r["restrict"].items():
            res_a[int(t)] += c
    res_s = sum(sum(r["restrict"].values()) for r in rs)
    other_a = sum(r.get("other", 0.0) for r in ra)
    other_s = sum(r.get("other", 0.0) for r in rs)
    s_day = int(solver_acc["final_day"])
    a_day = int(agent_acc["final_day"])
    # leak: slow commit = agent leak damage on days after the solver's last day
    slow = {r["t"]: r["leak"] for r in ra if r["tool"] == "advance_day" and (r["day"] or 0) >= s_day and r["leak"] > 0}
    for t, v in slow.items():
        add("slow_commit_leak_damage", v, t, f"leak while the solver had already accused (solver ended day {s_day})")
    early = sum(r["leak"] for r in rs if r["tool"] == "advance_day" and (r["day"] or 0) >= a_day)
    if early > 0:
        add("early_commit_credit", -early, None, f"solver leak damage after the agent's last day {a_day}")
    add("leak_timing_variance", (leak_a - leak_s) - sum(slow.values()) + early, None,
        "which days the mole leaked (shared days)")
    # canary
    d_can = can_a - can_s
    if d_can > 0:
        w = {s.t: s.regret for s in ep.steps if s.tool == "plant_canary" and s.ok}
        cost_t = {r["t"] for r in ra if r["canary"] > 0}
        w = {t: v for t, v in w.items() if t in cost_t} or {t: 1.0 for t in cost_t}
        for t, v in _spread(d_can, w).items():
            add("excess_canary_spend", v, t, "canary cost above the solver's, weighted by this split's solver regret")
    elif d_can < 0:
        add("fewer_canaries_credit", d_can, None, "the agent spent less on canaries than the solver")
    # restriction (+ any other true-V drops, which the env does not currently produce)
    d_res = sum(res_a.values()) - res_s
    if d_res > 0:
        for t, v in _spread(d_res, dict(res_a)).items():
            add("restriction_cost", v, t, "days this restriction was in force")
    elif d_res < 0:
        add("restriction_cost", d_res, None, "the solver spent more on restrictions")
    add("restriction_cost", other_a - other_s, None, "other true-V drops") if abs(other_a - other_s) > EPS else None
    total = sum(i["value"] for i in items)
    return {"gap": gap, "items": items, "sum": total, "residual": gap - total}


# ------------------------------------------------------------------------------------------- Gemini naming

class GalleryMode(BaseModel):
    category: str
    name: str = Field(description="<= 7 words, a failure mode name a judge understands")
    explanation: str = Field(description="2-3 sentences: what the agent does at these steps and why it loses value")
    quotes: list[dict] = Field(default_factory=list)


class _Quote(BaseModel):
    episode: str
    t: int
    quote: str = Field(description="5-30 words VERBATIM from the excerpt of that step (the agent's words if any)")


class _Card(BaseModel):
    name: str
    explanation: str
    quotes: list[_Quote]


def name_modes(cards: dict[str, list[tuple[Episode, int, float]]], ops: AtlasOps, verifier: Verifier, model: str,
               errors: list[str]) -> dict[str, dict]:
    from concurrent.futures import ThreadPoolExecutor

    def one(cat):
        ex = cards[cat][:6]
        text = "\n\n".join(excerpt(ep, t, before=5, after=1, rationale_chars=600) for ep, t, _ in ex if t is not None)
        if not text.strip():
            return cat, None
        q = ("You are naming one failure mode of LLM agents in Canary (a mole hunt with canary traps; a Bayesian "
             "reference solver replays every step). The value lost in this mode was computed by a program as: "
             f"'{CATEGORIES[cat][0]}'. Below are the steps (marked >>>) that carry the most of it. Name the mode, "
             "explain in 2-3 sentences what the agents do and why it costs value, and give one verbatim quote "
             "(5-30 words, prefer the agent's own `says:` words) per excerpt.\n\n" + text)
        try:
            r = ops.generate(model, [q], schema=inline_schema(_Card), tag=f"gallery:{cat}")
        except ReplayMiss as e:
            errors.append(f"gallery:{cat}: replay miss {e}")
            return cat, None
        except Exception as e:  # noqa: BLE001
            errors.append(f"gallery:{cat}: {type(e).__name__}: {str(e)[:150]}")
            return cat, None
        c, err = parse(r.get("text", ""), _Card)
        if c is None:
            errors.append(f"gallery:{cat}: {err}")
        return cat, c
    with ThreadPoolExecutor(max_workers=6) as pool:
        res = dict(pool.map(one, [c for c in cards if cards[c]]))
    out = {}
    for cat, c in res.items():
        if c is None:
            continue
        qs = [verifier.check(q.episode, q.t, q.quote, context=f"gallery:{cat}") for q in c.quotes]
        out[cat] = {"name": c.name, "explanation": c.explanation, "quotes": [q for q in qs if q["verified"]]}
    return out


# ------------------------------------------------------------------------------------------- build

def build(runs: list[str], replay: bool = False, model: str = "gemini-3.8-flash", charts: bool = True,
          log=print) -> dict:
    t0 = time.time()
    CACHE.mkdir(parents=True, exist_ok=True)
    snap = CACHE / "gallery_corpus.json.gz"
    if replay and snap.exists():
        payload = json.loads(gzip.decompress(snap.read_bytes()))
        eps = load_snapshot(CACHE / "episodes.json.gz")
        acc, sol = payload["agent"], payload["solver"]
    else:
        paths = [str(ROOT / r) if not Path(r).is_absolute() else r for r in runs]
        paths = [p for p in paths if Path(p).exists()]
        eps = load_corpus(paths)
        raw = {}
        for d in find_run_dirs(paths):
            if "reference" in d.parts:
                continue
            for line in (d / "episodes.jsonl").read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    raw.setdefault(str(d), []).append(e)
        by_run = defaultdict(list)
        for ep in eps:
            by_run[ep.run].append(ep)
        refs = solver_episodes(paths)
        acc, sol = {}, {}
        for run, lst in by_run.items():
            rs = raw.get(run, [])
            for ep in lst:
                e = next((x for x in rs if int(x["seed"]) == ep.seed and x["tier"] == ep.tier), None)
                if e is None:
                    continue
                key = (ep.tiers_version, ep.tier, ep.seed)
                if ep.seed >= 900_000:
                    acc[ep.id] = {"skip": "judge seed: world secret not available, no replay or solver baseline"}
                    continue
                a = replay_accounting(e, ep.tiers_version)
                if not a["faithful"]:
                    acc[ep.id] = {"skip": f"replay not faithful ({a['mismatched_results']} results differ)"}
                    continue
                from canary.analysis.accuse import audit_episode
                from canary.analysis.tags import to_result
                au = audit_episode(to_result(e))  # canary.analysis.accuse: posterior at the accusation, verdict
                a["accuse_audit"] = {k: au.get(k) for k in ("day", "p_accused", "p_top", "verdict")}
                acc[ep.id] = a
                sk = "|".join(map(str, key))
                if sk not in sol:
                    se = refs.get(key) or run_solver(*key)
                    sol[sk] = {"episode": se, "acc": replay_accounting(se, ep.tiers_version) if se else None}
        save_snapshot(eps, CACHE / "episodes.json.gz")
        snap.write_bytes(gzip.compress(json.dumps({"agent": acc, "solver": sol}, separators=(",", ":"),
                                                  default=str).encode(), mtime=0))
    # decomposition (pure code)
    rows, skipped = [], []
    for ep in eps:
        a = acc.get(ep.id)
        if a is None:
            continue
        if "skip" in a:
            skipped.append({"episode": ep.id, "cohort": ep.cohort, "reason": a["skip"]})
            continue
        s = sol.get(f"{ep.tiers_version}|{ep.tier}|{ep.seed}")
        if not s or not s.get("acc"):
            skipped.append({"episode": ep.id, "cohort": ep.cohort, "reason": "no solver episode for this seed"})
            continue
        d = decompose(ep, a, s["acc"], s["episode"])
        rows.append({"episode": ep.id, "cohort": ep.cohort, "family": ep.family, "model": ep.model,
                     "thinking": ep.thinking_level, "harness": ep.harness, "tiers_version": ep.tiers_version,
                     "tier": ep.tier, "seed": ep.seed, "agent_score": a["score"], "solver_score": s["acc"]["score"],
                     "accuse_audit": a.get("accuse_audit"), "harness_artifacts": a.get("harness_artifacts", 0),
                     **d})
    # aggregate
    total_gap = sum(r["gap"] for r in rows)
    lost = sum(r["gap"] for r in rows if r["gap"] > 0)
    by_cat: dict[str, dict] = {}
    for r in rows:
        for it in r["items"]:
            c = by_cat.setdefault(it["category"], {"value": 0.0, "episodes": set(), "steps": 0, "cohorts": Counter(),
                                                   "versions": Counter()})
            c["value"] += it["value"]
            c["versions"][r["tiers_version"]] += it["value"]
            c["episodes"].add(r["episode"])
            c["steps"] += it["t"] is not None
            c["cohorts"][r["cohort"]] += it["value"]
    by_ep = {e.id: e for e in eps}
    cards_in: dict[str, list[tuple[Episode, int, float]]] = defaultdict(list)
    for r in rows:
        for it in r["items"]:
            if it["t"] is not None and it["value"] > 0:
                cards_in[it["category"]].append((by_ep[r["episode"]], it["t"], it["value"]))
    for c in cards_in:  # strongest example per episode, spread over cohorts
        seen, best = set(), []
        for ep, t, v in sorted(cards_in[c], key=lambda x: -x[2]):
            if ep.id in seen:
                continue
            seen.add(ep.id)
            best.append((ep, t, v))
        cards_in[c] = best
    ops = AtlasOps(replay=replay, cache_dir=CACHE)
    errors: list[str] = []
    from .atlas_data import pack_corpus
    _, blocks = pack_corpus(eps)
    verifier = Verifier(eps, blocks)
    named = name_modes(cards_in, ops, verifier, model, errors)
    # cards
    cards = []
    CHARTS.mkdir(parents=True, exist_ok=True)
    for cat, c in sorted(by_cat.items(), key=lambda kv: -kv[1]["value"]):
        ex = cards_in.get(cat, [])[:3]
        examples = []
        for ep, t, v in ex:
            s = next((x for x in ep.steps if x.t == t), None)
            examples.append({"episode": ep.id, "t": t, "value": round(v, 4), "day": s.day if s else None,
                             "tool": s.tool if s else None, "step": step_line(s) if s else "",
                             "top_suspect": s.top if s else None, "p_top": s.p_top if s else None,
                             "p_true_mole": s.p_mole if s else None, "p_accused": s.p_accusee if s else None})
        chart = None
        if charts and ex:
            from .atlas_charts import render_belief_chart
            ep0 = ex[0][0]
            fn = f"{cat}.png"
            render_belief_chart(ep0, CHARTS / fn, dpi=70)
            chart = f"../../results/gemini/gallery_charts/{fn}"
        nm = named.get(cat, {})
        cards.append({"category": cat, "code_name": CATEGORIES[cat][0], "kind": CATEGORIES[cat][1],
                      "name": nm.get("name") or CATEGORIES[cat][0], "explanation": nm.get("explanation", ""),
                      "value": round(c["value"], 4), "share_of_net_gap": round(c["value"] / total_gap, 4) if total_gap else None,
                      "episodes": len(c["episodes"]), "steps": c["steps"],
                      "by_cohort": {k: round(v, 4) for k, v in c["cohorts"].most_common()},
                      "by_version": {k: round(v, 4) for k, v in sorted(c["versions"].items())},
                      "examples": examples, "quotes": nm.get("quotes", []), "chart": chart})
    max_resid = max((abs(r["residual"]) for r in rows), default=0.0)
    cohorts = defaultdict(lambda: {"episodes": 0, "gap": 0.0, "agent": 0.0, "solver": 0.0, "by_cat": Counter(),
                                   "verdicts": Counter()})
    for r in rows:
        c = cohorts[r["cohort"]]
        c["episodes"] += 1
        c["gap"] += r["gap"]
        c["agent"] += r["agent_score"]
        c["solver"] += r["solver_score"]
        c["verdicts"][(r.get("accuse_audit") or {}).get("verdict") or "none"] += 1
        for it in r["items"]:
            c["by_cat"][it["category"]] += it["value"]
    from .atlas import git_sha
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": git_sha(),
        "ledger_run_ids": sorted(ops.source_run_ids),
        "episodes_decomposed": len(rows), "episodes_skipped": skipped,
        "net_gap": round(total_gap, 6), "lost_value": round(lost, 6),
        "by_version": {v: {"episodes": sum(1 for r in rows if r["tiers_version"] == v),
                           "net_gap": round(sum(r["gap"] for r in rows if r["tiers_version"] == v), 4)}
                       for v in sorted({r["tiers_version"] for r in rows})},
        "tagged": round(sum(c["value"] for c in by_cat.values()), 6),
        "unexplained": round(total_gap - sum(c["value"] for c in by_cat.values()), 9),
        "max_episode_residual": max_resid,
        "replay_fidelity": ("every decomposed episode replays to identical tool results and score, except "
                            f"{sum(a.get('harness_artifacts', 0) for a in acc.values() if 'skip' not in a)} results "
                            "the harness itself produced (OpenCode output truncation, rejected non-Canary tools)"),
        "cards": cards,
        "cohorts": {k: {"episodes": v["episodes"], "mean_gap": round(v["gap"] / v["episodes"], 4),
                        "mean_agent": round(v["agent"] / v["episodes"], 4),
                        "mean_solver": round(v["solver"] / v["episodes"], 4),
                        "accusation_verdicts": dict(v["verdicts"]),
                        "by_category_mean": {c: round(x / v["episodes"], 4) for c, x in v["by_cat"].most_common()}}
                    for k, v in sorted(cohorts.items())},
        "episodes": rows,
        "verification": verifier.summary(),
        "errors": errors, "model": model, "replay": replay,
        "spend": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ops.stats.items()},
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=1, default=str))
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render(result))
    log(f"gallery: {len(rows)} episodes, net gap {total_gap:.3f}, unexplained {result['unexplained']:.2e}, "
        f"{len(cards)} cards, quotes {verifier.summary()}, {len(skipped)} skipped -> {OUT_JSON}, {OUT_MD}")
    return result


def _pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def render(r: dict) -> str:
    out = ["# Failure gallery: where every lost point went", "",
           f"*Generated {r['generated_at']} at `{r['git_sha']}` by `python -m canary.gemini.gallery`. "
           f"Numbers are computed in code; Gemini (`{r['model']}`) only names the modes, explains them and quotes the "
           "agents (quotes checked verbatim).*", "",
           "## How the accounting works", "",
           "For every agent episode that has a reference-solver episode on the same seed and rules version, the "
           "**gap = solver score - agent score** is split onto the agent's own steps. We replay the agent's exact "
           "actions in the environment (every replayed tool result and the final score match the recording), and the "
           "solver's, and read off where true company value went: leak damage per day, canary cost, restriction cost, "
           "and the outcome of the accusation. Each part is assigned to a step and a category; parts that are luck "
           "are their own categories, never folded into a failure mode. Per episode the categories sum to the gap "
           "(checked by a test).", "",
           f"- **{r['episodes_decomposed']} episodes decomposed**; net gap {r['net_gap']:+.3f} "
           f"(lost value on episodes below the solver: {r['lost_value']:.3f}).",
           f"- **Tagged: {r['tagged']:+.3f}. Unexplained: {r['unexplained']:.1e}** "
           f"(largest per-episode residual {r['max_episode_residual']:.1e}).",
           f"- Skipped (no replayable world or no solver baseline, listed in the JSON): {len(r['episodes_skipped'])}.",
           f"- Quotes: {r['verification']['quotes_verified']}/{r['verification']['quotes_checked']} verbatim.", "",
           "## Where the value went, per rules version (never pooled)", ""]
    vers = list(r.get("by_version", {}))
    out += ["| category | kind | " + " | ".join(f"{v} ({r['by_version'][v]['episodes']} eps, gap "
                                                f"{r['by_version'][v]['net_gap']:+.2f})" for v in vers) + " | episodes | steps |",
            "|---|---|" + "---|" * len(vers) + "---|---|"]
    for c in r["cards"]:
        cells = " | ".join(f"{c['by_version'].get(v, 0):+.3f}" for v in vers)
        out.append(f"| {c['code_name']} (`{c['category']}`) | {c['kind']} | {cells} | {c['episodes']} | {c['steps']} |")
    out += ["", "Every column sums exactly to that version's net gap (positive = value the agents lost against the "
            "solver; negative = luck or credit in the agents' favour)."]
    out += ["", "## Gallery", ""]
    for c in r["cards"]:
        per_v = ", ".join(f"{v} {x:+.3f}" for v, x in c["by_version"].items())
        out += [f"### {c['name']}", "", f"*Code category: `{c['category']}` ({c['kind']}). {per_v}; "
                f"{c['episodes']} episodes, {c['steps']} steps.*", ""]
        if c["explanation"]:
            out += [c["explanation"], ""]
        if c.get("chart"):
            out += [f"<img src=\"{c['chart']}\" width=\"420\" alt=\"belief trace\">", ""]
        for ex in c["examples"][:2]:
            out.append(f"- `{ex['episode']}` t={ex['t']} day {ex['day']} `{ex['tool']}`: {ex['value']:+.3f}. Solver "
                       f"posterior before the step: top suspect {ex['top_suspect']} ({ex['p_top']}), "
                       f"P(true mole)={ex['p_true_mole']}, P(accused)={ex['p_accused']}.")
        for q in c["quotes"][:2]:
            out.append(f"  > `{q['episode']}` t={q['t']}: \"{' '.join(q['quote'].split())[:240]}\"")
        out.append("")
    out += ["## By cohort (never pooled across models, thinking levels or rules versions)", "",
            "Accusation verdicts from `canary.analysis.accuse` (solver posterior on the accused at the accusation: "
            "justified >= 0.6; lucky = correct below 0.6; premature-wrong = wrong below 0.6).", "",
            "| cohort | episodes | mean agent | mean solver | mean gap | justified / lucky / premature-wrong / none | "
            "top categories (mean per episode) |", "|---|---|---|---|---|---|---|"]
    for k, v in r["cohorts"].items():
        top = ", ".join(f"{c} {x:+.3f}" for c, x in list(v["by_category_mean"].items())[:3])
        vd = v.get("accusation_verdicts", {})
        vs = " / ".join(str(vd.get(x, 0)) for x in ("justified", "lucky", "premature-wrong", "none"))
        out.append(f"| {k} | {v['episodes']} | {v['mean_agent']:.3f} | {v['mean_solver']:.3f} | {v['mean_gap']:+.3f} | "
                   f"{vs} | {top} |")
    out += ["", "Reproduce offline, no key: `python -m canary.gemini.gallery --replay`.", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", default=DEFAULT_RUNS)
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--no-charts", action="store_true")
    a = ap.parse_args(argv)
    build(a.runs, replay=a.replay, model=a.model, charts=not a.no_charts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
