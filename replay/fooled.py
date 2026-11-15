from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import replace
from typing import Any

from canary.analysis.tags import WHY, to_result
from canary.rules import TIERS_HISTORY, TIERS_VERSION, tier_params_for_episode, tiers_version
from canary.solver.policy import SolverPolicy, accuse_value
from replay.belief_trace import _fast_attribute, _fast_sp_belief
from replay.loader import make_episode_id, provenance_info

_EM_DASH = "\u2014"
_EN_DASH = "\u2013"

_SHOWCASE_KIND_RANK: dict[str, int] = {
    "premature_wrong": 0,
    "decoy_chase": 0,
    "ignored_delay": 0,
    "subthreshold_gamble": 1,
    "wrong_accusation": 2,
    "missed_mole": 3,
    "over_restriction": 4,
    "fingerprint_bad_luck": 5,
    "none": 6,
}

_TIER_RANK: dict[str, int] = {
    "hard": 0,
    "hard_forge": 0,
    "hard_rl": 0,
    "medium": 1,
    "easy": 2,
}

__all__ = [
    "analyze_pair_fooled",
    "breakeven_posterior",
    "detect_fooled_moment",
    "find_fooled_episodes",
    "rank_showcase_pairs",
]


def _ascii_clean(text: str) -> str:
    cleaned = text.replace(_EM_DASH, "-").replace(_EN_DASH, "-")
    return cleaned.encode("ascii", "replace").decode("ascii")


def _episode_is_valid(ep: dict[str, Any]) -> bool:
    if "valid" in ep:
        return bool(ep["valid"])
    meta = ep.get("meta")
    if isinstance(meta, dict) and meta.get("valid") is False:
        return False
    return True


def _resolve_tiers_version(episode: dict[str, Any]) -> str:
    for container in (
        episode,
        episode.get("meta") if isinstance(episode.get("meta"), dict) else {},
        episode.get("run_meta") if isinstance(episode.get("run_meta"), dict) else {},
    ):
        raw = container.get("tiers_version")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    tier = str(episode.get("tier", ""))
    steps = episode.get("steps") or ()
    if tier in ("easy", "medium", "hard", "hard_forge", "hard_rl"):
        inferred = tier_params_for_episode(tier, steps)
        current = tier_params_for_episode(tier, ())
        if inferred.n_employees != current.n_employees:
            return "v1.3"
    return TIERS_VERSION


@contextmanager
def _maybe_tiers_version(ver: str):
    ctx = tiers_version(ver) if ver in TIERS_HISTORY else nullcontext()
    with ctx:
        yield


def breakeven_posterior(v_value: float, wrong_score: float = -1.0) -> float:
    v = float(v_value)
    w = float(wrong_score)
    if w >= 0.0:
        return 0.0
    if v <= 0.0:
        return 1.0
    denom = v - w
    if denom <= 0.0:
        return 1.0
    p = -w / denom
    return max(0.0, min(1.0, p))


def _snapshot_episode(episode: dict[str, Any], ver: str) -> dict[str, Any]:
    ep_res = to_result(episode)
    with _maybe_tiers_version(ver):
        params = tier_params_for_episode(ep_res.tier, ep_res.steps)
        wrong_score = float(getattr(params, "wrong_accusation_score", -1.0))
        sp = SolverPolicy(params)
        steps = ep_res.steps

        valid_accuse = [
            i for i, st in enumerate(steps)
            if st.tool == "accuse" and (st.result or {}).get("ok", True) is not False
        ]
        all_accuse = valid_accuse or [i for i, st in enumerate(steps) if st.tool == "accuse"]
        accuse_idx = all_accuse[0] if all_accuse else None

        if accuse_idx is not None:
            for prev in steps[sp.seen:accuse_idx]:
                sp._ingest(prev)
            sp.seen = accuse_idx
            accuse_step = steps[accuse_idx]
            raw_emp = (accuse_step.args or {}).get("employee") or ep_res.accused
            accused = str(raw_emp) if raw_emp is not None else None
            v_at_moment = float(sp.V)
            p_breakeven = breakeven_posterior(v_at_moment, wrong_score)
            if sp.obs.employees:
                post = _fast_sp_belief(sp)
            else:
                n_emp = max(1, int(params.n_employees))
                post = {f"e{k:02d}": 1.0 / n_emp for k in range(n_emp)}
            p_accused = float(post.get(accused, 0.0)) if accused is not None else None
            top_suspect = min(post, key=lambda e: (-post[e], e)) if post else None
            p_top = float(post[top_suspect]) if top_suspect is not None else None
            ev_accuse = float(accuse_value(p_accused, v_at_moment, params)) if p_accused is not None else None
            ev_top = float(accuse_value(p_top, v_at_moment, params)) if p_top is not None else 0.0
            max_delay = max(params.delay_choices)
            accuse_day = int(accuse_step.day)
            pending_leak_days = sorted(
                int(d) for d in sp.obs.leak_days
                if not any(0 < it.surfaced_day - d <= max_delay for it in sp.obs.feed)
                and d + max_delay >= accuse_day
            )
            obs_decoy = sp.obs.decoy
        else:
            for prev in steps[sp.seen:]:
                sp._ingest(prev)
            sp.seen = len(steps)
            accused = str(ep_res.accused) if ep_res.accused is not None else None
            v_at_moment = float(sp.V)
            p_breakeven = breakeven_posterior(v_at_moment, wrong_score)
            post = _fast_sp_belief(sp) if sp.obs.employees else {}
            top_suspect = min(post, key=lambda e: (-post[e], e)) if post else None
            p_top = float(post[top_suspect]) if top_suspect is not None else None
            if accused is not None:
                if not post:
                    n_emp = max(1, int(params.n_employees))
                    post = {f"e{k:02d}": 1.0 / n_emp for k in range(n_emp)}
                    top_suspect = min(post, key=lambda e: (-post[e], e))
                    p_top = float(post[top_suspect])
                p_accused = float(post.get(accused, 0.0))
                ev_accuse = float(accuse_value(p_accused, v_at_moment, params))
            else:
                p_accused = None
                ev_accuse = None
            ev_top = float(accuse_value(p_top, v_at_moment, params)) if p_top is not None else 0.0
            max_delay = max(params.delay_choices)
            ref_day = int(ep_res.final_day)
            pending_leak_days = sorted(
                int(d) for d in sp.obs.leak_days
                if not any(0 < it.surfaced_day - d <= max_delay for it in sp.obs.feed)
                and d + max_delay >= ref_day
            )
            obs_decoy = sp.obs.decoy

    return {
        "ep_res": ep_res,
        "params": params,
        "accuse_idx": accuse_idx,
        "accused": accused,
        "v_at_moment": v_at_moment,
        "p_breakeven": p_breakeven,
        "p_accused": p_accused,
        "p_top": p_top,
        "top_suspect": top_suspect,
        "ev_accuse": ev_accuse,
        "ev_top": ev_top,
        "pending_leak_days": pending_leak_days,
        "obs_decoy": obs_decoy,
    }


def _resolve_decoy_id(
    episode: dict[str, Any],
    snap: dict[str, Any],
    solver_episode: dict[str, Any] | None,
    solver_snap: dict[str, Any] | None,
) -> str | None:
    ep_meta = episode.get("meta") if isinstance(episode.get("meta"), dict) else {}
    if isinstance(ep_meta.get("decoy"), str) and ep_meta["decoy"]:
        return ep_meta["decoy"]
    if solver_episode is not None:
        sol_meta = solver_episode.get("meta") if isinstance(solver_episode.get("meta"), dict) else {}
        if isinstance(sol_meta.get("decoy"), str) and sol_meta["decoy"]:
            return sol_meta["decoy"]
    if solver_snap is not None and solver_snap["obs_decoy"]:
        sol_decoy = str(solver_snap["obs_decoy"])
        if not (bool(solver_episode and solver_episode.get("correct")) and solver_snap["accused"] == sol_decoy):
            return sol_decoy
    obs_decoy = snap["obs_decoy"]
    if obs_decoy:
        cand = str(obs_decoy)
        if not (bool(episode.get("correct")) and snap["accused"] == cand):
            return cand
    return None


def _select_stop_step(
    steps: list[Any],
    attr_items: list[dict[str, Any]],
    accuse_idx: int | None,
    kind: str,
    is_decoy: bool,
    final_day: int,
) -> tuple[int, int, int]:
    n_steps = len(steps)
    if n_steps == 0:
        return 0, 0, final_day

    real_items = attr_items[:n_steps]

    if accuse_idx is not None:
        if kind == "over_restriction":
            candidates = [
                i for i, item in enumerate(real_items)
                if "over_restriction" in (item.get("tags") or ())
            ]
            if candidates:
                idx = max(candidates, key=lambda i: (float(real_items[i].get("regret", 0.0)), -i))
                return idx, int(steps[idx].t), int(steps[idx].day)
        if kind == "decoy_chase" and not is_decoy:
            candidates = [
                i for i, item in enumerate(real_items)
                if "decoy_chase" in (item.get("tags") or ())
            ]
            if candidates:
                idx = max(candidates, key=lambda i: (float(real_items[i].get("regret", 0.0)), -i))
                return idx, int(steps[idx].t), int(steps[idx].day)
        return accuse_idx, int(steps[accuse_idx].t), int(steps[accuse_idx].day)

    if kind in ("decoy_chase", "over_restriction"):
        candidates = [
            i for i, item in enumerate(real_items)
            if kind in (item.get("tags") or ())
        ]
        if candidates:
            idx = max(candidates, key=lambda i: (float(real_items[i].get("regret", 0.0)), -i))
            return idx, int(steps[idx].t), int(steps[idx].day)

    positive_regret = [
        i for i, item in enumerate(real_items)
        if float(item.get("regret", 0.0)) > 0.0
    ]
    if positive_regret:
        idx = max(positive_regret, key=lambda i: (float(real_items[i].get("regret", 0.0)), i))
        return idx, int(steps[idx].t), int(steps[idx].day)

    last_idx = n_steps - 1
    return last_idx, int(steps[last_idx].t), int(steps[last_idx].day)


def _build_headline(
    accused: str | None,
    stop_day: int,
    final_day: int,
    p_accused: float | None,
    p_top: float | None,
    top_suspect: str | None,
    p_breakeven: float,
    score: float,
) -> str:
    if accused is not None and p_accused is not None:
        return _ascii_clean(
            f"Accused {accused} on day {stop_day} at P={p_accused:.2f} "
            f"(break-even P={p_breakeven:.2f}); score {score:.2f}"
        )
    if p_top is not None and top_suspect is not None:
        return _ascii_clean(
            f"No accusation by day {final_day} with top suspect {top_suspect} at P={p_top:.2f} "
            f"(break-even P={p_breakeven:.2f}); score {score:.2f}"
        )
    return _ascii_clean(
        f"No accusation by day {final_day} (break-even P={p_breakeven:.2f}); score {score:.2f}"
    )


def _build_explanation(
    kind: str,
    accused: str | None,
    decoy_id: str | None,
    is_decoy: bool,
    stop_day: int,
    final_day: int,
    p_accused: float | None,
    p_top: float | None,
    top_suspect: str | None,
    p_breakeven: float,
    threshold_bar: float,
    ev_accuse: float | None,
    ev_top: float,
    pending_leak_days: list[int],
    regret_total: float,
) -> str:
    p_acc = p_accused if p_accused is not None else 0.0
    ev_acc = ev_accuse if ev_accuse is not None else 0.0
    if kind == "premature_wrong":
        text = (
            f"Agent accused {accused} on day {stop_day} with posterior P={p_acc:.2f}, "
            f"below break-even P={p_breakeven:.2f} (EV={ev_acc:+.2f}), firing an innocent employee."
        )
    elif kind == "decoy_chase":
        if is_decoy and accused is not None:
            text = (
                f"Agent chased decoy employee {accused} (the loud innocent) and accused on day {stop_day} "
                f"at P={p_acc:.2f} (break-even P={p_breakeven:.2f})."
            )
        else:
            target = decoy_id or "unknown"
            text = (
                f"Agent acted against decoy employee {target} (the loud innocent), "
                f"wasting investigation budget and company value."
            )
    elif kind == "ignored_delay":
        text = (
            f"Agent accused {accused} on day {stop_day} at P={p_acc:.2f} while closed leak days "
            f"{pending_leak_days} could still surface in the leak feed."
        )
    elif kind == "subthreshold_gamble":
        text = (
            f"Agent gambled by accusing {accused} on day {stop_day} at P={p_acc:.2f} below commitment bar "
            f"P={threshold_bar:.2f} (break-even P={p_breakeven:.2f}, EV={ev_acc:+.2f}); lucky hit."
        )
    elif kind == "fingerprint_bad_luck":
        text = (
            f"Agent accused {accused} on day {stop_day} with high posterior P={p_acc:.2f} (EV={ev_acc:+.2f}), "
            f"losing to canary fingerprint noise rather than a calibration failure."
        )
    elif kind == "wrong_accusation":
        text = (
            f"Agent accused {accused} on day {stop_day} at moderate posterior P={p_acc:.2f} "
            f"(break-even P={p_breakeven:.2f}) before reaching decisive certainty, firing an innocent employee."
        )
    elif kind == "missed_mole":
        suspect_label = top_suspect or "top suspect"
        p_best = p_top if p_top is not None else 0.0
        text = (
            f"Agent ended without an accusation on day {final_day} despite {suspect_label} having "
            f"P={p_best:.2f} above break-even P={p_breakeven:.2f} (missed EV={ev_top:+.2f})."
        )
    elif kind == "over_restriction":
        text = (
            f"Agent restricted low-probability employees without sufficient evidence "
            f"(total regret {regret_total:.2f})."
        )
    elif accused is not None:
        text = (
            f"Agent waited for decisive evidence and accused {accused} on day {stop_day} at P={p_acc:.2f} "
            f"above break-even P={p_breakeven:.2f} (EV={ev_acc:+.2f})."
        )
    elif p_top is not None:
        text = (
            f"Agent rationally abstained on day {final_day} because top posterior P={p_top:.2f} "
            f"did not beat break-even P={p_breakeven:.2f} (EV={ev_top:+.2f})."
        )
    else:
        text = f"Agent abstained without sufficient evidence by day {final_day}; abstaining scored 0.00."
    return _ascii_clean(text)


def _build_solver_comparison(
    agent_score: float,
    agent_luck_adj: float,
    agent_accused: str | None,
    agent_stop_day: int,
    agent_final_day: int,
    agent_p_accused: float | None,
    solver_episode: dict[str, Any],
    solver_ver: str,
    solver_snap: dict[str, Any],
) -> dict[str, Any]:
    s_tier = str(solver_episode["tier"])
    s_seed = int(solver_episode["seed"])
    s_agent = str(solver_episode.get("agent", "solver"))
    s_ep_id = str(
        solver_episode.get("episode_id") or make_episode_id(solver_ver, s_tier, s_seed, s_agent)
    )
    s_score = float(solver_episode.get("score", 0.0))
    s_accused = solver_snap["accused"]
    s_correct = bool(solver_episode.get("correct", False))
    s_abstained = s_accused is None
    s_final_day = int(solver_episode.get("final_day", 0))
    s_p_accused = solver_snap["p_accused"]
    s_p_top = solver_snap["p_top"]
    s_ev_accuse = solver_snap["ev_accuse"]
    s_luck_adj = float(s_ev_accuse) if (s_accused is not None and s_ev_accuse is not None) else 0.0

    score_delta = agent_score - s_score
    luck_adjusted_delta = agent_luck_adj - s_luck_adj

    a_pa = agent_p_accused if agent_p_accused is not None else 0.0
    s_pa = s_p_accused if s_p_accused is not None else 0.0
    s_pt = s_p_top if s_p_top is not None else 0.0

    if agent_accused is not None and s_abstained:
        contrast = (
            f"Agent accused {agent_accused} on day {agent_stop_day} at P={a_pa:.2f} (score {agent_score:.2f}); "
            f"solver abstained on day {s_final_day} with top P={s_pt:.2f} (score {s_score:.2f})."
        )
    elif agent_accused is not None and not s_abstained:
        contrast = (
            f"Agent accused {agent_accused} on day {agent_stop_day} at P={a_pa:.2f} (score {agent_score:.2f}); "
            f"solver accused {s_accused} on day {s_final_day} at P={s_pa:.2f} (score {s_score:.2f})."
        )
    elif agent_accused is None and not s_abstained:
        contrast = (
            f"Agent made no accusation by day {agent_final_day} (score {agent_score:.2f}); "
            f"solver accused {s_accused} on day {s_final_day} at P={s_pa:.2f} (score {s_score:.2f})."
        )
    else:
        contrast = (
            f"Both agent (day {agent_final_day}, score {agent_score:.2f}) and solver "
            f"(day {s_final_day}, score {s_score:.2f}) abstained."
        )

    return {
        "solver_episode_id": s_ep_id,
        "solver_score": s_score,
        "solver_accused": s_accused,
        "solver_correct": s_correct,
        "solver_abstained": s_abstained,
        "solver_final_day": s_final_day,
        "solver_p_accused": s_p_accused,
        "solver_p_top": s_p_top,
        "solver_luck_adjusted_score": s_luck_adj,
        "score_delta": score_delta,
        "luck_adjusted_delta": luck_adjusted_delta,
        "contrast": _ascii_clean(contrast),
    }


def _detect_fooled_impl(
    episode: dict[str, Any],
    solver_episode: dict[str, Any] | None = None,
    precomputed_solver: tuple[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tier = str(episode["tier"])
    seed = int(episode["seed"])
    agent = str(episode["agent"])
    ver = _resolve_tiers_version(episode)
    episode_id = str(episode.get("episode_id") or make_episode_id(ver, tier, seed, agent))

    ep_meta = episode.get("meta") if isinstance(episode.get("meta"), dict) else {}
    run_meta = episode.get("run_meta") if isinstance(episode.get("run_meta"), dict) else {}
    merged_meta = {**run_meta, **{k: v for k, v in ep_meta.items() if v is not None}}
    provenance = episode.get("provenance") or provenance_info(agent, merged_meta)

    snap = _snapshot_episode(episode, ver)
    if solver_episode is not None:
        if precomputed_solver is not None:
            solver_ver, solver_snap = precomputed_solver
        else:
            solver_ver = _resolve_tiers_version(solver_episode)
            solver_snap = _snapshot_episode(solver_episode, solver_ver)
    else:
        solver_ver = ver
        solver_snap = None

    decoy_id = _resolve_decoy_id(episode, snap, solver_episode, solver_snap)
    ep_res = snap["ep_res"]
    attr_input = (
        replace(ep_res, meta={**(ep_res.meta or {}), "decoy": decoy_id})
        if decoy_id is not None
        else ep_res
    )
    with _maybe_tiers_version(ver):
        attr_items = _fast_attribute(attr_input)

    accused = snap["accused"]
    correct = bool(episode.get("correct", False))
    score = float(episode.get("score", 0.0))
    final_day = int(episode.get("final_day", 0))
    p_accused = snap["p_accused"]
    p_top = snap["p_top"]
    top_suspect = snap["top_suspect"]
    v_at_moment = snap["v_at_moment"]
    p_breakeven = snap["p_breakeven"]
    ev_accuse = snap["ev_accuse"]
    ev_top = snap["ev_top"]
    pending_leak_days = snap["pending_leak_days"]
    luck_adjusted_score = float(ev_accuse) if (accused is not None and ev_accuse is not None) else 0.0

    is_decoy = bool(accused is not None and decoy_id is not None and accused == decoy_id and not correct)

    all_tags_set = {tag for item in attr_items for tag in (item.get("tags") or ())}
    if is_decoy:
        all_tags_set.add("decoy_chase")
    tags = sorted(all_tags_set)

    regret_total = round(sum(float(item.get("regret", 0.0)) for item in attr_items), 6)

    steps = ep_res.steps
    tagged_events: list[dict[str, Any]] = []
    for idx, item in enumerate(attr_items):
        item_tags = list(item.get("tags") or [])
        if idx == snap["accuse_idx"] and is_decoy and "decoy_chase" not in item_tags:
            item_tags.append("decoy_chase")
        if not item_tags:
            continue
        p_best_val = float(item.get("p_best") or 0.0)
        reasons = [_ascii_clean(WHY.get(t, t).format(p=p_best_val)) for t in item_tags]
        step_args = dict(steps[idx].args or {}) if idx < len(steps) else {}
        tagged_events.append({
            "step_index": idx if idx < len(steps) else max(0, len(steps) - 1),
            "t": int(item.get("t", idx)),
            "day": int(item.get("day", final_day)),
            "action": str(item.get("action", "")),
            "args": step_args,
            "regret": float(item.get("regret", 0.0)),
            "p_best": item.get("p_best"),
            "p_accused": item.get("p_accused"),
            "tags": item_tags,
            "reasons": reasons,
            "why": "; ".join(reasons),
        })

    threshold_bar = max(p_breakeven, 0.6)
    p_acc = p_accused if p_accused is not None else 0.0
    no_acc_regret = max(
        (float(item.get("regret", 0.0)) for item in attr_items if "no_accusation" in (item.get("tags") or ())),
        default=0.0,
    )
    missed_positive_ev = ev_top > 0.0 or no_acc_regret > 0.0

    if accused is None:
        verdict = "missed-mole" if missed_positive_ev else "rational-abstain"
    elif correct:
        verdict = "justified" if p_acc >= threshold_bar else "lucky"
    else:
        verdict = "premature-wrong" if p_acc < threshold_bar else "wrong"

    fooled = False
    bad_luck = False
    if is_decoy:
        kind = "decoy_chase"
        fooled = True
    elif accused is not None and "ignored_delay" in all_tags_set and (not correct or p_acc < threshold_bar):
        kind = "ignored_delay"
        fooled = True
    elif "decoy_chase" in all_tags_set:
        kind = "decoy_chase"
        fooled = True
    elif accused is not None and not correct:
        if p_acc >= 0.90:
            kind = "fingerprint_bad_luck"
            fooled = False
            bad_luck = True
        elif p_acc < threshold_bar:
            kind = "premature_wrong"
            fooled = True
        else:
            kind = "wrong_accusation"
            fooled = True
    elif accused is not None and correct and p_acc < threshold_bar:
        kind = "subthreshold_gamble"
        fooled = True
    elif accused is None and missed_positive_ev:
        kind = "missed_mole"
        fooled = True
    elif "over_restriction" in all_tags_set:
        kind = "over_restriction"
        fooled = True
    else:
        kind = "none"
        fooled = False

    step_index, stop_t, stop_day = _select_stop_step(
        steps,
        attr_items,
        snap["accuse_idx"],
        kind,
        is_decoy,
        final_day,
    )

    headline = _build_headline(
        accused=accused,
        stop_day=stop_day,
        final_day=final_day,
        p_accused=p_accused,
        p_top=p_top,
        top_suspect=top_suspect,
        p_breakeven=p_breakeven,
        score=score,
    )
    explanation = _build_explanation(
        kind=kind,
        accused=accused,
        decoy_id=decoy_id,
        is_decoy=is_decoy,
        stop_day=stop_day,
        final_day=final_day,
        p_accused=p_accused,
        p_top=p_top,
        top_suspect=top_suspect,
        p_breakeven=p_breakeven,
        threshold_bar=threshold_bar,
        ev_accuse=ev_accuse,
        ev_top=ev_top,
        pending_leak_days=pending_leak_days,
        regret_total=regret_total,
    )

    solver_comparison = (
        _build_solver_comparison(
            agent_score=score,
            agent_luck_adj=luck_adjusted_score,
            agent_accused=accused,
            agent_stop_day=stop_day,
            agent_final_day=final_day,
            agent_p_accused=p_accused,
            solver_episode=solver_episode,
            solver_ver=solver_ver,
            solver_snap=solver_snap,
        )
        if solver_episode is not None and solver_snap is not None
        else None
    )

    return {
        "episode_id": episode_id,
        "tiers_version": ver,
        "tier": tier,
        "seed": seed,
        "agent": agent,
        "provenance": dict(provenance),
        "fooled": fooled,
        "bad_luck": bad_luck,
        "kind": kind,
        "verdict": verdict,
        "step_index": step_index,
        "stop_t": stop_t,
        "stop_day": stop_day,
        "accused": accused,
        "correct": correct,
        "score": score,
        "p_accused": p_accused,
        "p_top": p_top,
        "top_suspect": top_suspect,
        "v_at_moment": v_at_moment,
        "p_breakeven": p_breakeven,
        "ev_accuse": ev_accuse,
        "luck_adjusted_score": luck_adjusted_score,
        "pending_leak_days": pending_leak_days,
        "is_decoy": is_decoy,
        "tags": tags,
        "regret_total": regret_total,
        "tagged_events": tagged_events,
        "headline": headline,
        "explanation": explanation,
        "solver_comparison": solver_comparison,
    }


def detect_fooled_moment(
    episode: dict[str, Any],
    solver_episode: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _detect_fooled_impl(episode, solver_episode=solver_episode)


def _analyze_pair_with_cache(
    pair: dict[str, Any],
    solver_cache: dict[int, tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    agent_ep = dict(pair["agent_episode"])
    raw_solver_ep = pair.get("solver_episode")
    solver_ep = dict(raw_solver_ep) if raw_solver_ep is not None else None
    if "tiers_version" not in agent_ep and pair.get("tiers_version"):
        agent_ep["tiers_version"] = pair["tiers_version"]
    if "provenance" not in agent_ep and pair.get("provenance"):
        agent_ep["provenance"] = pair["provenance"]
    precomputed: tuple[str, dict[str, Any]] | None = None
    if solver_ep is not None and raw_solver_ep is not None:
        if "tiers_version" not in solver_ep and pair.get("tiers_version"):
            solver_ep["tiers_version"] = pair["tiers_version"]
        if solver_cache is not None:
            cache_key = id(raw_solver_ep)
            precomputed = solver_cache.get(cache_key)
            if precomputed is None:
                s_ver = _resolve_tiers_version(solver_ep)
                precomputed = (s_ver, _snapshot_episode(solver_ep, s_ver))
                solver_cache[cache_key] = precomputed
    detected = _detect_fooled_impl(agent_ep, solver_episode=solver_ep, precomputed_solver=precomputed)
    pair_id = str(pair.get("pair_id") or f"{detected['episode_id']}__vs__solver")
    return {"pair_id": pair_id, **detected}


def analyze_pair_fooled(pair: dict[str, Any]) -> dict[str, Any]:
    return _analyze_pair_with_cache(pair, solver_cache=None)


def _fooled_sort_key(summary: dict[str, Any]) -> tuple[Any, ...]:
    is_real = summary.get("provenance", {}).get("kind") == "real"
    p_acc = summary.get("p_accused")
    p_be = float(summary.get("p_breakeven", 0.0))
    be_margin = round(float(p_acc) - p_be, 6) if p_acc is not None else float("inf")
    return (
        0 if is_real else 1,
        0 if summary.get("fooled") else 1,
        -round(float(summary.get("regret_total", 0.0)), 6),
        be_margin,
        str(summary.get("tiers_version", "")),
        str(summary.get("tier", "")),
        int(summary.get("seed", 0)),
        str(summary.get("agent", "")),
    )


def find_fooled_episodes(
    episodes: list[dict[str, Any]],
    real_only: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for ep in episodes:
        if not _episode_is_valid(ep):
            continue
        if real_only:
            prov = ep.get("provenance") or provenance_info(str(ep.get("agent", "")), ep.get("meta"))
            if prov.get("kind") != "real":
                continue
        summary = detect_fooled_moment(ep)
        if not summary["fooled"]:
            continue
        results.append(summary)
    results.sort(key=_fooled_sort_key)
    return results


def _showcase_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    is_real = item.get("provenance", {}).get("kind") == "real"
    solver_comp = item.get("solver_comparison") or {}
    solver_score = float(solver_comp.get("solver_score", 0.0))
    agent_score = float(item.get("score", 0.0))
    solver_beats = solver_score > agent_score + 1e-12
    score_delta = round(float(solver_comp.get("score_delta", 0.0)), 6)
    p_acc = item.get("p_accused")
    p_be = float(item.get("p_breakeven", 0.0))
    be_margin = round(float(p_acc) - p_be, 6) if p_acc is not None else float("inf")
    kind = str(item.get("kind", ""))
    kind_rank = _SHOWCASE_KIND_RANK.get(kind, 6)
    is_core_showcase = kind_rank <= 1
    return (
        0 if is_real else 1,
        0 if item.get("fooled") else 1,
        0 if solver_beats else 1,
        0 if is_core_showcase else 1,
        _TIER_RANK.get(str(item.get("tier", "")), 3),
        kind_rank,
        score_delta,
        -round(float(item.get("regret_total", 0.0)), 6),
        be_margin,
        str(item.get("tiers_version", "")),
        str(item.get("tier", "")),
        int(item.get("seed", 0)),
        str(item.get("agent", "")),
        str(item.get("pair_id", "")),
    )


def rank_showcase_pairs(
    pairs: list[dict[str, Any]],
    limit: int = 20,
    real_only: bool = True,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    solver_cache: dict[int, tuple[str, dict[str, Any]]] = {}
    candidates: list[dict[str, Any]] = []
    for pair in pairs:
        if real_only:
            agent_ep = pair.get("agent_episode") or {}
            prov = (
                pair.get("provenance")
                or agent_ep.get("provenance")
                or provenance_info(str(pair.get("agent") or agent_ep.get("agent", "")), agent_ep.get("meta"))
            )
            if prov.get("kind") != "real":
                continue
        analyzed = _analyze_pair_with_cache(pair, solver_cache=solver_cache)
        solver_comp = analyzed.get("solver_comparison")
        solver_beats = (
            solver_comp is not None
            and float(solver_comp["solver_score"]) > float(analyzed["score"]) + 1e-12
        )
        if analyzed["fooled"] or solver_beats:
            candidates.append(analyzed)
    candidates.sort(key=_showcase_sort_key)
    return candidates[:limit]
