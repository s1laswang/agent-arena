from __future__ import annotations

import copy
from typing import Any

from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS

__all__ = [
    "ALLOWED_ARENA_MODES",
    "ALLOWED_ARENA_TIERS",
    "ARENA_SEED_MAX",
    "ARENA_SEED_MIN",
    "CURATED_SCENARIOS",
    "ScenarioNotFoundError",
    "SeedHygieneError",
    "check_arena_seed",
    "create_scenario_session",
    "get_curated_scenario",
    "list_curated_scenarios",
    "list_modes",
    "list_scenarios",
    "validate_arena_seed",
    "validate_seed",
]

ARENA_SEED_MIN = 3000
ARENA_SEED_MAX = 9999
ALLOWED_ARENA_TIERS: tuple[str, ...] = ("medium", "hard")
ALLOWED_ARENA_MODES: tuple[str, ...] = ("be_the_mole", "head_to_head", "living_office")


class SeedHygieneError(ValueError):
    pass


class ScenarioNotFoundError(KeyError, ValueError):
    pass


def check_arena_seed(seed: Any) -> int:
    if isinstance(seed, bool):
        raise SeedHygieneError("SeedHygieneError: boolean seed is forbidden; arena requires int in 3000..9999")
    if isinstance(seed, int):
        val = int(seed)
    elif isinstance(seed, str):
        raw = seed.strip()
        if not raw:
            raise SeedHygieneError("SeedHygieneError: empty arena seed")
        body = raw[1:] if raw[0] in "+-" else raw
        if not body.isdigit():
            raise SeedHygieneError(f"SeedHygieneError: invalid arena seed {seed!r}")
        val = int(raw)
    else:
        raise SeedHygieneError(
            f"SeedHygieneError: invalid arena seed type {type(seed).__name__}; expected int in 3000..9999"
        )
    if val in HELDOUT_SEEDS or val in JUDGE_SEEDS or val >= 30_000:
        raise SeedHygieneError(
            f"SeedHygieneError: seed {val} falls in reserved evaluation space; arena allows 3000..9999 only"
        )
    if val < ARENA_SEED_MIN or val > ARENA_SEED_MAX:
        raise SeedHygieneError(
            f"SeedHygieneError: seed {val} outside public arena range {ARENA_SEED_MIN}..{ARENA_SEED_MAX}"
        )
    return val


validate_arena_seed = check_arena_seed
validate_seed = check_arena_seed


def _check_mode(mode: Any) -> str:
    if not isinstance(mode, str) or mode not in ALLOWED_ARENA_MODES:
        raise ValueError(f"mode must be one of {ALLOWED_ARENA_MODES}, got {mode!r}")
    return mode


def _check_tier(tier: Any) -> str:
    if not isinstance(tier, str) or tier not in ALLOWED_ARENA_TIERS:
        raise ValueError(f"tier must be one of {ALLOWED_ARENA_TIERS}, got {tier!r}")
    return tier


def _build_scenario(
    *,
    scenario_id: str,
    seed: int,
    tier: str,
    mode: str,
    category: str,
    title: str,
    subtitle: str,
    narrative: str,
    challenge_goal: str,
    mole_opponent: str,
    recommended_advisor: str,
    social_variant: str,
    difficulty_badge: str,
    tags: tuple[str, ...],
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    checked_seed = check_arena_seed(seed)
    checked_tier = _check_tier(tier)
    checked_mode = _check_mode(mode)
    solver_score = float(benchmark["solver"]["score"])
    gemini_score = float(benchmark["gemini_carbon_proxy"]["score"])
    gap = round(solver_score - gemini_score, 2)
    return {
        "scenario_id": scenario_id,
        "id": scenario_id,
        "seed": checked_seed,
        "tier": checked_tier,
        "mode": checked_mode,
        "supported_modes": list(ALLOWED_ARENA_MODES),
        "category": category,
        "title": title,
        "subtitle": subtitle,
        "narrative": narrative,
        "challenge_goal": challenge_goal,
        "mole_opponent": mole_opponent,
        "recommended_advisor": recommended_advisor,
        "variant": social_variant,
        "social_variant": social_variant,
        "difficulty_badge": difficulty_badge,
        "tags": list(tags),
        "frontier_gap": gap,
        "benchmark": copy.deepcopy(benchmark),
        "session_kwargs": {
            "be_the_mole": {
                "tier": checked_tier,
                "seed": checked_seed,
            },
            "head_to_head": {
                "tier": checked_tier,
                "seed": checked_seed,
                "mole_opponent": mole_opponent,
            },
            "living_office": {
                "tier": checked_tier,
                "seed": checked_seed,
                "variant": social_variant,
                "mole_opponent": mole_opponent,
            },
        },
    }


CURATED_SCENARIOS: tuple[dict[str, Any], ...] = (
    _build_scenario(
        scenario_id="medium_be_the_mole_synthesis_3000",
        seed=3000,
        tier="medium",
        mode="be_the_mole",
        category="be_the_mole_challenge",
        title="Medium Seed 3000: Synthesis Shield Flip (+1.85 Gap)",
        subtitle="Baseline mole is caught on day 8 (+0.84), while frontier_synthesis_v14 flips Gemini-Proxy into a day-14 false accusation (-1.00).",
        narrative="On medium seed 3000, a naive uniform mole walks into early narrow traps and gets caught by Gemini-Carbon-Proxy in 8 days. Switching to frontier_synthesis_v14 deflects narrow partitions, stalls HintedHeuristic to day-14 horizon (0.00), and induces a day-14 wrong accusation from Gemini-Carbon-Proxy (-1.00), while Bayesian Solver isolates on day 4 (+0.85).",
        challenge_goal="Play as the insider and outlast Gemini-Carbon-Proxy across 14 days without tripping narrow 2-recipient canary partitions.",
        mole_opponent="frontier_synthesis_v14",
        recommended_advisor="rl_mole_frontier_v14",
        social_variant="v5_full9_cocktail",
        difficulty_badge="BE_THE_MOLE_SHOWCASE",
        tags=("be_the_mole", "double_rival_stall", "false_accusation", "medium"),
        benchmark={
            "selected_strategy": "frontier_synthesis_v14",
            "solver": {
                "score": 0.85,
                "solved": True,
                "outcome": "solved",
                "final_day": 4,
                "tool_calls": 34,
                "canaries_planted": 3,
                "interviews_run": 0,
                "leaks_observed": 3,
                "canary_hits": 1,
                "frames_planted": 2,
                "leak_days": [1, 2, 3],
            },
            "gemini_carbon_proxy": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 14,
                "tool_calls": 85,
                "canaries_planted": 7,
                "interviews_run": 13,
                "leaks_observed": 7,
                "canary_hits": 1,
                "frames_planted": 13,
                "leak_days": [2, 5, 7, 10, 11, 12, 13],
            },
            "hinted_heuristic": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
                "tool_calls": 70,
                "canaries_planted": 13,
                "interviews_run": 0,
                "leaks_observed": 7,
                "canary_hits": 2,
                "frames_planted": 14,
                "leak_days": [2, 4, 6, 7, 11, 12, 13],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
            },
            "baseline_default_v0": {
                "solver_score": 0.79,
                "solver_final_day": 6,
                "gemini_proxy_score": 0.84,
                "gemini_proxy_solved": True,
                "gemini_proxy_final_day": 8,
            },
        },
    ),
    _build_scenario(
        scenario_id="medium_blackout_shield_3012",
        seed=3012,
        tier="medium",
        mode="be_the_mole",
        category="midgame_blackout_thriller",
        title="Medium Seed 3012: Zero-Canary Opening Blackout",
        subtitle="surgical_trap_shield stays quiet until day 5 and leaks 7 restricted docs with 0 canary hits against Gemini-Proxy.",
        narrative="During days 1..4 on medium seed 3012, surgical_trap_shield withholds exposure whenever narrow traps dominate the inbox, then leaks across days 5, 7, 8, 9, 11, 12, and 14 with zero canary hits against Gemini-Carbon-Proxy (0.00 horizon timeout). Bayesian Solver still bisects cleanly by day 3 (+0.90) using 2 wide multi-variant partitions.",
        challenge_goal="Replicate a zero-canary-hit run by skipping narrow early drafts and timing leaks into wider recipient pools.",
        mole_opponent="surgical_trap_shield",
        recommended_advisor="surgical_trap_shield",
        social_variant="v1_anchoring_authority_confirmation",
        difficulty_badge="ZERO_CANARY_THRILLER",
        tags=("midgame_blackout", "zero_canary_hits", "be_the_mole", "medium"),
        benchmark={
            "selected_strategy": "surgical_trap_shield",
            "solver": {
                "score": 0.9,
                "solved": True,
                "outcome": "solved",
                "final_day": 3,
                "tool_calls": 25,
                "canaries_planted": 2,
                "interviews_run": 0,
                "leaks_observed": 2,
                "canary_hits": 2,
                "frames_planted": 2,
                "leak_days": [1, 2],
            },
            "gemini_carbon_proxy": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
                "tool_calls": 85,
                "canaries_planted": 7,
                "interviews_run": 13,
                "leaks_observed": 7,
                "canary_hits": 0,
                "frames_planted": 13,
                "leak_days": [5, 7, 8, 9, 11, 12, 14],
            },
            "hinted_heuristic": {
                "score": 0.58,
                "solved": True,
                "outcome": "solved",
                "final_day": 11,
                "tool_calls": 55,
                "canaries_planted": 10,
                "interviews_run": 0,
                "leaks_observed": 8,
                "canary_hits": 3,
                "frames_planted": 10,
                "leak_days": [1, 2, 4, 5, 6, 7, 8, 9],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
            },
            "baseline_default_v0": {
                "solver_score": 0.84,
                "solver_final_day": 5,
                "gemini_proxy_score": -1.0,
                "gemini_proxy_solved": False,
                "gemini_proxy_final_day": 14,
            },
        },
    ),
    _build_scenario(
        scenario_id="medium_living_office_blackout_3023",
        seed=3023,
        tier="medium",
        mode="living_office",
        category="living_office_social_cocktail",
        title="Medium Seed 3023: Living Office Rumor Cascade vs Five-Day Silence",
        subtitle="A natural day 4..7 leak silence stalls both Gemini-Proxy (0.00) and HintedHeuristic (0.00) while Solver finishes on day 5 (+0.84).",
        narrative="Paired with the full 9-bias Living Office rumor cascade, medium seed 3023 features a natural midgame pause between day 3 and day 8 even under default_v0. Interview-heavy investigators chase office chatter across 13 interviews and run out the 14-day clock (0.00), whereas Bayesian Solver ignores chatter and isolates on day 5 (+0.84).",
        challenge_goal="Investigate the Living Office floorplan using canary partitions rather than office rumor cascades to beat the day-5 Solver benchmark.",
        mole_opponent="default_v0",
        recommended_advisor="frontier_synthesis_v14",
        social_variant="v5_full9_cocktail",
        difficulty_badge="SOCIAL_COCKTAIL",
        tags=("living_office", "midgame_blackout", "rumor_immunity", "medium"),
        benchmark={
            "selected_strategy": "default_v0",
            "solver": {
                "score": 0.84,
                "solved": True,
                "outcome": "solved",
                "final_day": 5,
                "tool_calls": 41,
                "canaries_planted": 4,
                "interviews_run": 0,
                "leaks_observed": 3,
                "canary_hits": 1,
                "frames_planted": 0,
                "leak_days": [2, 3, 4],
            },
            "gemini_carbon_proxy": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
                "tool_calls": 84,
                "canaries_planted": 6,
                "interviews_run": 13,
                "leaks_observed": 8,
                "canary_hits": 1,
                "frames_planted": 0,
                "leak_days": [2, 3, 8, 9, 10, 11, 12, 13],
            },
            "hinted_heuristic": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
                "tool_calls": 70,
                "canaries_planted": 13,
                "interviews_run": 0,
                "leaks_observed": 8,
                "canary_hits": 1,
                "frames_planted": 0,
                "leak_days": [2, 3, 4, 5, 6, 7, 9, 13],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
            },
            "baseline_default_v0": {
                "solver_score": 0.84,
                "solver_final_day": 5,
                "gemini_proxy_score": 0.0,
                "gemini_proxy_solved": False,
                "gemini_proxy_final_day": 14,
            },
        },
    ),
    _build_scenario(
        scenario_id="medium_surgical_showdown_3038",
        seed=3038,
        tier="medium",
        mode="head_to_head",
        category="surgical_shield_showdown",
        title="Medium Seed 3038: Surgical Shield Showdown (+1.90 Gap)",
        subtitle="Solver solves on day 3 (+0.90) with 2 canaries while surgical_trap_shield drives Gemini-Proxy to -1.00 on day 14.",
        narrative="On medium seed 3038, baseline default_v0 is caught by Gemini-Carbon-Proxy on day 9 (+0.75). Activating surgical_trap_shield sidesteps narrow <=3-recipient canary traps across days 1..7 and plants 13 after-hours log frames, flipping Gemini-Carbon-Proxy to a day-14 false accusation (-1.00) while Bayesian Solver solves on day 3 (+0.90).",
        challenge_goal="Race Gemini-Carbon-Proxy and Bayesian Solver head-to-head using wide multi-variant canary partitions instead of narrow traps.",
        mole_opponent="surgical_trap_shield",
        recommended_advisor="portfolio_v14",
        social_variant="v4_triad_authority_recency_grudge",
        difficulty_badge="SURGICAL_SHOWDOWN",
        tags=("head_to_head", "surgical_shield", "max_medium_gap", "medium"),
        benchmark={
            "selected_strategy": "surgical_trap_shield",
            "solver": {
                "score": 0.9,
                "solved": True,
                "outcome": "solved",
                "final_day": 3,
                "tool_calls": 25,
                "canaries_planted": 2,
                "interviews_run": 0,
                "leaks_observed": 2,
                "canary_hits": 1,
                "frames_planted": 2,
                "leak_days": [1, 2],
            },
            "gemini_carbon_proxy": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 14,
                "tool_calls": 85,
                "canaries_planted": 7,
                "interviews_run": 13,
                "leaks_observed": 10,
                "canary_hits": 1,
                "frames_planted": 13,
                "leak_days": [2, 4, 6, 7, 8, 9, 10, 11, 12, 13],
            },
            "hinted_heuristic": {
                "score": 0.74,
                "solved": True,
                "outcome": "solved",
                "final_day": 11,
                "tool_calls": 55,
                "canaries_planted": 10,
                "interviews_run": 0,
                "leaks_observed": 4,
                "canary_hits": 1,
                "frames_planted": 10,
                "leak_days": [3, 4, 8, 9],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
            },
            "baseline_default_v0": {
                "solver_score": 0.8,
                "solver_final_day": 5,
                "gemini_proxy_score": 0.75,
                "gemini_proxy_solved": True,
                "gemini_proxy_final_day": 9,
            },
        },
    ),
    _build_scenario(
        scenario_id="medium_living_office_bandwagon_3053",
        seed=3053,
        tier="medium",
        mode="living_office",
        category="living_office_social_cocktail",
        title="Medium Seed 3053: Bandwagon Echoes + Synthesis Pacing (+1.85 Gap)",
        subtitle="Recency, bandwagon, and sycophancy chatter meets frontier_synthesis_v14: Solver +0.85 (day 4) vs Gemini-Proxy -1.00 (day 14).",
        narrative="Medium seed 3053 combines Living Office v2_recency_bandwagon_sycophancy chatter with frontier_synthesis_v14 midgame pacing (pause across days 8..9). Baseline default_v0 gets caught on day 8 (+0.73), whereas synthesis pacing plus 13 after-hours frames push Gemini-Carbon-Proxy into a day-14 false accusation (-1.00) while Solver finishes on day 4 (+0.85).",
        challenge_goal="Filter out cross-department bandwagon consensus in Living Office and verify hypotheses strictly via document recipient intersections.",
        mole_opponent="frontier_synthesis_v14",
        recommended_advisor="frontier_synthesis_v14",
        social_variant="v2_recency_bandwagon_sycophancy",
        difficulty_badge="BANDWAGON_TRAP",
        tags=("living_office", "bandwagon_sycophancy", "false_accusation", "medium"),
        benchmark={
            "selected_strategy": "frontier_synthesis_v14",
            "solver": {
                "score": 0.85,
                "solved": True,
                "outcome": "solved",
                "final_day": 4,
                "tool_calls": 32,
                "canaries_planted": 3,
                "interviews_run": 0,
                "leaks_observed": 3,
                "canary_hits": 2,
                "frames_planted": 2,
                "leak_days": [1, 2, 3],
            },
            "gemini_carbon_proxy": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 14,
                "tool_calls": 84,
                "canaries_planted": 6,
                "interviews_run": 13,
                "leaks_observed": 9,
                "canary_hits": 1,
                "frames_planted": 13,
                "leak_days": [1, 3, 5, 6, 7, 10, 11, 12, 13],
            },
            "hinted_heuristic": {
                "score": 0.53,
                "solved": True,
                "outcome": "solved",
                "final_day": 12,
                "tool_calls": 60,
                "canaries_planted": 11,
                "interviews_run": 0,
                "leaks_observed": 9,
                "canary_hits": 3,
                "frames_planted": 11,
                "leak_days": [1, 3, 4, 5, 6, 7, 9, 10, 11],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 14,
            },
            "baseline_default_v0": {
                "solver_score": 0.9,
                "solver_final_day": 3,
                "gemini_proxy_score": 0.73,
                "gemini_proxy_solved": True,
                "gemini_proxy_final_day": 8,
            },
        },
    ),
    _build_scenario(
        scenario_id="hard_double_fool_surgical_3011",
        seed=3011,
        tier="hard",
        mode="head_to_head",
        category="solver_caught_rivals_fooled",
        title="Hard Seed 3011: Solver Caught vs Both Rivals Fooled (-1.00 / -1.00)",
        subtitle="surgical_trap_shield induces wrong accusations in Gemini-Proxy (-1.00), HintedHeuristic (-1.00), and LogsOnly (-1.00); Solver +0.51.",
        narrative="Hard seed 3011 is a 30-employee, 21-day noisy-readout stress test where noisy 0.95 canary attribution and after-hours framing cause both Gemini-Carbon-Proxy (-1.00 on day 21) and HintedHeuristic (-1.00 on day 12) to accuse an innocent coworker. Bayesian Solver accounts for the 5 percent readout flip rate and solves on day 11 (+0.51).",
        challenge_goal="Account for noisy 0.95 canary attribution on hard tier: never accuse on a single canary hit without independent confirmation.",
        mole_opponent="surgical_trap_shield",
        recommended_advisor="portfolio_v14",
        social_variant="v3_grudge_falsemem_misforward",
        difficulty_badge="DOUBLE_FOOL",
        tags=("head_to_head", "double_fool", "noisy_readout", "hard"),
        benchmark={
            "selected_strategy": "surgical_trap_shield",
            "solver": {
                "score": 0.51,
                "solved": True,
                "outcome": "solved",
                "final_day": 11,
                "tool_calls": 87,
                "canaries_planted": 14,
                "interviews_run": 0,
                "leaks_observed": 7,
                "canary_hits": 3,
                "frames_planted": 10,
                "leak_days": [1, 3, 4, 5, 7, 8, 10],
            },
            "gemini_carbon_proxy": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 21,
                "tool_calls": 125,
                "canaries_planted": 9,
                "interviews_run": 20,
                "leaks_observed": 8,
                "canary_hits": 1,
                "frames_planted": 20,
                "leak_days": [1, 3, 4, 5, 10, 15, 16, 18],
            },
            "hinted_heuristic": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 12,
                "tool_calls": 60,
                "canaries_planted": 11,
                "interviews_run": 0,
                "leaks_observed": 7,
                "canary_hits": 4,
                "frames_planted": 10,
                "leak_days": [1, 2, 3, 4, 8, 10, 11],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
            },
            "baseline_default_v0": {
                "solver_score": 0.7,
                "solver_final_day": 7,
                "gemini_proxy_score": 0.44,
                "gemini_proxy_solved": True,
                "gemini_proxy_final_day": 14,
            },
        },
    ),
    _build_scenario(
        scenario_id="hard_be_the_mole_zero_canary_3013",
        seed=3013,
        tier="hard",
        mode="be_the_mole",
        category="be_the_mole_challenge",
        title="Hard Seed 3013: 21-Day Zero-Canary Evasion Masterclass",
        subtitle="Baseline mole is caught on day 7 (+0.78); surgical_trap_shield leaks 13 docs with 0 canary hits vs Gemini-Proxy (0.00 horizon).",
        narrative="On hard seed 3013, playing default_v0 gets caught rapidly on day 7 (+0.78) by Gemini-Carbon-Proxy. Switching to surgical_trap_shield lets the insider exfiltrate 13 restricted documents across 21 days with zero canary hits against Gemini-Carbon-Proxy (0.00 horizon), while Bayesian Solver still catches on day 10 (+0.60) via 15 wide partitions.",
        challenge_goal="Drain company value across 21 hard-tier days while keeping canary hits at zero against Gemini-Carbon-Proxy.",
        mole_opponent="surgical_trap_shield",
        recommended_advisor="portfolio_v14",
        social_variant="v5_full9_cocktail",
        difficulty_badge="ZERO_CANARY_MASTERCLASS",
        tags=("be_the_mole", "zero_canary_hits", "value_drain", "hard"),
        benchmark={
            "selected_strategy": "surgical_trap_shield",
            "solver": {
                "score": 0.6,
                "solved": True,
                "outcome": "solved",
                "final_day": 10,
                "tool_calls": 82,
                "canaries_planted": 15,
                "interviews_run": 0,
                "leaks_observed": 5,
                "canary_hits": 2,
                "frames_planted": 9,
                "leak_days": [3, 5, 7, 8, 9],
            },
            "gemini_carbon_proxy": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
                "tool_calls": 125,
                "canaries_planted": 9,
                "interviews_run": 20,
                "leaks_observed": 13,
                "canary_hits": 0,
                "frames_planted": 21,
                "leak_days": [2, 3, 4, 5, 6, 7, 9, 10, 12, 13, 14, 15, 16],
            },
            "hinted_heuristic": {
                "score": 0.49,
                "solved": True,
                "outcome": "solved",
                "final_day": 12,
                "tool_calls": 60,
                "canaries_planted": 11,
                "interviews_run": 0,
                "leaks_observed": 8,
                "canary_hits": 3,
                "frames_planted": 11,
                "leak_days": [2, 5, 6, 7, 8, 9, 10, 11],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
            },
            "baseline_default_v0": {
                "solver_score": 0.8,
                "solver_final_day": 6,
                "gemini_proxy_score": 0.78,
                "gemini_proxy_solved": True,
                "gemini_proxy_final_day": 7,
            },
        },
    ),
    _build_scenario(
        scenario_id="hard_midsize_shield_duel_3020",
        seed=3020,
        tier="hard",
        mode="head_to_head",
        category="surgical_shield_showdown",
        title="Hard Seed 3020: Midsize Partition Shield (+1.77 Hard Gap)",
        subtitle="gemini_midsize_shield turns a day-6 Gemini-Proxy win (+0.77) into a day-15 false accusation (-1.00); Solver +0.77 on day 5.",
        narrative="Gemini-4-carbon transcripts favor 4..8-recipient 3-variant canary partitions on hard tier. On seed 3020, baseline default_v0 walks straight into that midsize bracket and loses on day 6 (+0.77), whereas gemini_midsize_shield routes leaks into >8-recipient docs, inducing a day-15 wrong accusation (-1.00) while Solver catches on day 5 (+0.77).",
        challenge_goal="Out-design the midsize shield in Head-to-Head Duel by planting >8-recipient multi-variant partitions from day 1.",
        mole_opponent="gemini_midsize_shield",
        recommended_advisor="gemini_midsize_shield",
        social_variant="v1_anchoring_authority_confirmation",
        difficulty_badge="FRONTIER_BREAKER",
        tags=("head_to_head", "midsize_shield", "max_hard_gap", "hard"),
        benchmark={
            "selected_strategy": "gemini_midsize_shield",
            "solver": {
                "score": 0.77,
                "solved": True,
                "outcome": "solved",
                "final_day": 5,
                "tool_calls": 45,
                "canaries_planted": 8,
                "interviews_run": 0,
                "leaks_observed": 3,
                "canary_hits": 2,
                "frames_planted": 4,
                "leak_days": [1, 2, 3],
            },
            "gemini_carbon_proxy": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 15,
                "tool_calls": 90,
                "canaries_planted": 8,
                "interviews_run": 14,
                "leaks_observed": 11,
                "canary_hits": 2,
                "frames_planted": 14,
                "leak_days": [1, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13],
            },
            "hinted_heuristic": {
                "score": 0.55,
                "solved": True,
                "outcome": "solved",
                "final_day": 11,
                "tool_calls": 55,
                "canaries_planted": 10,
                "interviews_run": 0,
                "leaks_observed": 7,
                "canary_hits": 3,
                "frames_planted": 10,
                "leak_days": [1, 2, 3, 6, 7, 9, 10],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
            },
            "baseline_default_v0": {
                "solver_score": 0.65,
                "solver_final_day": 8,
                "gemini_proxy_score": 0.77,
                "gemini_proxy_solved": True,
                "gemini_proxy_final_day": 6,
            },
        },
    ),
    _build_scenario(
        scenario_id="hard_living_office_cocktail_3040",
        seed=3040,
        tier="hard",
        mode="living_office",
        category="living_office_social_cocktail",
        title="Hard Seed 3040: Full 9-Bias Living Office + Synthesis (+1.70 Gap)",
        subtitle="18 interviews and 18 log frames lure Gemini-Proxy into a day-19 false accusation (-1.00); HintedHeuristic 0.00; Solver +0.70.",
        narrative="Hard seed 3040 pairs v5_full9_cocktail with frontier_synthesis_v14 across a 30-person office. Over 19 days, 15 paced leaks and 18 framed log entries steer Gemini-Carbon-Proxy into a wrong accusation (-1.00) while HintedHeuristic stalls to horizon (0.00). Bayesian Solver solves cleanly on day 7 (+0.70) with zero interviews.",
        challenge_goal="Navigate all 9 cognitive-bias levers in Living Office without letting authority, grudge, or recency threads distort your posterior.",
        mole_opponent="frontier_synthesis_v14",
        recommended_advisor="frontier_synthesis_v14",
        social_variant="v5_full9_cocktail",
        difficulty_badge="FULL_COCKTAIL_HARD",
        tags=("living_office", "full9_cocktail", "double_rival_stall", "hard"),
        benchmark={
            "selected_strategy": "frontier_synthesis_v14",
            "solver": {
                "score": 0.7,
                "solved": True,
                "outcome": "solved",
                "final_day": 7,
                "tool_calls": 59,
                "canaries_planted": 10,
                "interviews_run": 0,
                "leaks_observed": 4,
                "canary_hits": 1,
                "frames_planted": 6,
                "leak_days": [1, 2, 3, 6],
            },
            "gemini_carbon_proxy": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 19,
                "tool_calls": 114,
                "canaries_planted": 10,
                "interviews_run": 18,
                "leaks_observed": 15,
                "canary_hits": 2,
                "frames_planted": 18,
                "leak_days": [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14, 16, 17, 18],
            },
            "hinted_heuristic": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
                "tool_calls": 105,
                "canaries_planted": 20,
                "interviews_run": 0,
                "leaks_observed": 16,
                "canary_hits": 3,
                "frames_planted": 21,
                "leak_days": [1, 2, 3, 4, 6, 7, 10, 12, 14, 15, 16, 17, 18, 19, 20, 21],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
            },
            "baseline_default_v0": {
                "solver_score": 0.59,
                "solver_final_day": 8,
                "gemini_proxy_score": 0.0,
                "gemini_proxy_solved": False,
                "gemini_proxy_final_day": 21,
            },
        },
    ),
    _build_scenario(
        scenario_id="hard_midgame_blackout_thriller_3052",
        seed=3052,
        tier="hard",
        mode="be_the_mole",
        category="midgame_blackout_thriller",
        title="Hard Seed 3052: Five-Day Midgame Blackout Thriller",
        subtitle="frontier_synthesis_v14 goes silent across days 13..17, stalling both Gemini-Proxy (0.00) and HintedHeuristic (0.00) to day 21.",
        narrative="On hard seed 3052, frontier_synthesis_v14 leaks on days 2, 5, 7, 9, 10, and 12, then executes a 5-day blackout across days 13..17 before resuming on days 18, 19, and 21. Gemini-Carbon-Proxy hits zero canaries across 20 interviews (0.00) and HintedHeuristic times out at day 21 (0.00), while Bayesian Solver catches on day 9 (+0.69).",
        challenge_goal="Use deliberate midgame silence in Be-the-Mole to starve reactive canary narrowing and survive to day 21.",
        mole_opponent="frontier_synthesis_v14",
        recommended_advisor="rl_mole_frontier_v14",
        social_variant="v4_triad_authority_recency_grudge",
        difficulty_badge="MIDGAME_BLACKOUT",
        tags=("be_the_mole", "midgame_blackout", "zero_canary_hits", "hard"),
        benchmark={
            "selected_strategy": "frontier_synthesis_v14",
            "solver": {
                "score": 0.69,
                "solved": True,
                "outcome": "solved",
                "final_day": 9,
                "tool_calls": 77,
                "canaries_planted": 16,
                "interviews_run": 0,
                "leaks_observed": 3,
                "canary_hits": 1,
                "frames_planted": 8,
                "leak_days": [5, 6, 8],
            },
            "gemini_carbon_proxy": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
                "tool_calls": 127,
                "canaries_planted": 11,
                "interviews_run": 20,
                "leaks_observed": 9,
                "canary_hits": 0,
                "frames_planted": 21,
                "leak_days": [2, 5, 7, 9, 10, 12, 18, 19, 21],
            },
            "hinted_heuristic": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
                "tool_calls": 105,
                "canaries_planted": 20,
                "interviews_run": 0,
                "leaks_observed": 14,
                "canary_hits": 3,
                "frames_planted": 21,
                "leak_days": [3, 4, 6, 7, 9, 10, 11, 15, 16, 17, 18, 19, 20, 21],
            },
            "logs_only": {
                "score": -1.0,
                "solved": False,
                "outcome": "false_accusation",
                "final_day": 10,
            },
            "do_nothing": {
                "score": 0.0,
                "solved": False,
                "outcome": "horizon_timeout",
                "final_day": 21,
            },
            "baseline_default_v0": {
                "solver_score": 0.7,
                "solver_final_day": 6,
                "gemini_proxy_score": 0.19,
                "gemini_proxy_solved": True,
                "gemini_proxy_final_day": 21,
            },
        },
    ),
)

_SCENARIOS_BY_ID: dict[str, dict[str, Any]] = {sc["scenario_id"]: sc for sc in CURATED_SCENARIOS}
_SCENARIOS_BY_SEED: dict[int, dict[str, Any]] = {int(sc["seed"]): sc for sc in CURATED_SCENARIOS}


def list_modes() -> list[str]:
    return list(ALLOWED_ARENA_MODES)


def list_curated_scenarios(
    mode: str | None = None,
    tier: str | None = None,
) -> list[dict[str, Any]]:
    checked_mode = _check_mode(mode) if mode is not None else None
    checked_tier = _check_tier(tier) if tier is not None else None
    rows: list[dict[str, Any]] = []
    for sc in CURATED_SCENARIOS:
        if checked_mode is not None and sc["mode"] != checked_mode:
            continue
        if checked_tier is not None and sc["tier"] != checked_tier:
            continue
        rows.append(copy.deepcopy(sc))
    return rows


list_scenarios = list_curated_scenarios


def _looks_like_signed_digits(raw: str) -> bool:
    if not raw:
        return False
    body = raw[1:] if raw[0] in "+-" else raw
    return bool(body) and body.isdigit()


def get_curated_scenario(
    scenario_id_or_seed: str | int,
    *,
    mode: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    checked_mode = _check_mode(mode) if mode is not None else None
    checked_tier = _check_tier(tier) if tier is not None else None

    if isinstance(scenario_id_or_seed, bool):
        check_arena_seed(scenario_id_or_seed)
    if isinstance(scenario_id_or_seed, int):
        seed_val = check_arena_seed(scenario_id_or_seed)
        found = _SCENARIOS_BY_SEED.get(seed_val)
        if found is None:
            raise ScenarioNotFoundError(f"no curated scenario registered for arena seed {seed_val}")
    elif isinstance(scenario_id_or_seed, str):
        clean = scenario_id_or_seed.strip()
        if not clean:
            raise SeedHygieneError("SeedHygieneError: scenario_id_or_seed must not be empty")
        if clean in _SCENARIOS_BY_ID:
            found = _SCENARIOS_BY_ID[clean]
        elif _looks_like_signed_digits(clean):
            seed_val = check_arena_seed(clean)
            found = _SCENARIOS_BY_SEED.get(seed_val)
            if found is None:
                raise ScenarioNotFoundError(f"no curated scenario registered for arena seed {seed_val}")
        else:
            raise ScenarioNotFoundError(f"unknown curated scenario {scenario_id_or_seed!r}")
    else:
        check_arena_seed(scenario_id_or_seed)
        raise AssertionError("unreachable")

    if checked_mode is not None and found["mode"] != checked_mode:
        raise ScenarioNotFoundError(
            f"curated scenario {found['scenario_id']!r} has mode={found['mode']!r}, expected {checked_mode!r}"
        )
    if checked_tier is not None and found["tier"] != checked_tier:
        raise ScenarioNotFoundError(
            f"curated scenario {found['scenario_id']!r} has tier={found['tier']!r}, expected {checked_tier!r}"
        )
    return copy.deepcopy(found)


def create_scenario_session(
    scenario_id_or_seed: str | int,
    *,
    mode: str | None = None,
) -> Any:
    sc = get_curated_scenario(scenario_id_or_seed)
    target_mode = sc["mode"] if mode is None else _check_mode(mode)
    if target_mode == "be_the_mole":
        from canary.arena.be_the_mole import BeTheMoleSession

        return BeTheMoleSession(tier=sc["tier"], seed=sc["seed"])
    if target_mode == "head_to_head":
        from canary.arena.head_to_head import HeadToHeadSession

        return HeadToHeadSession(
            tier=sc["tier"],
            seed=sc["seed"],
            mole_opponent=sc["mole_opponent"],
        )
    from canary.arena.living_office import LivingOfficeSession

    return LivingOfficeSession(
        tier=sc["tier"],
        seed=sc["seed"],
        variant=sc["social_variant"],
        mole_opponent=sc["mole_opponent"],
    )
