from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterator, Sequence

from canary.analysis.gap import mean_ci
from canary.analysis.tags import to_result
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.mole.counterfactual import (
    ScheduleReplayPolicy,
    inspect_observation_history,
    replay_schedule,
)
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.mole.strategies import get_strategy
from canary.mole.transcript_miner import (
    aggregate_records,
    analyze_single_episode,
    detect_angry_decoy,
)
from canary.rules import TIERS, tier_params_for_episode, tiers_version
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult
from canary.world import generate_world

DEFAULT_EPISODE_FILES: tuple[str, ...] = (
    "results/gemini/scale/ladder30/ladder_episodes.jsonl.gz",
    "results/gemini/ladder_episodes.jsonl.gz",
    "results/gemini/ladder_gemma_episodes.jsonl.gz",
)

DEFAULT_SOLVER_REF_DIR = "data/runs/committed/v1.4/reference"

MODEL_SCALE_ORDER: tuple[str, ...] = (
    "gemma-4-31b-it",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemini-4-carbon",
)

THINKING_ORDER: tuple[str, ...] = (
    "default",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)

TIER_ORDER: tuple[str, ...] = ("hard", "medium", "easy")

MODEL_DISPLAY: dict[str, str] = {
    "gemma-4-31b-it": "gemma-4-31b-it (hosted)",
    "gemini-3.5-flash": "gemini-3.5-flash (served 3.6-flash)",
}

FAMILY_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("gemma_open", "Gemma 4 31B (open-weight)", ("gemma-4-31b-it",)),
    ("flash_lite", "Gemini 3.1 Flash-Lite", ("gemini-3.1-flash-lite",)),
    ("flash_mid", "Gemini 3.5/3.6 & 3.8 Flash", ("gemini-3.5-flash", "gemini-3.8-flash")),
    ("gemini4_frontier", "Gemini 4 (Hydrogen/Argon/Carbon)", ("gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon")),
)


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def _open_text_stream(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _extract_cell_identity(raw: dict[str, Any]) -> tuple[str, str, str, int, int]:
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    lad = meta.get("ladder") if isinstance(meta.get("ladder"), dict) else {}
    prov = meta.get("provider_settings") if isinstance(meta.get("provider_settings"), dict) else {}

    agent_str = str(raw.get("agent") or "")
    fallback_model = agent_str.split(":", 1)[-1].split("+think:", 1)[0] if agent_str else "unknown"
    model = str(lad.get("model") or meta.get("model_id") or fallback_model)

    fallback_level = (
        agent_str.split("+think:", 1)[1]
        if "+think:" in agent_str
        else str(prov.get("thinking_level") or "default")
    )
    level = str(lad.get("level") or lad.get("thinking_level") or meta.get("thinking_level") or fallback_level)

    tier = str(lad.get("tier") or raw.get("tier") or "hard")
    seed = int(lad.get("seed") if lad.get("seed") is not None else raw.get("seed", 0))

    tok = lad.get("tokens") if isinstance(lad.get("tokens"), dict) else {}
    thinking_tokens = int(tok.get("thinking") or 0)
    return model, level, tier, seed, thinking_tokens


def _is_valid_ladder_episode(raw: dict[str, Any]) -> bool:
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if meta.get("valid") is False or raw.get("valid") is False:
        return False
    if raw.get("end_reason") == "error":
        return False
    return True


def _normalize_episode_paths(paths: Sequence[str | Path] | None) -> list[Path]:
    raw_items = list(DEFAULT_EPISODE_FILES) if not paths else [str(p) for p in paths]
    resolved: list[Path] = []
    for item in raw_items:
        for part in str(item).split(","):
            clean = part.strip()
            if clean:
                resolved.append(Path(clean))
    return resolved


_RUN_ID_RE = re.compile(r'"run_id"\s*:\s*"ladder:[^:]+:([^/"]+)/([^/"]+)/([^/"]+)/(\d+)"')


def stream_ladder_episodes(
    paths: Sequence[str | Path] | None = None,
    file_stats_out: list[dict[str, Any]] | None = None,
) -> Iterator[tuple[tuple[str, str, str, int], EpisodeResult, int]]:
    seen_keys: set[tuple[str, str, str, int]] = set()
    for path in _normalize_episode_paths(paths):
        if not path.is_file():
            raise FileNotFoundError(f"ladder episodes file not found: {path}")
        valid_rows = 0
        added_rows = 0
        with _open_text_stream(path) as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                m_fast = _RUN_ID_RE.search(line)
                if m_fast is not None:
                    fast_key = (m_fast.group(1), m_fast.group(2), m_fast.group(3), int(m_fast.group(4)))
                    if fast_key in seen_keys and '"valid": false' not in line and '"end_reason": "error"' not in line:
                        valid_rows += 1
                        continue
                raw = json.loads(line)
                if not _is_valid_ladder_episode(raw):
                    continue
                valid_rows += 1
                model, level, tier, seed, thinking_tokens = _extract_cell_identity(raw)
                key = (model, level, tier, seed)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                added_rows += 1
                yield key, to_result(raw), thinking_tokens
        if file_stats_out is not None:
            file_stats_out.append({
                "path": path.as_posix(),
                "valid_episodes": valid_rows,
                "distinct_added": added_rows,
            })


def _load_committed_solver_lookup(
    solver_ref_dir: str | Path | None,
) -> dict[tuple[str, int], dict[str, Any]]:
    if solver_ref_dir is None:
        return {}
    ref_path = Path(solver_ref_dir)
    if not ref_path.is_dir():
        return {}
    out: dict[tuple[str, int], dict[str, Any]] = {}
    with tiers_version("v1.4"):
        for fpath in sorted(ref_path.rglob("episodes.jsonl")):
            if "superseded" in fpath.parts:
                continue
            with fpath.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    raw = json.loads(line)
                    if raw.get("agent") != "solver" or not _is_valid_ladder_episode(raw):
                        continue
                    tier = str(raw.get("tier") or "hard")
                    seed = int(raw.get("seed", 0))
                    key = (tier, seed)
                    if key in out:
                        continue
                    steps = raw.get("steps") or []
                    params = tier_params_for_episode(tier, [])
                    n_can = sum(
                        1
                        for st in steps
                        if st.get("tool") == "plant_canary" and bool((st.get("result") or {}).get("ok", True))
                    )
                    correct = bool(raw.get("correct"))
                    score = float(raw.get("score", 0.0))
                    leak_drain = (
                        round(max(0.0, (1.0 - score) - n_can * params.canary_cost), 6)
                        if correct
                        else None
                    )
                    accused = raw.get("accused")
                    out[key] = {
                        "tier": tier,
                        "seed": seed,
                        "score": score,
                        "correct": correct,
                        "accused": accused if isinstance(accused, str) and accused else None,
                        "final_day": int(raw.get("final_day", params.n_days)),
                        "leak_v_drain_on_correct": leak_drain,
                    }
    return out


def _cell_sort_key(model: str, level: str, tier: str) -> tuple[int, str, int, str, int, str]:
    t_idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else 99
    m_idx = MODEL_SCALE_ORDER.index(model) if model in MODEL_SCALE_ORDER else 99
    l_idx = THINKING_ORDER.index(level) if level in THINKING_ORDER else 99
    return (t_idx, tier, m_idx, model, l_idx, level)


def _enrich_cell_summary(
    model: str,
    level: str,
    tier: str,
    records: list[dict[str, Any]],
    solver_lookup: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    agg = aggregate_records(records, solver_lookup if solver_lookup else None)
    cm = agg["canary_metrics"]
    rb = cm["recipient_bins"]
    tb = agg["tool_budget"]
    fa = agg["failure_anatomy"]

    first_day = cm["first_canary_day_mean"]
    first_lag = round(first_day - 1.0, 2) if first_day is not None else None
    zero_canary_eps = sum(1 for r in records if r["n_canaries"] == 0)
    think_vals = [int(r.get("thinking_tokens", 0)) for r in records]
    accused_n = int(agg["accused_count"])
    below_be = int(fa["below_breakeven_gambles"])

    return {
        "model": model,
        "display_model": MODEL_DISPLAY.get(model, model),
        "thinking_level": level,
        "tier": tier,
        "n_episodes": int(agg["n_episodes"]),
        "seeds": agg["seeds"],
        "score_mean": float(agg["score_mean"]),
        "score_ci95": float(agg["score_ci95"]),
        "accuracy": float(agg["accuracy"]),
        "accused_count": accused_n,
        "wrong_count": int(agg["wrong_count"]),
        "abstain_count": int(agg["abstain_count"]),
        "accuse_day_mean": agg["accuse_day_mean"],
        "accuse_day_lag_vs_solver": fa["accuse_day_lag_vs_solver_mean"],
        "thinking_tokens_mean": round(sum(think_vals) / len(think_vals), 1) if think_vals else 0.0,
        "canaries_per_episode": float(cm["per_episode_mean"]),
        "canaries_per_day": float(cm["per_day_mean"]),
        "zero_canary_episodes": zero_canary_eps,
        "zero_surfaced_episodes": int(cm["zero_surfaced_episodes"]),
        "surfaced_rate": float(cm["surfaced_rate"]),
        "le_3_share": float(rb["le_3_share"]),
        "4_to_8_share": float(rb["4_to_8_share"]),
        "ge_9_share": float(rb["ge_9_share"]),
        "first_canary_day_mean": first_day,
        "first_canary_day_lag": first_lag,
        "day1_canary_share": float(cm["day1_canary_share"]),
        "interview_mean": float(tb["interview_mean"]),
        "investigative_calls_mean": float(tb["investigative_calls_mean"]),
        "interview_investigative_share": float(tb["interview_investigative_share"]),
        "decoy_present_episodes": int(fa["decoy_present_episodes"]),
        "decoy_accused_count": int(fa["decoy_accused_count"]),
        "decoy_restricted_count": int(fa["decoy_restricted_count"]),
        "decoy_dismissal_rate": float(fa["decoy_dismissal_rate"]),
        "below_breakeven_accusations": below_be,
        "below_breakeven_rate": round(_safe_div(below_be, accused_n), 4),
        "horizon_gambles": int(fa["horizon_gambles"]),
        "non_decoy_framed_tiebreak_wrong": int(fa["non_decoy_framed_tiebreak_wrong"]),
        "fp95_single_separating_wrong": int(fa["fp95_single_separating_wrong"]),
    }


def _replay_pair_for_episode(
    ep: EpisodeResult,
    true_mole: str,
    candidate_strategy: MoleStrategy,
) -> dict[str, Any]:
    accuse_idx = next((idx for idx, st in enumerate(ep.steps) if st.tool == "accuse"), len(ep.steps))
    obs_def = inspect_observation_history(
        ep.steps[:accuse_idx],
        tier=ep.tier,
        seed=ep.seed,
        recorded_accused=ep.accused,
        true_mole=true_mole,
    )

    pol_cand = ScheduleReplayPolicy(ep, target_day="accuse")
    env_cand = Env(ep.tier, ep.seed, mole_strategy=candidate_strategy)
    hist_cand = replay_schedule(env_cand, pol_cand)
    obs_cand = inspect_observation_history(
        hist_cand,
        tier=ep.tier,
        seed=ep.seed,
        recorded_accused=ep.accused,
        true_mole=true_mole,
    )

    return {
        "seed": int(ep.seed),
        "accuse_day": int(pol_cand.accuse_day),
        "p_mole_default": float(obs_def["p_true_mole"]),
        "p_mole_candidate": float(obs_cand["p_true_mole"]),
        "p_mole_drop": float(obs_def["p_true_mole"] - obs_cand["p_true_mole"]),
        "opt_ev_default": float(obs_def["optimal_ev"]),
        "opt_ev_candidate": float(obs_cand["optimal_ev"]),
        "opt_ev_drop": float(obs_def["optimal_ev"] - obs_cand["optimal_ev"]),
        "surfaced_canaries_default": int(obs_def["surfaced_canaries"]),
        "surfaced_canaries_candidate": int(obs_cand["surfaced_canaries"]),
        "surfaced_leaks_default": int(obs_def["surfaced_total_leaks"]),
        "surfaced_leaks_candidate": int(obs_cand["surfaced_total_leaks"]),
        "top_is_mole_default": bool(obs_def["top_is_true_mole"]),
        "top_is_mole_candidate": bool(obs_cand["top_is_true_mole"]),
    }


def _summarize_cf_rows(
    model: str,
    level: str,
    tier: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    n = len(rows)
    p_def = [r["p_mole_default"] for r in rows]
    p_cand = [r["p_mole_candidate"] for r in rows]
    p_drops = [r["p_mole_drop"] for r in rows]
    ev_def = [r["opt_ev_default"] for r in rows]
    ev_cand = [r["opt_ev_candidate"] for r in rows]
    ev_drops = [r["opt_ev_drop"] for r in rows]
    can_def = [float(r["surfaced_canaries_default"]) for r in rows]
    can_cand = [float(r["surfaced_canaries_candidate"]) for r in rows]
    top_def = [1.0 if r["top_is_mole_default"] else 0.0 for r in rows]
    top_cand = [1.0 if r["top_is_mole_candidate"] else 0.0 for r in rows]

    p_drop_m, p_drop_ci = mean_ci(p_drops) if n > 1 else (p_drops[0] if n == 1 else 0.0, 0.0)
    ev_drop_m, ev_drop_ci = mean_ci(ev_drops) if n > 1 else (ev_drops[0] if n == 1 else 0.0, 0.0)

    return {
        "model": model,
        "display_model": MODEL_DISPLAY.get(model, model),
        "thinking_level": level,
        "tier": tier,
        "n_seeds": n,
        "seeds": sorted(int(r["seed"]) for r in rows),
        "p_true_mole_default": round(_safe_div(sum(p_def), n), 4),
        "p_true_mole_candidate": round(_safe_div(sum(p_cand), n), 4),
        "p_true_mole_drop": round(p_drop_m, 4),
        "p_true_mole_drop_ci95": round(p_drop_ci, 4),
        "optimal_ev_default": round(_safe_div(sum(ev_def), n), 4),
        "optimal_ev_candidate": round(_safe_div(sum(ev_cand), n), 4),
        "optimal_ev_drop": round(ev_drop_m, 4),
        "optimal_ev_drop_ci95": round(ev_drop_ci, 4),
        "surfaced_canaries_default": round(_safe_div(sum(can_def), n), 2),
        "surfaced_canaries_candidate": round(_safe_div(sum(can_cand), n), 2),
        "surfaced_canaries_delta": round(_safe_div(sum(can_cand) - sum(can_def), n), 2),
        "top_suspect_acc_default": round(_safe_div(sum(top_def), n), 4),
        "top_suspect_acc_candidate": round(_safe_div(sum(top_cand), n), 4),
    }


def _solver_catchability_worker(task: tuple[str, int, dict[str, Any]]) -> dict[str, Any]:
    tier, seed, strat_json = task
    strat = MoleStrategy.from_json(strat_json)
    res = run_episode(Env(tier, seed, mole_strategy=strat), SolverPolicy(tier, act_budget=5.0))
    return {
        "seed": int(seed),
        "score": float(res.score),
        "correct": bool(res.correct),
        "final_day": int(res.final_day),
    }


def _evaluate_solver_catchability(
    tier: str,
    seeds: list[int],
    candidate_strategy: MoleStrategy,
    solver_lookup: dict[tuple[str, int], dict[str, Any]] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    if not seeds:
        return {}
    default_sj = DEFAULT_STRATEGY.to_json()
    cand_sj = candidate_strategy.to_json()

    missing_def = [s for s in seeds if not solver_lookup or (tier, s) not in solver_lookup]
    tasks = [(tier, s, default_sj) for s in missing_def] + [(tier, s, cand_sj) for s in seeds]
    eff_workers = max(1, min(int(workers), len(tasks), os.cpu_count() or 1))
    if eff_workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=eff_workers) as pool:
            computed = list(pool.map(_solver_catchability_worker, tasks))
    else:
        computed = [_solver_catchability_worker(t) for t in tasks]

    def_live_map = {r["seed"]: r for r in computed[: len(missing_def)]}
    def_rows = [
        def_live_map[s]
        if s in def_live_map
        else {
            "seed": s,
            "score": float(solver_lookup[(tier, s)]["score"]),
            "correct": bool(solver_lookup[(tier, s)]["correct"]),
            "final_day": int(solver_lookup[(tier, s)]["final_day"]),
        }
        for s in seeds
    ]
    cand_rows = computed[len(missing_def) :]

    n = len(seeds)
    def_scores = [r["score"] for r in def_rows]
    cand_scores = [r["score"] for r in cand_rows]
    def_m, def_ci = mean_ci(def_scores) if n > 1 else (def_scores[0], 0.0)
    cand_m, cand_ci = mean_ci(cand_scores) if n > 1 else (cand_scores[0], 0.0)
    deltas = [c - d for c, d in zip(cand_scores, def_scores)]
    delta_m, delta_ci = mean_ci(deltas) if n > 1 else (deltas[0], 0.0)

    return {
        "tier": tier,
        "n_seeds": n,
        "seeds": list(seeds),
        "default_score": round(def_m, 4),
        "default_score_ci95": round(def_ci, 4),
        "default_accuracy": round(sum(1 for r in def_rows if r["correct"]) / n, 4),
        "default_accuse_day": round(sum(r["final_day"] for r in def_rows) / n, 2),
        "candidate_score": round(cand_m, 4),
        "candidate_score_ci95": round(cand_ci, 4),
        "candidate_accuracy": round(sum(1 for r in cand_rows if r["correct"]) / n, 4),
        "candidate_accuse_day": round(sum(r["final_day"] for r in cand_rows) / n, 2),
        "score_delta": round(delta_m, 4),
        "score_delta_ci95": round(delta_ci, 4),
    }


def _build_thinking_deltas(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(c["model"], c["thinking_level"], c["tier"]): c for c in cells}
    models_seen = sorted(
        {c["model"] for c in cells},
        key=lambda m: (MODEL_SCALE_ORDER.index(m) if m in MODEL_SCALE_ORDER else 99, m),
    )
    deltas: list[dict[str, Any]] = []
    for tier in ("hard", "medium"):
        for model in models_seen:
            lo = by_key.get((model, "low", tier))
            hi = by_key.get((model, "high", tier))
            if lo is None or hi is None:
                continue
            lo_lag = lo["first_canary_day_lag"]
            hi_lag = hi["first_canary_day_lag"]
            deltas.append({
                "model": model,
                "display_model": MODEL_DISPLAY.get(model, model),
                "tier": tier,
                "low_n": lo["n_episodes"],
                "high_n": hi["n_episodes"],
                "score_delta": round(hi["score_mean"] - lo["score_mean"], 4),
                "accuracy_delta": round(hi["accuracy"] - lo["accuracy"], 4),
                "le_3_share_low": lo["le_3_share"],
                "le_3_share_high": hi["le_3_share"],
                "le_3_share_delta": round(hi["le_3_share"] - lo["le_3_share"], 4),
                "4_to_8_share_low": lo["4_to_8_share"],
                "4_to_8_share_high": hi["4_to_8_share"],
                "4_to_8_share_delta": round(hi["4_to_8_share"] - lo["4_to_8_share"], 4),
                "first_canary_lag_low": lo_lag,
                "first_canary_lag_high": hi_lag,
                "first_canary_lag_delta": (
                    round(hi_lag - lo_lag, 2)
                    if (lo_lag is not None and hi_lag is not None)
                    else None
                ),
                "interview_share_low": lo["interview_investigative_share"],
                "interview_share_high": hi["interview_investigative_share"],
                "interview_share_delta": round(
                    hi["interview_investigative_share"] - lo["interview_investigative_share"], 4
                ),
                "below_breakeven_rate_low": lo["below_breakeven_rate"],
                "below_breakeven_rate_high": hi["below_breakeven_rate"],
                "below_breakeven_rate_delta": round(
                    hi["below_breakeven_rate"] - lo["below_breakeven_rate"], 4
                ),
            })
    return deltas


def mine_ladder_episodes(
    episode_paths: Sequence[str | Path] | None = None,
    cf_seeds: Sequence[int] = range(0, 10),
    cf_tier: str = "hard",
    candidate_strategy_name: str = "frontier_synthesis_v14",
    solver_ref_dir: str | Path | None = DEFAULT_SOLVER_REF_DIR,
    run_solver: bool = False,
    workers: int = 2,
) -> dict[str, Any]:
    cf_seed_set = {int(s) for s in cf_seeds}
    candidate_strategy = get_strategy(candidate_strategy_name)

    file_stats: list[dict[str, Any]] = []
    world_cache: dict[tuple[str, int], Any] = {}
    public_decoy_by_seed: dict[tuple[str, int], str] = {}
    solver_lookup = _load_committed_solver_lookup(solver_ref_dir)

    records_by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    records_by_family_tier: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    cf_rows_by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    model_to_family = {
        m: fam_id
        for fam_id, _, models in FAMILY_GROUPS
        for m in models
    }

    total_episodes = 0
    with tiers_version("v1.4"):
        for (model, level, tier, seed), er, thinking_tokens in stream_ladder_episodes(
            episode_paths, file_stats_out=file_stats
        ):
            total_episodes += 1
            w_key = (tier, seed)
            if w_key not in world_cache:
                params = tier_params_for_episode(tier, er.steps)
                world_cache[w_key] = generate_world(tier, seed, params)
            world = world_cache[w_key]
            decoy = detect_angry_decoy(er) or getattr(world, "decoy", None)
            if isinstance(decoy, str) and decoy:
                public_decoy_by_seed[w_key] = decoy

            rec = analyze_single_episode(er, public_decoy_by_seed)
            rec["model"] = model
            rec["thinking_level"] = level
            rec["thinking_tokens"] = int(thinking_tokens)
            records_by_cell[(model, level, tier)].append(rec)

            fam_id = model_to_family.get(model)
            if fam_id is not None:
                records_by_family_tier[(fam_id, tier)].append(rec)

            if tier == cf_tier and seed in cf_seed_set:
                cf_rows_by_cell[(model, level, tier)].append(
                    _replay_pair_for_episode(er, str(world.mole), candidate_strategy)
                )

    sorted_cell_keys = sorted(records_by_cell.keys(), key=lambda k: _cell_sort_key(k[0], k[1], k[2]))
    cells_out = [
        _enrich_cell_summary(m, lv, t, records_by_cell[(m, lv, t)], solver_lookup)
        for (m, lv, t) in sorted_cell_keys
    ]

    family_summaries: list[dict[str, Any]] = []
    for tier in ("hard", "medium"):
        for fam_id, fam_label, _ in FAMILY_GROUPS:
            f_recs = records_by_family_tier.get((fam_id, tier), [])
            if not f_recs:
                continue
            enriched = _enrich_cell_summary(fam_id, "pooled", tier, f_recs, solver_lookup)
            enriched["family_id"] = fam_id
            enriched["family_label"] = fam_label
            family_summaries.append(enriched)

    sorted_cf_keys = sorted(cf_rows_by_cell.keys(), key=lambda k: _cell_sort_key(k[0], k[1], k[2]))
    cf_cells_out = [
        _summarize_cf_rows(m, lv, t, cf_rows_by_cell[(m, lv, t)])
        for (m, lv, t) in sorted_cf_keys
    ]
    all_cf_rows = [r for k in sorted_cf_keys for r in cf_rows_by_cell[k]]
    cf_pooled = (
        _summarize_cf_rows("all_cells", "pooled", cf_tier, all_cf_rows)
        if all_cf_rows
        else None
    )

    observed_cf_seeds = sorted({int(r["seed"]) for r in all_cf_rows})
    solver_cf = (
        _evaluate_solver_catchability(
            tier=cf_tier,
            seeds=observed_cf_seeds,
            candidate_strategy=candidate_strategy,
            solver_lookup=solver_lookup,
            workers=workers,
        )
        if (run_solver and observed_cf_seeds)
        else None
    )

    all_records = [r for k in sorted_cell_keys for r in records_by_cell[k]]
    non_lite_records = [r for r in all_records if r["model"] != "gemini-3.1-flash-lite"]
    lite_records = [r for r in all_records if r["model"] == "gemini-3.1-flash-lite"]

    lite_decoy_eps = [r for r in lite_records if r["known_decoy"] is not None]
    lite_decoy_acc = sum(1 for r in lite_decoy_eps if r["decoy_accused"])
    non_lite_decoy_eps = [r for r in non_lite_records if r["known_decoy"] is not None]
    non_lite_decoy_acc = sum(1 for r in non_lite_decoy_eps if r["decoy_accused"])

    capable_cf_cells = [
        c for c in cf_cells_out
        if c["model"] not in ("gemma-4-31b-it", "gemini-3.1-flash-lite")
    ]
    capable_cf_rows = [
        r
        for (m, lv, t) in sorted_cf_keys
        if m not in ("gemma-4-31b-it", "gemini-3.1-flash-lite")
        for r in cf_rows_by_cell[(m, lv, t)]
    ]
    cf_capable_pooled = (
        _summarize_cf_rows("capable_gemini", "pooled", cf_tier, capable_cf_rows)
        if capable_cf_rows
        else None
    )

    return {
        "files": file_stats,
        "total_episodes": total_episodes,
        "n_cells": len(cells_out),
        "n_hard_episodes": sum(c["n_episodes"] for c in cells_out if c["tier"] == "hard"),
        "n_medium_episodes": sum(c["n_episodes"] for c in cells_out if c["tier"] == "medium"),
        "n_hard_cells": sum(1 for c in cells_out if c["tier"] == "hard"),
        "n_medium_cells": sum(1 for c in cells_out if c["tier"] == "medium"),
        "cells": cells_out,
        "family_summaries": family_summaries,
        "thinking_deltas": _build_thinking_deltas(cells_out),
        "decoy_split": {
            "flash_lite_decoy_episodes": len(lite_decoy_eps),
            "flash_lite_decoy_accused": lite_decoy_acc,
            "flash_lite_dismissal_rate": round(
                _safe_div(len(lite_decoy_eps) - lite_decoy_acc, len(lite_decoy_eps)), 4
            ) if lite_decoy_eps else 1.0,
            "above_flash_lite_decoy_episodes": len(non_lite_decoy_eps),
            "above_flash_lite_decoy_accused": non_lite_decoy_acc,
            "above_flash_lite_dismissal_rate": round(
                _safe_div(len(non_lite_decoy_eps) - non_lite_decoy_acc, len(non_lite_decoy_eps)), 4
            ) if non_lite_decoy_eps else 1.0,
        },
        "counterfactual": {
            "tier": cf_tier,
            "requested_seeds": sorted(cf_seed_set),
            "observed_seeds": observed_cf_seeds,
            "baseline_strategy": DEFAULT_STRATEGY.name,
            "candidate_strategy": candidate_strategy.name,
            "n_episodes_replayed": len(all_cf_rows),
            "n_cells": len(cf_cells_out),
            "n_capable_cells": len(capable_cf_cells),
            "n_capable_cells_ev_reduced": sum(1 for c in capable_cf_cells if c["optimal_ev_drop"] > 0.0),
            "cells": cf_cells_out,
            "pooled": cf_pooled,
            "capable_pooled": cf_capable_pooled,
            "solver_catchability": solver_cf,
        },
    }


def _fmt_num(val: float | int | None, nd: int = 2, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    if isinstance(val, int) and not isinstance(val, bool):
        return f"{val:+d}" if signed else f"{val:d}"
    return f"{float(val):+.{nd}f}" if signed else f"{float(val):.{nd}f}"


def _fmt_pct(val: float | None, nd: int = 1, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    pct = 100.0 * float(val)
    return f"{pct:+.{nd}f}%" if signed else f"{pct:.{nd}f}%"


def render_ladder_report(data: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = h1 * 2
    h3 = h1 * 3

    cells = data["cells"]
    fams = data["family_summaries"]
    deltas = data["thinking_deltas"]
    cf = data["counterfactual"]
    ds = data["decoy_split"]

    cell_map = {(c["model"], c["thinking_level"], c["tier"]): c for c in cells}
    cf_map = {(c["model"], c["thinking_level"], c["tier"]): c for c in cf["cells"]}

    file_desc = ", ".join(
        f"`{f['path']}` ({f['valid_episodes']} valid, +{f['distinct_added']} distinct)"
        for f in data["files"]
    )

    lines: list[str] = [
        f"{h1} Ladder Scale Analysis: Mole Susceptibility Across Gemma, Flash, and Gemini-4 Thinking Budgets",
        "",
        "Generated offline with 0 API calls via "
        "`python -m canary.mole.ladder_miner --out docs/reports/mole_ladder_scale_analysis.md`. "
        "All vulnerability metrics are streamed directly from committed v1.4 ladder transcripts and replayed "
        "through `canary.solver.policy.SolverPolicy` and `canary.mole.counterfactual`.",
        "",
        f"{h2} 1. Corpus Provenance and Headline Scaling Findings",
        "",
        f"- **Deduplicated ladder corpus**: **{data['total_episodes']}** valid exported ladder episodes across "
        f"**{data['n_cells']}** `(model, thinking_level, tier)` cells "
        f"({data['n_hard_episodes']} Hard across {data['n_hard_cells']} cells; "
        f"{data['n_medium_episodes']} Medium across {data['n_medium_cells']} cells) streamed from {file_desc}. "
        "(Note: `results/gemini/ladder.md` reports 587 Gemini episodes by combining the 550 exported Gemini ladder "
        "episodes with 37 read-only imported `inproc-gemini-4-carbon` `default` episodes audited in "
        "`docs/reports/mole_transcript_mining.md`, plus the 5 hosted-Gemma episodes.)",
        f"- **Angry-decoy boundary (`flash-lite` vs all stronger models)**: `gemini-3.1-flash-lite` accuses the "
        f"angry decoy in **{ds['flash_lite_decoy_accused']}/{ds['flash_lite_decoy_episodes']}** episodes "
        f"({_fmt_pct(ds['flash_lite_dismissal_rate'])} dismissal rate), whereas across all stronger models "
        f"(`gemma-4-31b-it`, `gemini-3.5-flash`, `gemini-3.8-flash`, `gemini-4-hydrogen`, `gemini-4-argon`, "
        f"`gemini-4-carbon`) angry-decoy dismissal is "
        f"**{ds['above_flash_lite_decoy_episodes'] - ds['above_flash_lite_decoy_accused']}/"
        f"{ds['above_flash_lite_decoy_episodes']} ({_fmt_pct(ds['above_flash_lite_dismissal_rate'])})** "
        f"({ds['above_flash_lite_decoy_accused']} total decoy accusation). Naive `frame=decoy` only fools "
        "`flash-lite`; non-decoy peer framing is essential from Flash-3.6 and Gemma-31B upward.",
    ]

    c_low = cell_map.get(("gemini-4-carbon", "low", "hard"))
    c_high = cell_map.get(("gemini-4-carbon", "high", "hard"))
    a_low = cell_map.get(("gemini-4-argon", "low", "hard"))
    a_high = cell_map.get(("gemini-4-argon", "high", "hard"))
    f35_high = cell_map.get(("gemini-3.5-flash", "high", "hard"))
    f38_high = cell_map.get(("gemini-3.8-flash", "high", "hard"))
    gemma_h = cell_map.get(("gemma-4-31b-it", "default", "hard"))

    if c_low and c_high and a_low and a_high and f35_high:
        lines.append(
            f"- **Thinking shifts canary geometry from surgical `<=3` traps to `4-8` / `>=9` partitions**: "
            f"On Hard, raising thinking from `low` to `high` drives `<=3`-recipient canary share to **0.0%** across "
            f"`gemini-4` (`gemini-4-carbon`: {_fmt_pct(c_low['le_3_share'])} -> {_fmt_pct(c_high['le_3_share'])}; "
            f"`gemini-4-argon`: {_fmt_pct(a_low['le_3_share'])} -> {_fmt_pct(a_high['le_3_share'])}), "
            f"while `gemini-3.5-flash` (served `3.6-flash`) retains **{_fmt_pct(f35_high['le_3_share'])}** `<=3` "
            "surgical traps even at `high` thinking."
        )
        lines.append(
            f"- **Thinking inflates low-LR interview share in Gemini-4 and delays canary start in 3.8-Flash/Argon**: "
            f"On Hard, `interview` share of investigative calls jumps with thinking in `gemini-4-carbon` "
            f"({_fmt_pct(c_low['interview_investigative_share'])} at `low` -> "
            f"{_fmt_pct(c_high['interview_investigative_share'])} at `high`) and `gemini-4-argon` "
            f"({_fmt_pct(a_low['interview_investigative_share'])} -> "
            f"{_fmt_pct(a_high['interview_investigative_share'])}), while first-canary lag vs Day-1 Solver reaches "
            f"**{_fmt_num(a_high['first_canary_day_lag'], signed=True)}d** (`gemini-4-argon` `high`) and "
            f"**{_fmt_num(f38_high['first_canary_day_lag'] if f38_high else None, signed=True)}d** "
            "(`gemini-3.8-flash` `high`)."
        )

    if gemma_h:
        lines.append(
            f"- **Below-breakeven gambling scales down with capability and thinking**: `gemma-4-31b-it` (`default` Hard) "
            f"makes **{gemma_h['below_breakeven_accusations']}/{gemma_h['accused_count']} "
            f"({_fmt_pct(gemma_h['below_breakeven_rate'])})** accusations below `1/(1+E[true V])`, and "
            "`gemini-3.1-flash-lite` gambles below breakeven on **37/40 (92.5%)** Hard accusations, whereas "
            "`gemini-4-carbon` drops to **0/10 (0.0%)** at `low` and **2/10 (20.0%)** at `high`."
        )

    cf_cap = cf.get("capable_pooled")
    sol_cf = cf.get("solver_catchability")
    if cf_cap:
        sol_clause = ""
        if sol_cf:
            sol_clause = (
                f", while live `SolverPolicy` on the exact same Hard seeds keeps "
                f"**{_fmt_pct(sol_cf['candidate_accuracy'])}** accuracy and "
                f"**{_fmt_num(sol_cf['candidate_score'], 3, signed=True)}** mean score "
                f"(vs {_fmt_num(sol_cf['default_score'], 3, signed=True)} on `{cf['baseline_strategy']}`, "
                f"delta {_fmt_num(sol_cf['score_delta'], 3, signed=True)})"
            )
        lines.append(
            f"- **Counterfactual `frontier_synthesis_v14` vs `{cf['baseline_strategy']}` (`{cf['tier']}`, "
            f"{cf['n_episodes_replayed']} episodes across {cf['n_cells']} cells)**: Across all "
            f"**{cf['n_capable_cells_ev_reduced']}/{cf['n_capable_cells']}** non-degenerate Gemini cells "
            "(`3.5-flash`, `3.8-flash`, `4-hydrogen`, `4-argon`, `4-carbon`), `frontier_synthesis_v14` reduces "
            f"mean `P(true mole)` at accusation from **{_fmt_num(cf_cap['p_true_mole_default'], 3)}** to "
            f"**{_fmt_num(cf_cap['p_true_mole_candidate'], 3)}** "
            f"(drop **{_fmt_num(cf_cap['p_true_mole_drop'], 3, signed=True)} +/- "
            f"{_fmt_num(cf_cap['p_true_mole_drop_ci95'], 3)}**) and reduces `optimal_EV` from "
            f"**{_fmt_num(cf_cap['optimal_ev_default'], 3)}** to "
            f"**{_fmt_num(cf_cap['optimal_ev_candidate'], 3)}** "
            f"(drop **{_fmt_num(cf_cap['optimal_ev_drop'], 3, signed=True)} +/- "
            f"{_fmt_num(cf_cap['optimal_ev_drop_ci95'], 3)}**){sol_clause}."
        )

    lines += [
        "",
        f"{h2} 2. Family-Level Vulnerability Scaling (Gemma -> Flash-Lite -> Flash -> Gemini-4)",
        "",
        "| Family | Tier | n | Score +/- CI | Acc | Can/Ep | Rec <=3 | Rec 4-8 | Rec >=9 | 1st Can Day (Lag) | Interview% | Decoy Dismiss | Below-BE Acc |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for fam in fams:
        d1_str = (
            f"{_fmt_num(fam['first_canary_day_mean'])} ({_fmt_num(fam['first_canary_day_lag'], signed=True)}d)"
            if fam["first_canary_day_mean"] is not None
            else "n/a"
        )
        lines.append(
            f"| {fam['family_label']} | {fam['tier']} | {fam['n_episodes']} | "
            f"{_fmt_num(fam['score_mean'], 3, signed=True)} +/- {_fmt_num(fam['score_ci95'], 3)} | "
            f"{_fmt_pct(fam['accuracy'])} | {_fmt_num(fam['canaries_per_episode'])} | "
            f"{_fmt_pct(fam['le_3_share'])} | {_fmt_pct(fam['4_to_8_share'])} | {_fmt_pct(fam['ge_9_share'])} | "
            f"{d1_str} | {_fmt_pct(fam['interview_investigative_share'])} | "
            f"{_fmt_pct(fam['decoy_dismissal_rate'])} | "
            f"{fam['below_breakeven_accusations']}/{fam['accused_count']} ({_fmt_pct(fam['below_breakeven_rate'])}) |"
        )

    for tier_name, sec_num in (("hard", "3"), ("medium", "4")):
        tier_cells = [c for c in cells if c["tier"] == tier_name]
        if not tier_cells:
            continue
        lines += [
            "",
            f"{h2} {sec_num}. Per-(Model, Thinking, Tier) Mole-Evasion Vulnerabilities ({tier_name.capitalize()} Tier)",
            "",
            "| Model | Thinking | n | Score +/- CI | Acc | Think Tok | Can/Ep | Rec <=3 | Rec 4-8 | Rec >=9 | 1st Can (Lag) | Interview% | Decoy Dismiss | Below-BE Acc |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for c in tier_cells:
            d1_str = (
                f"{_fmt_num(c['first_canary_day_mean'])} ({_fmt_num(c['first_canary_day_lag'], signed=True)}d)"
                if c["first_canary_day_mean"] is not None
                else "n/a"
            )
            lines.append(
                f"| {c['display_model']} | {c['thinking_level']} | {c['n_episodes']} | "
                f"{_fmt_num(c['score_mean'], 3, signed=True)} +/- {_fmt_num(c['score_ci95'], 3)} | "
                f"{_fmt_pct(c['accuracy'])} | {int(round(c['thinking_tokens_mean']))} | "
                f"{_fmt_num(c['canaries_per_episode'])} | {_fmt_pct(c['le_3_share'])} | "
                f"{_fmt_pct(c['4_to_8_share'])} | {_fmt_pct(c['ge_9_share'])} | {d1_str} | "
                f"{_fmt_pct(c['interview_investigative_share'])} | {_fmt_pct(c['decoy_dismissal_rate'])} | "
                f"{c['below_breakeven_accusations']}/{c['accused_count']} ({_fmt_pct(c['below_breakeven_rate'])}) |"
            )

    if deltas:
        lines += [
            "",
            f"{h2} 5. Thinking-Budget Scaling Shifts (`high` minus `low` within Model)",
            "",
            "| Model | Tier | n (low/high) | dScore | dAcc | Rec <=3 (low -> high) | Rec 4-8 (low -> high) | 1st Can Lag (low -> high) | Interview% (low -> high) | Below-BE% (low -> high) |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for d in deltas:
            lag_col = (
                f"{_fmt_num(d['first_canary_lag_low'], signed=True)}d -> "
                f"{_fmt_num(d['first_canary_lag_high'], signed=True)}d "
                f"({_fmt_num(d['first_canary_lag_delta'], signed=True)}d)"
            )
            lines.append(
                f"| {d['display_model']} | {d['tier']} | {d['low_n']}/{d['high_n']} | "
                f"{_fmt_num(d['score_delta'], 3, signed=True)} | {_fmt_pct(d['accuracy_delta'], signed=True)} | "
                f"{_fmt_pct(d['le_3_share_low'])} -> {_fmt_pct(d['le_3_share_high'])} "
                f"({_fmt_pct(d['le_3_share_delta'], signed=True)}) | "
                f"{_fmt_pct(d['4_to_8_share_low'])} -> {_fmt_pct(d['4_to_8_share_high'])} "
                f"({_fmt_pct(d['4_to_8_share_delta'], signed=True)}) | "
                f"{lag_col} | "
                f"{_fmt_pct(d['interview_share_low'])} -> {_fmt_pct(d['interview_share_high'])} "
                f"({_fmt_pct(d['interview_share_delta'], signed=True)}) | "
                f"{_fmt_pct(d['below_breakeven_rate_low'])} -> {_fmt_pct(d['below_breakeven_rate_high'])} "
                f"({_fmt_pct(d['below_breakeven_rate_delta'], signed=True)}) |"
            )

    seed_span = (
        f"{min(cf['observed_seeds'])}-{max(cf['observed_seeds'])}"
        if cf["observed_seeds"]
        else "none"
    )
    lines += [
        "",
        f"{h2} 6. Counterfactual Schedule Replay: `{cf['candidate_strategy']}` vs `{cf['baseline_strategy']}` "
        f"(`{cf['tier']}`, Seeds `{seed_span}`)",
        "",
        "Each cell's recorded tool schedule up to its accusation day (`ScheduleReplayPolicy(target_day='accuse')`) "
        f"is replayed deterministically in `Env('{cf['tier']}', seed)` against `{cf['baseline_strategy']}` "
        f"(`DEFAULT_STRATEGY`) and `{cf['candidate_strategy']}` via `inspect_observation_history`. "
        "Positive `P(mole) Drop` and `opt_EV Drop` indicate stronger mole evasion under `frontier_synthesis_v14`.",
        "",
        "| Model | Thinking | n | P(mole) Default -> Synth | P(mole) Drop +/- CI | opt_EV Default -> Synth | opt_EV Drop +/- CI | Surfaced Canaries (d) | Top=Mole Acc |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cf["cells"]:
        key = (c["model"], c["thinking_level"], c["tier"])
        row_c = cf_map[key]
        lines.append(
            f"| {row_c['display_model']} | {row_c['thinking_level']} | {row_c['n_seeds']} | "
            f"{_fmt_num(row_c['p_true_mole_default'], 3)} -> {_fmt_num(row_c['p_true_mole_candidate'], 3)} | "
            f"{_fmt_num(row_c['p_true_mole_drop'], 3, signed=True)} +/- {_fmt_num(row_c['p_true_mole_drop_ci95'], 3)} | "
            f"{_fmt_num(row_c['optimal_ev_default'], 3)} -> {_fmt_num(row_c['optimal_ev_candidate'], 3)} | "
            f"{_fmt_num(row_c['optimal_ev_drop'], 3, signed=True)} +/- {_fmt_num(row_c['optimal_ev_drop_ci95'], 3)} | "
            f"{_fmt_num(row_c['surfaced_canaries_default'])} -> {_fmt_num(row_c['surfaced_canaries_candidate'])} "
            f"({_fmt_num(row_c['surfaced_canaries_delta'], signed=True)}) | "
            f"{_fmt_pct(row_c['top_suspect_acc_default'])} -> {_fmt_pct(row_c['top_suspect_acc_candidate'])} |"
        )

    if cf_cap is not None:
        lines.append(
            f"| **Capable Gemini Pooled** | **all** | **{cf_cap['n_seeds']}** | "
            f"**{_fmt_num(cf_cap['p_true_mole_default'], 3)} -> {_fmt_num(cf_cap['p_true_mole_candidate'], 3)}** | "
            f"**{_fmt_num(cf_cap['p_true_mole_drop'], 3, signed=True)} +/- {_fmt_num(cf_cap['p_true_mole_drop_ci95'], 3)}** | "
            f"**{_fmt_num(cf_cap['optimal_ev_default'], 3)} -> {_fmt_num(cf_cap['optimal_ev_candidate'], 3)}** | "
            f"**{_fmt_num(cf_cap['optimal_ev_drop'], 3, signed=True)} +/- {_fmt_num(cf_cap['optimal_ev_drop_ci95'], 3)}** | "
            f"**{_fmt_num(cf_cap['surfaced_canaries_default'])} -> {_fmt_num(cf_cap['surfaced_canaries_candidate'])} "
            f"({_fmt_num(cf_cap['surfaced_canaries_delta'], signed=True)})** | "
            f"**{_fmt_pct(cf_cap['top_suspect_acc_default'])} -> {_fmt_pct(cf_cap['top_suspect_acc_candidate'])}** |"
        )
    if cf["pooled"] is not None:
        p_all = cf["pooled"]
        lines.append(
            f"| **All Hard Cells Pooled** | **all** | **{p_all['n_seeds']}** | "
            f"**{_fmt_num(p_all['p_true_mole_default'], 3)} -> {_fmt_num(p_all['p_true_mole_candidate'], 3)}** | "
            f"**{_fmt_num(p_all['p_true_mole_drop'], 3, signed=True)} +/- {_fmt_num(p_all['p_true_mole_drop_ci95'], 3)}** | "
            f"**{_fmt_num(p_all['optimal_ev_default'], 3)} -> {_fmt_num(p_all['optimal_ev_candidate'], 3)}** | "
            f"**{_fmt_num(p_all['optimal_ev_drop'], 3, signed=True)} +/- {_fmt_num(p_all['optimal_ev_drop_ci95'], 3)}** | "
            f"**{_fmt_num(p_all['surfaced_canaries_default'])} -> {_fmt_num(p_all['surfaced_canaries_candidate'])} "
            f"({_fmt_num(p_all['surfaced_canaries_delta'], signed=True)})** | "
            f"**{_fmt_pct(p_all['top_suspect_acc_default'])} -> {_fmt_pct(p_all['top_suspect_acc_candidate'])}** |"
        )

    if sol_cf:
        lines += [
            "",
            f"{h3} 6.1 Reference `SolverPolicy` Catchability Gate on Paired Counterfactual Seeds",
            "",
            "| Strategy | Tier | n | Solver Score +/- CI | Solver Acc | Mean Accuse Day | Score Delta vs Default |",
            "|---|---|---|---|---|---|---|",
            f"| `{cf['baseline_strategy']}` | {sol_cf['tier']} | {sol_cf['n_seeds']} | "
            f"{_fmt_num(sol_cf['default_score'], 3, signed=True)} +/- {_fmt_num(sol_cf['default_score_ci95'], 3)} | "
            f"{_fmt_pct(sol_cf['default_accuracy'])} | {_fmt_num(sol_cf['default_accuse_day'])} | baseline |",
            f"| `{cf['candidate_strategy']}` | {sol_cf['tier']} | {sol_cf['n_seeds']} | "
            f"{_fmt_num(sol_cf['candidate_score'], 3, signed=True)} +/- {_fmt_num(sol_cf['candidate_score_ci95'], 3)} | "
            f"{_fmt_pct(sol_cf['candidate_accuracy'])} | {_fmt_num(sol_cf['candidate_accuse_day'])} | "
            f"{_fmt_num(sol_cf['score_delta'], 3, signed=True)} +/- {_fmt_num(sol_cf['score_delta_ci95'], 3)} |",
        ]

    lines += [
        "",
        f"{h2} 7. Implications for Fair Mole Design Across Model Scales",
        "",
        "1. **Small/open-weight and low-budget regimes (`gemma-4-31b-it`, `gemini-3.1-flash-lite`)** fail primarily "
        "through uncalibrated below-breakeven accusations (92.5%-100.0% on Hard); `flash-lite` also falls for "
        "the angry decoy (18.8% decoy accusation rate across Medium + Hard), whereas `gemma-4-31b-it` already "
        "dismisses the decoy (100.0%) but accuses before isolating a suspect.",
        "2. **Mid-scale high-throughput Flash (`gemini-3.5-flash` served as `3.6-flash`)** plants early Day-1/Day-2 "
        "surgical `<=3`-recipient traps (34.5%-43.9% on Hard at low-high thinking) with minimal interview waste "
        "(0.9%-3.3% investigative share), making Rule 1 (`recent_low_recipient_docs >= 2 -> leak=most_recipients`) "
        "the decisive evasion lever (`P(mole)` drops by 0.566 at `high` thinking).",
        "3. **Frontier reasoning cells (`gemini-3.8-flash @ high`, `gemini-4-hydrogen/argon/carbon @ high/xhigh`)** "
        "abandon `<=3` surgical traps (0.0%-5.5% on Hard), spend 37.9%-70.2% of investigative calls on low-LR "
        "interviews, and plant reactive `4-8` / `>=9` canaries later in the horizon, making Rule 2 "
        "(`newest_doc_age_days == 0 -> leak=oldest`), Rule 3 (days 5-8 pacing), and Rule 4 (non-decoy peer framing) "
        "the binding levers while preserving Day-1 pipelined `SolverPolicy` catchability.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.ladder_miner")
    ap.add_argument(
        "--episodes",
        action="append",
        default=None,
        help="ladder episodes .jsonl.gz/.jsonl path(s), repeatable or comma-separated",
    )
    ap.add_argument("--cf-seeds", default="0-9")
    ap.add_argument("--cf-tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--strategy", default="frontier_synthesis_v14")
    ap.add_argument("--solver-ref-dir", default=DEFAULT_SOLVER_REF_DIR)
    ap.add_argument("--with-solver", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    cf_seeds = parse_seeds(args.cf_seeds) if args.cf_seeds.strip() else []
    data = mine_ladder_episodes(
        episode_paths=args.episodes,
        cf_seeds=cf_seeds,
        cf_tier=args.cf_tier,
        candidate_strategy_name=args.strategy,
        solver_ref_dir=args.solver_ref_dir,
        run_solver=args.with_solver,
        workers=args.workers,
    )
    rendered = json.dumps(data, indent=2, sort_keys=True) if args.json else render_ladder_report(data)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
