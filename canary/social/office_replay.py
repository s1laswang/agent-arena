from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from canary.analysis.tags import to_result
from canary.baselines import BASELINES, BIAS_BASELINES, CALIBRATION_POLICIES
from canary.env import Env
from canary.rules import TIERS, TRACKS, tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts
from canary.text.template import TemplateProvider
from canary.types import EpisodeResult, Step

from .biases import BIAS_TYPES, DECOY_VOCAB
from .engine import EpisodeSocialState, V16SocialProvider, make_v16_provider, parse_v16_spec

PROVENANCE_BADGES: tuple[str, ...] = ("v16-template", "v16-gemini-stub", "v14-control")
FOOLED_ACTION_TOOLS: tuple[str, ...] = ("interview", "restrict_access", "accuse")
DEFAULT_FOOLED_THRESHOLD = 0.20


def provenance_badge_for_provider(provider: V16SocialProvider) -> str:
    if provider.variant_spec.get("control"):
        return "v14-control"
    if provider.mode == "gemini-stub":
        return "v16-gemini-stub"
    return "v16-template"


def _default_stub_cache_dir(cache_dir: str | Path | None = None) -> Path:
    if cache_dir is not None and str(cache_dir).strip():
        return Path(cache_dir)
    env_dir = os.environ.get("CANARY_GEMINI_CACHE_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path(tempfile.gettempdir()) / "opencode" / "v16_office_replay_stub_cache"


def resolve_replay_provider(
    variant: str = "v5_full9_cocktail",
    mode: str | None = None,
    cache_dir: str | Path | None = None,
) -> tuple[V16SocialProvider, str]:
    variant_name, parsed_mode = parse_v16_spec(variant, mode=mode)
    safe_mode = "gemini-stub" if parsed_mode == "gemini" else parsed_mode
    extra: dict[str, Any] = {}
    if safe_mode == "gemini-stub":
        extra["cache_dir"] = str(_default_stub_cache_dir(cache_dir))
    provider = make_v16_provider(variant_name, mode=safe_mode, **extra)
    return provider, provenance_badge_for_provider(provider)


def make_replay_policy(agent: str, tier: str, seed: int) -> Any:
    clean = str(agent or "solver").strip()
    if clean == "solver":
        return SolverPolicy(tier)
    if clean in BIAS_BASELINES:
        return BIAS_BASELINES[clean](seed=seed)
    if clean in BASELINES:
        return BASELINES[clean](seed=seed)
    if clean in CALIBRATION_POLICIES:
        return CALIBRATION_POLICIES[clean](seed=seed)
    known = sorted({"solver", *BIAS_BASELINES, *BASELINES, *CALIBRATION_POLICIES})
    raise ValueError(f"unknown replay agent {clean!r}; expected one of {', '.join(known)}")


def load_episode_record(
    episode_path: str | Path,
    *,
    tier: str | None = None,
    seed: int | None = None,
    agent: str | None = None,
) -> EpisodeResult:
    path = Path(episode_path)
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise ValueError(f"empty episode file: {path}")

    records: list[dict[str, Any]] = []
    if raw_text.startswith("["):
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            records.extend(x for x in parsed if isinstance(x, dict))
    else:
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        if len(lines) == 1:
            one = json.loads(lines[0])
            if isinstance(one, dict):
                records.append(one)
        else:
            try:
                whole = json.loads(raw_text)
                if isinstance(whole, dict):
                    records.append(whole)
                elif isinstance(whole, list):
                    records.extend(x for x in whole if isinstance(x, dict))
            except json.JSONDecodeError:
                for ln in lines:
                    obj = json.loads(ln)
                    if isinstance(obj, dict):
                        records.append(obj)

    if not records:
        raise ValueError(f"no episode records found in {path}")

    def _matches(rec: dict[str, Any], check_tier: bool, check_seed: bool, check_agent: bool) -> bool:
        if check_tier and tier is not None and str(rec.get("tier", "")) != str(tier):
            return False
        if check_seed and seed is not None and int(rec.get("seed", -1)) != int(seed):
            return False
        if check_agent and agent is not None and str(rec.get("agent", "")) != str(agent):
            return False
        return True

    for ct, cs, ca in (
        (True, True, True),
        (True, True, False),
        (False, True, False),
        (False, False, False),
    ):
        for rec in records:
            if _matches(rec, ct, cs, ca):
                rec_copy = dict(rec)
                if tier is not None:
                    rec_copy.setdefault("tier", tier)
                if seed is not None:
                    rec_copy.setdefault("seed", int(seed))
                rec_copy.setdefault("agent", agent or "recorded")
                rec_copy.setdefault("score", 0.0)
                return to_result(rec_copy)

    raise ValueError(f"no matching episode record in {path}")


def _coerce_episode(episode: EpisodeResult | dict[str, Any], tier: str, seed: int) -> EpisodeResult:
    if isinstance(episode, EpisodeResult):
        return episode
    if isinstance(episode, dict):
        d = dict(episode)
        d.setdefault("tier", tier)
        d.setdefault("seed", int(seed))
        d.setdefault("agent", "recorded")
        d.setdefault("score", 0.0)
        return to_result(d)
    raise TypeError(f"unsupported episode object: {type(episode)!r}")


def _summarize_step(st: Step) -> str:
    args = st.args if isinstance(st.args, dict) else {}
    res = st.result if isinstance(st.result, dict) else {}
    ok = bool(res.get("ok", False))
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    if not ok:
        err = str(res.get("error") or "failed")
        return f"{st.tool} ({err})"
    if st.tool == "plant_canary":
        cid = str(data.get("canary_id") or "")
        asg = args.get("assignment") if isinstance(args.get("assignment"), dict) else {}
        counts: dict[str, int] = {}
        for lab in asg.values():
            s_lab = str(lab)
            counts[s_lab] = counts.get(s_lab, 0) + 1
        groups = ", ".join(f"{k}:{counts[k]}" for k in sorted(counts))
        return f"plant_canary {cid} ({groups})" if cid else f"plant_canary ({groups})"
    if st.tool == "search_messages":
        q = str(args.get("query", ""))
        hits = data.get("messages") if isinstance(data.get("messages"), list) else []
        return f"search_messages {q!r} -> {len(hits)} hits"
    if st.tool == "read_message":
        return f"read_message {args.get('id', '')}"
    if st.tool == "interview":
        emp = str(args.get("employee", ""))
        topic = str(args.get("topic", ""))
        return f"interview {emp} ({topic})"
    if st.tool in ("restrict_access", "unrestrict_access", "accuse"):
        return f"{st.tool} {args.get('employee', '')}"
    if st.tool == "read_access_logs":
        d_from = args.get("day_from", 1)
        d_to = args.get("day_to", d_from)
        emp = args.get("employee")
        logs = data.get("logs") if isinstance(data.get("logs"), list) else []
        suffix = f" emp={emp}" if emp else ""
        return f"read_access_logs d{d_from}..d{d_to}{suffix} -> {len(logs)} entries"
    if st.tool == "check_leak_feed":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        return f"check_leak_feed -> {len(items)} surfaced"
    if st.tool == "list_documents":
        docs = data.get("documents") if isinstance(data.get("documents"), list) else []
        return f"list_documents -> {len(docs)} docs"
    if st.tool == "list_employees":
        emps = data.get("employees") if isinstance(data.get("employees"), list) else []
        return f"list_employees -> {len(emps)} staff"
    if st.tool == "advance_day":
        closed = data.get("closed_day", st.day)
        nxt = data.get("day")
        return f"advance_day (closed day {closed} -> day {nxt})" if nxt else f"advance_day (closed day {closed})"
    if st.tool == "status":
        v_val = data.get("V")
        return f"status V={float(v_val):.3f}" if isinstance(v_val, (int, float)) else "status"
    return st.tool


def _step_env_with_policy(
    env: Env,
    policy: Any,
    max_iters: int = 1000,
) -> tuple[EpisodeResult, dict[int, PublicDayFacts], dict[int, float], dict[int, list[dict[str, Any]]]]:
    facts_by_day: dict[int, PublicDayFacts] = {1: env._facts(1)}
    v_by_day: dict[int, float] = {1: float(env.visible_V())}
    leaks_by_day: dict[int, list[dict[str, Any]]] = {1: []}

    policy.reset(env.tools_spec(), env.instruction())
    for _ in range(max_iters):
        if env.done:
            break
        cur_day = env.day
        facts_by_day[cur_day] = env._facts(cur_day)
        v_by_day[cur_day] = float(env.visible_V())
        tool, args = policy.act(list(env.history))
        env.call(tool, dict(args or {}))
        new_day = env.day
        facts_by_day.setdefault(new_day, env._facts(new_day))
        v_by_day[new_day] = float(env.visible_V())
        leaks_by_day[cur_day] = [dict(f) for f in env._feed if int(f.get("surfaced_day", 10**9)) <= cur_day]
        leaks_by_day.setdefault(
            new_day,
            [dict(f) for f in env._feed if int(f.get("surfaced_day", 10**9)) <= new_day],
        )

    final_day = int(env.day)
    facts_by_day[final_day] = env._facts(final_day)
    v_by_day[final_day] = float(env.visible_V())
    leaks_by_day[final_day] = [dict(f) for f in env._feed if int(f.get("surfaced_day", 10**9)) <= final_day]
    ep = env.result(getattr(policy, "name", type(policy).__name__))
    return ep, facts_by_day, v_by_day, leaks_by_day


def _step_env_with_recorded_episode(
    env: Env,
    recorded: EpisodeResult,
) -> tuple[list[Step], int, dict[int, PublicDayFacts], dict[int, float], dict[int, list[dict[str, Any]]]]:
    facts_by_day: dict[int, PublicDayFacts] = {1: env._facts(1)}
    v_by_day: dict[int, float] = {1: float(env.visible_V())}
    leaks_by_day: dict[int, list[dict[str, Any]]] = {1: []}
    replayed_steps: list[Step] = []

    for idx, st in enumerate(recorded.steps):
        target_day = max(1, int(st.day or env.day))
        while not env.done and env.day < target_day:
            closing_day = env.day
            facts_by_day[closing_day] = env._facts(closing_day)
            v_by_day[closing_day] = float(env.visible_V())
            leaks_by_day[closing_day] = [
                dict(f) for f in env._feed if int(f.get("surfaced_day", 10**9)) <= closing_day
            ]
            env.call("advance_day", {})
            facts_by_day.setdefault(env.day, env._facts(env.day))
            v_by_day[env.day] = float(env.visible_V())

        cur_day = env.day if not env.done else target_day
        if not env.done:
            facts_by_day[cur_day] = env._facts(cur_day)
            v_by_day[cur_day] = float(env.visible_V())
            env.call(st.tool, dict(st.args or {}))
            live_step = env.history[-1]
            replayed_steps.append(
                Step(
                    t=idx,
                    day=int(st.day or live_step.day),
                    tool=live_step.tool,
                    args=dict(live_step.args),
                    result=dict(live_step.result),
                )
            )
            leaks_by_day[cur_day] = [dict(f) for f in env._feed if int(f.get("surfaced_day", 10**9)) <= cur_day]
            facts_by_day.setdefault(env.day, env._facts(env.day))
            v_by_day[env.day] = float(env.visible_V())
            leaks_by_day.setdefault(
                env.day,
                [dict(f) for f in env._feed if int(f.get("surfaced_day", 10**9)) <= env.day],
            )
        else:
            replayed_steps.append(
                Step(
                    t=idx,
                    day=target_day,
                    tool=str(st.tool),
                    args=dict(st.args or {}),
                    result=dict(st.result or {"ok": False, "data": {}, "error": "episode over"}),
                )
            )

    max_step_day = max((int(s.day) for s in replayed_steps), default=1)
    final_day = max(1, int(recorded.final_day or 0), int(env.day), max_step_day)
    while not env.done and env.day < final_day:
        closing = env.day
        facts_by_day[closing] = env._facts(closing)
        v_by_day[closing] = float(env.visible_V())
        leaks_by_day[closing] = [dict(f) for f in env._feed if int(f.get("surfaced_day", 10**9)) <= closing]
        env.call("advance_day", {})
        facts_by_day.setdefault(env.day, env._facts(env.day))
        v_by_day[env.day] = float(env.visible_V())

    for d in range(1, final_day + 1):
        if d not in facts_by_day:
            facts_by_day[d] = env._facts(min(d, env.day))
        v_by_day.setdefault(d, v_by_day.get(d - 1, float(env.visible_V())))
        leaks_by_day.setdefault(
            d,
            [dict(f) for f in env._feed if int(f.get("surfaced_day", 10**9)) <= d],
        )

    return replayed_steps, final_day, facts_by_day, v_by_day, leaks_by_day


def _posterior_by_day_from_steps(
    steps: list[Step],
    params: Any,
    roster_ids: list[str],
    final_day: int,
) -> dict[int, dict[str, float]]:
    sp = SolverPolicy(params)
    sp.obs.employees = list(roster_ids)
    snapshots: dict[int, dict[str, float]] = {}

    for idx, st in enumerate(steps):
        is_last_of_day = (
            idx + 1 == len(steps)
            or int(steps[idx + 1].day) != int(st.day)
            or st.tool == "accuse"
        )
        if is_last_of_day:
            for prev in steps[sp.seen : idx + 1]:
                if prev.tool != "accuse":
                    sp._ingest(prev)
            sp.seen = idx + 1
            snapshots[int(st.day)] = dict(sp.belief())

    sp0 = SolverPolicy(params)
    sp0.obs.employees = list(roster_ids)
    carry = dict(sp0.belief())

    out: dict[int, dict[str, float]] = {}
    for d in range(1, final_day + 1):
        if d in snapshots:
            carry = snapshots[d]
        out[d] = dict(carry)
    return out


def _annotate_day_messages(
    facts: PublicDayFacts,
    rendered_msgs: list[dict[str, Any]],
    day_events: tuple[dict[str, Any], ...],
    template_provider: TemplateProvider,
    provenance_badge: str,
) -> list[dict[str, Any]]:
    by_id = {e.id: e for e in facts.employees}
    raw_base_by_id = {str(m["id"]): m for m in template_provider.day_messages(facts)}
    is_control = provenance_badge == "v14-control"
    annotated: list[dict[str, Any]] = []

    for m in rendered_msgs:
        mid = str(m["id"])
        sender_id = str(m["sender"])
        sender_emp = by_id.get(sender_id)
        is_social = "-s" in mid
        social_ev: dict[str, Any] | None = None
        if is_social:
            suffix = mid.rsplit("-s", 1)[-1]
            if suffix.isdigit():
                ev_idx = int(suffix)
                if 0 <= ev_idx < len(day_events):
                    social_ev = day_events[ev_idx]

        is_decoy = bool(facts.decoy is not None and sender_id == facts.decoy)
        subj = str(m.get("subject", ""))
        body = str(m.get("body", ""))
        combined_low = f"{subj}\n{body}".lower()
        has_decoy_vocab = any(w in combined_low for w in DECOY_VOCAB)

        raw_m = raw_base_by_id.get(mid)
        scrubbed_rewrite = bool(
            not is_social
            and not is_decoy
            and not is_control
            and raw_m is not None
            and (str(raw_m.get("body", "")) != body or str(raw_m.get("subject", "")) != subj)
        )

        if is_decoy:
            tag = "decoy"
        elif is_control:
            tag = "non-decoy"
        else:
            tag = "scrubbed-non-decoy"

        annotated.append(
            {
                "id": mid,
                "day": int(m["day"]),
                "channel": str(m["channel"]),
                "sender": sender_id,
                "sender_name": sender_emp.name if sender_emp else sender_id,
                "recipients": [str(r) for r in m.get("recipients", ())],
                "subject": subj,
                "body": body,
                "is_social": is_social,
                "bias": str(social_ev["bias"]) if social_ev and "bias" in social_ev else None,
                "target": str(social_ev["target"]) if social_ev and "target" in social_ev else None,
                "is_decoy": is_decoy,
                "has_decoy_vocab": has_decoy_vocab,
                "scrubbed_rewrite": scrubbed_rewrite,
                "tag": tag,
                "provenance": provenance_badge,
            }
        )
    return annotated


def _format_social_event(
    ev: dict[str, Any],
    day: int,
    primary_suspect: str | None,
    secondary_suspect: str | None,
) -> dict[str, Any]:
    target_id = str(ev.get("target", ""))
    if target_id and target_id == primary_suspect:
        target_role = "primary_suspect"
    elif target_id and target_id == secondary_suspect:
        target_role = "secondary_suspect"
    else:
        target_role = "other"
    return {
        "bias": str(ev["bias"]),
        "day": int(ev.get("day", day)),
        "sender": str(ev["sender"]),
        "speaker_name": str(ev.get("speaker_name", "")),
        "target": target_id,
        "target_name": str(ev.get("target_name", "")),
        "target_role": target_role,
        "channel": str(ev["channel"]),
        "recipients": [str(r) for r in ev.get("recipients", ())],
        "subject": str(ev.get("subject", "")),
        "body": str(ev["body"]),
        "doc_title": str(ev.get("doc_title", "")),
    }


def build_office_replay(
    tier: str = "hard",
    seed: int = 5,
    variant: str = "v5_full9_cocktail",
    *,
    mode: str | None = None,
    episode: EpisodeResult | dict[str, Any] | None = None,
    episode_path: str | Path | None = None,
    agent: str = "solver",
    fooled_threshold: float = DEFAULT_FOOLED_THRESHOLD,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    if tier not in TIERS and tier not in TRACKS:
        raise ValueError(f"unknown tier {tier!r}")
    if episode is not None and episode_path is not None:
        raise ValueError("pass at most one of episode or episode_path")

    _, parsed_mode = parse_v16_spec(variant, mode=mode)
    needs_temp_cache = (
        parsed_mode in ("gemini", "gemini-stub")
        and cache_dir is None
        and not os.environ.get("CANARY_GEMINI_CACHE_DIR", "").strip()
    )
    if needs_temp_cache:
        with tempfile.TemporaryDirectory(prefix="v16_office_replay_") as tmp_dir:
            return build_office_replay(
                tier=tier,
                seed=seed,
                variant=variant,
                mode=mode,
                episode=episode,
                episode_path=episode_path,
                agent=agent,
                fooled_threshold=fooled_threshold,
                cache_dir=tmp_dir,
            )

    provider, provenance_badge = resolve_replay_provider(variant=variant, mode=mode, cache_dir=cache_dir)
    env = Env(tier=tier, seed=int(seed), text_provider=provider)

    if episode is not None or episode_path is not None:
        recorded_ep = (
            _coerce_episode(episode, tier=tier, seed=int(seed))
            if episode is not None
            else load_episode_record(episode_path, tier=tier, seed=int(seed))
        )
        steps, final_day, facts_by_day, v_by_day, leaks_by_day = _step_env_with_recorded_episode(env, recorded_ep)
        active_ep = EpisodeResult(
            tier=tier,
            seed=int(seed),
            agent=recorded_ep.agent,
            steps=steps,
            score=float(recorded_ep.score if recorded_ep.steps else env.score()),
            accused=recorded_ep.accused if recorded_ep.accused is not None else env._accused,
            correct=bool(recorded_ep.correct if recorded_ep.accused is not None else env._correct),
            final_day=final_day,
            end_reason=str(recorded_ep.end_reason or env._end_reason or "horizon"),
            meta=dict(recorded_ep.meta or {}),
        )
    else:
        policy = make_replay_policy(agent=agent, tier=tier, seed=int(seed))
        active_ep, facts_by_day, v_by_day, leaks_by_day = _step_env_with_policy(env, policy)
        steps = list(active_ep.steps)
        final_day = max(1, int(active_ep.final_day or 1))

    day1_facts = facts_by_day[1]
    roster_ids = [e.id for e in day1_facts.employees]
    roster_set = set(roster_ids)

    rendered_by_day: dict[int, list[dict[str, Any]]] = {}
    for d in range(1, final_day + 1):
        rendered_by_day[d] = provider.day_messages(facts_by_day[d])

    soc_state: EpisodeSocialState | None = provider.episode_state(day1_facts.tier, day1_facts.seed)
    primary_suspect = soc_state.primary_suspect if soc_state is not None else None
    secondary_suspect = soc_state.secondary_suspect if soc_state is not None else None
    social_targets = {x for x in (primary_suspect, secondary_suspect) if x}

    params = tier_params_for_episode(tier, steps)
    if episode is None and episode_path is None and active_ep.agent == "solver":
        ref_ep = active_ep
    else:
        ref_prov, _ = resolve_replay_provider(variant=provider.variant, mode=provider.mode, cache_dir=cache_dir)
        ref_env = Env(tier=tier, seed=int(seed), text_provider=ref_prov)
        ref_ep, _, _, _ = _step_env_with_policy(ref_env, SolverPolicy(params))

    max_day_needed = max(final_day, int(ref_ep.final_day or 1))
    ref_post_by_day = _posterior_by_day_from_steps(ref_ep.steps, params, roster_ids, max_day_needed)
    agent_post_by_day = _posterior_by_day_from_steps(steps, params, roster_ids, final_day)

    formatted_events_by_day: dict[int, list[dict[str, Any]]] = {}
    for d in range(1, final_day + 1):
        raw_evs = soc_state.events_by_day.get(d, ()) if soc_state is not None else ()
        formatted_events_by_day[d] = [
            _format_social_event(ev, d, primary_suspect, secondary_suspect)
            for ev in raw_evs
        ]

    sp_step = SolverPolicy(params)
    sp_step.obs.employees = list(roster_ids)
    actions_by_day: dict[int, list[dict[str, Any]]] = {d: [] for d in range(1, final_day + 1)}
    fooled_by_day: dict[int, list[dict[str, Any]]] = {d: [] for d in range(1, final_day + 1)}
    all_fooled_moments: list[dict[str, Any]] = []

    for idx, st in enumerate(steps):
        d = min(final_day, max(1, int(st.day or 1)))
        agent_post_before = dict(sp_step.belief())
        ref_post = ref_post_by_day[d]
        ref_top = max(ref_post, key=ref_post.get) if ref_post else None
        ref_p_top = float(ref_post[ref_top]) if ref_top is not None else 0.0

        args = st.args if isinstance(st.args, dict) else {}
        emp = args.get("employee")
        target_emp = str(emp) if isinstance(emp, str) and emp in roster_set else None
        solver_p_target = round(float(ref_post.get(target_emp, 0.0)), 6) if target_emp is not None else None
        agent_obs_p_target = round(float(agent_post_before.get(target_emp, 0.0)), 6) if target_emp is not None else None

        is_fooled = bool(
            st.tool in FOOLED_ACTION_TOOLS
            and target_emp is not None
            and target_emp in social_targets
            and solver_p_target is not None
            and solver_p_target < float(fooled_threshold)
        )

        if is_fooled and target_emp is not None and solver_p_target is not None:
            prior_evs = [
                ev
                for prev_d in range(1, d + 1)
                for ev in formatted_events_by_day.get(prev_d, ())
                if ev["target"] == target_emp
            ]
            fooled_item = {
                "t": int(st.t if st.t is not None else idx),
                "day": d,
                "tool": str(st.tool),
                "target": target_emp,
                "target_role": "primary_suspect" if target_emp == primary_suspect else "secondary_suspect",
                "solver_p_target": solver_p_target,
                "agent_obs_p_target": agent_obs_p_target,
                "solver_top_suspect": ref_top,
                "solver_p_top": round(ref_p_top, 6),
                "prior_social_mentions": len(prior_evs),
                "prior_biases": sorted({ev["bias"] for ev in prior_evs}),
            }
            fooled_by_day[d].append(fooled_item)
            all_fooled_moments.append(fooled_item)

        actions_by_day[d].append(
            {
                "t": int(st.t if st.t is not None else idx),
                "day": d,
                "tool": str(st.tool),
                "args": dict(args),
                "ok": bool((st.result or {}).get("ok", False)),
                "summary": _summarize_step(st),
                "target": target_emp,
                "solver_p_target": solver_p_target,
                "agent_obs_p_target": agent_obs_p_target,
                "fooled": is_fooled,
            }
        )

        if st.tool != "accuse":
            sp_step._ingest(st)

    template_provider = TemplateProvider()
    cum_mentions: dict[str, int] = {}
    days_out: list[dict[str, Any]] = []

    for d in range(1, final_day + 1):
        f_day = facts_by_day[d]
        raw_evs = soc_state.events_by_day.get(d, ()) if soc_state is not None else ()
        day_events = formatted_events_by_day[d]
        for ev in day_events:
            tgt = ev["target"]
            if tgt:
                cum_mentions[tgt] = cum_mentions.get(tgt, 0) + 1

        day_msgs = _annotate_day_messages(
            facts=f_day,
            rendered_msgs=rendered_by_day[d],
            day_events=raw_evs,
            template_provider=template_provider,
            provenance_badge=provenance_badge,
        )

        ref_post = ref_post_by_day[d]
        agent_post = agent_post_by_day[d]
        ref_top = max(ref_post, key=ref_post.get) if ref_post else None
        agent_top = max(agent_post, key=agent_post.get) if agent_post else None
        ranked_ref = sorted(ref_post.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

        posterior_rec = {
            "top_suspect": ref_top,
            "p_top_suspect": round(float(ref_post[ref_top]), 6) if ref_top is not None else 0.0,
            "p_primary_suspect": (
                round(float(ref_post.get(primary_suspect, 0.0)), 6)
                if primary_suspect is not None
                else None
            ),
            "p_secondary_suspect": (
                round(float(ref_post.get(secondary_suspect, 0.0)), 6)
                if secondary_suspect is not None
                else None
            ),
            "agent_top_suspect": agent_top,
            "agent_p_top_suspect": round(float(agent_post[agent_top]), 6) if agent_top is not None else 0.0,
            "agent_p_primary_suspect": (
                round(float(agent_post.get(primary_suspect, 0.0)), 6)
                if primary_suspect is not None
                else None
            ),
            "agent_p_secondary_suspect": (
                round(float(agent_post.get(secondary_suspect, 0.0)), 6)
                if secondary_suspect is not None
                else None
            ),
            "top_candidates": [{"employee": eid, "p": round(float(prob), 4)} for eid, prob in ranked_ref],
            "social_mentions_to_date": {
                k: int(cum_mentions.get(k, 0))
                for k in (primary_suspect, secondary_suspect)
                if k is not None
            },
        }

        day_docs = [
            {
                "doc_id": str(doc.get("doc_id", "")),
                "title": str(doc.get("title", "")),
                "day": int(doc.get("day", d)),
                "recipients": [str(r) for r in doc.get("recipients", ())],
                "is_canary": str(doc.get("doc_id", "")).startswith("c"),
            }
            for doc in f_day.docs
        ]

        days_out.append(
            {
                "day": d,
                "V": round(float(v_by_day.get(d, 1.0)), 6),
                "restricted": list(f_day.restricted),
                "documents": day_docs,
                "surfaced_leaks": leaks_by_day.get(d, []),
                "social_events": day_events,
                "messages": day_msgs,
                "actions": actions_by_day[d],
                "posterior": posterior_rec,
                "fooled_moments": fooled_by_day[d],
            }
        )

    employees_out = [
        {
            "id": e.id,
            "name": e.name,
            "dept": e.dept,
            "role": e.role,
            "clearance": e.clearance,
        }
        for e in day1_facts.employees
    ]

    return {
        "tier": tier,
        "seed": int(seed),
        "variant": provider.variant,
        "mode": provider.mode,
        "provider_name": provider.name,
        "provenance": provenance_badge,
        "company": day1_facts.company,
        "decoy": day1_facts.decoy,
        "fooled_threshold": float(fooled_threshold),
        "employees": employees_out,
        "social_state": {
            "primary_suspect": primary_suspect,
            "secondary_suspect": secondary_suspect,
            "authority_speakers": list(soc_state.authority_speakers) if soc_state is not None else [],
            "grudge_pairs": [list(p) for p in soc_state.grudge_pairs] if soc_state is not None else [],
            "active_biases": [str(b) for b in provider.variant_spec.get("biases", ())],
            "all_bias_types": list(BIAS_TYPES),
        },
        "episode_summary": {
            "agent": active_ep.agent,
            "final_day": final_day,
            "accused": active_ep.accused,
            "correct": bool(active_ep.correct),
            "score": round(float(active_ep.score), 6),
            "end_reason": active_ep.end_reason,
            "total_steps": len(steps),
            "fooled_count": len(all_fooled_moments),
        },
        "solver_reference_summary": {
            "agent": ref_ep.agent,
            "final_day": int(ref_ep.final_day),
            "accused": ref_ep.accused,
            "correct": bool(ref_ep.correct),
            "score": round(float(ref_ep.score), 6),
        },
        "fooled_moments": all_fooled_moments,
        "days": days_out,
    }


def _safe_json_for_html(payload: dict[str, Any]) -> str:
    dumped = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return dumped.replace("</", "<\\/")


def render_office_replay_html(
    replay: dict[str, Any],
    *,
    out_path: str | Path | None = None,
) -> str:
    esc = html.escape
    company = esc(str(replay.get("company", "Canary Office")))
    tier = esc(str(replay.get("tier", "")))
    seed = int(replay.get("seed", 0))
    variant = esc(str(replay.get("variant", "")))
    prov = esc(str(replay.get("provenance", "")))
    decoy = replay.get("decoy")
    soc = replay.get("social_state") or {}
    prim = soc.get("primary_suspect")
    sec = soc.get("secondary_suspect")
    ep = replay.get("episode_summary") or {}
    sol_ref = replay.get("solver_reference_summary") or {}
    days = replay.get("days") or []
    fooled = replay.get("fooled_moments") or []

    total_social = sum(len(d.get("social_events") or ()) for d in days)
    seen_biases = sorted({ev["bias"] for d in days for ev in (d.get("social_events") or ())})
    verdict_label = (
        "CORRECT ACCUSATION"
        if ep.get("correct")
        else ("WRONG ACCUSATION" if ep.get("accused") else "NO ACCUSATION")
    )
    verdict_cls = "good" if ep.get("correct") else "bad"

    summary_rows: list[str] = []
    for d in days:
        d_num = int(d["day"])
        post = d.get("posterior") or {}
        top_id = esc(str(post.get("top_suspect") or "-"))
        p_top = float(post.get("p_top_suspect") or 0.0)
        p_prim = post.get("p_primary_suspect")
        p_sec = post.get("p_secondary_suspect")
        p_prim_txt = f"{float(p_prim):.4f}" if p_prim is not None else "n/a"
        p_sec_txt = f"{float(p_sec):.4f}" if p_sec is not None else "n/a"
        evs = d.get("social_events") or []
        ev_txt = ", ".join(f"{esc(ev['bias'])}->{esc(ev['target'])}" for ev in evs) or "none"
        acts = d.get("actions") or []
        act_txt = ", ".join(esc(a["tool"]) for a in acts) or "none"
        f_cnt = len(d.get("fooled_moments") or ())
        f_cell = f"<span class='pill bad'>FOOLED ({f_cnt})</span>" if f_cnt else "<span class='muted'>0</span>"
        summary_rows.append(
            f"<tr data-day-row='{d_num}'>"
            f"<td class='num'>Day {d_num}</td>"
            f"<td class='num'>{float(d.get('V', 1.0)):.3f}</td>"
            f"<td>{ev_txt}</td>"
            f"<td class='num'>{top_id} ({p_top:.4f})</td>"
            f"<td class='num'>{p_prim_txt}</td>"
            f"<td class='num'>{p_sec_txt}</td>"
            f"<td>{act_txt}</td>"
            f"<td>{f_cell}</td>"
            f"</tr>"
        )

    fooled_banner = ""
    if fooled:
        items_html = "".join(
            f"<li><b>Day {int(f['day'])} (t={int(f['t'])})</b>: "
            f"<code>{esc(str(f['tool']))}({esc(str(f['target']))})</code> on {esc(str(f['target_role']))} "
            f"while solver P({esc(str(f['target']))}) = <b>{float(f['solver_p_target']):.4f}</b> "
            f"(solver top: {esc(str(f.get('solver_top_suspect') or '-'))} at {float(f.get('solver_p_top') or 0.0):.4f}; "
            f"prior social mentions: {int(f.get('prior_social_mentions', 0))}, "
            f"biases: {esc(', '.join(f.get('prior_biases') or ())) or 'none'})</li>"
            for f in fooled
        )
        fooled_banner = (
            "<section class='alert-box' data-testid='fooled-banner'>"
            f"<h2>Fooled Moments Detected ({len(fooled)})</h2>"
            f"<ul>{items_html}</ul>"
            "</section>"
        )

    payload_json = _safe_json_for_html(replay)

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{company} - Canary V1.6 Office Replay ({tier} seed {seed}, {variant})</title>
<style>
:root {{
  --bg: rgb(245, 247, 250);
  --panel: rgb(255, 255, 255);
  --line: rgb(216, 222, 229);
  --text: rgb(26, 32, 44);
  --muted: rgb(90, 102, 117);
  --accent: rgb(25, 103, 145);
  --good: rgb(27, 122, 70);
  --good-bg: rgb(232, 247, 238);
  --bad: rgb(179, 38, 30);
  --bad-bg: rgb(253, 239, 238);
  --warn: rgb(154, 103, 0);
  --warn-bg: rgb(254, 246, 228);
  --social: rgb(98, 54, 168);
  --social-bg: rgb(243, 237, 253);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
.topbar {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 12px 18px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}}
.topbar h1 {{ font-size: 16px; margin: 0; }}
.spacer {{ flex: 1; }}
.muted {{ color: var(--muted); }}
.num {{ font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, Consolas, monospace; }}
.pill {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid var(--line);
  background: var(--bg);
}}
.pill.good {{ color: var(--good); background: var(--good-bg); border-color: var(--good); }}
.pill.bad {{ color: var(--bad); background: var(--bad-bg); border-color: var(--bad); }}
.pill.warn {{ color: var(--warn); background: var(--warn-bg); border-color: var(--warn); }}
.pill.social {{ color: var(--social); background: var(--social-bg); border-color: var(--social); }}
.pill.prov {{ color: var(--accent); border-color: var(--accent); background: rgb(234, 244, 250); }}
.kpis {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
  gap: 10px;
  padding: 12px 18px 4px;
}}
.kpi {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
}}
.kpi .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }}
.kpi .val {{ font-size: 15px; font-weight: 600; margin-top: 3px; }}
.transport {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: 8px 18px;
  padding: 10px 12px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
}}
button, select {{
  font: inherit;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
}}
button:hover, select:hover {{ border-color: var(--accent); }}
button.active-day {{ background: var(--accent); color: rgb(255, 255, 255); border-color: var(--accent); }}
input[type=range] {{ flex: 1; min-width: 140px; accent-color: var(--accent); }}
.day-buttons {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.alert-box {{
  margin: 8px 18px;
  padding: 10px 14px;
  background: var(--bad-bg);
  border: 1px solid var(--bad);
  border-radius: 6px;
}}
.alert-box h2 {{ margin: 0 0 6px; font-size: 13px; text-transform: uppercase; color: var(--bad); }}
.alert-box ul {{ margin: 0; padding-left: 18px; }}
.workspace {{
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 14px;
  padding: 6px 18px 14px;
}}
@media (max-width: 980px) {{
  .workspace {{ grid-template-columns: 1fr; }}
}}
.card-panel {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 12px;
}}
.card-panel h2 {{
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin: 0 0 10px;
}}
.dept-group {{ margin-bottom: 10px; }}
.dept-group h3 {{ font-size: 12px; margin: 6px 0; color: var(--muted); }}
.desk-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}}
.desk {{
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 7px 9px;
  background: var(--panel);
  font-size: 12px;
}}
.desk.primary-target {{ border-left: 4px solid var(--social); background: var(--social-bg); }}
.desk.secondary-target {{ border-left: 4px solid var(--warn); background: var(--warn-bg); }}
.desk.solver-top {{ box-shadow: inset 0 0 0 1.5px var(--good); }}
.desk.fooled-hit {{ border-color: var(--bad); background: var(--bad-bg); }}
.desk.restricted {{ opacity: 0.68; }}
.desk-head {{ display: flex; align-items: center; gap: 5px; flex-wrap: wrap; font-weight: 600; }}
.bar-row {{ display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: 12px; }}
.bar-track {{ flex: 1; height: 10px; background: var(--bg); border: 1px solid var(--line); border-radius: 4px; overflow: hidden; }}
.bar-fill {{ height: 100%; background: var(--accent); }}
.bar-fill.good {{ background: var(--good); }}
.bar-fill.social {{ background: var(--social); }}
.bar-fill.warn {{ background: var(--warn); }}
.event-list, .msg-list, .act-list {{ list-style: none; margin: 0; padding: 0; }}
.event-list li, .msg-list li, .act-list li {{
  padding: 8px 0;
  border-top: 1px solid var(--line);
}}
.event-list li:first-child, .msg-list li:first-child, .act-list li:first-child {{ border-top: 0; }}
.meta-line {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; margin-bottom: 3px; }}
.filters {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; font-size: 12px; align-items: center; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; background: var(--panel); }}
th, td {{ text-align: left; padding: 6px 8px; border-top: 1px solid var(--line); vertical-align: top; }}
th {{ font-size: 11px; text-transform: uppercase; color: var(--muted); border-top: 0; }}
.overview-wrap {{ padding: 0 18px 24px; }}
</style>
</head>
<body>
<header class="topbar">
  <h1>{company}: Office Social Replay</h1>
  <span class="pill prov" data-testid="provenance-badge">{prov}</span>
  <span class="pill">{tier} / seed {seed}</span>
  <span class="pill social">{variant}</span>
  <span class="spacer"></span>
  <span class="pill">agent: {esc(str(ep.get("agent", "")))}</span>
  <span class="pill {verdict_cls}">{verdict_label} (score {float(ep.get("score", 0.0)):+.2f})</span>
</header>

<section class="kpis">
  <div class="kpi">
    <div class="label">Social Targets (Public Trap)</div>
    <div class="val num">primary: {esc(str(prim or "none"))} | secondary: {esc(str(sec or "none"))}</div>
    <div class="muted">{total_social} events across {len(seen_biases)} biases</div>
  </div>
  <div class="kpi">
    <div class="label">Decoy Persona (Public)</div>
    <div class="val num">{esc(str(decoy or "none"))}</div>
    <div class="muted">preserved angry baseline; non-decoy scrubbed</div>
  </div>
  <div class="kpi">
    <div class="label">Agent Outcome</div>
    <div class="val num">day {int(ep.get("final_day", 1))}: accused {esc(str(ep.get("accused") or "none"))}</div>
    <div class="muted">{int(ep.get("total_steps", 0))} tool calls, {len(fooled)} fooled moments</div>
  </div>
  <div class="kpi">
    <div class="label">Reference SolverPolicy</div>
    <div class="val num">day {int(sol_ref.get("final_day", 1))}: accused {esc(str(sol_ref.get("accused") or "none"))}</div>
    <div class="muted">score {float(sol_ref.get("score", 0.0)):+.2f} (calibrated leak Bayes)</div>
  </div>
</section>

{fooled_banner}

<section class="transport" aria-label="Day transport">
  <button type="button" id="btn-play">Play</button>
  <button type="button" id="btn-prev">Prev Day</button>
  <button type="button" id="btn-next">Next Day</button>
  <input type="range" id="day-slider" min="1" max="{max(1, len(days))}" value="1" aria-label="Day selector">
  <span id="day-indicator" class="num">Day 1 / {max(1, len(days))}</span>
  <div id="day-buttons" class="day-buttons"></div>
</section>

<main class="workspace">
  <div>
    <section class="card-panel">
      <h2>Bayesian Leak Posterior vs Office Chatter (<span id="post-day-label">Day 1</span>)</h2>
      <div id="divergence-box"></div>
    </section>
    <section class="card-panel">
      <h2>Office Floor by Department (<span id="floor-day-label">Day 1</span>)</h2>
      <div id="office-floor"></div>
    </section>
    <section class="card-panel">
      <h2>Agent Tool Actions (<span id="actions-day-label">Day 1</span>)</h2>
      <ol id="actions-list" class="act-list"></ol>
    </section>
  </div>
  <div>
    <section class="card-panel">
      <h2>Structured V1.6 Social Events (<span id="events-day-label">Day 1</span>)</h2>
      <div class="filters">
        <label>Bias <select id="filter-bias"><option value="">All biases</option></select></label>
        <label>Employee <select id="filter-emp"><option value="">All employees</option></select></label>
      </div>
      <ol id="social-events-list" class="event-list"></ol>
    </section>
    <section class="card-panel">
      <h2>Rendered Day Messages (<span id="msgs-day-label">Day 1</span>)</h2>
      <div class="filters">
        <label>Tag
          <select id="filter-tag">
            <option value="">All tags</option>
            <option value="decoy">decoy</option>
            <option value="scrubbed-non-decoy">scrubbed-non-decoy</option>
            <option value="non-decoy">non-decoy</option>
          </select>
        </label>
        <label><input type="checkbox" id="filter-social-only"> Social only</label>
      </div>
      <ol id="messages-list" class="msg-list"></ol>
    </section>
  </div>
</main>

<section class="overview-wrap">
  <div class="card-panel">
    <h2>Per-Day Timeline Summary (Days 1..{max(1, len(days))})</h2>
    <table>
      <thead>
        <tr>
          <th>Day</th>
          <th>Visible V</th>
          <th>Social Events (bias-&gt;target)</th>
          <th>Solver Top Suspect</th>
          <th>Solver P(primary)</th>
          <th>Solver P(secondary)</th>
          <th>Agent Actions</th>
          <th>Fooled</th>
        </tr>
      </thead>
      <tbody>
        {''.join(summary_rows)}
      </tbody>
    </table>
  </div>
</section>

<script id="office-replay-data" type="application/json">{payload_json}</script>
<script>
(function() {{
  const raw = document.getElementById("office-replay-data").textContent;
  const DATA = JSON.parse(raw);
  const days = DATA.days || [];
  if (!days.length) return;

  const empById = {{}};
  (DATA.employees || []).forEach(e => {{ empById[e.id] = e; }});
  const prim = DATA.social_state ? DATA.social_state.primary_suspect : null;
  const sec = DATA.social_state ? DATA.social_state.secondary_suspect : null;
  const decoy = DATA.decoy || null;

  let curIdx = 0;
  let timer = null;

  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
  const el = id => document.getElementById(id);

  const biasSel = el("filter-bias");
  const allBiases = Array.from(new Set(days.flatMap(d => (d.social_events || []).map(ev => ev.bias)))).sort();
  allBiases.forEach(b => {{
    const opt = document.createElement("option");
    opt.value = b;
    opt.textContent = b;
    biasSel.appendChild(opt);
  }});

  const empSel = el("filter-emp");
  (DATA.employees || []).forEach(e => {{
    const opt = document.createElement("option");
    opt.value = e.id;
    opt.textContent = e.id + " - " + e.name + " (" + e.dept + ")";
    empSel.appendChild(opt);
  }});

  const btnWrap = el("day-buttons");
  days.forEach((d, idx) => {{
    const b = document.createElement("button");
    b.type = "button";
    const fCnt = (d.fooled_moments || []).length;
    b.textContent = "D" + d.day + (fCnt ? " !" : "");
    b.onclick = () => {{ stopPlay(); setIdx(idx); }};
    btnWrap.appendChild(b);
  }});

  function renderDivergence(d) {{
    const p = d.posterior || {{}};
    const pTop = Number(p.p_top_suspect || 0);
    const pPrim = p.p_primary_suspect != null ? Number(p.p_primary_suspect) : null;
    const pSec = p.p_secondary_suspect != null ? Number(p.p_secondary_suspect) : null;
    const mentions = p.social_mentions_to_date || {{}};
    const primMentions = prim ? (mentions[prim] || 0) : 0;
    const secMentions = sec ? (mentions[sec] || 0) : 0;

    let htmlOut = "";
    htmlOut += '<div class="bar-row"><span class="num" style="width:210px">Solver top: ' + esc(p.top_suspect || "-") + ' (' + (pTop * 100).toFixed(1) + '%)</span>' +
      '<div class="bar-track"><div class="bar-fill good" style="width:' + Math.min(100, pTop * 100).toFixed(1) + '%"></div></div></div>';
    if (prim) {{
      htmlOut += '<div class="bar-row"><span class="num" style="width:210px">Solver P(primary ' + esc(prim) + '): ' + ((pPrim || 0) * 100).toFixed(1) + '%</span>' +
        '<div class="bar-track"><div class="bar-fill social" style="width:' + Math.min(100, (pPrim || 0) * 100).toFixed(1) + '%"></div></div>' +
        '<span class="pill social">' + primMentions + ' social hits</span></div>';
    }}
    if (sec) {{
      htmlOut += '<div class="bar-row"><span class="num" style="width:210px">Solver P(secondary ' + esc(sec) + '): ' + ((pSec || 0) * 100).toFixed(1) + '%</span>' +
        '<div class="bar-track"><div class="bar-fill warn" style="width:' + Math.min(100, (pSec || 0) * 100).toFixed(1) + '%"></div></div>' +
        '<span class="pill warn">' + secMentions + ' social hits</span></div>';
    }}
    const leaks = d.surfaced_leaks || [];
    htmlOut += '<div class="muted" style="margin-top:6px">Visible V: <b class="num">' + Number(d.V || 1).toFixed(3) + '</b> | Surfaced leaks through Day ' + d.day + ': <b class="num">' + leaks.length + '</b></div>';
    el("divergence-box").innerHTML = htmlOut;
  }}

  function renderFloor(d) {{
    const p = d.posterior || {{}};
    const topId = p.top_suspect;
    const restricted = new Set(d.restricted || []);
    const fooledTargets = new Set((d.fooled_moments || []).map(f => f.target));
    const mentions = p.social_mentions_to_date || {{}};
    const byDept = {{}};
    (DATA.employees || []).forEach(e => {{
      (byDept[e.dept] = byDept[e.dept] || []).push(e);
    }});

    el("office-floor").innerHTML = Object.keys(byDept).sort().map(dept => {{
      const cards = byDept[dept].map(e => {{
        const cls = ["desk"];
        if (e.id === prim) cls.push("primary-target");
        if (e.id === sec) cls.push("secondary-target");
        if (e.id === topId) cls.push("solver-top");
        if (fooledTargets.has(e.id)) cls.push("fooled-hit");
        if (restricted.has(e.id)) cls.push("restricted");

        const badges = [];
        if (e.id === prim) badges.push('<span class="pill social">primary (' + (mentions[e.id] || 0) + ')</span>');
        if (e.id === sec) badges.push('<span class="pill warn">secondary (' + (mentions[e.id] || 0) + ')</span>');
        if (e.id === decoy) badges.push('<span class="pill">decoy</span>');
        if (e.id === topId) badges.push('<span class="pill good">solver top</span>');
        if (restricted.has(e.id)) badges.push('<span class="pill warn">restricted</span>');
        if (fooledTargets.has(e.id)) badges.push('<span class="pill bad">fooled action</span>');
        if (d.day === DATA.episode_summary.final_day && DATA.episode_summary.accused === e.id) {{
          badges.push('<span class="pill ' + (DATA.episode_summary.correct ? 'good' : 'bad') + '">accused</span>');
        }}
        return '<article class="' + cls.join(" ") + '" data-emp="' + esc(e.id) + '">' +
          '<div class="desk-head"><span class="num">' + esc(e.id) + '</span>' +
          (e.clearance != null ? '<span class="muted">L' + esc(e.clearance) + '</span>' : '') +
          badges.join("") + '</div>' +
          '<div>' + esc(e.name) + '</div>' +
          '<div class="muted">' + esc(e.role) + '</div>' +
          '</article>';
      }}).join("");
      return '<div class="dept-group"><h3>' + esc(dept) + '</h3><div class="desk-grid">' + cards + '</div></div>';
    }}).join("");
  }}

  function renderEvents(d) {{
    const fBias = biasSel.value;
    const fEmp = empSel.value;
    const evs = (d.social_events || []).filter(ev =>
      (!fBias || ev.bias === fBias) &&
      (!fEmp || ev.sender === fEmp || ev.target === fEmp)
    );
    if (!evs.length) {{
      el("social-events-list").innerHTML = '<li class="muted">No social events matching filter on Day ' + d.day + '.</li>';
      return;
    }}
    el("social-events-list").innerHTML = evs.map(ev =>
      '<li><div class="meta-line">' +
      '<span class="pill social">' + esc(ev.bias) + '</span>' +
      '<span class="pill">' + esc(ev.channel) + '</span>' +
      '<span class="num">' + esc(ev.sender) + ' (' + esc(ev.speaker_name) + ') -&gt; ' + esc(ev.target) + ' (' + esc(ev.target_name) + ')</span>' +
      '<span class="pill">' + esc(ev.target_role) + '</span>' +
      '</div>' +
      '<div><b>' + esc(ev.subject) + '</b></div>' +
      '<div>' + esc(ev.body) + '</div></li>'
    ).join("");
  }}

  function renderMessages(d) {{
    const fTag = el("filter-tag").value;
    const fEmp = empSel.value;
    const socialOnly = el("filter-social-only").checked;
    const msgs = (d.messages || []).filter(m =>
      (!fTag || m.tag === fTag) &&
      (!socialOnly || m.is_social) &&
      (!fEmp || m.sender === fEmp || m.target === fEmp)
    );
    if (!msgs.length) {{
      el("messages-list").innerHTML = '<li class="muted">No messages matching filter on Day ' + d.day + '.</li>';
      return;
    }}
    el("messages-list").innerHTML = msgs.map(m => {{
      const tagCls = m.tag === "decoy" ? "warn" : (m.tag === "scrubbed-non-decoy" ? "good" : "");
      return '<li><div class="meta-line">' +
        '<span class="num">' + esc(m.id) + '</span>' +
        '<span class="pill">' + esc(m.channel) + '</span>' +
        '<span class="num">from ' + esc(m.sender) + ' (' + esc(m.sender_name) + ')</span>' +
        '<span class="pill ' + tagCls + '">' + esc(m.tag) + '</span>' +
        (m.scrubbed_rewrite ? '<span class="pill good">vocab-rewritten</span>' : '') +
        (m.bias ? '<span class="pill social">' + esc(m.bias) + '</span>' : '') +
        '<span class="pill prov">' + esc(m.provenance) + '</span>' +
        '</div>' +
        (m.subject ? '<div><b>' + esc(m.subject) + '</b></div>' : '') +
        '<div>' + esc(m.body) + '</div></li>';
    }}).join("");
  }}

  function renderActions(d) {{
    const acts = d.actions || [];
    if (!acts.length) {{
      el("actions-list").innerHTML = '<li class="muted">No agent tool calls recorded on Day ' + d.day + '.</li>';
      return;
    }}
    el("actions-list").innerHTML = acts.map(a =>
      '<li><div class="meta-line">' +
      '<span class="num">t=' + a.t + '</span>' +
      '<span class="num"><b>' + esc(a.summary) + '</b></span>' +
      (a.solver_p_target != null ? '<span class="pill">solver P(' + esc(a.target) + ')=' + Number(a.solver_p_target).toFixed(4) + '</span>' : '') +
      (a.fooled ? '<span class="pill bad">FOOLED MOMENT</span>' : '') +
      (!a.ok ? '<span class="pill bad">error</span>' : '') +
      '</div></li>'
    ).join("");
  }}

  function render() {{
    const d = days[curIdx];
    const lbl = "Day " + d.day;
    el("day-indicator").textContent = "Day " + d.day + " / " + days[days.length - 1].day;
    el("day-slider").value = String(curIdx + 1);
    ["post-day-label", "floor-day-label", "actions-day-label", "events-day-label", "msgs-day-label"].forEach(id => {{
      el(id).textContent = lbl;
    }});
    Array.from(btnWrap.children).forEach((b, i) => b.classList.toggle("active-day", i === curIdx));
    renderDivergence(d);
    renderFloor(d);
    renderEvents(d);
    renderMessages(d);
    renderActions(d);
  }}

  function setIdx(i) {{
    curIdx = Math.max(0, Math.min(days.length - 1, i));
    render();
  }}
  function stopPlay() {{
    if (timer) {{ clearInterval(timer); timer = null; }}
    el("btn-play").textContent = "Play";
  }}
  function togglePlay() {{
    if (timer) return stopPlay();
    if (curIdx >= days.length - 1) curIdx = 0;
    el("btn-play").textContent = "Pause";
    timer = setInterval(() => {{
      if (curIdx >= days.length - 1) return stopPlay();
      setIdx(curIdx + 1);
    }}, 700);
  }}

  el("btn-play").onclick = togglePlay;
  el("btn-prev").onclick = () => {{ stopPlay(); setIdx(curIdx - 1); }};
  el("btn-next").onclick = () => {{ stopPlay(); setIdx(curIdx + 1); }};
  el("day-slider").oninput = e => {{ stopPlay(); setIdx(Number(e.target.value) - 1); }};
  biasSel.onchange = () => renderEvents(days[curIdx]);
  empSel.onchange = () => {{ renderEvents(days[curIdx]); renderMessages(days[curIdx]); }};
  el("filter-tag").onchange = () => renderMessages(days[curIdx]);
  el("filter-social-only").onchange = () => renderMessages(days[curIdx]);
  document.addEventListener("keydown", e => {{
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT") return;
    if (e.key === " ") {{ e.preventDefault(); togglePlay(); }}
    else if (e.key === "ArrowRight") {{ e.preventDefault(); stopPlay(); setIdx(curIdx + 1); }}
    else if (e.key === "ArrowLeft") {{ e.preventDefault(); stopPlay(); setIdx(curIdx - 1); }}
  }});

  render();
}})();
</script>
</body>
</html>
"""
    if out_path is not None:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc, encoding="utf-8")
    return doc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m canary.social.office_replay",
        description="Keyless V1.6 Office Social Replay extractor and self-contained HTML viewer.",
    )
    ap.add_argument("--tier", default="hard", choices=[*TIERS, *TRACKS])
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--variant", default="v5_full9_cocktail")
    ap.add_argument("--mode", default=None, choices=["template", "gemini-stub"])
    ap.add_argument("--episode", default=None, help="Optional EpisodeResult JSON/JSONL file path")
    ap.add_argument("--agent", default="solver", help="Policy used when --episode is omitted")
    ap.add_argument("--fooled-threshold", type=float, default=DEFAULT_FOOLED_THRESHOLD)
    ap.add_argument("--out", required=True, help="Output path for self-contained HTML replay")
    ap.add_argument("--json-out", default=None, help="Optional output path for replay JSON")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    replay = build_office_replay(
        tier=args.tier,
        seed=args.seed,
        variant=args.variant,
        mode=args.mode,
        episode_path=args.episode,
        agent=args.agent,
        fooled_threshold=args.fooled_threshold,
    )
    render_office_replay_html(replay, out_path=args.out)
    if args.json_out:
        json_target = Path(args.json_out)
        json_target.parent.mkdir(parents=True, exist_ok=True)
        json_target.write_text(json.dumps(replay, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "tier": replay["tier"],
        "seed": replay["seed"],
        "variant": replay["variant"],
        "provenance": replay["provenance"],
        "agent": replay["episode_summary"]["agent"],
        "final_day": replay["episode_summary"]["final_day"],
        "accused": replay["episode_summary"]["accused"],
        "correct": replay["episode_summary"]["correct"],
        "score": replay["episode_summary"]["score"],
        "primary_suspect": replay["social_state"]["primary_suspect"],
        "secondary_suspect": replay["social_state"]["secondary_suspect"],
        "social_events": sum(len(d["social_events"]) for d in replay["days"]),
        "fooled_count": replay["episode_summary"]["fooled_count"],
        "out": str(args.out),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
