from __future__ import annotations

import math
from typing import Any

from canary.rules import (
    KNOWN_V_MODE,
    KNOWN_V_MODE_HISTORY,
    TIERS,
    TIERS_HISTORY,
    TIERS_V13,
    TIERS_VERSION,
    TRACKS,
    TierParams,
    tier_params_for_episode,
)
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute
from canary.types import EpisodeResult, Step

_TIERS_V14: dict[str, TierParams] = dict(TIERS)

_OBS_NOOP_TOOLS: frozenset[str] = frozenset({
    "accuse",
    "read_message",
    "restrict_access",
    "unrestrict_access",
})

__all__ = [
    "compute_belief_trace",
    "resolve_episode_params",
]


def _explicit_tiers_version(ep: dict[str, Any]) -> str | None:
    top = ep.get("tiers_version")
    if isinstance(top, str) and top.strip():
        return top.strip()
    meta = ep.get("meta")
    if isinstance(meta, dict):
        meta_ver = meta.get("tiers_version")
        if isinstance(meta_ver, str) and meta_ver.strip():
            return meta_ver.strip()
    run_meta = ep.get("run_meta")
    if isinstance(run_meta, dict):
        run_ver = run_meta.get("tiers_version")
        if isinstance(run_ver, str) and run_ver.strip():
            return run_ver.strip()
    return None


def resolve_episode_params(ep: dict[str, Any]) -> TierParams:
    tier = str(ep.get("tier") or "hard")
    base_tier = TRACKS.get(tier, tier)
    version = _explicit_tiers_version(ep)
    if version in ("v1.2", "v1.3") and base_tier in TIERS_V13:
        return TIERS_V13[base_tier]
    if version is not None and version in TIERS_HISTORY:
        hist = TIERS_HISTORY[version]
        if base_tier in hist:
            return hist[base_tier]
    if version == "v1.4" and base_tier in _TIERS_V14:
        return _TIERS_V14[base_tier]
    return tier_params_for_episode(tier, ep.get("steps") or ())


def _resolve_version_and_params(ep: dict[str, Any]) -> tuple[str, TierParams]:
    params = resolve_episode_params(ep)
    explicit = _explicit_tiers_version(ep)
    if explicit is not None:
        return explicit, params
    tier = str(ep.get("tier") or "hard")
    base_tier = TRACKS.get(tier, tier)
    if (
        base_tier in TIERS_V13
        and params == TIERS_V13[base_tier]
        and params != _TIERS_V14.get(base_tier)
    ):
        return "v1.3", params
    return TIERS_VERSION, params


def _leak_timing_known_for_version(tiers_version: str) -> bool:
    known_v_mode = KNOWN_V_MODE_HISTORY.get(tiers_version, KNOWN_V_MODE)
    return not bool(known_v_mode)


def _is_numeric(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _compute_break_even_p(known_v: float, wrong_accusation_score: float) -> float:
    abs_ws = abs(float(wrong_accusation_score))
    kv = max(0.0, float(known_v))
    denom = kv + abs_ws
    if denom <= 0.0:
        return 0.0
    return min(1.0, max(0.0, abs_ws / denom))


def _top_from_posterior(post: dict[str, float]) -> tuple[str, float]:
    best_emp, best_p = min(post.items(), key=lambda kv: (-kv[1], kv[0]))
    return str(best_emp), float(best_p)


def _to_step(raw: Step | dict[str, Any], idx: int) -> Step:
    if isinstance(raw, Step):
        return Step(
            t=int(raw.t),
            day=int(raw.day),
            tool=str(raw.tool),
            args=dict(raw.args) if isinstance(raw.args, dict) else {},
            result=(
                dict(raw.result)
                if isinstance(raw.result, dict)
                else {"ok": True, "data": {}, "error": None}
            ),
        )
    t_val = raw.get("t", idx)
    day_val = raw.get("day", 1)
    args_val = raw.get("args")
    res_val = raw.get("result")
    return Step(
        t=int(idx if t_val is None else t_val),
        day=int(1 if day_val is None else day_val),
        tool=str(raw.get("tool", "")),
        args=dict(args_val) if isinstance(args_val, dict) else {},
        result=(
            dict(res_val)
            if isinstance(res_val, dict)
            else {"ok": True, "data": {}, "error": None}
        ),
    )


def _to_episode_result(ep: dict[str, Any], steps: list[Step]) -> EpisodeResult:
    raw_meta = ep.get("meta")
    meta_dict = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    raw_score = ep.get("score", 0.0)
    score_val = float(raw_score) if _is_numeric(raw_score) else 0.0
    raw_final_day = ep.get("final_day")
    if _is_numeric(raw_final_day):
        final_day_val = int(raw_final_day)
    else:
        final_day_val = steps[-1].day if steps else 1
    end_reason_val = str(
        ep.get("end_reason") or ("accused" if ep.get("accused") else "horizon")
    )
    return EpisodeResult(
        tier=str(ep.get("tier") or "hard"),
        seed=int(ep.get("seed", 0)),
        agent=str(ep.get("agent") or "unknown"),
        steps=steps,
        score=score_val,
        accused=ep.get("accused"),
        correct=bool(ep.get("correct", False)),
        final_day=final_day_val,
        end_reason=end_reason_val,
        meta=meta_dict,
    )


def _resolve_v_for_luck(ep: dict[str, Any], known_v: float) -> float:
    correct = bool(ep.get("correct", False))
    raw_score = ep.get("score", 0.0)
    score = float(raw_score) if _is_numeric(raw_score) else 0.0
    if correct and score > 0.0:
        return score
    meta = ep.get("meta")
    if isinstance(meta, dict):
        if _is_numeric(meta.get("V_final")):
            return float(meta["V_final"])
        if _is_numeric(meta.get("V")):
            return float(meta["V"])
    return float(known_v)


def _classify_verdict(
    correct: bool,
    p_accused: float,
    break_even_p: float,
) -> str:
    if p_accused >= break_even_p:
        return "justified" if correct else "wrong_justified"
    return "lucky" if correct else "premature_wrong"


def compute_belief_trace(ep: dict[str, Any]) -> dict[str, Any]:
    tiers_version, params = _resolve_version_and_params(ep)
    leak_timing_known = _leak_timing_known_for_version(tiers_version)
    default_employees = [f"e{k:02d}" for k in range(params.n_employees)]

    sp = SolverPolicy(params, use_v_drops=leak_timing_known)
    sp.obs.employees = list(default_employees)
    sp.obs.leak_timing_known = leak_timing_known

    raw_steps = list(ep.get("steps") or [])
    step_objs = [_to_step(s, idx) for idx, s in enumerate(raw_steps)]
    ep_result = _to_episode_result(ep, step_objs)
    attr_rows = attribute(ep_result)

    curr_post = sp.belief()
    curr_top_suspect, curr_p_top = _top_from_posterior(curr_post)
    init_known_v = 1.0
    init_break_even_p = _compute_break_even_p(
        init_known_v,
        params.wrong_accusation_score,
    )
    initial: dict[str, Any] = {
        "step_index": 0,
        "t": -1,
        "day": 1,
        "posterior": dict(curr_post),
        "p_top": curr_p_top,
        "top_suspect": curr_top_suspect,
        "known_v": init_known_v,
        "break_even_p": init_break_even_p,
    }

    step_traces: list[dict[str, Any]] = []
    accuse_snapshot: tuple[
        int,
        int,
        int,
        Step,
        dict[str, float],
        float,
        str,
        float,
    ] | None = None

    for i, st in enumerate(step_objs):
        post_before = dict(curr_post)
        top_before = curr_top_suspect
        p_top_before = curr_p_top
        known_v_before = max(0.0, float(sp.V))

        ok = bool((st.result or {}).get("ok", True))
        if accuse_snapshot is None and st.tool == "accuse" and ok:
            accuse_snapshot = (
                i + 1,
                int(st.t),
                int(st.day),
                st,
                post_before,
                p_top_before,
                top_before,
                known_v_before,
            )

        prev_decoy = sp.obs.decoy
        prev_status_state = (
            (
                sp.obs.today,
                frozenset(sp.obs.closed_days),
                frozenset(sp.obs.leak_days),
            )
            if st.tool == "status"
            else None
        )
        sp._ingest(st)
        if not sp.obs.employees:
            sp.obs.employees = list(default_employees)
        sp.obs.leak_timing_known = leak_timing_known

        status_unchanged = st.tool == "status" and prev_status_state == (
            sp.obs.today,
            frozenset(sp.obs.closed_days),
            frozenset(sp.obs.leak_days),
        )
        obs_unchanged = (
            (not ok)
            or (st.tool in _OBS_NOOP_TOOLS)
            or status_unchanged
            or (st.tool == "search_messages" and sp.obs.decoy == prev_decoy)
        )
        if not obs_unchanged:
            curr_post = sp.belief()
            curr_top_suspect, curr_p_top = _top_from_posterior(curr_post)

        known_v_after = max(0.0, float(sp.V))
        break_even_after = _compute_break_even_p(
            known_v_after,
            params.wrong_accusation_score,
        )
        attr_item = attr_rows[i] if i < len(attr_rows) else {}
        step_regret = float(attr_item.get("regret", 0.0))
        step_tags = [str(tag) for tag in (attr_item.get("tags") or [])]

        step_traces.append({
            "step_index": i + 1,
            "t": int(st.t),
            "day": int(st.day),
            "tool": str(st.tool),
            "posterior_before": post_before,
            "posterior": dict(curr_post),
            "p_top": curr_p_top,
            "top_suspect": curr_top_suspect,
            "p_top_before": p_top_before,
            "top_suspect_before": top_before,
            "known_v": known_v_after,
            "break_even_p": break_even_after,
            "regret": step_regret,
            "tags": step_tags,
        })

    accuse_audit: dict[str, Any] | None = None
    luck_adjusted_score = 0.0

    if accuse_snapshot is not None:
        (
            acc_step_idx,
            acc_t,
            acc_day,
            acc_st,
            acc_post_before,
            acc_p_top,
            acc_top_suspect,
            acc_known_v,
        ) = accuse_snapshot
        acc_emp_raw = (
            acc_st.args.get("employee")
            or ((acc_st.result or {}).get("data") or {}).get("accused")
            or ep.get("accused")
        )
        accused_str = str(acc_emp_raw) if acc_emp_raw is not None else ""
        correct = bool(ep.get("correct", False))
        p_accused = float(acc_post_before.get(accused_str, 0.0))
        break_even_p = _compute_break_even_p(
            acc_known_v,
            params.wrong_accusation_score,
        )
        v_for_luck = _resolve_v_for_luck(ep, acc_known_v)
        luck_adjusted_score = float(
            p_accused * v_for_luck
            + (1.0 - p_accused) * float(params.wrong_accusation_score)
        )
        verdict = _classify_verdict(correct, p_accused, break_even_p)
        accuse_audit = {
            "step_index": acc_step_idx,
            "t": acc_t,
            "day": acc_day,
            "accused": accused_str,
            "correct": correct,
            "p_accused": p_accused,
            "p_top": float(acc_p_top),
            "top_suspect": str(acc_top_suspect),
            "known_v": float(acc_known_v),
            "v_for_luck": float(v_for_luck),
            "break_even_p": float(break_even_p),
            "luck_adjusted_score": luck_adjusted_score,
            "verdict": verdict,
        }
    elif isinstance(ep.get("accused"), str) and ep["accused"].strip():
        accused_str = ep["accused"].strip()
        correct = bool(ep.get("correct", False))
        acc_step_idx = len(step_traces)
        acc_t = step_traces[-1]["t"] if step_traces else -1
        acc_day = int(
            ep.get("final_day")
            or (step_traces[-1]["day"] if step_traces else 1)
        )
        acc_known_v = (
            step_traces[-1]["known_v"] if step_traces else init_known_v
        )
        p_accused = float(curr_post.get(accused_str, 0.0))
        break_even_p = _compute_break_even_p(
            acc_known_v,
            params.wrong_accusation_score,
        )
        v_for_luck = _resolve_v_for_luck(ep, acc_known_v)
        luck_adjusted_score = float(
            p_accused * v_for_luck
            + (1.0 - p_accused) * float(params.wrong_accusation_score)
        )
        verdict = _classify_verdict(correct, p_accused, break_even_p)
        accuse_audit = {
            "step_index": acc_step_idx,
            "t": acc_t,
            "day": acc_day,
            "accused": accused_str,
            "correct": correct,
            "p_accused": p_accused,
            "p_top": float(curr_p_top),
            "top_suspect": str(curr_top_suspect),
            "known_v": float(acc_known_v),
            "v_for_luck": float(v_for_luck),
            "break_even_p": float(break_even_p),
            "luck_adjusted_score": luck_adjusted_score,
            "verdict": verdict,
        }

    return {
        "tiers_version": tiers_version,
        "n_employees": int(params.n_employees),
        "initial": initial,
        "steps": step_traces,
        "accuse_audit": accuse_audit,
        "luck_adjusted_score": luck_adjusted_score,
        "decoy_inferred": sp.obs.decoy,
    }
