"""Six-check V1.6 Social TextProvider fairness, hygiene, calibration, and replay audit."""
from __future__ import annotations

import argparse
import importlib
import json
import math
import random
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from canary import rules as canary_rules
from canary.analysis.accuse import audit_episode
from canary.analysis.gap import mean_ci
from canary.baselines import DoNothing, Heuristic, StopEarly, StopEarlyQuit
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.rules import TIERS, tier_params, tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts
from canary.text.gemini import get_provider
from canary.text.lint import lint_messages, lint_text
from canary.text.template import SIGNALS, TOPICS, TemplateProvider
from canary.types import EpisodeResult, Step

CHECK_NAMES: tuple[str, ...] = (
    "public_facts_only",
    "anger_words_hygiene",
    "lint_clean",
    "solver_calibration_parity",
    "zero_baselines",
    "replay_and_paired_gap",
)

ANGER_WORDS: tuple[str, ...] = tuple(SolverPolicy.ANGER_WORDS)

REQUIRED_MSG_KEYS: frozenset[str] = frozenset(
    {"id", "day", "channel", "sender", "recipients", "subject", "body"}
)

_TEMPLATE_SOLVER_CACHE: dict[tuple[Any, ...], EpisodeResult] = {}


class SanitizedTemplateProvider:
    """Reference V1.6-clean wrapper over TemplateProvider avoiding non-decoy ANGER_WORDS collisions."""

    name = "sanitized_template"

    def __init__(self) -> None:
        self._inner = TemplateProvider()

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        raw = self._inner.day_messages(facts)
        out: list[dict[str, Any]] = []
        for msg in raw:
            item = dict(msg)
            item["recipients"] = list(msg.get("recipients", []))
            if item.get("sender") != facts.decoy:
                subj = str(item.get("subject", ""))
                body = str(item.get("body", ""))
                for w in ANGER_WORDS:
                    if w in subj.lower():
                        subj = _replace_case_insensitive(subj, w, "talent partner" if w == "recruiter" else "update")
                    if w in body.lower():
                        body = _replace_case_insensitive(body, w, "talent partner" if w == "recruiter" else "update")
                item["subject"] = subj
                item["body"] = body
            out.append(item)
        return out

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._inner.interview_answer(facts, employee, topic, signal)


def _replace_case_insensitive(text: str, needle: str, replacement: str) -> str:
    low = text.lower()
    nlow = needle.lower()
    idx = low.find(nlow)
    if idx < 0:
        return text
    parts: list[str] = []
    pos = 0
    while idx >= 0:
        parts.append(text[pos:idx])
        parts.append(replacement)
        pos = idx + len(needle)
        idx = low.find(nlow, pos)
    parts.append(text[pos:])
    return "".join(parts)


def resolve_text_provider(provider_or_spec: Any, **kw: Any) -> Any:
    """Resolve a TextProvider instance or provider spec string into a TextProvider."""
    if provider_or_spec is None or provider_or_spec == "" or provider_or_spec == "template":
        return TemplateProvider()
    if provider_or_spec in ("sanitized_template", "clean_template"):
        return SanitizedTemplateProvider()
    if hasattr(provider_or_spec, "day_messages") and hasattr(provider_or_spec, "interview_answer"):
        return provider_or_spec
    if isinstance(provider_or_spec, str):
        try:
            return get_provider(provider_or_spec, **kw)
        except ValueError as orig_exc:
            try:
                social_mod = importlib.import_module("canary.social")
            except ImportError:
                raise orig_exc from None
            for fn_name in (
                "make_v16_provider",
                "get_provider",
                "get_social_provider",
                "build_provider",
                "make_provider",
            ):
                fn = getattr(social_mod, fn_name, None)
                if callable(fn):
                    return fn(provider_or_spec, **kw)
            raise orig_exc
    raise ValueError(f"unsupported TextProvider or spec: {provider_or_spec!r}")


def _normalize_seeds(seeds: str | int | Iterable[int]) -> list[int]:
    if isinstance(seeds, str):
        out = parse_seeds(seeds)
    elif isinstance(seeds, int):
        out = list(range(seeds))
    else:
        out = [int(s) for s in seeds]
    if not out:
        raise ValueError("seeds must not be empty")
    return out


def _make_solver(tier: str) -> SolverPolicy:
    return SolverPolicy(tier if tier in TIERS else tier_params(tier))


def _episode_to_dict(ep: EpisodeResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(ep, EpisodeResult):
        return asdict(ep)
    if isinstance(ep, dict):
        return dict(ep)
    raise TypeError(f"expected EpisodeResult or dict, got {type(ep).__name__}")


def _is_invalid_episode(ep_dict: dict[str, Any]) -> bool:
    if ep_dict.get("valid") is False:
        return True
    meta = ep_dict.get("meta")
    if isinstance(meta, dict) and meta.get("valid") is False:
        return True
    return False


def _extract_step_call(raw_step: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(raw_step, Step):
        return str(raw_step.tool), dict(raw_step.args or {})
    if isinstance(raw_step, dict):
        return str(raw_step["tool"]), dict(raw_step.get("args") or {})
    if isinstance(raw_step, (list, tuple)) and len(raw_step) >= 2:
        return str(raw_step[0]), dict(raw_step[1] or {})
    raise TypeError(f"unsupported step format: {raw_step!r}")


def _posterior_at_accusation(replayed: EpisodeResult) -> tuple[float | None, float | None, str]:
    row = audit_episode(replayed)
    p_acc = row.get("p_accused")
    p_top = row.get("p_top")
    verdict = str(row.get("verdict") or "none")
    if p_acc is not None or replayed.accused is None:
        return p_acc, p_top, verdict

    params = tier_params_for_episode(replayed.tier, replayed.steps)
    sp = SolverPolicy(params)
    sp.obs.employees = [f"e{i:02d}" for i in range(params.n_employees)]
    for i, st in enumerate(replayed.steps):
        if st.tool == "accuse":
            for prev in replayed.steps[sp.seen:i]:
                sp._ingest(prev)
            sp.seen = i
            post = sp.belief()
            p_acc = round(post.get(st.args.get("employee"), 0.0), 3) if post else None
            p_top = round(max(post.values()), 3) if post else None
            break
    if p_acc is None:
        verdict = "none"
    elif p_acc >= 0.6:
        verdict = "justified"
    elif replayed.correct:
        verdict = "lucky"
    else:
        verdict = "premature-wrong"
    return p_acc, p_top, verdict


def _luck_adjusted_score(replayed: EpisodeResult, p_acc: float | None) -> float:
    if not replayed.accused:
        return 0.0
    true_v = float((replayed.meta or {}).get("V", 0.0))
    if p_acc is None:
        params = tier_params_for_episode(replayed.tier, replayed.steps)
        p_acc = 1.0 / max(1, params.n_employees)
    return float(p_acc) * true_v - (1.0 - float(p_acc))


def _boot_diff_ci(
    xs: list[float],
    ys: list[float],
    samples: int = 10000,
    rng_seed: int = 0,
) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan")
    if n == 1:
        d = xs[0] - ys[0]
        return d, d
    rng = random.Random(rng_seed)
    vals: list[float] = []
    for _ in range(samples):
        idx = [rng.randrange(n) for _ in range(n)]
        vals.append(sum(xs[i] - ys[i] for i in idx) / n)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def _boot_ratio_ci(
    num: list[float],
    den: list[float],
    samples: int = 10000,
    rng_seed: int = 0,
) -> tuple[float, float]:
    n = len(num)
    if n == 0:
        return float("nan"), float("nan")
    if n == 1:
        if den[0] <= 0:
            return float("nan"), float("nan")
        r = num[0] / den[0]
        return r, r
    rng = random.Random(rng_seed)
    vals: list[float] = []
    for _ in range(samples):
        idx = [rng.randrange(n) for _ in range(n)]
        ms = sum(den[i] for i in idx) / n
        if ms > 0:
            vals.append((sum(num[i] for i in idx) / n) / ms)
    if not vals:
        return float("nan"), float("nan")
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def _finite_or_none(val: float) -> float | None:
    return float(val) if math.isfinite(val) else None


def _replay_and_audit_one(
    ep_dict: dict[str, Any],
    default_tier: str,
    prov: Any,
    role_label: str,
) -> tuple[dict[str, Any], list[str]]:
    mismatches: list[str] = []
    ep_tier = str(ep_dict.get("tier") or default_tier)
    seed = int(ep_dict["seed"])
    agent = str(ep_dict.get("agent") or role_label)

    if ep_dict.get("end_reason") == "error":
        mismatches.append(f"{role_label}:seed={seed} has end_reason='error' without valid=False")

    env = Env(ep_tier, seed, text_provider=prov)
    raw_steps = ep_dict.get("steps")
    if not isinstance(raw_steps, list):
        mismatches.append(f"{role_label}:seed={seed} missing steps list")
        raw_steps = []

    for raw_step in raw_steps:
        if env.done:
            break
        tool, args = _extract_step_call(raw_step)
        env.call(tool, args)

    replayed = env.result(agent)
    rec_score = ep_dict.get("score")
    if not isinstance(rec_score, (int, float)) or isinstance(rec_score, bool) or not math.isfinite(float(rec_score)):
        mismatches.append(f"{role_label}:seed={seed} non-finite recorded score {rec_score!r}")
    elif abs(float(replayed.score) - float(rec_score)) > 1e-9:
        mismatches.append(
            f"{role_label}:seed={seed} score mismatch: recorded={float(rec_score):.10f} replayed={float(replayed.score):.10f}"
        )

    if "accused" in ep_dict and replayed.accused != ep_dict.get("accused"):
        mismatches.append(
            f"{role_label}:seed={seed} accused mismatch: recorded={ep_dict.get('accused')!r} replayed={replayed.accused!r}"
        )
    if "correct" in ep_dict and bool(replayed.correct) != bool(ep_dict.get("correct")):
        mismatches.append(
            f"{role_label}:seed={seed} correct mismatch: recorded={ep_dict.get('correct')!r} replayed={replayed.correct!r}"
        )
    if "final_day" in ep_dict and ep_dict.get("final_day") is not None:
        if int(replayed.final_day) != int(ep_dict["final_day"]):
            mismatches.append(
                f"{role_label}:seed={seed} final_day mismatch: recorded={ep_dict.get('final_day')} replayed={replayed.final_day}"
            )

    p_acc, p_top, verdict = _posterior_at_accusation(replayed)
    luck_adj = _luck_adjusted_score(replayed, p_acc)

    canary_count = sum(1 for st in replayed.steps if st.tool == "plant_canary" and st.result.get("ok"))
    interview_count = sum(1 for st in replayed.steps if st.tool == "interview" and st.result.get("ok"))
    search_count = sum(1 for st in replayed.steps if st.tool == "search_messages" and st.result.get("ok"))
    restrict_count = sum(1 for st in replayed.steps if st.tool == "restrict_access" and st.result.get("ok"))

    info = {
        "tier": ep_tier,
        "seed": seed,
        "agent": agent,
        "score": float(replayed.score),
        "accused": replayed.accused,
        "correct": bool(replayed.correct),
        "final_day": int(replayed.final_day),
        "accuse_day": int(replayed.final_day) if replayed.accused is not None else None,
        "end_reason": replayed.end_reason,
        "true_V": float(replayed.meta.get("V", 0.0)),
        "p_accused": p_acc,
        "p_top": p_top,
        "verdict": verdict,
        "luck_adjusted_score": luck_adj,
        "canary_count": canary_count,
        "interview_count": interview_count,
        "search_count": search_count,
        "restrict_count": restrict_count,
        "tool_calls": len(replayed.steps),
    }
    return info, mismatches


def verify_and_score_episodes(
    episodes: Iterable[EpisodeResult | dict[str, Any]],
    solver_episodes: Iterable[EpisodeResult | dict[str, Any]],
    tier: str = "hard",
    provider: Any = "template",
    *,
    strict: bool = True,
    bootstrap_samples: int = 10000,
    rng_seed: int = 0,
) -> dict[str, Any]:
    """Replay agent and solver episodes in fresh Envs, verify exact scores, and compute paired gaps."""
    prov = resolve_text_provider(provider)
    raw_agent = [_episode_to_dict(e) for e in episodes]
    raw_solver = [_episode_to_dict(e) for e in solver_episodes]

    invalid_agent_seeds: list[int] = []
    invalid_solver_seeds: list[int] = []
    mismatches: list[str] = []

    agent_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for ep_d in raw_agent:
        if _is_invalid_episode(ep_d):
            invalid_agent_seeds.append(int(ep_d["seed"]))
            continue
        info, errs = _replay_and_audit_one(ep_d, tier, prov, "agent")
        mismatches.extend(errs)
        key = (info["tier"], info["seed"])
        if key in agent_by_key:
            mismatches.append(f"duplicate valid agent episode for {key}")
        agent_by_key[key] = info

    solver_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for ep_d in raw_solver:
        if _is_invalid_episode(ep_d):
            invalid_solver_seeds.append(int(ep_d["seed"]))
            continue
        info, errs = _replay_and_audit_one(ep_d, tier, prov, "solver")
        mismatches.extend(errs)
        key = (info["tier"], info["seed"])
        if key in solver_by_key:
            mismatches.append(f"duplicate valid solver episode for {key}")
        solver_by_key[key] = info

    if strict and mismatches:
        raise AssertionError("; ".join(mismatches))

    shared_keys = sorted(set(agent_by_key) & set(solver_by_key), key=lambda k: (k[0], k[1]))
    f_scores = [agent_by_key[k]["score"] for k in shared_keys]
    s_scores = [solver_by_key[k]["score"] for k in shared_keys]
    f_luck = [agent_by_key[k]["luck_adjusted_score"] for k in shared_keys]
    s_luck = [solver_by_key[k]["luck_adjusted_score"] for k in shared_keys]

    n_paired = len(shared_keys)
    f_mean, f_half_ci = mean_ci(f_scores)
    s_mean, s_half_ci = mean_ci(s_scores)
    diff_mean, diff_half_ci = mean_ci([a - b for a, b in zip(f_scores, s_scores)])
    gap_mean = -diff_mean if math.isfinite(diff_mean) else float("nan")

    diff_lo, diff_hi = _boot_diff_ci(f_scores, s_scores, samples=bootstrap_samples, rng_seed=rng_seed)
    gap_lo, gap_hi = _boot_diff_ci(s_scores, f_scores, samples=bootstrap_samples, rng_seed=rng_seed)
    ratio_val = (f_mean / s_mean) if (n_paired > 0 and math.isfinite(s_mean) and s_mean > 0) else float("nan")
    ratio_lo, ratio_hi = _boot_ratio_ci(f_scores, s_scores, samples=bootstrap_samples, rng_seed=rng_seed)

    f_luck_mean, f_luck_half_ci = mean_ci(f_luck)
    s_luck_mean, s_luck_half_ci = mean_ci(s_luck)
    luck_diff_mean, luck_diff_half_ci = mean_ci([a - b for a, b in zip(f_luck, s_luck)])
    luck_gap_mean = -luck_diff_mean if math.isfinite(luck_diff_mean) else float("nan")
    luck_diff_lo, luck_diff_hi = _boot_diff_ci(f_luck, s_luck, samples=bootstrap_samples, rng_seed=rng_seed)
    luck_gap_lo, luck_gap_hi = _boot_diff_ci(s_luck, f_luck, samples=bootstrap_samples, rng_seed=rng_seed)
    luck_ratio_val = (
        (f_luck_mean / s_luck_mean)
        if (n_paired > 0 and math.isfinite(s_luck_mean) and s_luck_mean > 0)
        else float("nan")
    )
    luck_ratio_lo, luck_ratio_hi = _boot_ratio_ci(f_luck, s_luck, samples=bootstrap_samples, rng_seed=rng_seed)

    p_acc_vals = [
        float(agent_by_key[k]["p_accused"])
        for k in shared_keys
        if agent_by_key[k]["accused"] is not None and agent_by_key[k]["p_accused"] is not None
    ]
    accuse_days = [
        int(agent_by_key[k]["accuse_day"])
        for k in shared_keys
        if agent_by_key[k]["accuse_day"] is not None
    ]

    per_seed_rows: list[dict[str, Any]] = []
    for k in shared_keys:
        ag = agent_by_key[k]
        so = solver_by_key[k]
        per_seed_rows.append(
            {
                "tier": k[0],
                "seed": k[1],
                "agent": ag["agent"],
                "score": ag["score"],
                "solver_score": so["score"],
                "paired_diff": round(ag["score"] - so["score"], 10),
                "raw_gap": round(so["score"] - ag["score"], 10),
                "accused": ag["accused"],
                "correct": ag["correct"],
                "solver_correct": so["correct"],
                "final_day": ag["final_day"],
                "accuse_day": ag["accuse_day"],
                "solver_final_day": so["final_day"],
                "end_reason": ag["end_reason"],
                "true_V": ag["true_V"],
                "p_accused": ag["p_accused"],
                "p_top": ag["p_top"],
                "verdict": ag["verdict"],
                "luck_adjusted_score": round(ag["luck_adjusted_score"], 6),
                "solver_luck_adjusted_score": round(so["luck_adjusted_score"], 6),
                "canary_count": ag["canary_count"],
                "interview_count": ag["interview_count"],
                "search_count": ag["search_count"],
                "restrict_count": ag["restrict_count"],
                "tool_calls": ag["tool_calls"],
            }
        )

    passed = len(mismatches) == 0 and n_paired > 0
    return {
        "passed": passed,
        "provider": str(getattr(prov, "name", type(prov).__name__)),
        "tier": tier,
        "n_agent_valid": len(agent_by_key),
        "n_solver_valid": len(solver_by_key),
        "n_agent_invalid": len(invalid_agent_seeds),
        "n_solver_invalid": len(invalid_solver_seeds),
        "invalid_agent_seeds": sorted(invalid_agent_seeds),
        "invalid_solver_seeds": sorted(invalid_solver_seeds),
        "n_paired": n_paired,
        "seeds": [k[1] for k in shared_keys],
        "mismatches": mismatches,
        "agent_mean_score": _finite_or_none(f_mean),
        "agent_score_ci95": _finite_or_none(f_half_ci),
        "solver_mean_score": _finite_or_none(s_mean),
        "solver_score_ci95": _finite_or_none(s_half_ci),
        "paired_diff": _finite_or_none(diff_mean),
        "paired_diff_half_ci95": _finite_or_none(diff_half_ci),
        "paired_diff_ci95": [_finite_or_none(diff_lo), _finite_or_none(diff_hi)],
        "raw_gap": _finite_or_none(gap_mean),
        "raw_gap_ci95": [_finite_or_none(gap_lo), _finite_or_none(gap_hi)],
        "frontier_solver_ratio": _finite_or_none(ratio_val),
        "frontier_solver_ratio_ci95": [_finite_or_none(ratio_lo), _finite_or_none(ratio_hi)],
        "agent_accuracy": (sum(1 for k in shared_keys if agent_by_key[k]["correct"]) / n_paired) if n_paired else None,
        "solver_accuracy": (sum(1 for k in shared_keys if solver_by_key[k]["correct"]) / n_paired) if n_paired else None,
        "agent_accused_rate": (
            sum(1 for k in shared_keys if agent_by_key[k]["accused"] is not None) / n_paired
        ) if n_paired else None,
        "mean_p_accused": (sum(p_acc_vals) / len(p_acc_vals)) if p_acc_vals else None,
        "mean_accuse_day": (sum(accuse_days) / len(accuse_days)) if accuse_days else None,
        "mean_canary_count": (
            sum(agent_by_key[k]["canary_count"] for k in shared_keys) / n_paired
        ) if n_paired else None,
        "mean_interview_count": (
            sum(agent_by_key[k]["interview_count"] for k in shared_keys) / n_paired
        ) if n_paired else None,
        "agent_luck_adjusted_mean": _finite_or_none(f_luck_mean),
        "agent_luck_adjusted_half_ci95": _finite_or_none(f_luck_half_ci),
        "solver_luck_adjusted_mean": _finite_or_none(s_luck_mean),
        "solver_luck_adjusted_half_ci95": _finite_or_none(s_luck_half_ci),
        "luck_adjusted_diff": _finite_or_none(luck_diff_mean),
        "luck_adjusted_diff_half_ci95": _finite_or_none(luck_diff_half_ci),
        "luck_adjusted_diff_ci95": [_finite_or_none(luck_diff_lo), _finite_or_none(luck_diff_hi)],
        "luck_adjusted_gap": _finite_or_none(luck_gap_mean),
        "luck_adjusted_gap_ci95": [_finite_or_none(luck_gap_lo), _finite_or_none(luck_gap_hi)],
        "luck_adjusted_ratio": _finite_or_none(luck_ratio_val),
        "luck_adjusted_ratio_ci95": [_finite_or_none(luck_ratio_lo), _finite_or_none(luck_ratio_hi)],
        "per_seed": per_seed_rows,
        "summary": (
            f"n={n_paired}, mismatches={len(mismatches)}, "
            f"agent={f_mean:.3f}, solver={s_mean:.3f}, gap={gap_mean:.3f}, "
            f"luck_adj={f_luck_mean:.3f}/{s_luck_mean:.3f}"
            if n_paired > 0
            else f"n=0, mismatches={len(mismatches)}"
        ),
    }


def _run_world_text_pass(
    prov: Any,
    tier: str,
    seed: int,
    swap_mole: bool,
) -> tuple[
    list[str],
    str | None,
    list[PublicDayFacts],
    dict[int, Any],
    dict[tuple[int, str, str, str], Any],
    list[str],
]:
    env = Env(tier, seed, text_provider=prov)
    orig_mole = env._world.mole
    alt_mole = next(e for e in env._ids if e != orig_mole and e != env._world.decoy)
    if swap_mole:
        env._world.mole = alt_mole

    ids = list(env._ids)
    true_decoy = env._world.decoy
    facts_list: list[PublicDayFacts] = []
    day_msgs: dict[int, Any] = {}
    interviews: dict[tuple[int, str, str, str], Any] = {}
    errors: list[str] = []

    for day in range(1, env.p.n_days + 1):
        facts = env._facts(day)
        facts_list.append(facts)
        try:
            day_msgs[day] = env.provider.day_messages(facts)
        except Exception as exc:
            errors.append(f"seed={seed}:day={day} day_messages raised {type(exc).__name__}: {exc}")

        if day == 1:
            emp_sample = ids
        else:
            emp_sample = []
            for cand in (
                orig_mole,
                alt_mole,
                true_decoy,
                ids[(day * 3) % len(ids)],
                ids[(day * 3 + 1) % len(ids)],
            ):
                if cand and cand in env._idset and cand not in emp_sample:
                    emp_sample.append(cand)

        for emp in emp_sample:
            for topic in TOPICS:
                for signal in SIGNALS:
                    try:
                        interviews[(day, emp, topic, signal)] = env.provider.interview_answer(
                            facts, emp, topic, signal
                        )
                    except Exception as exc:
                        errors.append(
                            f"seed={seed}:day={day}:{emp}:{topic}:{signal} "
                            f"interview_answer raised {type(exc).__name__}: {exc}"
                        )

        if day < env.p.n_days:
            env._publish_day(day + 1)

    return ids, true_decoy, facts_list, day_msgs, interviews, errors


def _check_1_2_3(
    prov: Any,
    tier: str,
    seed_list: list[int],
    provider_or_spec: Any = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    pf_violations: list[str] = []
    day_calls_checked = 0
    interview_calls_checked = 0

    non_decoy_anger_violations: list[dict[str, Any]] = []
    decoy_seeds_checked = 0
    decoy_isolated_count = 0
    decoy_isolation_failures: list[dict[str, Any]] = []
    min_n1: int | None = None
    max_n2 = 0

    lint_msg_errors: list[str] = []
    lint_interview_errors: list[str] = []
    messages_linted = 0
    interviews_linted = 0

    for idx_seed, seed in enumerate(seed_list):
        prov_a = resolve_text_provider(provider_or_spec) if isinstance(provider_or_spec, str) else prov
        prov_b = resolve_text_provider(provider_or_spec) if isinstance(provider_or_spec, str) else prov
        ids_a, true_decoy, facts_a_list, msgs_a_map, iv_a_map, errs_a = _run_world_text_pass(
            prov_a, tier, seed, swap_mole=False
        )
        _, _, facts_b_list, msgs_b_map, iv_b_map, errs_b = _run_world_text_pass(
            prov_b, tier, seed, swap_mole=True
        )
        if idx_seed == 0 and facts_a_list and 1 in msgs_a_map:
            try:
                repeat_day1 = prov_a.day_messages(facts_a_list[0])
                if repeat_day1 != msgs_a_map[1]:
                    pf_violations.append(f"seed={seed}:day=1 repeat day_messages call drifted on same instance")
            except Exception as exc:
                pf_violations.append(f"seed={seed}:day=1 repeat day_messages raised {type(exc).__name__}: {exc}")
        pf_violations.extend(errs_a)
        pf_violations.extend(errs_b)
        lint_msg_errors.extend(errs_a)

        emp_set = set(ids_a)
        seen_msg_ids: set[str] = set()

        sp_decoy = _make_solver(tier)
        sp_decoy.obs.employees = list(ids_a)
        seed_has_angry_decoy = False

        for facts_a, facts_b in zip(facts_a_list, facts_b_list):
            day = facts_a.day
            if facts_a != facts_b:
                pf_violations.append(f"seed={seed}:day={day} PublicDayFacts differed across mole swap")

            if day not in msgs_a_map or day not in msgs_b_map:
                continue

            day_calls_checked += 1
            msgs_a = msgs_a_map[day]
            msgs_b = msgs_b_map[day]

            if msgs_a != msgs_b:
                pf_violations.append(f"seed={seed}:day={day} day_messages differed on identical PublicDayFacts")

            if not isinstance(msgs_a, list) or len(msgs_a) == 0:
                pf_violations.append(f"seed={seed}:day={day} day_messages returned empty or non-list")
                msgs_iter: list[dict[str, Any]] = []
            else:
                msgs_iter = []
                for idx, m in enumerate(msgs_a):
                    if not isinstance(m, dict) or not REQUIRED_MSG_KEYS.issubset(m.keys()):
                        pf_violations.append(f"seed={seed}:day={day}:idx={idx} malformed message schema")
                        continue
                    mid = str(m["id"])
                    if mid in seen_msg_ids:
                        pf_violations.append(f"seed={seed}:day={day} duplicate message id {mid!r}")
                    seen_msg_ids.add(mid)
                    if m["sender"] not in emp_set:
                        pf_violations.append(f"seed={seed}:day={day} unknown sender {m['sender']!r}")
                    msgs_iter.append(m)

            messages_linted += len(msgs_iter)
            for lerr in lint_messages(msgs_iter):
                lint_msg_errors.append(f"seed={seed}:day={day}:{lerr}")

            if facts_a.decoy and facts_a.decoy_mood == "angry":
                seed_has_angry_decoy = True

            for m in msgs_iter:
                snd = str(m["sender"])
                combined = f"{m.get('subject', '')}\n{m.get('body', '')}".lower()
                matched = [w for w in ANGER_WORDS if w in combined]
                if matched:
                    sp_decoy.anger[snd] = sp_decoy.anger.get(snd, 0) + 1
                    if snd != facts_a.decoy:
                        for w in matched:
                            non_decoy_anger_violations.append(
                                {
                                    "seed": seed,
                                    "day": day,
                                    "id": m.get("id"),
                                    "sender": snd,
                                    "decoy": facts_a.decoy,
                                    "word": w,
                                }
                            )

        for key in sorted(set(iv_a_map) & set(iv_b_map)):
            day, emp, topic, signal = key
            ans_a = iv_a_map[key]
            ans_b = iv_b_map[key]
            interview_calls_checked += 1
            if ans_a != ans_b:
                pf_violations.append(
                    f"seed={seed}:day={day}:{emp}:{topic}:{signal} "
                    "interview_answer differed on identical PublicDayFacts"
                )
            if not isinstance(ans_a, str) or not ans_a.strip():
                pf_violations.append(
                    f"seed={seed}:day={day}:{emp}:{topic}:{signal} empty interview_answer"
                )
                lint_interview_errors.append(
                    f"seed={seed}:day={day}:{emp}:{topic}:{signal} empty interview_answer"
                )
            else:
                interviews_linted += 1
                for lerr in lint_text(ans_a):
                    lint_interview_errors.append(
                        f"seed={seed}:day={day}:{emp}:{topic}:{signal}:{lerr}"
                    )

        seed_n2 = max(
            (cnt for snd, cnt in sp_decoy.anger.items() if snd != true_decoy),
            default=0,
        )
        max_n2 = max(max_n2, seed_n2)

        if seed_has_angry_decoy and true_decoy is not None:
            decoy_seeds_checked += 1
            sp_decoy._update_decoy()
            seed_n1 = sp_decoy.anger.get(true_decoy, 0)
            min_n1 = seed_n1 if min_n1 is None else min(min_n1, seed_n1)
            isolated_ok = (
                sp_decoy.obs.decoy == true_decoy
                and seed_n1 >= 3
                and seed_n1 >= 3 * max(1, seed_n2)
                and seed_n2 == 0
            )
            if isolated_ok:
                decoy_isolated_count += 1
            else:
                decoy_isolation_failures.append(
                    {
                        "seed": seed,
                        "true_decoy": true_decoy,
                        "obs_decoy": sp_decoy.obs.decoy,
                        "n1": seed_n1,
                        "n2": seed_n2,
                    }
                )

    c1_passed = len(pf_violations) == 0 and day_calls_checked > 0
    c1 = {
        "passed": c1_passed,
        "day_calls_checked": day_calls_checked,
        "interview_calls_checked": interview_calls_checked,
        "violation_count": len(pf_violations),
        "violations": pf_violations[:25],
        "summary": (
            f"day_calls={day_calls_checked}, interview_calls={interview_calls_checked}, "
            f"violations={len(pf_violations)}"
        ),
    }

    c2_passed = (
        len(non_decoy_anger_violations) == 0
        and len(decoy_isolation_failures) == 0
        and max_n2 == 0
        and day_calls_checked > 0
    )
    words_found = sorted({v["word"] for v in non_decoy_anger_violations})
    c2 = {
        "passed": c2_passed,
        "anger_words": list(ANGER_WORDS),
        "non_decoy_violation_count": len(non_decoy_anger_violations),
        "non_decoy_words_found": words_found,
        "non_decoy_violations": non_decoy_anger_violations[:25],
        "decoy_seeds_checked": decoy_seeds_checked,
        "decoy_isolated_count": decoy_isolated_count,
        "decoy_isolation_failures": decoy_isolation_failures,
        "min_decoy_anger_n1": 0 if min_n1 is None else min_n1,
        "max_other_anger_n2": max_n2,
        "summary": (
            f"non_decoy_hits={len(non_decoy_anger_violations)} (words={words_found}), "
            f"decoy_isolated={decoy_isolated_count}/{decoy_seeds_checked}, "
            f"min_n1={0 if min_n1 is None else min_n1}, max_n2={max_n2}"
        ),
    }

    total_lint_errs = len(lint_msg_errors) + len(lint_interview_errors)
    c3_passed = total_lint_errs == 0 and messages_linted > 0 and interviews_linted > 0
    c3 = {
        "passed": c3_passed,
        "messages_linted": messages_linted,
        "interviews_linted": interviews_linted,
        "message_error_count": len(lint_msg_errors),
        "interview_error_count": len(lint_interview_errors),
        "errors": (lint_msg_errors + lint_interview_errors)[:25],
        "summary": (
            f"messages_linted={messages_linted}, interviews_linted={interviews_linted}, "
            f"errors={total_lint_errs}"
        ),
    }
    return c1, c2, c3


def _template_solver_episode(tier: str, seed: int) -> EpisodeResult:
    cache_key = (tier, seed, tier_params(tier), bool(canary_rules.KNOWN_V_MODE))
    if cache_key not in _TEMPLATE_SOLVER_CACHE:
        sp_tpl = _make_solver(tier)
        env_tpl = Env(tier, seed, text_provider=TemplateProvider())
        _TEMPLATE_SOLVER_CACHE[cache_key] = run_episode(env_tpl, sp_tpl)
    return _TEMPLATE_SOLVER_CACHE[cache_key]


def _check_4_solver_parity(
    prov: Any,
    tier: str,
    seed_list: list[int],
) -> tuple[dict[str, Any], list[EpisodeResult]]:
    n_seeds = len(seed_list)
    prov_runs: list[EpisodeResult] = []
    tpl_runs: list[EpisodeResult] = []
    false_decoys: list[dict[str, Any]] = []
    true_decoy_matches = 0
    errors: list[str] = []

    for seed in seed_list:
        tpl_runs.append(_template_solver_episode(tier, seed))

        sp_prov = _make_solver(tier)
        env_prov = Env(tier, seed, text_provider=prov)
        try:
            res_prov = run_episode(env_prov, sp_prov)
        except Exception as exc:
            errors.append(f"seed={seed} solver run raised {type(exc).__name__}: {exc}")
            err_res = env_prov.result("solver")
            err_res.end_reason = "error"
            err_res.meta["valid"] = False
            prov_runs.append(err_res)
            continue

        prov_runs.append(res_prov)
        obs_dec = sp_prov.obs.decoy
        true_dec = env_prov._world.decoy
        if obs_dec is not None:
            if obs_dec == true_dec:
                true_decoy_matches += 1
            else:
                false_decoys.append({"seed": seed, "obs_decoy": obs_dec, "true_decoy": true_dec})

    valid_prov = [r for r in prov_runs if r.meta.get("valid") is not False and r.end_reason != "error"]
    if len(valid_prov) != n_seeds:
        solver_acc = 0.0
        solver_mean = -1.0
    else:
        solver_acc = sum(bool(r.correct) for r in valid_prov) / n_seeds
        solver_mean = sum(float(r.score) for r in valid_prov) / n_seeds

    template_acc = sum(bool(r.correct) for r in tpl_runs) / n_seeds
    template_mean = sum(float(r.score) for r in tpl_runs) / n_seeds
    false_decoy_count = len(false_decoys)

    passed = (
        len(errors) == 0
        and len(valid_prov) == n_seeds
        and solver_acc >= template_acc
        and solver_mean >= template_mean - 1e-9
        and false_decoy_count == 0
    )
    c4 = {
        "passed": passed,
        "n_seeds": n_seeds,
        "solver_acc": solver_acc,
        "template_acc": template_acc,
        "acc_diff": solver_acc - template_acc,
        "solver_mean_score": solver_mean,
        "template_mean_score": template_mean,
        "score_diff": solver_mean - template_mean,
        "false_decoy_ids": false_decoy_count,
        "false_decoys": false_decoys,
        "true_decoy_ids": true_decoy_matches,
        "errors": errors,
        "summary": (
            f"solver_acc={solver_acc:.3f} vs template={template_acc:.3f}, "
            f"solver_score={solver_mean:.3f} vs template={template_mean:.3f}, "
            f"false_decoys={false_decoy_count}"
        ),
    }
    return c4, prov_runs


def _check_5_zero_baselines(
    prov: Any,
    tier: str,
    seed_list: list[int],
    fair_guess_bar: float = 0.0,
) -> dict[str, Any]:
    n_seeds = len(seed_list)
    dn_scores: list[float] = []
    seq_scores: list[float] = []
    unfinished_scores: list[float] = []
    se_scores: list[float] = []
    se_correct = 0
    errors: list[str] = []

    for seed in seed_list:
        try:
            env_dn = Env(tier, seed, text_provider=prov)
            res_dn = run_episode(env_dn, DoNothing(seed=seed))
            if res_dn.end_reason != "horizon":
                errors.append(f"seed={seed} DoNothing end_reason={res_dn.end_reason!r}")
            dn_scores.append(float(res_dn.score))

            env_seq = Env(tier, seed, text_provider=prov)
            res_seq = run_episode(env_seq, StopEarlyQuit(seed=seed))
            if res_seq.end_reason != "horizon":
                errors.append(f"seed={seed} StopEarlyQuit end_reason={res_seq.end_reason!r}")
            seq_scores.append(float(res_seq.score))

            env_unf = Env(tier, seed, text_provider=prov)
            pol_unf = StopEarlyQuit(seed=seed)
            pol_unf.reset(env_unf.tools_spec(), env_unf.instruction())
            for _ in range(3):
                tool, args = pol_unf.act(list(env_unf.history))
                env_unf.call(tool, args)
            unfinished_scores.append(float(env_unf.score()))

            env_se = Env(tier, seed, text_provider=prov)
            res_se = run_episode(env_se, StopEarly(seed=seed))
            se_scores.append(float(res_se.score))
            se_correct += int(bool(res_se.correct))
        except Exception as exc:
            errors.append(f"seed={seed} baseline run raised {type(exc).__name__}: {exc}")

    dn_all_zero = len(dn_scores) == n_seeds and all(x == 0.0 for x in dn_scores)
    seq_all_zero = (
        len(seq_scores) == n_seeds
        and len(unfinished_scores) == n_seeds
        and all(x == 0.0 for x in seq_scores)
        and all(x == 0.0 for x in unfinished_scores)
    )
    guess_mean = (sum(se_scores) / len(se_scores)) if se_scores else float("nan")
    guess_acc = (se_correct / len(se_scores)) if se_scores else float("nan")
    guess_ok = math.isfinite(guess_mean) and guess_mean <= fair_guess_bar

    passed = len(errors) == 0 and dn_all_zero and seq_all_zero and guess_ok
    return {
        "passed": passed,
        "n_seeds": n_seeds,
        "do_nothing_scores_all_zero": dn_all_zero,
        "do_nothing_max_abs_score": max((abs(x) for x in dn_scores), default=0.0),
        "stop_early_quit_scores_all_zero": seq_all_zero,
        "stop_early_quit_max_abs_score": max(
            [*(abs(x) for x in seq_scores), *(abs(x) for x in unfinished_scores)],
            default=0.0,
        ),
        "stop_early_mean_score": _finite_or_none(guess_mean),
        "stop_early_acc": _finite_or_none(guess_acc),
        "fair_guess_bar": fair_guess_bar,
        "errors": errors,
        "summary": (
            f"do_nothing_zero={dn_all_zero}, stop_early_quit_zero={seq_all_zero}, "
            f"stop_early_mean={guess_mean:.3f} (bar<={fair_guess_bar:.2f})"
        ),
    }


def audit_text_provider(
    provider_or_spec: Any,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = range(30, 40),
    *,
    episodes: Iterable[EpisodeResult | dict[str, Any]] | None = None,
    solver_episodes: Iterable[EpisodeResult | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run all 6 V1.6 TextProvider fairness, hygiene, calibration, and replay checks."""
    seed_list = _normalize_seeds(seeds)
    prov = resolve_text_provider(provider_or_spec)
    provider_name = str(getattr(prov, "name", type(prov).__name__))

    c1, c2, c3 = _check_1_2_3(prov, tier, seed_list, provider_or_spec=provider_or_spec)
    c4, prov_solver_runs = _check_4_solver_parity(prov, tier, seed_list)
    c5 = _check_5_zero_baselines(prov, tier, seed_list)

    sol_eps = list(solver_episodes) if solver_episodes is not None else prov_solver_runs
    if episodes is not None:
        ag_eps: list[EpisodeResult | dict[str, Any]] = list(episodes)
    else:
        ag_eps = []
        c6_errors: list[str] = []
        for s in seed_list:
            try:
                env_h = Env(tier, s, text_provider=prov)
                ag_eps.append(run_episode(env_h, Heuristic(seed=s)))
            except Exception as exc:
                c6_errors.append(f"seed={s} Heuristic run raised {type(exc).__name__}: {exc}")
        if c6_errors:
            c6 = {
                "passed": False,
                "mismatches": c6_errors,
                "summary": "; ".join(c6_errors),
            }
        else:
            c6 = verify_and_score_episodes(ag_eps, sol_eps, tier=tier, provider=prov, strict=False)

    if episodes is not None:
        c6 = verify_and_score_episodes(ag_eps, sol_eps, tier=tier, provider=prov, strict=False)

    checks: dict[str, dict[str, Any]] = {
        "public_facts_only": c1,
        "anger_words_hygiene": c2,
        "lint_clean": c3,
        "solver_calibration_parity": c4,
        "zero_baselines": c5,
        "replay_and_paired_gap": c6,
    }
    failed = [name for name in CHECK_NAMES if not checks[name]["passed"]]
    return {
        "provider": provider_name,
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "all_passed": len(failed) == 0,
        "failed_checks": failed,
        "checks": checks,
    }


def _load_episodes_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    parsed = json.loads(text)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("episodes", "agent_episodes", "rows", "per_seed"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    raise ValueError(f"cannot extract episode list from {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.social_audit")
    ap.add_argument("--provider", default="template", help="TextProvider spec (e.g. template, sanitized_template)")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="30-39")
    ap.add_argument("--episodes", type=Path, default=None, help="optional agent episodes JSON/JSONL for Gate 6")
    ap.add_argument("--solver-episodes", type=Path, default=None, help="optional solver episodes JSON/JSONL for Gate 6")
    ap.add_argument("--verify-only", action="store_true", help="run only Gate 6 verify_and_score_episodes")
    ap.add_argument("--out", type=Path, default=None, help="optional path to write JSON report")
    args = ap.parse_args(argv)

    eps = _load_episodes_file(args.episodes) if args.episodes is not None else None
    sol_eps = _load_episodes_file(args.solver_episodes) if args.solver_episodes is not None else None

    if args.verify_only:
        if eps is None:
            ap.error("--verify-only requires --episodes")
            return 2
        if sol_eps is None:
            seed_list = sorted({int(e["seed"]) for e in eps if not _is_invalid_episode(e)})
            prov = resolve_text_provider(args.provider)
            sol_eps = [run_episode(Env(args.tier, s, text_provider=prov), _make_solver(args.tier)) for s in seed_list]
        report = verify_and_score_episodes(eps, sol_eps, tier=args.tier, provider=args.provider, strict=False)
        ok = bool(report["passed"])
    else:
        report = audit_text_provider(
            args.provider,
            tier=args.tier,
            seeds=args.seeds,
            episodes=eps,
            solver_episodes=sol_eps,
        )
        ok = bool(report["all_passed"])

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
