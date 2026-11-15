from __future__ import annotations

import copy
import json
import math
import time
from typing import Any, Mapping

from canary.env import Env
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TRAIN_SEEDS, tier_params
from canary.solver.belief import _fallback, behaviour_logliks
from canary.solver.policy import SolverPolicy

__all__ = [
    "PUBLIC_DEV_SEED_MAX",
    "PUBLIC_DEV_SEED_MIN",
    "RIVAL_STRATEGIES",
    "RIVAL_STRATEGY_JSONS",
    "check_seed",
    "compare_human_mole",
    "compare_human_mole_json",
    "get_mole_briefing",
    "get_mole_briefing_json",
    "safe_compare_human_mole",
    "safe_compare_human_mole_json",
    "validate_seed",
]

PUBLIC_DEV_SEED_MIN = 3000
PUBLIC_DEV_SEED_MAX = 9999

RIVAL_STRATEGY_JSONS: dict[str, dict[str, Any]] = {
    "default_v0": DEFAULT_STRATEGY.to_json(),
    "patient_wide_v1": {
        "name": "patient_wide_v1",
        "rules": [
            {
                "if": [
                    ["day", "<=", 7],
                    ["recent_low_recipient_docs", ">=", 2],
                    ["n_restricted_colleagues", ">=", 1],
                ],
                "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
            },
            {
                "if": [
                    ["day", "<=", 7],
                    ["recent_low_recipient_docs", ">=", 2],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [
                    ["day", "<=", 7],
                    ["min_recipient_count", "<=", 4],
                    ["max_recipient_count", ">=", 8],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [["n_restricted_colleagues", ">=", 1]],
                "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
            },
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "frontier_synthesis_v14": {
        "name": "frontier_synthesis_v14",
        "rules": [
            {
                "if": [
                    ["day", "<=", 6],
                    ["recent_low_recipient_docs", ">=", 2],
                    ["n_restricted_colleagues", ">=", 1],
                ],
                "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
            },
            {
                "if": [
                    ["day", "<=", 6],
                    ["recent_low_recipient_docs", ">=", 2],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [
                    ["day", ">=", 5],
                    ["day", "<=", 8],
                    ["days_since_last_leak", "<", 2],
                ],
                "then": {"leak": "none", "frame": "random_peer"},
            },
            {
                "if": [
                    ["day", "<=", 6],
                    ["min_recipient_count", "<=", 8],
                    ["max_recipient_count", ">=", 14],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [["n_restricted_colleagues", ">=", 1]],
                "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
            },
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
}

RIVAL_STRATEGIES: dict[str, MoleStrategy] = {
    "default_v0": DEFAULT_STRATEGY,
    "patient_wide_v1": MoleStrategy.from_json(RIVAL_STRATEGY_JSONS["patient_wide_v1"]),
    "frontier_synthesis_v14": MoleStrategy.from_json(RIVAL_STRATEGY_JSONS["frontier_synthesis_v14"]),
}

_RIVAL_CACHE: dict[tuple[str, int, str], dict[str, Any]] = {}
_MAX_CACHE_SIZE = 96


class _FastTextProvider:
    name = "arena_fast"

    def day_messages(self, facts: Any) -> list[dict[str, Any]]:
        if facts.decoy and facts.day == 1:
            return [
                {
                    "id": "m1-0",
                    "day": 1,
                    "channel": "chat",
                    "sender": facts.decoy,
                    "recipients": [],
                    "subject": "promotion",
                    "body": "Skipped for promotion again.",
                },
                {
                    "id": "m1-1",
                    "day": 1,
                    "channel": "chat",
                    "sender": facts.decoy,
                    "recipients": [],
                    "subject": "raise",
                    "body": "Flat raise again this cycle.",
                },
                {
                    "id": "m1-2",
                    "day": 1,
                    "channel": "chat",
                    "sender": facts.decoy,
                    "recipients": [],
                    "subject": "deserve",
                    "body": "I deserve better than burn out.",
                },
            ]
        return []

    def interview_answer(self, facts: Any, employee: str, topic: str, signal: str) -> str:
        return signal


_FAST_TEXT = _FastTextProvider()


def _fast_posterior(
    obs: Any,
    params: Any,
    behaviour_temper: float = 0.6,
    choice_temper: float = 0.5,
    noleak_temper: float = 0.5,
) -> dict[str, float]:
    emps = obs.employees
    if not emps:
        return {}
    window = getattr(params, "leak_window_days", 3)
    delays = tuple(params.delay_choices)
    pd = 1.0 / len(delays)
    min_dl = min(delays)
    n_emp = len(emps)
    careful = params.careful_mole
    fp_acc = getattr(params, "fingerprint_accuracy", 1.0)

    surfaced: dict[str, int] = {}
    for it in obs.feed:
        prev = surfaced.get(it.doc_id)
        if prev is None or it.surfaced_day < prev:
            surfaced[it.doc_id] = it.surfaced_day

    seen: set[str] = set()
    items = []
    for it in sorted(obs.feed, key=lambda x: (x.surfaced_day, x.doc_id)):
        if it.doc_id not in seen:
            seen.add(it.doc_id)
            items.append(it)

    m_items = len(items)
    item_docs = [obs.docs.get(it.doc_id) for it in items]
    impossible: set[str] = set()
    if obs.decoy is not None:
        impossible.add(obs.decoy)
    for it, doc in zip(items, item_docs):
        if doc is None:
            continue
        rec = doc.recipients
        exact_var = fp_acc >= 1.0 and doc.is_canary and doc.variants and it.variant
        for s in emps:
            if s not in rec or (exact_var and doc.variants.get(s) != it.variant):
                impossible.add(s)

    alive_emps = [s for s in emps if s not in impossible]
    if not alive_emps:
        return _fallback(obs)

    days = sorted(obs.closed_days)
    today = obs.today
    docs_by_day: dict[int, list[tuple[str, frozenset[str], float]]] = {d: [] for d in days}
    for doc in obs.docs.values():
        w = max(0.05, 1.0 - len(doc.recipients) / n_emp) if (careful and doc.is_canary) else 1.0
        sd = surfaced.get(doc.doc_id)
        lo_d = doc.day
        hi_d = doc.day + window - 1
        for d in days:
            if lo_d <= d <= hi_d and (sd is None or sd > d):
                docs_by_day[d].append((doc.doc_id, doc.recipients, w))

    latest = [it.surfaced_day - min_dl for it in items]
    p_noleak = max(1e-12, 1.0 - params.p_leak) ** noleak_temper
    p_leak = params.p_leak
    pend_by_day = {d: p_leak * sum(pd for dl in delays if d + dl > today) for d in days}
    delay_set = set(delays)
    full_mask = (1 << m_items) - 1
    beh = behaviour_logliks(obs, params) if behaviour_temper > 0 else {}

    req_by_idx: list[int] = []
    for idx in range(len(days)):
        nd = days[idx + 1] if idx + 1 < len(days) else None
        req = 0
        if nd is not None:
            for j in range(m_items):
                if latest[j] < nd:
                    req |= 1 << j
        req_by_idx.append(req)

    day_surf = [
        {j: it.doc_id for j, it in enumerate(items) if (it.surfaced_day - d) in delay_set}
        for d in days
    ]

    logs: dict[str, float] = {s: -math.inf for s in emps}
    for s in alive_emps:
        vf: list[float] = []
        possible = True
        for it, doc in zip(items, item_docs):
            if not (it.variant and doc and doc.variants):
                vf.append(1.0)
                continue
            mine = doc.variants.get(s)
            k = len(set(doc.variants.values()))
            if mine == it.variant:
                vf.append(fp_acc)
            elif mine is None or k <= 1:
                possible = False
                break
            else:
                vf.append((1.0 - fp_acc) / (k - 1))
        if not possible:
            continue

        states: dict[int, float] = {0: 1.0}
        scale_log = 0.0
        for idx, d in enumerate(days):
            total_w = 0.0
            wdoc: dict[str, float] = {}
            for did, rec, w in docs_by_day[d]:
                if s in rec:
                    total_w += w
                    wdoc[did] = w
            if total_w <= 0.0:
                req = req_by_idx[idx]
                if req:
                    states = {m: v for m, v in states.items() if (m & req) == req}
                    if not states:
                        break
                continue
            stay_mult = p_noleak + pend_by_day[d]
            cand_j = []
            for j, did in day_surf[idx].items():
                if did in wdoc:
                    f = p_leak * ((wdoc[did] / total_w) ** choice_temper) * pd * vf[j]
                    if f > 0.0:
                        cand_j.append((1 << j, f))
            nxt: dict[int, float] = {}
            for mask, w_cur in states.items():
                nxt[mask] = nxt.get(mask, 0.0) + w_cur * stay_mult
                for bit, f in cand_j:
                    if not (mask & bit):
                        nm = mask | bit
                        nxt[nm] = nxt.get(nm, 0.0) + w_cur * f
            req = req_by_idx[idx]
            if req:
                nxt = {m: v for m, v in nxt.items() if (m & req) == req}
            if not nxt:
                states = nxt
                break
            if len(nxt) > 32:
                nxt = dict(sorted(nxt.items(), key=lambda kv: -kv[1])[:32])
            mx = max(nxt.values())
            if mx < 1e-100:
                inv = 1.0 / mx
                nxt = {m: v * inv for m, v in nxt.items()}
                scale_log += math.log(mx)
            states = nxt

        wf = states.get(full_mask, 0.0)
        if wf > 0.0:
            lp = math.log(wf) + scale_log
            if behaviour_temper > 0:
                lp += behaviour_temper * beh[s]
                for who, ev in obs.interviews:
                    if who == s:
                        pe = params.p_evasive_innocent
                        pm = min(0.999, pe * params.interview_lr)
                        lp += behaviour_temper * (math.log(pm / pe) if ev else math.log((1 - pm) / (1 - pe)))
            logs[s] = lp

    top_lp = max(logs.values()) if logs else -math.inf
    if top_lp == -math.inf:
        return _fallback(obs)
    norm = sum(math.exp(v - top_lp) for v in logs.values())
    return {s: math.exp(v - top_lp) / norm for s, v in logs.items()}


class _FastSolverPolicy(SolverPolicy):
    def belief(self) -> dict[str, float]:
        self.obs.leak_timing_known = self.v_drops_reveal_leaks()
        if self.obs.leak_timing_known:
            return super().belief()
        return _fast_posterior(
            self.obs,
            self.P,
            self.behaviour_temper,
            self.choice_temper,
            self.noleak_temper,
        )


def _validate_tier(tier: Any) -> str:
    if not isinstance(tier, str) or tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    return tier


def _validate_seed(seed: Any) -> int:
    if isinstance(seed, bool):
        raise ValueError("seed must be an integer public dev seed in 3000..9999")
    if isinstance(seed, int):
        s = seed
    elif isinstance(seed, str):
        stripped = seed.strip()
        if not stripped or not (stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit())):
            raise ValueError("seed must be an integer public dev seed in 3000..9999")
        s = int(stripped)
        if stripped != str(s):
            raise ValueError("seed must be an integer public dev seed in 3000..9999")
    else:
        raise ValueError("seed must be an integer public dev seed in 3000..9999")
    if (
        s not in DEV_SEEDS
        or s < PUBLIC_DEV_SEED_MIN
        or s > PUBLIC_DEV_SEED_MAX
        or s in JUDGE_SEEDS
        or s in HELDOUT_SEEDS
        or s in TRAIN_SEEDS
    ):
        raise ValueError(f"seed {s} is outside public dev seeds 3000..9999 and cannot be inspected")
    return s


validate_seed = _validate_seed
check_seed = _validate_seed


def _parse_summary(human_mole_summary: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(human_mole_summary, str):
        try:
            parsed = json.loads(human_mole_summary)
        except ValueError as exc:
            raise ValueError("human_mole_summary is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("human_mole_summary JSON must decode to an object")
        return parsed
    if isinstance(human_mole_summary, Mapping):
        return dict(human_mole_summary)
    raise ValueError("human_mole_summary must be a dict or JSON string")


def _first_present(summary: Mapping[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in summary and summary[key] is not None:
            return summary[key]
    return default


def _is_human_unfinished(summary: Mapping[str, Any]) -> bool:
    for flag in ("human_done", "humanDone", "done", "episode_over", "episodeOver"):
        if flag in summary and not bool(summary[flag]):
            return True
    status = str(summary.get("status", "")).strip().lower()
    if status in ("in_progress", "active", "running", "open", "pending"):
        return True
    return False


def _normalize_human_summary(summary: Mapping[str, Any], max_days: int) -> dict[str, Any]:
    raw_days = _first_present(
        summary,
        ("days_survived", "daysSurvived", "final_day", "finalDay", "day", "days"),
        max_days,
    )
    default_leaks = 0
    for list_key in (
        "leaks_made",
        "leaksMade",
        "leak_history",
        "leakHistory",
        "leaks_surfaced",
        "leaksSurfaced",
        "leaked_canaries",
        "leakedCanaries",
    ):
        seq = summary.get(list_key)
        if isinstance(seq, list):
            default_leaks = len(seq)
            break
    raw_leaks = _first_present(
        summary,
        ("leaks_landed", "leaks_count", "leaksLanded", "leaksCount", "leaks", "n_leaks"),
        default_leaks,
    )
    raw_caught = _first_present(
        summary,
        ("caught", "accused_correct", "accusedCorrect", "solver_caught", "solverCaught", "correct"),
        None,
    )
    if raw_caught is None:
        if "survived" in summary and summary["survived"] is not None:
            raw_caught = not bool(summary["survived"])
        elif isinstance(summary.get("caught_by_canary"), Mapping) or isinstance(summary.get("caughtByCanary"), Mapping):
            raw_caught = True
        else:
            raw_caught = False
    caught_flag = bool(raw_caught)

    solver_sub = summary.get("solver")
    solver_sub_score = (
        solver_sub.get("score")
        if isinstance(solver_sub, Mapping) and solver_sub.get("score") is not None
        else None
    )
    raw_score = _first_present(
        summary,
        ("solver_score", "solverScore", "investigator_score", "investigatorScore", "score"),
        solver_sub_score,
    )
    if raw_score is None:
        hm_raw = _first_present(
            summary,
            ("humanMoleScore", "human_mole_score", "mole_score", "moleScore"),
            None,
        )
        if hm_raw is not None:
            hm_val = float(hm_raw)
            if hm_val < 0.0:
                raw_score = -hm_val
            elif caught_flag and 0.0 <= hm_val <= 1.0:
                raw_score = 1.0 - hm_val
            else:
                raw_score = 0.0
        else:
            raw_score = 0.0

    return {
        "days_survived": max(0, int(raw_days)),
        "leaks_landed": max(0, int(raw_leaks)),
        "solver_score": round(float(raw_score), 4),
        "caught": caught_flag,
    }


def _delay_text(delays: tuple[int, ...]) -> str:
    lo, hi = min(delays), max(delays)
    return f"{lo} day" if lo == hi else f"{lo}-{hi} days"


def get_mole_briefing(tier: str = "medium") -> dict[str, Any]:
    clean_tier = _validate_tier(tier)
    p = tier_params(clean_tier)
    delay_str = _delay_text(p.delay_choices)
    return {
        "tier": clean_tier,
        "tier_facts": {
            "n_employees": p.n_employees,
            "n_days": p.n_days,
            "p_leak": p.p_leak,
            "leak_window_days": p.leak_window_days,
            "delay_choices": list(p.delay_choices),
            "leak_damage": p.leak_damage,
            "canaries_per_day": p.canaries_per_day,
            "max_variants": p.max_variants,
            "low_recipient_threshold": p.low_recipient_threshold,
            "fingerprint_accuracy": p.fingerprint_accuracy,
            "framing": p.framing,
            "careful_mole": p.careful_mole,
        },
        "headline": (
            f"Mode 3 Tactical Briefing ({clean_tier} tier: {p.n_employees} staff, {p.n_days} days, "
            f"up to {p.canaries_per_day} canary trap(s)/day across {p.max_variants} variants)."
        ),
        "rules": [
            {
                "id": "recipient_width",
                "title": "Recipient-set width controls Bayesian exposure",
                "detail": (
                    f"Every surfaced leak eliminates staff outside its recipient list. Wide department documents "
                    f"across {p.n_employees} employees dilute likelihood across many holders, whereas narrow "
                    f"documents isolate you rapidly."
                ),
            },
            {
                "id": "canary_traps",
                "title": f"Avoid 2-3 person surgical canary traps (up to {p.max_variants} variants)",
                "detail": (
                    f"Security splits suspects into up to {p.max_variants} variant labels (A/B/C). Frontier "
                    f"investigators plant narrow <= {p.low_recipient_threshold} recipient traps early; leaking one "
                    f"collapses the suspect pool in a single surface event."
                ),
            },
            {
                "id": "freshness_and_delay",
                "title": f"{p.leak_window_days}-day freshness window and {delay_str} surfacing lag",
                "detail": (
                    f"You can only leak documents received within the last {p.leak_window_days} days, and leaked "
                    f"items surface {delay_str} later. Yesterday's risky leak detonates days later alongside newer "
                    f"traps."
                ),
            },
            {
                "id": "framing_vs_canary",
                "title": "Peer-framing noise distracts heuristics, not Bayesian canary math",
                "detail": (
                    "Non-decoy peer framing shifts heuristic and LLM tie-breaks (+0.086 counterfactual EV drop, "
                    "while angry decoys were dismissed in 100% of 159 frontier runs), whereas SolverPolicy "
                    "downweights behavioral logs (temper=0.6) and hunts canary variants."
                ),
            },
        ],
        "rival_profiles": [
            {
                "strategy": "default_v0",
                "label": "Default Mole (Baseline)",
                "summary": "Picks eligible documents at random with careful-mole weighting and adds no peer framing.",
            },
            {
                "strategy": "patient_wide_v1",
                "label": "Patient Wide v1 (Dual-Tier Shield)",
                "summary": "Routes early trap-heavy days into wide-recipient documents and frames restricted or random peers.",
            },
            {
                "strategy": "frontier_synthesis_v14",
                "label": "Frontier Synthesis v1.4 (Benchmark Rival)",
                "summary": "Combines early low-recipient trap deflection, wide-doc preference, days 5-8 leak pacing, and non-decoy peer framing.",
            },
        ],
    }


def get_mole_briefing_json(tier: str = "medium") -> str:
    return json.dumps(get_mole_briefing(tier))


def _run_rival_episode(tier: str, seed: int, strategy_name: str) -> dict[str, Any]:
    cache_key = (tier, seed, strategy_name)
    cached = _RIVAL_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    strat = RIVAL_STRATEGIES[strategy_name]
    env = Env(tier, seed, text_provider=_FAST_TEXT, mole_strategy=strat)
    if tier == "hard":
        pol = _FastSolverPolicy(tier, max_candidates=6, multi_candidates=3, max_pending=1, adaptive=True)
    else:
        pol = _FastSolverPolicy(tier, max_candidates=14, adaptive=True)
    pol.reset([], "not visible until they surface")
    while not env.done:
        tool, args = pol.act(env.history)
        env.call(tool, args)

    verdict = env.verdict()
    final_day = int(verdict["final_day"])

    trace_stats: dict[int, tuple[float, int]] = {}
    for snap in pol.trace:
        post = snap["post"]
        if post:
            top_p = max(post.values())
            alive_n = sum(1 for v in post.values() if v > 0.01)
            trace_stats[int(snap["day"])] = (round(top_p, 4), int(alive_n))

    leak_ledger = [entry for entry in env.ledger() if entry.event == "leak"]
    leak_events: list[dict[str, Any]] = []
    for idx, item in enumerate(env._feed):
        doc_id = str(item["doc_id"])
        doc = env._doc_by_id.get(doc_id, {})
        day_leaked = int(leak_ledger[idx].day) if idx < len(leak_ledger) else max(1, int(item["surfaced_day"]) - 1)
        surfaced_day = int(item["surfaced_day"])
        surfaced_before_end = surfaced_day <= final_day
        variant = item.get("variant")
        variants_map = doc.get("variants") or {}
        variant_group_size = len(variants_map.get(variant, ())) if variant and variants_map else None

        prev_day_p, prev_alive = trace_stats.get(max(1, surfaced_day - 1), (round(1.0 / env.p.n_employees, 4), env.p.n_employees))
        surf_p, surf_alive = trace_stats.get(surfaced_day, (prev_day_p, prev_alive))
        leak_events.append(
            {
                "day_leaked": day_leaked,
                "surfaced_day": surfaced_day,
                "doc_id": doc_id,
                "recipient_count": len(doc.get("recipients", ())),
                "variant": str(variant) if variant is not None else None,
                "variant_group_size": int(variant_group_size) if variant_group_size is not None else None,
                "surfaced_before_end": surfaced_before_end,
                "max_posterior_before": prev_day_p if surfaced_before_end else None,
                "max_posterior_after": surf_p if surfaced_before_end else None,
                "active_suspects_after": surf_alive if surfaced_before_end else None,
            }
        )

    surfaced_canary_groups = [
        int(ev["variant_group_size"])
        for ev in leak_events
        if ev["surfaced_before_end"] and ev["variant_group_size"] is not None
    ]
    out = {
        "strategy": strategy_name,
        "days_survived": final_day,
        "leaks_landed": len(leak_events),
        "canary_leaks_surfaced": len(surfaced_canary_groups),
        "narrowest_variant_group": min(surfaced_canary_groups) if surfaced_canary_groups else None,
        "solver_score": round(float(verdict["score"]), 4),
        "caught": bool(verdict["correct"]),
        "final_day": final_day,
        "leak_events": leak_events,
    }
    if len(_RIVAL_CACHE) >= _MAX_CACHE_SIZE:
        _RIVAL_CACHE.pop(next(iter(_RIVAL_CACHE)))
    _RIVAL_CACHE[cache_key] = copy.deepcopy(out)
    return out


def _decisive_event(rival: Mapping[str, Any]) -> dict[str, Any] | None:
    surfaced = [ev for ev in rival.get("leak_events", []) if ev.get("surfaced_before_end")]
    canaries = [ev for ev in surfaced if ev.get("variant") is not None]
    if canaries:
        return min(
            canaries,
            key=lambda ev: (
                ev.get("variant_group_size") or 999,
                -(
                    (ev.get("max_posterior_after") or 0.0)
                    - (ev.get("max_posterior_before") or 0.0)
                ),
            ),
        )
    if surfaced:
        return min(surfaced, key=lambda ev: (ev.get("recipient_count") or 999, ev.get("surfaced_day") or 999))
    return None


def _build_tactical_debrief(
    tier: str,
    seed: int,
    human: Mapping[str, Any],
    default_mole: Mapping[str, Any],
    patient_mole: Mapping[str, Any],
    synthesis_mole: Mapping[str, Any],
    raw_human: Mapping[str, Any],
) -> list[str]:
    p = tier_params(tier)
    bullets: list[str] = []

    h_outcome = "caught by investigator" if human["caught"] else "evaded accusation"
    bullets.append(
        f"Seed {seed} ({tier}) outcome: you survived {human['days_survived']}/{p.n_days} days with "
        f"{human['leaks_landed']} leak(s) ({h_outcome}, investigator score {human['solver_score']:+.2f}) "
        f"vs default_v0 ({default_mole['days_survived']}d, {default_mole['solver_score']:+.2f})."
    )

    human_canary: Mapping[str, Any] | None = None
    cbc = raw_human.get("caught_by_canary")
    if not isinstance(cbc, Mapping):
        cbc = raw_human.get("caughtByCanary")
    if isinstance(cbc, Mapping) and cbc.get("variant") is not None:
        human_canary = cbc
    if human_canary is None:
        for list_key in (
            "leaked_canaries",
            "leakedCanaries",
            "leak_history",
            "leakHistory",
            "leaks_made",
            "leaksMade",
        ):
            seq = raw_human.get(list_key)
            if isinstance(seq, list):
                for item in seq:
                    if isinstance(item, Mapping) and item.get("variant") is not None:
                        human_canary = item
                        break
            if human_canary is not None:
                break

    pivot = _decisive_event(default_mole) or _decisive_event(synthesis_mole)
    if human_canary is not None:
        h_doc = str(
            _first_present(
                human_canary,
                ("doc_id", "docId", "raw_doc_id", "rawDocId"),
                "canary",
            )
        )
        h_var = str(human_canary.get("variant"))
        var_recs = _first_present(human_canary, ("variant_recipients", "variantRecipients"), None)
        default_grp = len(var_recs) if isinstance(var_recs, list) else "?"
        h_grp = _first_present(
            human_canary,
            ("variant_group_size", "variantGroupSize", "recipient_count", "recipientCount"),
            default_grp,
        )
        bullets.append(
            f"Canary exposure in your run: leaking {h_doc} (variant {h_var}, group size {h_grp}) handed "
            f"SolverPolicy a direct variant partition update across {p.n_employees} staff."
        )
    elif pivot is not None and pivot.get("variant") is not None:
        bullets.append(
            f"Trap forensics on seed {seed}: when {default_mole['strategy']} leaked {pivot['doc_id']} on day "
            f"{pivot['day_leaked']} (variant {pivot['variant']}, group size {pivot['variant_group_size']}), "
            f"its day-{pivot['surfaced_day']} surface jumped SolverPolicy top posterior from "
            f"{pivot['max_posterior_before']:.2f} to {pivot['max_posterior_after']:.2f} "
            f"({pivot['active_suspects_after']} active suspect(s) >1%)."
        )
    elif pivot is not None:
        bullets.append(
            f"Recipient narrowing on seed {seed}: {pivot['doc_id']} ({pivot['recipient_count']} recipients, "
            f"surfaced day {pivot['surfaced_day']}) moved SolverPolicy top posterior from "
            f"{pivot['max_posterior_before']:.2f} to {pivot['max_posterior_after']:.2f} without a canary hit."
        )
    else:
        bullets.append(
            f"No leaked documents surfaced before day {default_mole['final_day']} on seed {seed}, keeping "
            f"SolverPolicy near its prior across {p.n_employees} employees."
        )

    bullets.append(
        f"Benchmark rivals on ({tier}, seed {seed}): frontier_synthesis_v14 survived "
        f"{synthesis_mole['days_survived']} days ({synthesis_mole['leaks_landed']} leaks, "
        f"{synthesis_mole['canary_leaks_surfaced']} surfaced canaries, SolverPolicy score "
        f"{synthesis_mole['solver_score']:+.2f}); patient_wide_v1 survived "
        f"{patient_mole['days_survived']} days (SolverPolicy score {patient_mole['solver_score']:+.2f})."
    )

    delay_str = _delay_text(p.delay_choices)
    if human["caught"] and human["days_survived"] < synthesis_mole["days_survived"]:
        bullets.append(
            f"Coaching adjustment: prefer wide department docs during days 1-7 when <= {p.low_recipient_threshold} "
            f"recipient traps appear, and account for the {delay_str} surfacing lag because SolverPolicy "
            f"downweights after-hours framing (temper=0.6)."
        )
    elif human["leaks_landed"] < synthesis_mole["leaks_landed"]:
        bullets.append(
            f"Coaching adjustment: you stayed quiet ({human['leaks_landed']} leak(s) vs "
            f"{synthesis_mole['leaks_landed']} by frontier_synthesis_v14); exploit wide-recipient regular docs "
            f"inside the {p.leak_window_days}-day window to deal V-damage (-{p.leak_damage:.2f}/leak) safely."
        )
    else:
        bullets.append(
            f"Coaching takeaway: your leak discipline matched or beat the benchmark mole horizon while navigating "
            f"a {p.leak_window_days}-day freshness window and {delay_str} feed delay."
        )

    return bullets


def _rival_row(label: str, policy: str, row: Mapping[str, Any]) -> dict[str, Any]:
    days = int(row["days_survived"])
    leaks = int(row["leaks_landed"])
    score = round(float(row["solver_score"]), 4)
    return {
        "label": label,
        "policy": policy,
        "days_survived": days,
        "daysSurvived": days,
        "leaks_landed": leaks,
        "leaksLanded": leaks,
        "solver_score": score,
        "solverScore": score,
        "caught": bool(row["caught"]),
    }


def compare_human_mole(
    tier: str,
    seed: int,
    human_mole_summary: Mapping[str, Any] | str,
) -> dict[str, Any]:
    clean_tier = _validate_tier(tier)
    clean_seed = _validate_seed(seed)
    raw_summary = _parse_summary(human_mole_summary)
    if _is_human_unfinished(raw_summary):
        raise ValueError("human episode is not finished yet")

    t0 = time.perf_counter()
    p = tier_params(clean_tier)
    human = _normalize_human_summary(raw_summary, p.n_days)
    default_mole = _run_rival_episode(clean_tier, clean_seed, "default_v0")
    patient_mole = _run_rival_episode(clean_tier, clean_seed, "patient_wide_v1")
    synthesis_mole = _run_rival_episode(clean_tier, clean_seed, "frontier_synthesis_v14")
    rivals = [
        _rival_row("You (Human Mole)", "human", human),
        _rival_row("Default Mole (default_v0)", "default_v0", default_mole),
        _rival_row("Patient Wide v1 (patient_wide_v1)", "patient_wide_v1", patient_mole),
        _rival_row("Frontier Synthesis v1.4", "frontier_synthesis_v14", synthesis_mole),
    ]
    debrief = _build_tactical_debrief(
        clean_tier,
        clean_seed,
        human,
        default_mole,
        patient_mole,
        synthesis_mole,
        raw_summary,
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    return {
        "tier": clean_tier,
        "seed": clean_seed,
        "human": human,
        "default_mole": default_mole,
        "synthesis_mole": synthesis_mole,
        "patient_mole": patient_mole,
        "rivals": rivals,
        "tactical_debrief": debrief,
        "tacticalDebrief": list(debrief),
        "elapsed_ms": elapsed_ms,
    }


def compare_human_mole_json(
    tier: str,
    seed: int,
    human_mole_summary: Mapping[str, Any] | str,
) -> str:
    return json.dumps(compare_human_mole(tier, seed, human_mole_summary))


def safe_compare_human_mole(
    tier: str,
    seed: int,
    human_mole_summary: Mapping[str, Any] | str,
) -> dict[str, Any]:
    clean_tier = _validate_tier(tier)
    clean_seed = _validate_seed(seed)
    raw_summary = _parse_summary(human_mole_summary)
    if _is_human_unfinished(raw_summary):
        return {"sealed": True, "status": "[SEALED]"}
    return compare_human_mole(clean_tier, clean_seed, raw_summary)


def safe_compare_human_mole_json(
    tier: str,
    seed: int,
    human_mole_summary: Mapping[str, Any] | str,
) -> str:
    return json.dumps(safe_compare_human_mole(tier, seed, human_mole_summary))
