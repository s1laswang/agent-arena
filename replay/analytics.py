from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict
from typing import Any, Callable

from canary.analysis.tags import WHY as TAG_WHY
from canary.rules import (
    TIERS,
    TIERS_HISTORY,
    TIERS_V13,
    TIERS_VERSION,
    TRACKS,
    TierParams,
    tier_params_for_episode,
    tiers_version as rules_tiers_version,
)
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute as solver_attribute_regret
from canary.types import EpisodeResult, Step
from replay.loader import make_episode_id, pair_with_solver

SCRIPTED_AGENTS: frozenset[str] = frozenset({
    "solver",
    "do_nothing",
    "stop_early",
    "random",
    "restrict_all",
    "probe_all",
    "accuse_decoy",
    "accuse_most_logs",
    "obvious_heuristic",
    "logs_minus_decoy",
    "logs_only",
    "heuristic",
    "grok_tactics",
    "stub",
})

REAL_PREFIXES: tuple[str, ...] = (
    "openai:",
    "gemini:",
    "codex:",
    "opencode:",
    "claude:",
    "anthropic:",
    "google:",
    "xai:",
    "grok:",
    "deepseek:",
    "mistral:",
    "qwen:",
)

TIER_SORT_ORDER: dict[str, int] = {
    "hard": 0,
    "hard_forge": 1,
    "hard_rl": 2,
    "medium": 3,
    "easy": 4,
}

_EM_DASH = chr(0x2014)
_EN_DASH = chr(0x2013)

__all__ = [
    "REAL_PREFIXES",
    "SCRIPTED_AGENTS",
    "TIER_SORT_ORDER",
    "aggregate_failure_tags",
    "attribute_episode_regret",
    "bootstrap_mean_ci",
    "build_analytics_summary",
    "build_gap_table",
    "compute_episode_luck_stats",
    "infer_provenance",
    "infer_tiers_version",
    "paired_bootstrap_ratio_ci",
    "rank_featured_replays",
]


def _sanitize_text(text: Any) -> str:
    return str(text).replace(_EM_DASH, "-").replace(_EN_DASH, "-")


def _clean_float(val: Any, ndigits: int | None = None) -> float | None:
    if val is None:
        return None
    f = float(val)
    if not math.isfinite(f):
        return None
    return round(f, ndigits) if ndigits is not None else f


def _to_step(raw: Any) -> Step:
    if isinstance(raw, Step):
        return raw
    return Step(
        t=int(raw.get("t", 0) or 0),
        day=int(raw.get("day", 1) or 1),
        tool=str(raw.get("tool", "") or ""),
        args=dict(raw.get("args") or {}),
        result=dict(raw.get("result") or {}),
    )


def _to_episode_result(ep_dict: dict[str, Any]) -> EpisodeResult:
    steps = [_to_step(s) for s in (ep_dict.get("steps") or [])]
    return EpisodeResult(
        tier=str(ep_dict.get("tier") or "medium"),
        seed=int(ep_dict.get("seed", 0)),
        agent=str(ep_dict.get("agent") or "unknown"),
        steps=steps,
        score=float(ep_dict.get("score", 0.0)),
        accused=ep_dict.get("accused"),
        correct=bool(ep_dict.get("correct", False)),
        final_day=int(ep_dict.get("final_day", 0)),
        end_reason=str(ep_dict.get("end_reason") or "error"),
        meta=dict(ep_dict.get("meta") or {}),
    )


def _version_tuple(version: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", str(version or ""))]
    return tuple(nums) if nums else (0,)


def _version_sort_key(version: str) -> tuple[tuple[int, ...], str]:
    return (tuple(-x for x in _version_tuple(version)), str(version or ""))


def infer_tiers_version(ep_dict: dict[str, Any]) -> str:
    explicit = (
        ep_dict.get("tiers_version")
        or (ep_dict.get("meta") or {}).get("tiers_version")
        or (ep_dict.get("run_meta") or {}).get("tiers_version")
    )
    if explicit:
        return str(explicit)
    tier = str(ep_dict.get("tier") or "medium")
    steps = [_to_step(s) for s in (ep_dict.get("steps") or [])]
    params = tier_params_for_episode(tier, steps)
    base_tier = TRACKS.get(tier, tier)
    for ver in sorted(TIERS_HISTORY, key=_version_tuple, reverse=True):
        hist_p = TIERS_HISTORY[ver].get(base_tier)
        if hist_p is not None and hist_p == params and params != TIERS.get(base_tier):
            return ver
    return TIERS_VERSION


def _resolve_tier_params(
    ep_dict: dict[str, Any],
    steps: list[Step],
    tiers_version: str | None,
) -> TierParams:
    tier = str(ep_dict.get("tier") or "medium")
    base_tier = TRACKS.get(tier, tier)
    ver = (
        tiers_version
        or ep_dict.get("tiers_version")
        or (ep_dict.get("meta") or {}).get("tiers_version")
        or (ep_dict.get("run_meta") or {}).get("tiers_version")
    )
    if ver in ("v1.3", "v1.2") and base_tier in TIERS_V13:
        return TIERS_V13[base_tier]
    if ver == "v1.4" and base_tier in TIERS:
        return TIERS[base_tier]
    if ver and ver in TIERS_HISTORY and base_tier in TIERS_HISTORY[ver]:
        return TIERS_HISTORY[ver][base_tier]
    return tier_params_for_episode(tier, steps)


def infer_provenance(agent: str, ep_dict: dict[str, Any] | None = None) -> dict[str, str]:
    existing = (ep_dict or {}).get("provenance")
    ag = str(agent or "").strip()
    if isinstance(existing, dict) and existing.get("kind") in ("real", "scripted"):
        kind = str(existing["kind"])
        model_id = str(existing.get("model_id") or ag)
        default_lbl = f"REAL {model_id}" if kind == "real" else "SCRIPTED"
        label = _sanitize_text(existing.get("label") or default_lbl)
        return {"kind": kind, "label": label, "model_id": model_id}

    low = ag.lower()
    meta = (ep_dict or {}).get("meta") if isinstance((ep_dict or {}).get("meta"), dict) else {}
    run_meta = (ep_dict or {}).get("run_meta") if isinstance((ep_dict or {}).get("run_meta"), dict) else {}
    explicit_prov = meta.get("provenance") or run_meta.get("provenance")

    if (
        low in SCRIPTED_AGENTS
        or low.startswith(("stub:", "scripted:", "baseline:"))
        or explicit_prov == "scripted"
    ):
        return {"kind": "scripted", "label": "SCRIPTED", "model_id": ag}

    raw_model = meta.get("model") or run_meta.get("model")
    if (
        explicit_prov == "real"
        or raw_model
        or low.startswith(REAL_PREFIXES)
        or low == "grok"
        or "/" in ag
        or any(
            tok in low
            for tok in ("gpt-", "gemini", "claude", "o1-", "o3-", "o4-", "sonnet", "opus", "flash", "carbon")
        )
    ):
        model_id = str(raw_model or ag)
        return {"kind": "real", "label": f"REAL {model_id}", "model_id": model_id}

    return {"kind": "scripted", "label": "SCRIPTED", "model_id": ag}


def compute_episode_luck_stats(
    ep_dict: dict[str, Any],
    tiers_version: str | None = None,
) -> dict[str, Any]:
    steps = [_to_step(s) for s in (ep_dict.get("steps") or [])]
    P = _resolve_tier_params(ep_dict, steps, tiers_version)
    sp = SolverPolicy(P)
    sp.obs.employees = [f"e{k:02d}" for k in range(P.n_employees)]
    accused = ep_dict.get("accused")
    accuse_idx: int | None = None
    accuse_day: int | None = None
    for idx, st in enumerate(steps):
        if st.tool == "accuse" and (st.result or {}).get("ok", True):
            accuse_idx = idx
            accuse_day = int(st.day)
            if not accused:
                accused = (st.args or {}).get("employee")
            break
    limit_idx = accuse_idx if accuse_idx is not None else len(steps)
    for prev in steps[:limit_idx]:
        sp._ingest(prev)
    sp.seen = limit_idx
    post = sp.belief() if sp.obs.employees else {}
    computed_p_top = _clean_float(max(post.values())) if post else None
    p_top = (
        _clean_float(ep_dict.get("p_top"))
        if ep_dict.get("p_top") is not None
        else computed_p_top
    )
    meta = ep_dict.get("meta") if isinstance(ep_dict.get("meta"), dict) else {}
    v_recorded = meta.get("V") if meta.get("V") is not None else meta.get("V_final")
    wrong_pen = abs(float(P.wrong_accusation_score))

    if accused:
        if accuse_day is None and ep_dict.get("final_day") is not None:
            accuse_day = int(ep_dict["final_day"])
        if ep_dict.get("p_accused") is not None:
            p_accused = float(ep_dict["p_accused"])
            if p_top is None or p_top < p_accused:
                p_top = p_accused
        else:
            p_accused = float(post.get(str(accused), 0.0))
        score = float(ep_dict.get("score", 0.0))
        correct = bool(ep_dict.get("correct", False))
        v_est = score if (correct and score > 0) else float(v_recorded if v_recorded is not None else sp.V)
        v_est = max(0.0, v_est)
        luck_adjusted = p_accused * v_est + (1.0 - p_accused) * float(P.wrong_accusation_score)
        denom = v_est + wrong_pen
        break_even_p = (wrong_pen / denom) if denom > 0 else 1.0
        premature = bool(p_accused < break_even_p)
        return {
            "p_accused": _clean_float(p_accused),
            "p_top": _clean_float(p_top),
            "break_even_p": float(_clean_float(break_even_p) or 1.0),
            "luck_adjusted_score": float(_clean_float(luck_adjusted) or 0.0),
            "premature": premature,
            "abstained": False,
            "accuse_day": accuse_day,
            "v_at_accuse": float(_clean_float(v_est) or 0.0),
        }

    v_est = max(0.0, float(v_recorded if v_recorded is not None else sp.V))
    denom = v_est + wrong_pen
    break_even_p = (wrong_pen / denom) if denom > 0 else 1.0
    return {
        "p_accused": None,
        "p_top": _clean_float(p_top),
        "break_even_p": float(_clean_float(break_even_p) or 1.0),
        "luck_adjusted_score": 0.0,
        "premature": False,
        "abstained": True,
        "accuse_day": None,
        "v_at_accuse": float(_clean_float(v_est) or 0.0),
    }


def _infer_accuse_day(ep_dict: dict[str, Any], abstained: bool) -> int | None:
    if abstained:
        return None
    for raw in ep_dict.get("steps") or []:
        st = _to_step(raw)
        if st.tool == "accuse" and (st.result or {}).get("ok", True):
            return int(st.day)
    if ep_dict.get("final_day") is not None:
        return int(ep_dict["final_day"])
    return None


def _cached_luck_stats(
    ep_dict: dict[str, Any],
    tiers_version: str | None,
    cache: dict[tuple[int, str | None], dict[str, Any]],
) -> dict[str, Any]:
    key = (id(ep_dict), tiers_version)
    if key in cache:
        return cache[key]
    attached = ep_dict.get("luck_stats")
    has_all_top = (
        ep_dict.get("luck_adjusted_score") is not None
        and ep_dict.get("premature") is not None
        and ep_dict.get("abstained") is not None
    )
    if isinstance(attached, dict) and all(k in attached for k in ("luck_adjusted_score", "premature", "abstained")):
        abstained = bool(attached["abstained"])
        acc_day = attached.get("accuse_day")
        if acc_day is None:
            acc_day = _infer_accuse_day(ep_dict, abstained)
        res = {
            "p_accused": _clean_float(attached.get("p_accused")),
            "p_top": _clean_float(attached.get("p_top")),
            "break_even_p": float(_clean_float(attached.get("break_even_p", 0.5)) or 0.5),
            "luck_adjusted_score": float(_clean_float(attached["luck_adjusted_score"]) or 0.0),
            "premature": bool(attached["premature"]),
            "abstained": abstained,
            "accuse_day": int(acc_day) if acc_day is not None else None,
            "v_at_accuse": float(_clean_float(attached.get("v_at_accuse", 0.0)) or 0.0),
        }
        cache[key] = res
        return res
    if has_all_top:
        abstained = bool(ep_dict["abstained"])
        acc_day = ep_dict.get("accuse_day")
        if acc_day is None:
            acc_day = _infer_accuse_day(ep_dict, abstained)
        res = {
            "p_accused": _clean_float(ep_dict.get("p_accused")),
            "p_top": _clean_float(ep_dict.get("p_top")),
            "break_even_p": float(_clean_float(ep_dict.get("break_even_p", 0.5)) or 0.5),
            "luck_adjusted_score": float(_clean_float(ep_dict["luck_adjusted_score"]) or 0.0),
            "premature": bool(ep_dict["premature"]),
            "abstained": abstained,
            "accuse_day": int(acc_day) if acc_day is not None else None,
            "v_at_accuse": float(_clean_float(ep_dict.get("v_at_accuse", 0.0)) or 0.0),
        }
        cache[key] = res
        return res
    res = compute_episode_luck_stats(ep_dict, tiers_version=tiers_version)
    if ep_dict.get("luck_adjusted_score") is not None:
        res = dict(res, luck_adjusted_score=float(_clean_float(ep_dict["luck_adjusted_score"]) or 0.0))
    if ep_dict.get("premature") is not None:
        res = dict(res, premature=bool(ep_dict["premature"]))
    if ep_dict.get("abstained") is not None:
        res = dict(res, abstained=bool(ep_dict["abstained"]))
    cache[key] = res
    return res


def bootstrap_mean_ci(
    vals: list[float],
    n_boot: int = 2000,
    seed: int = 42,
) -> tuple[float | None, float | None, float | None]:
    n = len(vals)
    if n == 0:
        return (None, None, None)
    clean = [float(x) for x in vals]
    mean_val = round(sum(clean) / n, 4)
    if n == 1 or n_boot <= 0:
        return (mean_val, mean_val, mean_val)
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(n_boot):
        total = sum(clean[rng.randrange(n)] for _ in range(n))
        samples.append(total / n)
    samples.sort()
    lo_idx = int(0.025 * len(samples))
    hi_idx = max(0, min(len(samples) - 1, int(0.975 * len(samples)) - 1))
    if hi_idx < lo_idx:
        hi_idx = lo_idx
    return (mean_val, round(samples[lo_idx], 4), round(samples[hi_idx], 4))


def paired_bootstrap_ratio_ci(
    agent_vals: list[float],
    solver_vals: list[float],
    n_boot: int = 2000,
    seed: int = 42,
) -> tuple[float | None, float | None, float | None]:
    if len(agent_vals) != len(solver_vals):
        raise ValueError("agent_vals and solver_vals must have equal length")
    n = len(solver_vals)
    if n == 0:
        return (None, None, None)
    a_clean = [float(x) for x in agent_vals]
    s_clean = [float(x) for x in solver_vals]
    s_sum = sum(s_clean)
    if (s_sum / n) <= 1e-6:
        return (None, None, None)
    ratio = round(sum(a_clean) / s_sum, 4)
    if n == 1 or n_boot <= 0:
        return (ratio, ratio, ratio)
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        bs = sum(s_clean[i] for i in idx)
        if (bs / n) > 1e-6:
            ba = sum(a_clean[i] for i in idx)
            samples.append(ba / bs)
    if not samples:
        return (ratio, None, None)
    samples.sort()
    lo_idx = int(0.025 * len(samples))
    hi_idx = max(0, min(len(samples) - 1, int(0.975 * len(samples)) - 1))
    if hi_idx < lo_idx:
        hi_idx = lo_idx
    return (ratio, round(samples[lo_idx], 4), round(samples[hi_idx], 4))


def _is_valid_episode(ep_dict: dict[str, Any]) -> bool:
    if ep_dict.get("valid") is False:
        return False
    meta = ep_dict.get("meta")
    if isinstance(meta, dict) and meta.get("valid") is False:
        return False
    return True


def _group_row_sort_key(
    tiers_ver: str,
    tier: str,
    agent: str,
    prov_kind: str,
    primary_desc: float = 0.0,
    secondary_desc: float = 0.0,
) -> tuple[Any, ...]:
    if agent == "solver":
        agent_bucket = 0
    elif prov_kind == "real":
        agent_bucket = 1
    else:
        agent_bucket = 2
    return (
        _version_sort_key(tiers_ver),
        TIER_SORT_ORDER.get(tier, 99),
        tier,
        agent_bucket,
        -primary_desc,
        -secondary_desc,
        agent,
    )


def build_gap_table(
    episodes: list[dict[str, Any]],
    invalid_counts: dict[tuple[str, str, str], int] | None = None,
) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    skipped_invalid: Counter[tuple[str, str, str]] = Counter()
    for idx, ep in enumerate(episodes):
        tv = infer_tiers_version(ep)
        tier = str(ep.get("tier") or "medium")
        agent = str(ep.get("agent") or "unknown")
        key = (tv, tier, agent)
        if not _is_valid_episode(ep):
            skipped_invalid[key] += 1
            continue
        groups[key].append((idx, ep))

    solver_by_group: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    for (tv, tier, agent), items in groups.items():
        if agent == "solver":
            ordered = sorted(items, key=lambda pair: (int(pair[1].get("seed", 0)), pair[0]))
            solver_by_group[(tv, tier)] = {int(ep["seed"]): ep for _, ep in ordered}

    luck_cache: dict[tuple[int, str | None], dict[str, Any]] = {}
    unsorted_rows: list[dict[str, Any]] = []
    for (tv, tier, agent), items in groups.items():
        ordered = [ep for _, ep in sorted(items, key=lambda pair: (int(pair[1].get("seed", 0)), pair[0]))]
        n = len(ordered)
        if n == 0:
            continue
        prov = infer_provenance(agent, ordered[0])
        inv_n = (
            int(invalid_counts.get((tv, tier, agent), 0))
            if invalid_counts is not None
            else int(skipped_invalid.get((tv, tier, agent), 0))
        )
        scores = [float(ep.get("score", 0.0)) for ep in ordered]
        luck_list = [_cached_luck_stats(ep, tv, luck_cache) for ep in ordered]
        mean_score, score_ci_low, score_ci_high = bootstrap_mean_ci(scores)
        assert mean_score is not None
        score_ci_halfwidth = (
            round((score_ci_high - score_ci_low) / 2.0, 4)
            if (score_ci_low is not None and score_ci_high is not None)
            else 0.0
        )
        luck_vals = [float(ls["luck_adjusted_score"]) for ls in luck_list]
        luck_mean, luck_mean_ci_low, luck_mean_ci_high = bootstrap_mean_ci(luck_vals)
        assert luck_mean is not None

        correct_count = sum(1 for ep in ordered if ep.get("correct"))
        accused_indices = [i for i, ls in enumerate(luck_list) if not ls["abstained"]]
        accused_count = len(accused_indices)
        correct_when_accused = sum(1 for i in accused_indices if ordered[i].get("correct"))

        accuracy = round(correct_count / n, 4)
        accuracy_when_accused = round(correct_when_accused / accused_count, 4) if accused_count > 0 else None
        accuse_rate = round(accused_count / n, 4)
        abstain_rate = round((n - accused_count) / n, 4)
        premature_rate = round(sum(1 for ls in luck_list if ls["premature"]) / n, 4)

        accuse_days = [int(ls["accuse_day"]) for ls in luck_list if ls.get("accuse_day") is not None]
        mean_accuse_day = round(sum(accuse_days) / len(accuse_days), 4) if accuse_days else None

        p_accused_vals = [float(ls["p_accused"]) for ls in luck_list if ls.get("p_accused") is not None]
        mean_p_accused = round(sum(p_accused_vals) / len(p_accused_vals), 4) if p_accused_vals else None

        solver_seed_map = solver_by_group.get((tv, tier), {})
        paired = [(ep, solver_seed_map[int(ep["seed"])]) for ep in ordered if int(ep["seed"]) in solver_seed_map]
        paired_n = len(paired)
        if paired_n > 0:
            a_sc = [float(a.get("score", 0.0)) for a, _ in paired]
            s_sc = [float(s.get("score", 0.0)) for _, s in paired]
            a_lk = [float(_cached_luck_stats(a, tv, luck_cache)["luck_adjusted_score"]) for a, _ in paired]
            s_lk = [float(_cached_luck_stats(s, tv, luck_cache)["luck_adjusted_score"]) for _, s in paired]
            solver_paired_mean: float | None = round(sum(s_sc) / paired_n, 4)
            paired_delta: float | None = round(sum(x - y for x, y in zip(a_sc, s_sc)) / paired_n, 4)
            ratio, ci_low, ci_high = paired_bootstrap_ratio_ci(a_sc, s_sc)
            luck_ratio, luck_lo, luck_hi = paired_bootstrap_ratio_ci(a_lk, s_lk)
        else:
            solver_paired_mean = None
            paired_delta = None
            ratio, ci_low, ci_high = (None, None, None)
            luck_ratio, luck_lo, luck_hi = (None, None, None)

        unsorted_rows.append({
            "tiers_version": tv,
            "tier": tier,
            "agent": agent,
            "provenance": prov,
            "n": n,
            "invalid_n": inv_n,
            "paired_n": paired_n,
            "mean_score": mean_score,
            "score_ci_low": score_ci_low,
            "score_ci_high": score_ci_high,
            "score_ci_halfwidth": score_ci_halfwidth,
            "luck_adjusted_mean": luck_mean,
            "luck_mean_ci_low": luck_mean_ci_low,
            "luck_mean_ci_high": luck_mean_ci_high,
            "solver_paired_mean": solver_paired_mean,
            "solver_score": solver_paired_mean,
            "paired_delta": paired_delta,
            "score_delta": paired_delta,
            "ratio": ratio,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "luck_adjusted_ratio": luck_ratio,
            "luck_ci_low": luck_lo,
            "luck_ci_high": luck_hi,
            "accuracy": accuracy,
            "accuracy_when_accused": accuracy_when_accused,
            "accuse_rate": accuse_rate,
            "abstain_rate": abstain_rate,
            "premature_accuse_rate": premature_rate,
            "mean_accuse_day": mean_accuse_day,
            "mean_p_accused": mean_p_accused,
        })

    rows = sorted(
        unsorted_rows,
        key=lambda row: _group_row_sort_key(
            row["tiers_version"],
            row["tier"],
            row["agent"],
            row["provenance"]["kind"],
            row["luck_adjusted_mean"],
            row["mean_score"],
        ),
    )
    return {"rows": rows}


def attribute_episode_regret(
    ep_dict: dict[str, Any],
    tiers_version: str | None = None,
    attribute_fn: Callable[[EpisodeResult], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    tv = str(tiers_version or infer_tiers_version(ep_dict))
    fn = attribute_fn if attribute_fn is not None else solver_attribute_regret
    ep_res = _to_episode_result(ep_dict)
    if tv == TIERS_VERSION or tv in TIERS_HISTORY:
        with rules_tiers_version(tv):
            raw_items = fn(ep_res) or []
    else:
        raw_items = fn(ep_res) or []

    cleaned: list[dict[str, Any]] = []
    for item in raw_items:
        entry: dict[str, Any] = {
            "t": int(item["t"]) if item.get("t") is not None else None,
            "day": int(item["day"]) if item.get("day") is not None else None,
            "action": _sanitize_text(item.get("action") or ""),
            "regret": float(_clean_float(item.get("regret"), 6) or 0.0),
            "p_best": _clean_float(item.get("p_best"), 4),
            "tags": [_sanitize_text(t) for t in (item.get("tags") or [])],
        }
        if item.get("p_accused") is not None:
            entry["p_accused"] = _clean_float(item.get("p_accused"), 4)
        cleaned.append(entry)
    return cleaned


def aggregate_failure_tags(
    episodes: list[dict[str, Any]],
    attribute_fn: Callable[[EpisodeResult], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    skipped_invalid: Counter[tuple[str, str, str]] = Counter()
    for idx, ep in enumerate(episodes):
        tv = infer_tiers_version(ep)
        tier = str(ep.get("tier") or "medium")
        agent = str(ep.get("agent") or "unknown")
        key = (tv, tier, agent)
        if not _is_valid_episode(ep):
            skipped_invalid[key] += 1
            continue
        groups[key].append((idx, ep))

    unsorted_rows: list[dict[str, Any]] = []
    for (tv, tier, agent), items in groups.items():
        ordered = [ep for _, ep in sorted(items, key=lambda pair: (int(pair[1].get("seed", 0)), pair[0]))]
        n = len(ordered)
        if n == 0:
            continue
        prov = infer_provenance(agent, ordered[0])
        inv_n = int(skipped_invalid.get((tv, tier, agent), 0))
        scores: list[float] = []
        regret_total = 0.0
        tag_stats: dict[str, dict[str, Any]] = {}

        for ep in ordered:
            seed = int(ep.get("seed", 0))
            ep_id = str(ep.get("episode_id") or ep.get("id") or make_episode_id(tv, tier, seed, agent))
            scores.append(float(ep.get("score", 0.0)))
            steps_by_t = {st.t: st for st in (_to_step(s) for s in (ep.get("steps") or []))}
            seen_in_ep: set[str] = set()
            for item in attribute_episode_regret(ep, tiers_version=tv, attribute_fn=attribute_fn):
                r = float(item.get("regret", 0.0))
                regret_total += r
                for tag in item.get("tags", []):
                    d = tag_stats.setdefault(
                        tag,
                        {"count": 0, "episodes_with": 0, "regret_sum": 0.0, "worst": None},
                    )
                    d["count"] += 1
                    d["regret_sum"] += r
                    if tag not in seen_in_ep:
                        d["episodes_with"] += 1
                        seen_in_ep.add(tag)
                    prev_worst = d["worst"]
                    if prev_worst is None or r > float(prev_worst["regret"]):
                        t_val = item.get("t")
                        step_obj = steps_by_t.get(t_val) if isinstance(t_val, int) else None
                        p_val = float(item["p_best"]) if item.get("p_best") is not None else 0.0
                        why_tmpl = TAG_WHY.get(tag, tag)
                        why_text = _sanitize_text(why_tmpl.format(p=p_val))
                        d["worst"] = {
                            "episode_id": ep_id,
                            "seed": seed,
                            "t": t_val,
                            "day": item.get("day"),
                            "tool": item.get("action"),
                            "args": dict(step_obj.args) if step_obj is not None else {},
                            "regret": round(r, 4),
                            "p_best": item.get("p_best"),
                            "why": why_text,
                        }

        finalized_tags: dict[str, dict[str, Any]] = {}
        for tag, d in sorted(
            tag_stats.items(),
            key=lambda kv: (-kv[1]["regret_sum"], -kv[1]["episodes_with"], -kv[1]["count"], kv[0]),
        ):
            finalized_tags[tag] = {
                "count": int(d["count"]),
                "episodes_with": int(d["episodes_with"]),
                "rate": round(d["episodes_with"] / n, 4),
                "regret_sum": round(float(d["regret_sum"]), 4),
                "worst": d["worst"],
            }

        top_tags = [
            t
            for t, _ in sorted(
                finalized_tags.items(),
                key=lambda kv: (-kv[1]["rate"], -kv[1]["regret_sum"], kv[0]),
            )[:3]
        ]
        mean_score = round(sum(scores) / n, 4)
        unsorted_rows.append({
            "tiers_version": tv,
            "tier": tier,
            "agent": agent,
            "provenance": prov,
            "n": n,
            "invalid_n": inv_n,
            "mean_score": mean_score,
            "regret_total": round(regret_total, 4),
            "regret_mean": round(regret_total / n, 4),
            "top_tags": top_tags,
            "tags": finalized_tags,
        })

    rows = sorted(
        unsorted_rows,
        key=lambda row: _group_row_sort_key(
            row["tiers_version"],
            row["tier"],
            row["agent"],
            row["provenance"]["kind"],
            -row["regret_mean"],
            row["mean_score"],
        ),
    )
    return {"rows": rows}


def _first_not_none(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in mapping and mapping[k] is not None:
            return mapping[k]
    return None


def _extract_fooled_summary(
    item: dict[str, Any],
    agent_ep: dict[str, Any],
    luck_stats: dict[str, Any],
) -> tuple[int | None, int | None, str | None, str | None]:
    fooled_obj = item.get("fooled")
    if not isinstance(fooled_obj, dict):
        fooled_obj = agent_ep.get("fooled") if isinstance(agent_ep.get("fooled"), dict) else {}

    raw_step = _first_not_none(item, ("fooled_step",))
    if raw_step is None:
        raw_step = _first_not_none(fooled_obj, ("fooled_step", "step", "t", "step_index"))
    raw_day = _first_not_none(item, ("fooled_day",))
    if raw_day is None:
        raw_day = _first_not_none(fooled_obj, ("fooled_day", "day"))
    raw_kind = _first_not_none(item, ("fooled_kind",))
    if raw_kind is None:
        raw_kind = _first_not_none(fooled_obj, ("fooled_kind", "kind", "tag", "type"))
    raw_headline = _first_not_none(item, ("fooled_headline",))
    if raw_headline is None:
        raw_headline = _first_not_none(fooled_obj, ("fooled_headline", "headline", "summary", "title", "why", "reason"))

    steps = [_to_step(s) for s in (agent_ep.get("steps") or [])]
    accused = agent_ep.get("accused")
    accuse_step: Step | None = None
    for st in steps:
        if st.tool == "accuse" and (st.result or {}).get("ok", True):
            accuse_step = st
            if not accused:
                accused = (st.args or {}).get("employee")
            break

    if raw_step is None:
        if accuse_step is not None:
            raw_step = accuse_step.t
        elif steps:
            raw_step = steps[-1].t
    if raw_day is None:
        if accuse_step is not None:
            raw_day = accuse_step.day
        elif agent_ep.get("final_day") is not None:
            raw_day = int(agent_ep["final_day"])

    correct = bool(agent_ep.get("correct", False))
    p_acc = luck_stats.get("p_accused")
    be_p = luck_stats.get("break_even_p", 0.5)
    decoy = (agent_ep.get("meta") or {}).get("decoy")

    if raw_kind is None:
        if accused and not correct:
            if decoy and str(accused) == str(decoy):
                raw_kind = "decoy_chase"
            elif luck_stats.get("premature"):
                raw_kind = "premature_accusation"
            else:
                raw_kind = "wrong_accusation"
        elif accused and correct and luck_stats.get("premature"):
            raw_kind = "lucky_guess"
        elif not accused:
            raw_kind = "no_accusation"
        else:
            raw_kind = "justified_accusation"

    if raw_headline is None:
        day_label = f"day {int(raw_day)}" if raw_day is not None else "final day"
        if accused and not correct:
            if raw_kind == "decoy_chase":
                raw_headline = f"Chased disgruntled decoy {accused} on {day_label} instead of isolating the mole"
            elif p_acc is not None and luck_stats.get("premature"):
                raw_headline = (
                    f"Prematurely accused innocent {accused} on {day_label} "
                    f"(posterior {p_acc:.2f} below break-even {be_p:.2f})"
                )
            else:
                raw_headline = f"Accused innocent {accused} on {day_label}"
        elif accused and correct and luck_stats.get("premature") and p_acc is not None:
            raw_headline = f"Gambled early on {accused} on {day_label} (posterior {p_acc:.2f} below break-even {be_p:.2f})"
        elif not accused:
            raw_headline = f"Ended on {day_label} without accusing while leaks drained company value"
        else:
            raw_headline = f"Accused {accused} on {day_label}"

    step_out = int(raw_step) if raw_step is not None else None
    day_out = int(raw_day) if raw_day is not None else None
    kind_out = _sanitize_text(raw_kind) if raw_kind is not None else None
    head_out = _sanitize_text(raw_headline) if raw_headline is not None else None
    return (step_out, day_out, kind_out, head_out)


def _version_bonus(version: str) -> float:
    if version == "v1.4":
        return 40.0
    if version == "v1.3":
        return 20.0
    if version == "v1.2":
        return 0.0
    vt = _version_tuple(version)
    minor = vt[1] if len(vt) > 1 else 0
    return float(max(-10, min(60, (minor - 2) * 20)))


def rank_featured_replays(paired_items: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    if limit <= 0 or not paired_items:
        return []

    luck_cache: dict[tuple[int, str | None], dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []

    for item in paired_items:
        agent_ep = item.get("agent_episode") or {}
        solver_ep = item.get("solver_episode") or {}
        if not agent_ep or not solver_ep:
            continue
        if not _is_valid_episode(agent_ep) or not _is_valid_episode(solver_ep):
            continue
        agent = str(item.get("agent") or agent_ep.get("agent") or "")
        if agent == "solver":
            continue
        tv = str(item.get("tiers_version") or infer_tiers_version(agent_ep))
        tier = str(item.get("tier") or agent_ep.get("tier") or "medium")
        seed = int(item["seed"] if "seed" in item and item["seed"] is not None else agent_ep.get("seed", 0))
        prov = infer_provenance(agent, item if isinstance(item.get("provenance"), dict) else agent_ep)

        agent_score = float(agent_ep.get("score", 0.0))
        solver_score = float(solver_ep.get("score", 0.0))
        agent_luck_stats = _cached_luck_stats(agent_ep, tv, luck_cache)
        solver_luck_stats = _cached_luck_stats(solver_ep, tv, luck_cache)
        luck_adj = (
            float(item["luck_adjusted_score"])
            if item.get("luck_adjusted_score") is not None
            else float(agent_luck_stats["luck_adjusted_score"])
        )

        fooled_step, fooled_day, fooled_kind, fooled_headline = _extract_fooled_summary(
            item, agent_ep, agent_luck_stats
        )

        agent_ep_id = str(
            item.get("agent_episode_id")
            or agent_ep.get("episode_id")
            or agent_ep.get("id")
            or make_episode_id(tv, tier, seed, agent)
        )
        solver_agent_name = str(solver_ep.get("agent") or "solver")
        solver_ep_id = str(
            item.get("solver_episode_id")
            or solver_ep.get("episode_id")
            or solver_ep.get("id")
            or make_episode_id(tv, tier, seed, solver_agent_name)
        )
        pair_id = str(item.get("pair_id") or f"{agent_ep_id}__vs__solver")

        solver_ok = bool(solver_ep.get("correct", False))
        solver_strong = solver_ok and solver_score > 0.3
        agent_ok = bool(agent_ep.get("correct", False))
        agent_accused = not bool(agent_luck_stats["abstained"])
        gap = solver_score - agent_score
        luck_gap = float(solver_luck_stats["luck_adjusted_score"]) - luck_adj

        real_bonus = 1000.0 if prov["kind"] == "real" else 0.0
        if solver_strong and (not agent_ok) and agent_accused:
            drama_bonus = 300.0
        elif solver_ok and (not agent_ok) and agent_accused:
            drama_bonus = 220.0
        elif solver_strong and (not agent_ok):
            drama_bonus = 150.0
        elif solver_ok and (not agent_ok):
            drama_bonus = 100.0
        elif solver_strong and agent_ok and bool(agent_luck_stats["premature"]):
            drama_bonus = 60.0
        elif solver_strong:
            drama_bonus = 30.0
        elif solver_ok:
            drama_bonus = 15.0
        else:
            drama_bonus = 0.0

        trap_bonus = 0.0
        if (not agent_ok) and agent_accused:
            if fooled_kind in ("decoy_chase", "ignored_delay"):
                trap_bonus = 20.0
            elif fooled_kind in ("premature_accusation", "premature_gamble") or bool(agent_luck_stats["premature"]):
                trap_bonus = 15.0

        base_score = (
            real_bonus
            + drama_bonus
            + trap_bonus
            + _version_bonus(tv)
            + 25.0 * gap
            + 5.0 * max(0.0, luck_gap)
        )

        summary = {
            "pair_id": pair_id,
            "tiers_version": tv,
            "tier": tier,
            "seed": seed,
            "agent_episode_id": agent_ep_id,
            "solver_episode_id": solver_ep_id,
            "agent": agent,
            "provenance": prov,
            "agent_score": round(agent_score, 4),
            "solver_score": round(solver_score, 4),
            "score_delta": round(agent_score - solver_score, 4),
            "luck_adjusted_score": round(luck_adj, 4),
            "fooled_step": fooled_step,
            "fooled_day": fooled_day,
            "fooled_kind": fooled_kind,
            "fooled_headline": fooled_headline,
        }
        candidates.append({"summary": summary, "base_score": base_score})

    selected: list[dict[str, Any]] = []
    used_indices: set[int] = set()
    seen_agent: Counter[str] = Counter()
    seen_agent_tier: Counter[tuple[str, str]] = Counter()
    seen_tier: Counter[str] = Counter()
    seen_world: Counter[tuple[str, str, int]] = Counter()

    target = min(limit, len(candidates))
    for _ in range(target):
        best_idx: int | None = None
        best_key: tuple[Any, ...] | None = None
        for idx, cand in enumerate(candidates):
            if idx in used_indices:
                continue
            s = cand["summary"]
            ag = s["agent"]
            tr = s["tier"]
            tv = s["tiers_version"]
            sd = s["seed"]
            diversity_penalty = min(
                180.0,
                35.0 * seen_agent_tier[(ag, tr)]
                + 20.0 * seen_agent[ag]
                + 8.0 * seen_tier[tr]
                + 15.0 * seen_world[(tv, tr, sd)],
            )
            eff_score = cand["base_score"] - diversity_penalty
            key = (
                -eff_score,
                -cand["base_score"],
                _version_sort_key(tv),
                TIER_SORT_ORDER.get(tr, 99),
                ag,
                sd,
                s["pair_id"],
            )
            if best_key is None or key < best_key:
                best_key = key
                best_idx = idx
        if best_idx is None:
            break
        used_indices.add(best_idx)
        chosen = candidates[best_idx]["summary"]
        selected.append(chosen)
        seen_agent[chosen["agent"]] += 1
        seen_agent_tier[(chosen["agent"], chosen["tier"])] += 1
        seen_tier[chosen["tier"]] += 1
        seen_world[(chosen["tiers_version"], chosen["tier"], chosen["seed"])] += 1

    return selected


def build_analytics_summary(
    episodes: list[dict[str, Any]],
    paired_items: list[dict[str, Any]] | None = None,
    featured_limit: int = 8,
    include_failure_tags: bool = True,
) -> dict[str, Any]:
    pairs = paired_items if paired_items is not None else pair_with_solver(episodes)
    return {
        "gap_table": build_gap_table(episodes),
        "featured_replays": rank_featured_replays(pairs, limit=featured_limit),
        "failure_tags": aggregate_failure_tags(episodes) if include_failure_tags else {"rows": []},
    }
