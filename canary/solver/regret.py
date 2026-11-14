"""Per-decision regret: replay an episode's observations, rebuild the solver belief at every step,
and score the agent's action against the solver's choice under one value estimate.

    attribute(episode: EpisodeResult) -> list[{t, day, action, regret, p_best, tags}]

Value estimate (v1, heuristic but shared by agent and solver):
  Q_accuse(e)  = V * P(e) + (1-P(e)) * wrong_accusation_score
  Q_continue   = 0.98 * max(0, V - c_day * days_needed)   with
                 c_day = p_leak*leak_damage + canary_cost,
                 days_needed = log(n_eff) / (log(max_variants+1) * p_leak * 0.6), n_eff = 1/sum p^2
  V*(belief)   = max(max_e Q_accuse(e), Q_continue)
"""
from __future__ import annotations

import math
from collections import Counter

from ..rules import TIERS, tier_params
from ..types import EpisodeResult
from .params import params_from_instruction
from .policy import SolverPolicy, accuse_value


def q_continue(post, V, P, days_left):
    if days_left <= 0:
        return 0.0
    neff = 1.0 / max(1e-12, sum(p * p for p in post.values()))
    rate = math.log(P.max_variants + 1) * P.p_leak * 0.6
    need = math.log(max(neff, 1.0)) / max(rate, 1e-6)
    if need > days_left:
        return 0.5 * max(0.0, V - (P.p_leak * P.leak_damage + P.canary_cost) * days_left) * max(post.values())
    return 0.98 * max(0.0, V - (P.p_leak * P.leak_damage + P.canary_cost) * need)


def _gini(post, assignment):
    mass = Counter()
    for e, p in post.items():
        mass[assignment.get(e, "__none__")] += p
    return 1.0 - sum(m * m for m in mass.values())


def attribute(episode: EpisodeResult, instruction: str | None = None) -> list[dict]:
    P = params_from_instruction(instruction) if instruction else None
    P = P or tier_params(episode.tier)
    sp = SolverPolicy(P)
    decoy = (episode.meta or {}).get("decoy")
    out: list[dict] = []
    seen_today: Counter = Counter()
    last_day = None
    steps = episode.steps
    for i, st in enumerate(steps):
        # belief BEFORE this action, from steps[:i]
        for prev in steps[sp.seen:i]:
            sp._ingest(prev)
        sp.seen = i
        o = sp.obs
        if not o.employees:
            out.append(dict(t=st.t, day=st.day, action=st.tool, regret=0.0, p_best=None, tags=[]))
            continue
        post = sp.belief()
        V = sp.V
        best = max(post, key=post.get)
        days_left = P.n_days - st.day
        qc = q_continue(post, V, P, days_left)
        vstar = max(accuse_value(post[best], V, P), qc, 0.0)
        tags: list[str] = []
        regret = 0.0
        if st.day != last_day:
            seen_today.clear()
            last_day = st.day
        key = (st.tool, repr(sorted((st.args or {}).items())))
        seen_today[key] += 1
        ok = (st.result or {}).get("ok", True)
        if st.tool == "accuse":
            e = st.args.get("employee")
            pe = post.get(e, 0.0)
            regret = max(0.0, vstar - accuse_value(pe, V, P))
            if pe < 0.6:
                tags.append("premature_accusation")
            if decoy and e == decoy:
                tags.append("decoy_chase")
            pending = [d for d in o.leak_days
                       if not any(0 < it.surfaced_day - d <= max(P.delay_choices) for it in o.feed)
                       and d + max(P.delay_choices) >= st.day]
            if pending and pe < 0.9:
                tags.append("ignored_delay")
        elif st.tool == "advance_day":
            regret = max(0.0, accuse_value(post[best], V, P) - max(qc, 0.0))
        elif st.tool == "plant_canary" and ok:
            asg = st.args.get("assignment") or {}
            g_agent = _gini(post, asg)
            g_solver = _gini(post, sp.partition(post))
            regret = max(0.0, g_solver - g_agent) * P.p_leak * P.leak_damage * 2 + 0.0
            if g_agent < 0.2:
                tags.append("uninformative_canary")
        elif st.tool == "restrict_access" and ok:
            e = st.args.get("employee")
            regret = P.restrict_cost_per_day * max(1, days_left) * (1 - post.get(e, 0.0))
            if post.get(e, 0.0) < 0.1:
                tags.append("over_restriction")
            if decoy and e == decoy:
                tags.append("decoy_chase")
        if not ok or (seen_today[key] > 1 and st.tool not in ("status", "advance_day")):
            tags.append("budget_waste")
        out.append(dict(t=st.t, day=st.day, action=st.tool, regret=round(regret, 6),
                        p_best=round(post[best], 4), tags=tags))
    if episode.end_reason != "accused":
        for prev in steps[sp.seen:]:
            sp._ingest(prev)
        post = sp.belief() if sp.obs.employees else {}
        best_v = max(0.0, accuse_value(max(post.values()), sp.V, P)) if post else 0.0
        out.append(dict(t=len(steps), day=episode.final_day, action="(no accusation)",
                        regret=round(best_v, 6), p_best=round(max(post.values()), 4) if post else None,
                        tags=["no_accusation"]))
    return out
