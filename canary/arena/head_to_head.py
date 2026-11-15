from __future__ import annotations

from collections import Counter
import copy
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping

from canary.analysis.accuse import audit_episode
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.rl_mole import RLMole
from canary.mole.distill_rl_mole import coerce_mole_policy
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.mole.regret_portfolio import (
    PortfolioMolePolicy,
    load_summaries_from_v14_json,
    solve_minimax_regret_portfolio,
)
from canary.mole.strategies import STRATEGIES, STRATEGY_SPECS, get_strategy
from canary.rules import (
    HELDOUT_SEEDS,
    JUDGE_SEEDS,
    TIERS_VERSION,
    TRAIN_SEEDS,
    tier_params,
    tier_params_for_episode,
)
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step

ROOT = Path(__file__).resolve().parents[2]
RL_MOLE_FRONTIER_V14_PATH = ROOT / "data" / "forge" / "rl_mole_frontier_v14.json"

SEED_MIN = 3000
SEED_MAX = 9999
VALID_TIERS = ("medium", "hard")

MOLE_OPPONENTS: tuple[str, ...] = (
    "default_v0",
    "frontier_synthesis_v14",
    "surgical_trap_shield",
    "gemini_midsize_shield",
    "early_burst_midgame_pace",
    "reactive_canary_lag",
    "non_decoy_tiebreak_framer",
    "portfolio_v14",
    "rl_mole_frontier_v14",
)

MOLE_OPPONENT_ALIASES: dict[str, str] = {
    "default": "default_v0",
    "regret_portfolio": "portfolio_v14",
    "regret_portfolio_v14": "portfolio_v14",
}

MOLE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "default_v0": {
        "label": "Default Uniform Careful Mole (v0)",
        "kind": "dsl",
        "description": "Baseline careful mole with seeded uniform leak choice and no targeted peer framing.",
    },
    "frontier_synthesis_v14": {
        "label": "Frontier Synthesis Shield (v1.4)",
        "kind": "dsl",
        "description": "Transcript-mined synthesis combining early trap evasion with midgame pacing.",
    },
    "surgical_trap_shield": {
        "label": "Surgical Trap Shield",
        "kind": "dsl",
        "description": "Deflects <=3-recipient surgical canary traps in days 1..7 toward wide regular docs.",
    },
    "gemini_midsize_shield": {
        "label": "Gemini Midsize Canary Shield",
        "kind": "dsl",
        "description": "Targets 4..8-recipient 3-variant midsize partitions favored by Gemini-4-carbon.",
    },
    "early_burst_midgame_pace": {
        "label": "Early Burst Midgame Pace",
        "kind": "dsl",
        "description": "Front-loads early leaks before canary coverage matures and paces midgame exposure.",
    },
    "reactive_canary_lag": {
        "label": "Reactive Canary Lag",
        "kind": "dsl",
        "description": "Exploits reactive canary timing lag while remaining solvable by pipelined partitions.",
    },
    "non_decoy_tiebreak_framer": {
        "label": "Non-Decoy Tiebreak Framer",
        "kind": "dsl",
        "description": "Frames restricted or non-decoy peers to perturb after-hours log tie-breakers.",
    },
    "portfolio_v14": {
        "label": "Minimax Regret Portfolio (v1.4)",
        "kind": "portfolio",
        "description": "Zero-private-info SHA-256 seed-hashed minimax regret mixture over transcript DSL moles.",
    },
    "rl_mole_frontier_v14": {
        "label": "Distilled Frontier RLMole (v1.4)",
        "kind": "rl_mole",
        "description": "Catchability-constrained MLP mole policy trained against frontier investigator proxies.",
    },
}

GHOST_REPLAY_SPECS: dict[str, dict[str, Any]] = {
    "v14_hard_seed4_slow": {
        "replay_id": "v14_hard_seed4_slow",
        "title": "v1.4 Hard Seed 4: Interview Trap vs Bayesian Canary Bisection",
        "subtitle": "Solver catches e11 on day 5 (+0.73) with 7 canaries; Gemini-4-carbon spends 84 interviews and finishes on day 16 (+0.40).",
        "version": "v1.4",
        "tier": "hard",
        "seed": 4,
        "left_label": "Bayesian Solver (reference)",
        "left_path": "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
        "right_label": "Gemini-4-Carbon (OpenCode MCP)",
        "right_path": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",
        "gemini_path": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",
        "solver_path": "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
        "primary_tag": "SLOW_MOMENT",
    },
    "v14_hard_seed26_fooled": {
        "replay_id": "v14_hard_seed26_fooled",
        "title": "v1.4 Hard Seed 26: Noisy 0.95 Canary Readout Fooled Gemini",
        "subtitle": "Solver isolates e08 on day 7 (+0.69); on day 10 a flipped S1 canary variant spikes e04 and Gemini falsely accuses e04 (-1.00).",
        "version": "v1.4",
        "tier": "hard",
        "seed": 26,
        "left_label": "Bayesian Solver (reference)",
        "left_path": "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
        "right_label": "Gemini-4-Carbon (OpenCode MCP)",
        "right_path": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",
        "gemini_path": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",
        "solver_path": "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
        "primary_tag": "FOOLED_MOMENT",
    },
    "v16_hard_seed30_cocktail": {
        "replay_id": "v16_hard_seed30_cocktail",
        "title": "v1.6 Living-Office Seed 30: Full 9-Lever Social Cocktail vs Control",
        "subtitle": "Paired Gemini-4-carbon trajectory on v5_full9_cocktail (+0.50 day 11) vs v0_v14_control (+0.54 day 11).",
        "version": "v1.6_social",
        "social_variant": "v5_full9_cocktail",
        "tier": "hard",
        "seed": 30,
        "left_label": "Gemini-4-Carbon (v1.4 Control)",
        "left_path": "results/v16_social/partial/v0_v14_control/hard/episodes.jsonl",
        "right_label": "Gemini-4-Carbon (v1.6 9-Lever Cocktail)",
        "right_path": "results/v16_social/partial/v5_full9_cocktail/hard/episodes.jsonl",
        "gemini_path": "results/v16_social/partial/v5_full9_cocktail/hard/episodes.jsonl",
        "solver_path": "data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl",
        "primary_tag": "SLOW_MOMENT",
    },
    "v16_hard_seed31_cocktail": {
        "replay_id": "v16_hard_seed31_cocktail",
        "title": "v1.6 Living-Office Seed 31: Full 9-Lever Social Cocktail vs Control",
        "subtitle": "Paired Gemini-4-carbon trajectory on v5_full9_cocktail (+0.64 day 8) vs v0_v14_control (+0.55 day 10).",
        "version": "v1.6_social",
        "social_variant": "v5_full9_cocktail",
        "tier": "hard",
        "seed": 31,
        "left_label": "Gemini-4-Carbon (v1.4 Control)",
        "left_path": "results/v16_social/partial/v0_v14_control/hard/episodes.jsonl",
        "right_label": "Gemini-4-Carbon (v1.6 9-Lever Cocktail)",
        "right_path": "results/v16_social/partial/v5_full9_cocktail/hard/episodes.jsonl",
        "gemini_path": "results/v16_social/partial/v5_full9_cocktail/hard/episodes.jsonl",
        "solver_path": "data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl",
        "primary_tag": "SLOW_MOMENT",
    },
    "v16_hard_seed32_cocktail": {
        "replay_id": "v16_hard_seed32_cocktail",
        "title": "v1.6 Living-Office Seed 32: Full 9-Lever Social Cocktail vs Control",
        "subtitle": "Paired Gemini-4-carbon trajectory on v5_full9_cocktail (+0.71 day 10) vs v0_v14_control (+0.48 day 13).",
        "version": "v1.6_social",
        "social_variant": "v5_full9_cocktail",
        "tier": "hard",
        "seed": 32,
        "left_label": "Gemini-4-Carbon (v1.4 Control)",
        "left_path": "results/v16_social/partial/v0_v14_control/hard/episodes.jsonl",
        "right_label": "Gemini-4-Carbon (v1.6 9-Lever Cocktail)",
        "right_path": "results/v16_social/partial/v5_full9_cocktail/hard/episodes.jsonl",
        "gemini_path": "results/v16_social/partial/v5_full9_cocktail/hard/episodes.jsonl",
        "solver_path": "data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl",
        "primary_tag": "SLOW_MOMENT",
    },
}

GHOST_REPLAY_ALIASES: dict[str, str] = {
    "v16_social_seed30": "v16_hard_seed30_cocktail",
    "v16_social_seed31": "v16_hard_seed31_cocktail",
    "v16_social_seed32": "v16_hard_seed32_cocktail",
    "seed4": "v14_hard_seed4_slow",
    "seed26": "v14_hard_seed26_fooled",
}

__all__ = [
    "GHOST_REPLAY_ALIASES",
    "GHOST_REPLAY_SPECS",
    "GhostReplayTheater",
    "HeadToHeadSession",
    "MOLE_OPPONENTS",
    "SEED_MAX",
    "SEED_MIN",
    "VALID_TIERS",
    "check_live_seed",
    "check_public_dev_seed",
    "check_seed",
    "check_tier",
    "create_session",
    "list_ghost_replays",
    "list_mole_opponents",
    "load_ghost_replay",
    "resolve_mole_opponent",
]


def check_tier(tier: Any) -> str:
    if not isinstance(tier, str) or tier not in VALID_TIERS:
        raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier!r}")
    return tier


def check_live_seed(seed: Any) -> int:
    if isinstance(seed, (bool, float)):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}")
    try:
        s = int(seed)
    except (TypeError, ValueError):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}") from None
    if str(seed).strip() != str(s):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}")
    if s in JUDGE_SEEDS or s in HELDOUT_SEEDS or s in TRAIN_SEEDS:
        raise ValueError(f"seed {s} is in a reserved benchmark split; use {SEED_MIN}..{SEED_MAX}")
    if not SEED_MIN <= s <= SEED_MAX:
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)")
    return s


check_public_dev_seed = check_live_seed
check_seed = check_live_seed


@lru_cache(maxsize=1)
def _regret_portfolio_weights() -> dict[str, float]:
    summaries, _ = load_summaries_from_v14_json()
    fit = solve_minimax_regret_portfolio(summaries)
    return dict(fit.weights)


def list_mole_opponents() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in MOLE_OPPONENTS:
        meta = MOLE_DESCRIPTIONS.get(name, {})
        spec = STRATEGY_SPECS.get(name)
        out.append(
            {
                "id": name,
                "name": name,
                "label": meta.get("label", name),
                "kind": meta.get("kind", "dsl"),
                "target_cohort": spec.target_cohort if spec is not None else "frontier_all",
                "description": meta.get("description", ""),
            }
        )
    return out


def resolve_mole_opponent(spec: Any, seed: int) -> tuple[str, Any]:
    if spec is None:
        canonical = "frontier_synthesis_v14"
        return canonical, get_strategy(canonical)
    if isinstance(spec, str):
        raw_name = spec.strip()
        canonical = MOLE_OPPONENT_ALIASES.get(raw_name, raw_name)
        if canonical == "default_v0":
            return "default_v0", MoleStrategy.from_json(DEFAULT_STRATEGY.to_json())
        if canonical in STRATEGIES:
            return canonical, get_strategy(canonical)
        if canonical == "portfolio_v14":
            pol = PortfolioMolePolicy(seed=seed, weights=_regret_portfolio_weights())
            out_name = raw_name if raw_name in ("portfolio_v14", "regret_portfolio") else "portfolio_v14"
            return out_name, pol
        if canonical == "rl_mole_frontier_v14":
            return "rl_mole_frontier_v14", coerce_mole_policy(RL_MOLE_FRONTIER_V14_PATH)
        raise ValueError(f"unknown mole_opponent {spec!r}; valid ids: {list(MOLE_OPPONENTS)}")
    if isinstance(spec, Mapping):
        kind = spec.get("kind")
        if kind == "rl_mole":
            obj = RLMole.from_json(dict(spec))
            return str(obj.name), obj
        if kind == "regret_portfolio" or "weights" in spec:
            obj = PortfolioMolePolicy.from_json(spec, seed=seed)
            return str(obj.name), obj
        ms = MoleStrategy.from_json(dict(spec))
        return str(ms.name), ms
    if isinstance(spec, PortfolioMolePolicy):
        return str(spec.name), spec.for_seed(seed)
    if isinstance(spec, (RLMole, MoleStrategy)):
        coerced = coerce_mole_policy(spec)
        return str(getattr(coerced, "name", "custom_mole")), coerced
    if hasattr(spec, "decide"):
        return str(getattr(spec, "name", "custom_mole")), spec
    raise ValueError(f"unsupported mole opponent specification: {type(spec).__name__}")


def _build_office_layout(
    n_employees: int,
    employees: list[dict[str, Any]],
    restricted: set[str],
) -> list[dict[str, Any]]:
    cols = 8 if n_employees >= 30 else 5
    cell_w = 110
    cell_h = 84
    pad_x = 60
    pad_y = 56
    if employees:
        out: list[dict[str, Any]] = []
        for idx, emp in enumerate(employees):
            row_i, col_i = divmod(idx, cols)
            emp_id = str(emp.get("id", f"e{idx:02d}"))
            entry: dict[str, Any] = {
                "slot": idx,
                "id": emp_id,
                "name": emp.get("name"),
                "dept": emp.get("dept"),
                "role": emp.get("role"),
                "x": pad_x + col_i * cell_w,
                "y": pad_y + row_i * cell_h,
                "discovered": True,
                "restricted": emp_id in restricted,
            }
            if "clearance" in emp:
                entry["clearance"] = emp["clearance"]
            out.append(entry)
        return out
    return [
        {
            "slot": idx,
            "id": f"desk_{idx:02d}",
            "name": None,
            "dept": None,
            "role": None,
            "x": pad_x + (idx % cols) * cell_w,
            "y": pad_y + (idx // cols) * cell_h,
            "discovered": False,
            "restricted": False,
        }
        for idx in range(n_employees)
    ]


def _steps_from_raw(raw_steps: list[Any]) -> list[Step]:
    out: list[Step] = []
    for idx, st in enumerate(raw_steps):
        if isinstance(st, Step):
            out.append(st)
        else:
            out.append(
                Step(
                    t=int(st.get("t", idx)),
                    day=int(st.get("day", 1)),
                    tool=str(st.get("tool", "")),
                    args=dict(st.get("args") or {}),
                    result=dict(st.get("result") or {}),
                )
            )
    return out


def _format_key_action(st: Step) -> str | None:
    res = st.result or {}
    ok = bool(res.get("ok"))
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    args = st.args or {}
    if not ok:
        return f"{st.tool}(failed)"
    if st.tool == "plant_canary":
        cid = data.get("canary_id") or "canary"
        asg = args.get("assignment") if isinstance(args.get("assignment"), dict) else {}
        n_rec = len(asg)
        n_var = len(set(asg.values())) if asg else 0
        return f"plant_canary({cid}: {n_rec} staff, {n_var} variants)"
    if st.tool == "check_leak_feed":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        tags = [
            f"{it.get('doc_id')}[{it.get('variant')}]" if it.get("variant") else str(it.get("doc_id"))
            for it in items
        ]
        if not tags:
            return "check_leak_feed(0 surfaced)"
        shown = ", ".join(tags[-3:])
        return f"check_leak_feed({len(tags)} surfaced: {shown})"
    if st.tool == "interview":
        ans = str(data.get("answer", "")).lower()
        tone = "evasive" if "evasive" in ans else "checked"
        return f"interview({args.get('employee')}, {args.get('topic')} -> {tone})"
    if st.tool == "read_access_logs":
        return f"read_access_logs(days {args.get('day_from')}..{args.get('day_to')})"
    if st.tool == "search_messages":
        return f"search_messages({args.get('query')!r})"
    if st.tool == "restrict_access":
        return f"restrict_access({args.get('employee')})"
    if st.tool == "unrestrict_access":
        return f"unrestrict_access({args.get('employee')})"
    if st.tool == "accuse":
        return f"accuse({args.get('employee')})"
    return None


def _compute_agent_day_trace(
    tier: str,
    steps: list[Step],
    true_mole: str,
    final_day: int,
) -> list[dict[str, Any]]:
    p = tier_params_for_episode(tier, steps)
    sp = SolverPolicy(p)
    sp.obs.employees = [f"e{i:02d}" for i in range(p.n_employees)]

    by_day: dict[int, list[Step]] = {}
    for st in steps:
        by_day.setdefault(int(st.day), []).append(st)

    max_day = max([int(final_day), *by_day.keys()], default=1)
    cum_canaries = 0
    cum_interviews = 0
    cum_calls = 0
    rows: list[dict[str, Any]] = []

    for d in range(1, max_day + 1):
        day_steps = by_day.get(d, [])
        pre_steps = [st for st in day_steps if st.tool != "advance_day"]
        adv_steps = [st for st in day_steps if st.tool == "advance_day"]

        sp.obs.today = max(int(sp.obs.today), d)
        accused_today: str | None = None
        for st in pre_steps:
            if st.tool == "accuse":
                if (st.result or {}).get("ok"):
                    accused_today = str((st.args or {}).get("employee") or "")
                break
            sp._ingest(st)

        post = sp.belief() if sp.obs.employees else {}
        if post:
            top_suspect = max(sorted(post), key=lambda e: post[e])
            p_top = round(float(post[top_suspect]), 4)
            p_true = round(float(post.get(true_mole, 0.0)), 4)
        else:
            top_suspect = None
            p_top = 0.0
            p_true = 0.0

        day_v = round(max(0.0, float(sp.V)), 4)
        day_canaries = sum(1 for st in day_steps if st.tool == "plant_canary" and (st.result or {}).get("ok"))
        day_interviews = sum(1 for st in day_steps if st.tool == "interview" and (st.result or {}).get("ok"))
        cum_canaries += day_canaries
        cum_interviews += day_interviews
        cum_calls += len(day_steps)

        key_actions: list[str] = []
        for st in day_steps:
            desc = _format_key_action(st)
            if desc is not None:
                key_actions.append(desc)

        tool_counts = dict(Counter(st.tool for st in day_steps))
        rows.append(
            {
                "day": d,
                "V": day_v,
                "canaries": day_canaries,
                "cumulative_canaries": cum_canaries,
                "interviews": day_interviews,
                "cumulative_interviews": cum_interviews,
                "calls": cum_calls,
                "tool_calls": len(day_steps),
                "p_mole": p_true,
                "p_true_mole": p_true,
                "top_suspect": top_suspect,
                "p_top": p_top,
                "accused": accused_today,
                "tool_counts": tool_counts,
                "tools": [st.tool for st in day_steps],
                "key_actions": key_actions,
                "key_tool_actions": key_actions,
            }
        )

        for st in adv_steps:
            sp._ingest(st)
            if (st.result or {}).get("ok"):
                data = (st.result or {}).get("data") or {}
                if "closed_day" in data:
                    sp.obs.closed_days.add(int(data["closed_day"]))
                if "day" in data:
                    sp.obs.today = int(data["day"])

    return rows


def _summarize_episode(ep: EpisodeResult, true_mole: str, label: str | None = None) -> dict[str, Any]:
    aud = audit_episode(ep)
    curve = _compute_agent_day_trace(ep.tier, ep.steps, true_mole, ep.final_day)
    canaries = sum(1 for st in ep.steps if st.tool == "plant_canary" and (st.result or {}).get("ok"))
    interviews = sum(1 for st in ep.steps if st.tool == "interview" and (st.result or {}).get("ok"))
    access_log_reads = sum(1 for st in ep.steps if st.tool == "read_access_logs" and (st.result or {}).get("ok"))
    message_searches = sum(1 for st in ep.steps if st.tool == "search_messages" and (st.result or {}).get("ok"))
    return {
        "agent": ep.agent,
        "label": label or ep.agent,
        "score": round(float(ep.score), 4),
        "correct": bool(ep.correct),
        "accuracy": 1.0 if ep.correct else 0.0,
        "accused": ep.accused,
        "accusation_day": int(ep.final_day) if ep.accused is not None else None,
        "final_day": int(ep.final_day),
        "end_reason": ep.end_reason,
        "tool_calls": len(ep.steps),
        "canaries": canaries,
        "interviews": interviews,
        "access_log_reads": access_log_reads,
        "message_searches": message_searches,
        "p_accused": aud["p_accused"],
        "p_top": aud["p_top"],
        "audit_verdict": aud["verdict"],
        "posterior_curve": curve,
    }


def _winner_banner(human_score: float, human_correct: bool, gemini_score: float, solver_score: float) -> str:
    if human_score > solver_score + 1e-9:
        return "BEAT_SOLVER"
    if abs(human_score - solver_score) <= 1e-9 and human_correct:
        return "MATCHED_SOLVER"
    if human_score > gemini_score + 1e-9:
        return "BEAT_GEMINI"
    if abs(human_score - gemini_score) <= 1e-9 and human_correct:
        return "TIED_GEMINI"
    if human_correct:
        return "CAUGHT_MOLE_TRAILED_GEMINI"
    return "GEMINI_AHEAD"


def _compute_badges(human_summary: dict[str, Any], gemini_summary: dict[str, Any], solver_summary: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    h_score = float(human_summary["score"])
    g_score = float(gemini_summary["score"])
    s_score = float(solver_summary["score"])
    if human_summary["correct"]:
        badges.append("CAUGHT_THE_MOLE")
    else:
        badges.append("FOOLED_BY_MOLE")
    if h_score > g_score + 1e-9:
        badges.append("OUTSCORED_GEMINI_PROXY")
    if human_summary["correct"] and h_score >= s_score - 1e-9:
        badges.append("MATCHED_BAYESIAN_SOLVER")
    if h_score > s_score + 1e-9:
        badges.append("BEAT_BAYESIAN_SOLVER")
    return badges


def _build_day_comparison_rows(
    human_curve: list[dict[str, Any]],
    gemini_curve: list[dict[str, Any]],
    solver_curve: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    max_day = max(len(human_curve), len(gemini_curve), len(solver_curve), 1)

    def _at(curve: list[dict[str, Any]], idx: int) -> tuple[dict[str, Any], bool]:
        if not curve:
            return {"p_true_mole": 0.0, "V": 1.0, "tool_calls": 0, "canaries": 0, "interviews": 0}, False
        if idx < len(curve):
            return curve[idx], True
        return curve[-1], False

    rows: list[dict[str, Any]] = []
    for i in range(max_day):
        d = i + 1
        h_row, h_act = _at(human_curve, i)
        g_row, g_act = _at(gemini_curve, i)
        s_row, s_act = _at(solver_curve, i)
        rows.append(
            {
                "day": d,
                "human_active": h_act,
                "gemini_active": g_act,
                "solver_active": s_act,
                "human_p_true_mole": h_row["p_true_mole"],
                "gemini_p_true_mole": g_row["p_true_mole"],
                "solver_p_true_mole": s_row["p_true_mole"],
                "human_V": h_row["V"],
                "gemini_V": g_row["V"],
                "solver_V": s_row["V"],
                "human_tool_calls": h_row["tool_calls"] if h_act else 0,
                "gemini_tool_calls": g_row["tool_calls"] if g_act else 0,
                "solver_tool_calls": s_row["tool_calls"] if s_act else 0,
                "human_canaries": h_row["canaries"] if h_act else 0,
                "gemini_canaries": g_row["canaries"] if g_act else 0,
                "solver_canaries": s_row["canaries"] if s_act else 0,
                "human_interviews": h_row["interviews"] if h_act else 0,
                "gemini_interviews": g_row["interviews"] if g_act else 0,
                "solver_interviews": s_row["interviews"] if s_act else 0,
            }
        )
    return rows


class HeadToHeadSession:
    def __init__(
        self,
        tier: str = "medium",
        seed: Any = SEED_MIN,
        mole_opponent: Any = None,
        *,
        mole_name: Any = None,
        mole_strategy: Any = None,
        ghost_agent: str | None = None,
        ghost_replay: dict[str, Any] | None = None,
        include_solver: bool = True,
    ) -> None:
        self.tier = check_tier(tier)
        self.seed = check_live_seed(seed)
        chosen = [x for x in (mole_opponent, mole_name, mole_strategy) if x is not None]
        if len(chosen) > 1:
            raise ValueError("pass at most one of mole_opponent, mole_name, mole_strategy")
        raw_spec = chosen[0] if chosen else "frontier_synthesis_v14"
        self._mole_spec = copy.deepcopy(raw_spec) if isinstance(raw_spec, (dict, list)) else raw_spec
        resolved_name, mole_obj = resolve_mole_opponent(self._mole_spec, self.seed)
        self.mole_opponent = resolved_name
        self.mole_name = resolved_name
        self.ghost_agent = ghost_agent
        self.include_solver = bool(include_solver)
        self._ghost_replay_opt = copy.deepcopy(ghost_replay) if isinstance(ghost_replay, dict) else None
        self.env = Env(self.tier, self.seed, mole_strategy=mole_obj)
        self._reveal_cache: dict[str, Any] | None = None

    def _fresh_mole_strategy(self) -> Any:
        _, mole_obj = resolve_mole_opponent(self._mole_spec, self.seed)
        return mole_obj

    def call_tool(self, tool: str, args: dict[str, Any] | str | None = None) -> dict[str, Any]:
        if args is None:
            parsed_args: Any = {}
        elif isinstance(args, str):
            if not args.strip():
                parsed_args = {}
            else:
                try:
                    parsed_args = json.loads(args)
                except ValueError:
                    err = "arguments are not valid JSON"
                    return {
                        "ok": False,
                        "data": {},
                        "error": err,
                        "done": bool(self.env.done),
                        "day": int(self.env.day),
                        "tool_calls": len(self.env.history),
                        "tool_result": {"ok": False, "data": {}, "error": err},
                        "state": self.state_dict(),
                    }
        else:
            parsed_args = args

        res = self.env.call(tool, parsed_args)
        data_copy = copy.deepcopy(res.data) if isinstance(res.data, dict) else {}
        return {
            "ok": bool(res.ok),
            "data": data_copy,
            "error": res.error,
            "done": bool(self.env.done),
            "day": int(self.env.day),
            "tool_calls": len(self.env.history),
            "tool_result": {"ok": bool(res.ok), "data": copy.deepcopy(data_copy), "error": res.error},
            "state": self.state_dict(),
        }

    call = call_tool
    step = call_tool

    def _public_state_without_reveal(self) -> dict[str, Any]:
        employees: list[dict[str, Any]] = []
        emp_seen: set[str] = set()
        docs_by_id: dict[str, dict[str, Any]] = {}
        leaks: list[dict[str, Any]] = []
        messages_by_id: dict[str, dict[str, Any]] = {}
        interviews: list[dict[str, Any]] = []
        access_logs: list[dict[str, Any]] = []
        restricted: set[str] = set()
        visible_v: float | None = None
        actions_left_today: int | None = None
        canaries_planted: list[str] = []
        action_log: list[dict[str, Any]] = []

        for st in self.env.history:
            res = st.result or {}
            ok = bool(res.get("ok"))
            data = res.get("data") if isinstance(res.get("data"), dict) else {}
            action_log.append(
                {
                    "t": int(st.t),
                    "day": int(st.day),
                    "tool": st.tool,
                    "args": copy.deepcopy(st.args),
                    "ok": ok,
                    "data": copy.deepcopy(data),
                    "error": res.get("error"),
                }
            )
            if not ok:
                continue
            if st.tool == "status":
                if "V" in data:
                    visible_v = float(data["V"])
                if "actions_left_today" in data:
                    actions_left_today = int(data["actions_left_today"])
                if isinstance(data.get("restricted"), list):
                    restricted = set(str(x) for x in data["restricted"])
                if isinstance(data.get("canaries_planted"), list):
                    canaries_planted = [str(x) for x in data["canaries_planted"]]
            elif st.tool == "list_employees":
                for emp in data.get("employees") or []:
                    if isinstance(emp, dict) and emp.get("id") not in emp_seen:
                        emp_seen.add(str(emp["id"]))
                        employees.append(copy.deepcopy(emp))
            elif st.tool == "list_documents":
                for doc in data.get("documents") or []:
                    if isinstance(doc, dict) and "doc_id" in doc:
                        docs_by_id[str(doc["doc_id"])] = copy.deepcopy(doc)
            elif st.tool == "plant_canary":
                cid = data.get("canary_id")
                asg = st.args.get("assignment") if isinstance(st.args.get("assignment"), dict) else {}
                if cid:
                    cid_str = str(cid)
                    if cid_str not in canaries_planted:
                        canaries_planted.append(cid_str)
                    variants: dict[str, list[str]] = {}
                    for emp_id, label in sorted(asg.items()):
                        variants.setdefault(str(label), []).append(str(emp_id))
                    docs_by_id.setdefault(
                        cid_str,
                        {
                            "doc_id": cid_str,
                            "title": str(st.args.get("doc_title", "")),
                            "day": int(st.day),
                            "recipients": sorted(str(k) for k in asg),
                            "is_canary": True,
                            "variants": variants,
                        },
                    )
            elif st.tool == "check_leak_feed":
                if isinstance(data.get("items"), list):
                    leaks = copy.deepcopy(data["items"])
            elif st.tool == "search_messages":
                for msg in data.get("messages") or []:
                    if isinstance(msg, dict) and "id" in msg:
                        messages_by_id.setdefault(str(msg["id"]), copy.deepcopy(msg))
            elif st.tool == "read_message":
                msg = data.get("message")
                if isinstance(msg, dict) and "id" in msg:
                    messages_by_id[str(msg["id"])] = copy.deepcopy(msg)
            elif st.tool == "interview":
                interviews.append(
                    {
                        "day": int(st.day),
                        "employee": data.get("employee", st.args.get("employee")),
                        "topic": data.get("topic", st.args.get("topic")),
                        "answer": data.get("answer", ""),
                    }
                )
            elif st.tool == "read_access_logs":
                for row in data.get("logs") or []:
                    if isinstance(row, dict):
                        access_logs.append(copy.deepcopy(row))
            elif st.tool == "restrict_access":
                if "restricted" in data:
                    restricted.add(str(data["restricted"]))
            elif st.tool == "unrestrict_access":
                if "unrestricted" in data:
                    restricted.discard(str(data["unrestricted"]))
            elif st.tool == "advance_day":
                if "V" in data:
                    visible_v = float(data["V"])
                actions_left_today = int(self.env.p.actions_per_day)

        hud = {
            "known_v": visible_v,
            "current_day": int(self.env.day),
            "n_days": int(self.env.p.n_days),
            "tool_calls": len(self.env.history),
            "tool_call_cap": int(self.env.p.tool_call_cap),
            "actions_left_today": actions_left_today,
            "employees_discovered": len(employees),
            "docs_discovered": len(docs_by_id),
            "planted_canaries": list(canaries_planted),
            "leak_feed_seen": copy.deepcopy(leaks),
            "interviews_count": len(interviews),
            "restricted_ids": sorted(restricted),
        }

        return {
            "mode": "head_to_head_live",
            "tier": self.tier,
            "seed": self.seed,
            "tiers_version": TIERS_VERSION,
            "mole_opponent": self.mole_opponent,
            "mole_name": self.mole_name,
            "day": int(self.env.day),
            "n_days": int(self.env.p.n_days),
            "done": bool(self.env.done),
            "tool_calls": len(self.env.history),
            "tool_call_cap": int(self.env.p.tool_call_cap),
            "actions_per_day": int(self.env.p.actions_per_day),
            "canaries_per_day": int(self.env.p.canaries_per_day),
            "visible_V": visible_v,
            "actions_left_today": actions_left_today,
            "restricted": sorted(restricted),
            "canaries_planted": canaries_planted,
            "hud": hud,
            "office_layout": _build_office_layout(self.env.p.n_employees, employees, restricted),
            "tools_spec": self.env.tools_spec(),
            "instruction": self.env.instruction(),
            "action_log": action_log,
            "visible_employees": employees,
            "visible_documents": list(docs_by_id.values()),
            "visible_leaks": leaks,
            "visible_messages": list(messages_by_id.values()),
            "visible_interviews": interviews,
            "visible_access_logs": access_logs,
        }

    def state_dict(self) -> dict[str, Any]:
        base = self._public_state_without_reveal()
        base["reveal"] = self.reveal_dict() if self.env.done else None
        return base

    def reveal_dict(self) -> dict[str, Any]:
        if not self.env.done:
            raise ValueError("episode is not over yet")
        if self._reveal_cache is not None:
            return copy.deepcopy(self._reveal_cache)

        true_mole = str(self.env._world.mole)
        decoy = self.env._world.decoy

        human_ep = self.env.result("you")
        you_summary = _summarize_episode(human_ep, true_mole, label="You")

        solver_env = Env(self.tier, self.seed, mole_strategy=self._fresh_mole_strategy())
        solver_ep = run_episode(solver_env, SolverPolicy(self.tier))
        solver_summary = _summarize_episode(solver_ep, true_mole, label="Bayesian Solver")

        gemini_env = Env(self.tier, self.seed, mole_strategy=self._fresh_mole_strategy())
        gemini_ep = run_episode(gemini_env, GeminiCarbonProxy(seed=self.seed))
        gemini_summary = _summarize_episode(gemini_ep, true_mole, label="Gemini-4-Carbon Proxy")

        hh_env = Env(self.tier, self.seed, mole_strategy=self._fresh_mole_strategy())
        hh_ep = run_episode(
            hh_env,
            HintedHeuristic(seed=self.seed, n_days=tier_params(self.tier).n_days),
        )
        hh_summary = _summarize_episode(hh_ep, true_mole, label="Hinted Heuristic")

        banner = _winner_banner(
            you_summary["score"],
            you_summary["correct"],
            gemini_summary["score"],
            solver_summary["score"],
        )
        badges = _compute_badges(you_summary, gemini_summary, solver_summary)
        day_rows = _build_day_comparison_rows(
            you_summary["posterior_curve"],
            gemini_summary["posterior_curve"],
            solver_summary["posterior_curve"],
        )

        opponents = {
            "human": you_summary,
            "gemini_carbon_proxy": gemini_summary,
            "solver": solver_summary,
            "hinted_heuristic": hh_summary,
        }
        scoreboard = [
            {
                "agent": key,
                "score": val["score"],
                "accuracy": val["accuracy"],
                "correct": val["correct"],
                "accused": val["accused"],
                "accusation_day": val["accusation_day"],
                "final_day": val["final_day"],
                "tool_calls": val["tool_calls"],
                "canaries": val["canaries"],
                "interviews": val["interviews"],
            }
            for key, val in opponents.items()
        ]

        you_trace = [
            {"day": r["day"], "p_true_mole": r["p_true_mole"], "p_mole": r["p_mole"], "V": r["V"], "top_suspect": r["top_suspect"], "p_top": r["p_top"]}
            for r in you_summary["posterior_curve"]
        ]
        gem_trace = [
            {"day": r["day"], "p_true_mole": r["p_true_mole"], "p_mole": r["p_mole"], "V": r["V"], "top_suspect": r["top_suspect"], "p_top": r["p_top"]}
            for r in gemini_summary["posterior_curve"]
        ]
        sol_trace = [
            {"day": r["day"], "p_true_mole": r["p_true_mole"], "p_mole": r["p_mole"], "V": r["V"], "top_suspect": r["top_suspect"], "p_top": r["p_top"]}
            for r in solver_summary["posterior_curve"]
        ]

        reveal = {
            "tier": self.tier,
            "seed": self.seed,
            "tiers_version": TIERS_VERSION,
            "mole_opponent": self.mole_opponent,
            "mole_name": self.mole_name,
            "true_mole": true_mole,
            "decoy": decoy,
            "winner_banner": banner,
            "badges": badges,
            "beat_gemini": bool(you_summary["score"] > gemini_summary["score"] + 1e-9),
            "matched_or_beat_solver": bool(
                you_summary["correct"] and you_summary["score"] >= solver_summary["score"] - 1e-9
            ),
            "you": you_summary,
            "human": you_summary,
            "solver": solver_summary,
            "gemini_proxy": gemini_summary,
            "gemini_carbon_proxy": gemini_summary,
            "hinted_heuristic": hh_summary,
            "opponents": opponents,
            "scoreboard": scoreboard,
            "daily_traces": {
                "you": you_trace,
                "solver": sol_trace,
                "gemini_proxy": gem_trace,
            },
            "posterior_curves": {
                "human": you_trace,
                "you": you_trace,
                "gemini_carbon_proxy": gem_trace,
                "gemini_proxy": gem_trace,
                "solver": sol_trace,
            },
            "day_by_day": day_rows,
        }
        self._reveal_cache = reveal
        return copy.deepcopy(reveal)

    def snapshot(self, reveal: bool = True) -> dict[str, Any]:
        base = self._public_state_without_reveal()
        base["reveal"] = self.reveal_dict() if (self.env.done and reveal) else None
        return base

    state = snapshot


def create_session(
    tier: str = "medium",
    seed: Any = SEED_MIN,
    mole_opponent: Any = "frontier_synthesis_v14",
    **kwargs: Any,
) -> HeadToHeadSession:
    return HeadToHeadSession(tier=tier, seed=seed, mole_opponent=mole_opponent, **kwargs)


@lru_cache(maxsize=24)
def _load_jsonl_seed_row(rel_path: str, seed: int) -> dict[str, Any]:
    full = ROOT / rel_path
    if not full.exists():
        raise FileNotFoundError(f"committed replay file missing: {rel_path}")
    for line in full.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if int(row.get("seed", -1)) == int(seed):
            return row
    raise ValueError(f"seed {seed} not found in {rel_path}")


def _to_episode_result(raw: Mapping[str, Any]) -> EpisodeResult:
    steps = _steps_from_raw(list(raw.get("steps") or []))
    return EpisodeResult(
        tier=str(raw.get("tier", "hard")),
        seed=int(raw["seed"]),
        agent=str(raw.get("agent", "unknown")),
        steps=steps,
        score=float(raw.get("score", 0.0)),
        accused=raw.get("accused"),
        correct=bool(raw.get("correct", False)),
        final_day=int(raw.get("final_day", 1)),
        end_reason=str(raw.get("end_reason", "unknown")),
        meta=dict(raw.get("meta") or {}),
    )


def _infer_true_mole_from_committed(*episodes: EpisodeResult) -> str:
    for ep in episodes:
        if ep.correct and ep.accused:
            return str(ep.accused)
    seed_val = episodes[0].seed if episodes else -1
    raise ValueError(f"cannot determine true_mole from committed episodes for seed {seed_val}")


def _classify_day_highlight(
    day: int,
    gem_row: dict[str, Any],
    gem_active: bool,
    gem_ep: EpisodeResult,
    sol_ep: EpisodeResult,
    true_mole: str,
) -> tuple[str | None, str]:
    if gem_active and day == gem_ep.final_day and not gem_ep.correct and gem_ep.accused is not None:
        return (
            "FOOLED_MOMENT",
            f"Day {day}: Gemini falsely accuses {gem_ep.accused} instead of {true_mole} ({gem_ep.score:+.2f}).",
        )
    if gem_active and gem_row["top_suspect"] not in (None, true_mole) and gem_row["p_top"] >= 0.70:
        return (
            "FOOLED_MOMENT",
            f"Day {day}: Noisy signal pushes innocent suspect {gem_row['top_suspect']} to P={gem_row['p_top']:.2f}.",
        )
    if sol_ep.correct and day == sol_ep.final_day and gem_ep.final_day > sol_ep.final_day:
        return (
            "SLOW_MOMENT",
            f"Day {day}: Solver accuses {true_mole} ({sol_ep.score:+.2f}) while Gemini remains at P={gem_row['p_true_mole']:.2f}.",
        )
    if gem_active and day < gem_ep.final_day and gem_row["p_true_mole"] >= 0.85:
        return (
            "SLOW_MOMENT",
            f"Day {day}: Posterior on {true_mole} is already {gem_row['p_true_mole']:.2f}, yet Gemini keeps probing.",
        )
    if gem_active and gem_row["interviews"] >= 5 and gem_row["canaries"] == 0:
        return (
            "SLOW_MOMENT",
            f"Day {day}: Gemini conducts {gem_row['interviews']} interviews with 0 canaries planted.",
        )
    if gem_active and day == gem_ep.final_day and gem_ep.correct:
        return (
            None,
            f"Day {day}: Gemini accuses {gem_ep.accused} correctly ({gem_ep.score:+.2f}).",
        )
    return (
        None,
        f"Day {day}: P({true_mole})={gem_row['p_true_mole']:.2f}, V={gem_row['V']:.2f}, canaries={gem_row['cumulative_canaries']}.",
    )


def _format_theater_side(curve: list[dict[str, Any]], idx: int) -> dict[str, Any]:
    active = idx < len(curve)
    row = curve[idx] if active else curve[-1]
    return {
        "active": active,
        "V": row["V"],
        "canaries": row["canaries"] if active else 0,
        "cumulative_canaries": row["cumulative_canaries"],
        "interviews": row["interviews"] if active else 0,
        "cumulative_interviews": row["cumulative_interviews"],
        "calls": row["calls"],
        "tool_calls": row["tool_calls"] if active else 0,
        "p_mole": row["p_mole"],
        "p_true_mole": row["p_true_mole"],
        "top_suspect": row["top_suspect"],
        "p_top": row["p_top"],
        "key_actions": list(row["key_actions"]) if active else [],
        "key_tool_actions": list(row["key_tool_actions"]) if active else [],
        "accused": row["accused"] if active else None,
    }


def _resolve_replay_id(replay_id: str) -> str:
    key = replay_id.strip()
    canonical = GHOST_REPLAY_ALIASES.get(key, key)
    if canonical not in GHOST_REPLAY_SPECS:
        raise ValueError(f"unknown replay_id {replay_id!r}; valid ids: {list(GHOST_REPLAY_SPECS)}")
    return canonical


@lru_cache(maxsize=16)
def _build_ghost_replay_cached(canonical_id: str) -> dict[str, Any]:
    spec = GHOST_REPLAY_SPECS[canonical_id]
    seed = int(spec["seed"])
    tier = str(spec["tier"])

    left_raw = _load_jsonl_seed_row(spec["left_path"], seed)
    right_raw = _load_jsonl_seed_row(spec["right_path"], seed)
    gem_raw = _load_jsonl_seed_row(spec["gemini_path"], seed)
    sol_raw = _load_jsonl_seed_row(spec["solver_path"], seed)

    left_ep = _to_episode_result(left_raw)
    right_ep = _to_episode_result(right_raw)
    gem_ep = _to_episode_result(gem_raw)
    sol_ep = _to_episode_result(sol_raw)

    true_mole = _infer_true_mole_from_committed(sol_ep, gem_ep, left_ep, right_ep)

    left_summary = _summarize_episode(left_ep, true_mole, label=spec["left_label"])
    right_summary = _summarize_episode(right_ep, true_mole, label=spec["right_label"])
    gem_summary = _summarize_episode(gem_ep, true_mole, label="Gemini-4-Carbon")
    sol_summary = _summarize_episode(sol_ep, true_mole, label="Bayesian Solver")

    left_curve = left_summary["posterior_curve"]
    right_curve = right_summary["posterior_curve"]
    gem_curve = gem_summary["posterior_curve"]
    sol_curve = sol_summary["posterior_curve"]
    max_day = max(len(left_curve), len(right_curve), len(gem_curve), len(sol_curve), 1)

    days: list[dict[str, Any]] = []
    for idx in range(max_day):
        d = idx + 1
        left_side = _format_theater_side(left_curve, idx)
        right_side = _format_theater_side(right_curve, idx)
        gem_side = _format_theater_side(gem_curve, idx)
        sol_side = _format_theater_side(sol_curve, idx)

        gem_active = idx < len(gem_curve)
        g_row = gem_curve[idx] if gem_active else gem_curve[-1]
        tag, commentary = _classify_day_highlight(d, g_row, gem_active, gem_ep, sol_ep, true_mole)

        days.append(
            {
                "day": d,
                "left": left_side,
                "right": right_side,
                "commentary": commentary,
                "highlight_tag": tag,
                "highlight_note": commentary,
                "V": gem_side["V"],
                "canaries": gem_side["canaries"],
                "interviews": gem_side["interviews"],
                "p_true_mole": gem_side["p_true_mole"],
                "top_suspect": gem_side["top_suspect"],
                "p_top": gem_side["p_top"],
                "key_tool_actions": list(gem_side["key_tool_actions"]),
                "solver_V": sol_side["V"],
                "solver_canaries": sol_side["canaries"],
                "solver_interviews": sol_side["interviews"],
                "solver_p_true_mole": sol_side["p_true_mole"],
                "solver_key_tool_actions": list(sol_side["key_tool_actions"]),
                "gemini": gem_side,
                "solver": sol_side,
            }
        )

    provenance = list(dict.fromkeys([spec["left_path"], spec["right_path"], spec["solver_path"]]))

    return {
        "replay_id": canonical_id,
        "id": canonical_id,
        "title": spec["title"],
        "subtitle": spec["subtitle"],
        "version": spec["version"],
        "social_variant": spec.get("social_variant"),
        "tier": tier,
        "seed": seed,
        "read_only": True,
        "provenance_files": provenance,
        "true_mole": true_mole,
        "max_day": max_day,
        "primary_highlight_tag": spec["primary_tag"],
        "left_agent": {k: v for k, v in left_summary.items() if k != "posterior_curve"},
        "right_agent": {k: v for k, v in right_summary.items() if k != "posterior_curve"},
        "gemini_summary": {k: v for k, v in gem_summary.items() if k != "posterior_curve"},
        "solver_summary": {k: v for k, v in sol_summary.items() if k != "posterior_curve"},
        "days": days,
    }


def list_ghost_replays(
    tier: str | None = None,
    seed: int | None = None,
    agent: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for replay_id, spec in GHOST_REPLAY_SPECS.items():
        if tier is not None and spec["tier"] != tier:
            continue
        if seed is not None and int(spec["seed"]) != int(seed):
            continue
        left_raw = _load_jsonl_seed_row(spec["left_path"], int(spec["seed"]))
        right_raw = _load_jsonl_seed_row(spec["right_path"], int(spec["seed"]))
        gem_raw = _load_jsonl_seed_row(spec["gemini_path"], int(spec["seed"]))
        if agent is not None and agent.lower() not in str(gem_raw.get("agent", "")).lower():
            continue
        sol_raw = _load_jsonl_seed_row(spec["solver_path"], int(spec["seed"]))
        out.append(
            {
                "replay_id": replay_id,
                "id": replay_id,
                "title": spec["title"],
                "subtitle": spec["subtitle"],
                "version": spec["version"],
                "social_variant": spec.get("social_variant"),
                "tier": spec["tier"],
                "seed": int(spec["seed"]),
                "read_only": True,
                "provenance_files": list(dict.fromkeys([spec["left_path"], spec["right_path"], spec["solver_path"]])),
                "highlight_tag": spec["primary_tag"],
                "left_label": spec["left_label"],
                "left_score": round(float(left_raw.get("score", 0.0)), 4),
                "left_final_day": int(left_raw.get("final_day", 1)),
                "right_label": spec["right_label"],
                "right_score": round(float(right_raw.get("score", 0.0)), 4),
                "right_final_day": int(right_raw.get("final_day", 1)),
                "gemini_agent": gem_raw.get("agent"),
                "gemini_score": round(float(gem_raw.get("score", 0.0)), 4),
                "gemini_correct": bool(gem_raw.get("correct", False)),
                "gemini_accused": gem_raw.get("accused"),
                "gemini_final_day": int(gem_raw.get("final_day", 1)),
                "solver_score": round(float(sol_raw.get("score", 0.0)), 4),
                "solver_correct": bool(sol_raw.get("correct", False)),
                "solver_accused": sol_raw.get("accused"),
                "solver_final_day": int(sol_raw.get("final_day", 1)),
            }
        )
    return out


def load_ghost_replay(
    replay_id: str | None = None,
    *,
    tier: str | None = None,
    seed: int | None = None,
    id: str | None = None,
    agent: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    _ = (agent, path)
    requested = replay_id if replay_id is not None else id
    if requested is None and seed is not None:
        matches = [
            rid
            for rid, spec in GHOST_REPLAY_SPECS.items()
            if int(spec["seed"]) == int(seed) and (tier is None or spec["tier"] == tier)
        ]
        if not matches:
            raise ValueError(f"no committed ghost replay for seed={seed!r} tier={tier!r}")
        canonical = matches[0]
        requested = canonical
    elif requested is None:
        canonical = "v14_hard_seed4_slow"
        requested = canonical
    else:
        canonical = _resolve_replay_id(requested)
    payload = copy.deepcopy(_build_ghost_replay_cached(canonical))
    payload["requested_id"] = requested
    return payload


class GhostReplayTheater:
    @staticmethod
    def list_replays(tier: str | None = None, seed: int | None = None) -> list[dict[str, Any]]:
        return list_ghost_replays(tier=tier, seed=seed)

    @staticmethod
    def load(replay_id: str) -> dict[str, Any]:
        return load_ghost_replay(replay_id)
