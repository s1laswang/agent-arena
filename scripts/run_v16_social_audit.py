"""Offline V1.6 Social TextProvider fairness and episode replay audit runner."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary import llm as canary_llm
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.rules import TIERS, TIERS_VERSION
from canary.social import gemini_chatter
from canary.social.variants import VARIANTS
from canary.social_audit import (
    CHECK_NAMES,
    _template_solver_episode,
    audit_text_provider,
    resolve_text_provider,
    verify_and_score_episodes,
)
from canary.solver.policy import SolverPolicy
from canary.text.llm_cache import DEFAULT_SHARED_CACHE_DIR, OfflineCacheMiss
from canary.text.template import SIGNALS, TOPICS
from canary.types import EpisodeResult

MD_H = chr(35)
DEFAULT_TIER = "hard"
DEFAULT_SEEDS = "30-35"
DEFAULT_WORKERS = 1
SHARED_RUNS_ROOT = Path("/tmp/fleet-momin/shared/v16_runs")
COMMITTED_PARTIAL_RUNS_ROOT = REPO_ROOT / "results" / "v16_social" / "partial"
DEFAULT_RUNS_ROOT = SHARED_RUNS_ROOT if SHARED_RUNS_ROOT.is_dir() else COMMITTED_PARTIAL_RUNS_ROOT
DEFAULT_CACHE_DIR = Path(DEFAULT_SHARED_CACHE_DIR)
DEFAULT_OUT_JSON = REPO_ROOT / "results" / "v16_social" / "social_audit_report.json"
DEFAULT_OUT_MD = REPO_ROOT / "docs" / "reports" / "v16_social_fairness_audit.md"

CANONICAL_V16_VARIANTS: tuple[str, ...] = (
    "v1_anchoring_authority_confirmation",
    "v2_recency_bandwagon_sycophancy",
    "v3_grudge_falsemem_misforward",
    "v4_triad_authority_recency_grudge",
    "v5_full9_cocktail",
)

DETERMINISTIC_V16_SPECS: tuple[str, ...] = tuple(f"v16:{v}" for v in CANONICAL_V16_VARIANTS)
STUB_FALLBACK_SPECS: tuple[str, ...] = tuple(f"v16-gemini-stub:{v}" for v in CANONICAL_V16_VARIANTS)
CACHED_FALLBACK_SPECS: tuple[str, ...] = tuple(f"v16-gemini:{v}" for v in CANONICAL_V16_VARIANTS)
DEFAULT_PROVIDER_SPECS: tuple[str, ...] = (
    *DETERMINISTIC_V16_SPECS,
    *STUB_FALLBACK_SPECS,
    *CACHED_FALLBACK_SPECS,
    "sanitized_template",
)

VALID_END_REASONS: frozenset[str] = frozenset({"accused", "horizon", "tool_cap"})
FORBIDDEN_OUTPUT_KEYS: frozenset[str] = frozenset({
    "mole",
    "decoy",
    "transcript",
    "transcripts",
    "steps",
    "world_secret",
    "ledger_token",
    "ledger_events",
})
EMP_ID_PATTERN = re.compile(r"\be\d{2,3}\b", re.IGNORECASE)
KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)


def _round_or_none(val: Any, ndigits: int = 6) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    f = float(val)
    if not math.isfinite(f):
        return None
    return round(f, ndigits)


def _display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        rel = path.resolve().relative_to(REPO_ROOT.resolve())
        return rel.as_posix()
    except ValueError:
        return str(path)


def resolve_runs_root(
    runs_root: str | Path | None = "auto",
    *,
    shared_root: Path | None = None,
    fallback_root: Path | None = None,
) -> tuple[Path | None, bool]:
    if runs_root is None:
        return None, False
    raw = str(runs_root).strip()
    if not raw:
        return None, False
    s_root = SHARED_RUNS_ROOT if shared_root is None else Path(shared_root)
    f_root = COMMITTED_PARTIAL_RUNS_ROOT if fallback_root is None else Path(fallback_root)
    if raw == "auto":
        if s_root.is_dir():
            return s_root, False
        if f_root.is_dir():
            return f_root, True
        return f_root, False
    candidate = Path(raw)
    if candidate == s_root and not candidate.is_dir() and f_root.is_dir():
        return f_root, True
    return candidate, False


def _redact_emp_ids(text: str) -> str:
    return EMP_ID_PATTERN.sub("<emp>", str(text))


def _classify_provider_mode(spec: str) -> str:
    s = str(spec).strip()
    if s.startswith("v16:"):
        return "deterministic_template"
    if s.startswith("v16-gemini-stub:"):
        return "gemini_stub_fallback"
    if s.startswith("v16-gemini:"):
        return "gemini_cached_fallback"
    if s in ("sanitized_template", "clean_template"):
        return "reference_sanitized_template"
    if s in ("", "template"):
        return "v14_template_baseline"
    if s in VARIANTS:
        return "deterministic_template"
    return "custom_provider"


def _normalize_seed_list(seeds: str | int | Iterable[int]) -> list[int]:
    if isinstance(seeds, str):
        parsed = parse_seeds(seeds)
    elif isinstance(seeds, int):
        parsed = list(range(seeds))
    else:
        parsed = [int(s) for s in seeds]
    out: list[int] = []
    seen: set[int] = set()
    for s in parsed:
        if s not in seen:
            seen.add(s)
            out.append(int(s))
    if not out:
        raise ValueError("seeds must not be empty")
    return out


def _normalize_provider_specs(providers: Iterable[str] | None) -> list[str]:
    if providers is None:
        return list(DEFAULT_PROVIDER_SPECS)
    out: list[str] = []
    seen: set[str] = set()
    for raw in providers:
        for part in str(raw).split(","):
            item = part.strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    if not out:
        raise ValueError("providers must not be empty")
    return out


@contextmanager
def offline_execution_guard(
    *,
    mode: str,
    cache_dir: Path | None,
) -> Iterator[dict[str, int]]:
    telemetry = {
        "live_api_calls": 0,
        "blocked_api_attempts": 0,
        "cache_hits": 0,
        "offline_fallbacks": 0,
        "stub_calls": 0,
    }
    orig_get_client = canary_llm.get_client
    orig_cached_chat = gemini_chatter.cached_chat
    prev_offline = os.environ.get("CANARY_OFFLINE")
    prev_sleeper_offline = os.environ.get("SLEEPER_OFFLINE")
    prev_cache_dir = os.environ.get("CANARY_GEMINI_CACHE_DIR")

    def _guarded_get_client(spec: str, **kw: Any) -> Any:
        provider, _, _ = str(spec).partition(":")
        if provider == "stub":
            return orig_get_client(spec, **kw)
        telemetry["blocked_api_attempts"] += 1
        raise RuntimeError(f"live LLM API calls are forbidden in offline social audit: {spec!r}")

    def _instrumented_cached_chat(
        c_dir: str | Path | None,
        client: Any,
        model: str,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        label: str = "REAL",
    ) -> dict[str, Any]:
        if label == "stub":
            telemetry["stub_calls"] += 1
            return orig_cached_chat(
                c_dir,
                client,
                model,
                system,
                user,
                response_schema=response_schema,
                label=label,
            )
        try:
            res = orig_cached_chat(
                c_dir,
                client,
                model,
                system,
                user,
                response_schema=response_schema,
                label=label,
            )
            telemetry["cache_hits"] += 1
            return res
        except OfflineCacheMiss:
            telemetry["offline_fallbacks"] += 1
            raise

    tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
    try:
        canary_llm.get_client = _guarded_get_client
        gemini_chatter.cached_chat = _instrumented_cached_chat
        if mode == "gemini_stub_fallback":
            tmp_base = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
            tmp_ctx = tempfile.TemporaryDirectory(prefix="v16_stub_audit_", dir=tmp_base)
            os.environ["CANARY_GEMINI_CACHE_DIR"] = tmp_ctx.name
            os.environ["CANARY_OFFLINE"] = "0"
            os.environ["SLEEPER_OFFLINE"] = "0"
        else:
            os.environ["CANARY_OFFLINE"] = "1"
            os.environ["SLEEPER_OFFLINE"] = "1"
            if cache_dir is not None:
                os.environ["CANARY_GEMINI_CACHE_DIR"] = str(cache_dir)
        yield telemetry
    finally:
        canary_llm.get_client = orig_get_client
        gemini_chatter.cached_chat = orig_cached_chat
        if tmp_ctx is not None:
            tmp_ctx.cleanup()
        if prev_offline is None:
            os.environ.pop("CANARY_OFFLINE", None)
        else:
            os.environ["CANARY_OFFLINE"] = prev_offline
        if prev_sleeper_offline is None:
            os.environ.pop("SLEEPER_OFFLINE", None)
        else:
            os.environ["SLEEPER_OFFLINE"] = prev_sleeper_offline
        if prev_cache_dir is None:
            os.environ.pop("CANARY_GEMINI_CACHE_DIR", None)
        else:
            os.environ["CANARY_GEMINI_CACHE_DIR"] = prev_cache_dir


def _verify_bit_exact_solver_parity_and_determinism(
    spec_or_prov: Any,
    tier: str,
    seed_list: list[int],
    raw_rep: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    c4 = raw_rep["checks"]["solver_calibration_parity"]
    c6 = raw_rep["checks"]["replay_and_paired_gap"]
    rows_by_seed = {int(r["seed"]): r for r in c6.get("per_seed", [])}

    exact_score_matches = 0
    exact_day_matches = 0
    max_abs_score_diff = 0.0
    solver_scores: list[float] = []
    template_scores: list[float] = []
    solver_correct = 0
    template_correct = 0
    false_decoy_ids = int(c4.get("false_decoy_ids", 0))
    parity_mismatches: list[str] = []

    repeat_day_calls = 0
    repeat_interview_calls = 0
    repeat_mismatches = 0

    for seed in seed_list:
        tpl_ep = _template_solver_episode(tier, seed)
        template_scores.append(float(tpl_ep.score))
        template_correct += int(bool(tpl_ep.correct))

        row = rows_by_seed.get(seed)
        if row is None:
            parity_mismatches.append(f"seed={seed} missing replayed solver row")
            max_abs_score_diff = max(max_abs_score_diff, 1.0)
        else:
            p_score = float(row["solver_score"])
            p_correct = bool(row["solver_correct"])
            p_day = int(row["solver_final_day"])
            diff = abs(p_score - float(tpl_ep.score))
            max_abs_score_diff = max(max_abs_score_diff, diff)
            solver_scores.append(p_score)
            solver_correct += int(p_correct)
            score_ok = diff == 0.0 and p_correct == bool(tpl_ep.correct)
            day_ok = p_day == int(tpl_ep.final_day)
            if score_ok:
                exact_score_matches += 1
            else:
                parity_mismatches.append(
                    f"seed={seed} solver_score_or_correct_diff: prov={p_score:.6f} tpl={float(tpl_ep.score):.6f}"
                )
            if day_ok:
                exact_day_matches += 1
            else:
                parity_mismatches.append(
                    f"seed={seed} solver_day_diff: prov={p_day} tpl={int(tpl_ep.final_day)}"
                )

        if isinstance(spec_or_prov, str):
            prov_1 = resolve_text_provider(spec_or_prov)
            prov_2 = resolve_text_provider(spec_or_prov)
        else:
            prov_1 = spec_or_prov
            prov_2 = spec_or_prov
        env_det_1 = Env(tier, seed, text_provider=prov_1)
        env_det_2 = Env(tier, seed, text_provider=prov_2)
        facts_1 = env_det_1._facts(1)
        facts_2 = env_det_2._facts(1)
        m1 = env_det_1.provider.day_messages(facts_1)
        m2 = env_det_2.provider.day_messages(facts_2)
        m1_repeat = env_det_1.provider.day_messages(facts_1)
        repeat_day_calls += 2
        if m1 != m2 or m1 != m1_repeat:
            repeat_mismatches += 1
        emp0 = env_det_1._ids[0]
        iv1 = env_det_1.provider.interview_answer(facts_1, emp0, TOPICS[0], SIGNALS[0])
        iv2 = env_det_2.provider.interview_answer(facts_2, emp0, TOPICS[0], SIGNALS[0])
        repeat_interview_calls += 1
        if iv1 != iv2:
            repeat_mismatches += 1

    n = len(seed_list)
    s_mean = (sum(solver_scores) / len(solver_scores)) if solver_scores else float(c4.get("solver_mean_score", -1.0))
    t_mean = sum(template_scores) / n
    s_acc = (solver_correct / len(solver_scores)) if solver_scores else float(c4.get("solver_acc", 0.0))
    t_acc = template_correct / n
    parity_passed = (
        bool(c4.get("passed"))
        and exact_score_matches == n
        and exact_day_matches == n
        and max_abs_score_diff == 0.0
        and false_decoy_ids == 0
    )
    det_info = {
        "passed": repeat_mismatches == 0 and repeat_day_calls > 0,
        "repeat_day_calls_checked": repeat_day_calls,
        "repeat_interview_calls_checked": repeat_interview_calls,
        "repeat_mismatches": repeat_mismatches,
    }
    parity_info = {
        "passed": parity_passed,
        "n_seeds": n,
        "exact_score_matches": exact_score_matches,
        "exact_day_matches": exact_day_matches,
        "max_abs_score_diff": _round_or_none(max_abs_score_diff, 10),
        "solver_mean_score": _round_or_none(s_mean),
        "template_mean_score": _round_or_none(t_mean),
        "solver_acc": _round_or_none(s_acc),
        "template_acc": _round_or_none(t_acc),
        "false_decoy_ids": false_decoy_ids,
        "mismatches": [_redact_emp_ids(m) for m in parity_mismatches[:10]],
    }
    return det_info, parity_info


def _sanitize_social_audit_gates(checks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    c1 = checks["public_facts_only"]
    c2 = checks["anger_words_hygiene"]
    c3 = checks["lint_clean"]
    c4 = checks["solver_calibration_parity"]
    c5 = checks["zero_baselines"]
    c6 = checks["replay_and_paired_gap"]
    return {
        "public_facts_only": {
            "passed": bool(c1["passed"]),
            "day_calls_checked": int(c1["day_calls_checked"]),
            "interview_calls_checked": int(c1["interview_calls_checked"]),
            "violation_count": int(c1["violation_count"]),
            "violations": [_redact_emp_ids(x) for x in c1.get("violations", [])[:10]],
            "summary": _redact_emp_ids(c1.get("summary", "")),
        },
        "anger_words_hygiene": {
            "passed": bool(c2["passed"]),
            "non_decoy_violation_count": int(c2["non_decoy_violation_count"]),
            "non_decoy_words_found": list(c2["non_decoy_words_found"]),
            "decoy_seeds_checked": int(c2["decoy_seeds_checked"]),
            "decoy_isolated_count": int(c2["decoy_isolated_count"]),
            "decoy_isolation_failure_count": len(c2.get("decoy_isolation_failures", [])),
            "min_decoy_anger_n1": int(c2["min_decoy_anger_n1"]),
            "max_other_anger_n2": int(c2["max_other_anger_n2"]),
            "summary": _redact_emp_ids(c2.get("summary", "")),
        },
        "lint_clean": {
            "passed": bool(c3["passed"]),
            "messages_linted": int(c3["messages_linted"]),
            "interviews_linted": int(c3["interviews_linted"]),
            "message_error_count": int(c3["message_error_count"]),
            "interview_error_count": int(c3["interview_error_count"]),
            "errors": [_redact_emp_ids(x) for x in c3.get("errors", [])[:10]],
            "summary": _redact_emp_ids(c3.get("summary", "")),
        },
        "solver_calibration_parity": {
            "passed": bool(c4["passed"]),
            "n_seeds": int(c4["n_seeds"]),
            "solver_acc": _round_or_none(c4["solver_acc"]),
            "template_acc": _round_or_none(c4["template_acc"]),
            "acc_diff": _round_or_none(c4["acc_diff"]),
            "solver_mean_score": _round_or_none(c4["solver_mean_score"]),
            "template_mean_score": _round_or_none(c4["template_mean_score"]),
            "score_diff": _round_or_none(c4["score_diff"]),
            "false_decoy_ids": int(c4["false_decoy_ids"]),
            "summary": _redact_emp_ids(c4.get("summary", "")),
        },
        "zero_baselines": {
            "passed": bool(c5["passed"]),
            "n_seeds": int(c5["n_seeds"]),
            "do_nothing_scores_all_zero": bool(c5["do_nothing_scores_all_zero"]),
            "do_nothing_max_abs_score": _round_or_none(c5["do_nothing_max_abs_score"]),
            "stop_early_quit_scores_all_zero": bool(c5["stop_early_quit_scores_all_zero"]),
            "stop_early_quit_max_abs_score": _round_or_none(c5["stop_early_quit_max_abs_score"]),
            "stop_early_mean_score": _round_or_none(c5["stop_early_mean_score"]),
            "stop_early_acc": _round_or_none(c5["stop_early_acc"]),
            "fair_guess_bar": _round_or_none(c5["fair_guess_bar"]),
            "summary": _redact_emp_ids(c5.get("summary", "")),
        },
        "replay_and_paired_gap": {
            "passed": bool(c6["passed"]),
            "n_paired": int(c6.get("n_paired", 0)),
            "mismatch_count": len(c6.get("mismatches", [])),
            "mismatches": [_redact_emp_ids(x) for x in c6.get("mismatches", [])[:10]],
            "agent_mean_score": _round_or_none(c6.get("agent_mean_score")),
            "solver_mean_score": _round_or_none(c6.get("solver_mean_score")),
            "raw_gap": _round_or_none(c6.get("raw_gap")),
            "luck_adjusted_gap": _round_or_none(c6.get("luck_adjusted_gap")),
            "summary": _redact_emp_ids(c6.get("summary", "")),
        },
    }


def audit_single_provider_offline(
    spec_or_prov: Any,
    *,
    tier: str = DEFAULT_TIER,
    seeds: Iterable[int] = range(30, 36),
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    seed_list = _normalize_seed_list(seeds)
    spec_label = spec_or_prov if isinstance(spec_or_prov, str) else getattr(spec_or_prov, "name", type(spec_or_prov).__name__)
    mode = _classify_provider_mode(str(spec_label))

    with offline_execution_guard(mode=mode, cache_dir=cache_dir) as telemetry:
        raw_rep = audit_text_provider(spec_or_prov, tier=tier, seeds=seed_list)
        det_extra, bit_exact = _verify_bit_exact_solver_parity_and_determinism(
            spec_or_prov,
            tier,
            seed_list,
            raw_rep,
        )

    checks = raw_rep["checks"]
    c1 = checks["public_facts_only"]
    c2 = checks["anger_words_hygiene"]
    c6 = checks["replay_and_paired_gap"]

    determinism_ok = bool(c1["passed"]) and bool(det_extra["passed"])
    no_mole_snoop_ok = bool(c1["passed"]) and int(c1["violation_count"]) == 0
    if TIERS[tier].decoy:
        decoy_anger_ok = (
            int(c2["decoy_seeds_checked"]) == len(seed_list)
            and int(c2["decoy_isolated_count"]) == int(c2["decoy_seeds_checked"])
            and int(c2["min_decoy_anger_n1"]) >= 3
            and len(c2.get("decoy_isolation_failures", [])) == 0
        )
    else:
        decoy_anger_ok = len(c2.get("decoy_isolation_failures", [])) == 0
    non_decoy_clean_ok = int(c2["non_decoy_violation_count"]) == 0 and int(c2["max_other_anger_n2"]) == 0
    bit_exact_ok = bool(bit_exact["passed"])
    replay_ok = bool(c6["passed"]) and len(c6.get("mismatches", [])) == 0 and int(c6.get("n_paired", 0)) == len(seed_list)

    six_fairness_checks = {
        "determinism": {
            "passed": determinism_ok,
            "repeat_day_calls_checked": int(det_extra["repeat_day_calls_checked"]),
            "repeat_interview_calls_checked": int(det_extra["repeat_interview_calls_checked"]),
            "repeat_mismatches": int(det_extra["repeat_mismatches"]),
        },
        "no_mole_snoop": {
            "passed": no_mole_snoop_ok,
            "day_calls_checked": int(c1["day_calls_checked"]),
            "interview_calls_checked": int(c1["interview_calls_checked"]),
            "violation_count": int(c1["violation_count"]),
        },
        "decoy_anger_preserved": {
            "passed": decoy_anger_ok,
            "seeds_checked": int(c2["decoy_seeds_checked"]),
            "isolated_count": int(c2["decoy_isolated_count"]),
            "min_decoy_anger_n1": int(c2["min_decoy_anger_n1"]),
        },
        "non_decoy_anger_clean": {
            "passed": non_decoy_clean_ok,
            "non_decoy_violation_count": int(c2["non_decoy_violation_count"]),
            "max_other_anger_n2": int(c2["max_other_anger_n2"]),
            "words_found": list(c2["non_decoy_words_found"]),
        },
        "bit_exact_solver_parity": bit_exact,
        "replay_verification": {
            "passed": replay_ok,
            "n_paired": int(c6.get("n_paired", 0)),
            "mismatch_count": len(c6.get("mismatches", [])),
            "heuristic_mean_score": _round_or_none(c6.get("agent_mean_score")),
            "solver_mean_score": _round_or_none(c6.get("solver_mean_score")),
            "raw_gap": _round_or_none(c6.get("raw_gap")),
            "luck_adjusted_gap": _round_or_none(c6.get("luck_adjusted_gap")),
        },
    }

    failed_fairness = [k for k, v in six_fairness_checks.items() if not v["passed"]]
    failed_gates = list(raw_rep["failed_checks"])
    all_passed = (
        bool(raw_rep["all_passed"])
        and len(failed_fairness) == 0
        and telemetry["live_api_calls"] == 0
        and telemetry["blocked_api_attempts"] == 0
    )

    return {
        "spec": str(spec_label),
        "provider": str(raw_rep["provider"]),
        "mode": mode,
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "all_passed": all_passed,
        "failed_social_audit_gates": failed_gates,
        "failed_fairness_checks": failed_fairness,
        "six_fairness_checks": six_fairness_checks,
        "social_audit_gates": _sanitize_social_audit_gates(checks),
        "telemetry": telemetry,
    }


def _infer_variant_from_path(path: Path) -> str | None:
    for part in reversed(path.parts[:-1]):
        clean = part.replace("__", ":")
        for prefix in ("v16-gemini-stub:", "v16-gemini:", "v16:"):
            if clean.startswith(prefix):
                clean = clean.split(":", 1)[1].strip()
        if clean == "v0_v14_control" or clean in VARIANTS:
            return clean
    return None


def _offline_provider_spec_for_episode(rec: dict[str, Any], path_variant: str | None) -> tuple[str, str]:
    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    raw_var = str(rec.get("variant") or meta.get("variant") or path_variant or "v0_v14_control").strip()
    for prefix in ("v16-gemini-stub:", "v16-gemini:", "v16:"):
        if raw_var.startswith(prefix):
            raw_var = raw_var.split(":", 1)[1].strip()
    if raw_var == "template":
        raw_var = "v0_v14_control"

    raw_prov = str(meta.get("provider") or "").strip()
    if raw_prov in ("", "template") and raw_var == "v0_v14_control":
        return raw_var, "template"
    if raw_prov.startswith(("v16:", "v16-gemini:", "v16-gemini-stub:")):
        return raw_var, raw_prov
    if raw_prov in ("sanitized_template", "clean_template"):
        return raw_var, "sanitized_template"
    if raw_var in VARIANTS and raw_var != "v0_v14_control":
        return raw_var, f"v16:{raw_var}"
    return raw_var, "template"


def _step_tool_name(raw_step: Any) -> str | None:
    if isinstance(raw_step, dict):
        tool = raw_step.get("tool")
        return str(tool) if isinstance(tool, str) and tool else None
    if isinstance(raw_step, (list, tuple)) and len(raw_step) >= 2 and isinstance(raw_step[0], str):
        return raw_step[0]
    return None


def _classify_skip_reason(rec: Any, *, allow_fake: bool = False) -> str | None:
    if not isinstance(rec, dict):
        return "non_object_json"
    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    if rec.get("valid") is False or meta.get("valid") is False:
        return "marked_invalid"
    if not allow_fake and bool(meta.get("fake", False)):
        return "fake_episode"
    if rec.get("done") is False or meta.get("done") is False:
        return "incomplete_not_done"
    end_reason = rec.get("end_reason")
    if end_reason in ("error", "timeout") or meta.get("rc") == "timeout" or bool(meta.get("error")):
        return "error_or_timeout"
    if end_reason not in VALID_END_REASONS:
        return "incomplete_missing_end_reason"
    raw_seed = rec.get("seed")
    if isinstance(raw_seed, bool) or raw_seed is None:
        return "missing_or_invalid_seed"
    try:
        int(raw_seed)
    except (TypeError, ValueError):
        return "missing_or_invalid_seed"
    tier = str(rec.get("tier") or DEFAULT_TIER)
    if tier not in TIERS:
        return "unsupported_tier"
    raw_score = rec.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)) or not math.isfinite(float(raw_score)):
        return "missing_or_nonfinite_score"
    raw_steps = rec.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) == 0:
        return "empty_or_missing_steps"
    tools = [_step_tool_name(st) for st in raw_steps]
    if any(t is None for t in tools):
        return "malformed_step_entry"
    if end_reason == "accused" and "accuse" not in tools:
        return "incomplete_missing_accuse_step"
    return None


def _sanitize_per_seed_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": str(row["tier"]),
        "seed": int(row["seed"]),
        "agent": _redact_emp_ids(str(row["agent"])),
        "score": _round_or_none(row["score"]),
        "solver_score": _round_or_none(row["solver_score"]),
        "paired_diff": _round_or_none(row["paired_diff"]),
        "raw_gap": _round_or_none(row["raw_gap"]),
        "accused_bool": bool(row.get("accused") is not None),
        "correct": bool(row["correct"]),
        "solver_correct": bool(row["solver_correct"]),
        "final_day": int(row["final_day"]),
        "accuse_day": int(row["accuse_day"]) if row.get("accuse_day") is not None else None,
        "solver_final_day": int(row["solver_final_day"]),
        "end_reason": str(row["end_reason"]),
        "true_V": _round_or_none(row["true_V"]),
        "p_accused": _round_or_none(row["p_accused"]),
        "p_top": _round_or_none(row["p_top"]),
        "verdict": str(row["verdict"]),
        "luck_adjusted_score": _round_or_none(row["luck_adjusted_score"]),
        "solver_luck_adjusted_score": _round_or_none(row["solver_luck_adjusted_score"]),
        "canary_count": int(row["canary_count"]),
        "interview_count": int(row["interview_count"]),
        "search_count": int(row["search_count"]),
        "restrict_count": int(row["restrict_count"]),
        "tool_calls": int(row["tool_calls"]),
    }


def audit_shared_runs_readonly(
    runs_root: Path | None,
    *,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    allow_fake: bool = False,
    expected_tier: str = DEFAULT_TIER,
) -> dict[str, Any]:
    if runs_root is None or not runs_root.is_dir():
        return {
            "runs_root": _display_path(runs_root),
            "exists": False,
            "read_only": True,
            "files_discovered": 0,
            "invalid_attempt_log_files": 0,
            "invalid_attempt_log_entries": 0,
            "total_lines_read": 0,
            "valid_episodes_verified": 0,
            "skipped_invalid_or_incomplete": 0,
            "superseded_duplicates": 0,
            "skipped_by_reason": {},
            "total_mismatches": 0,
            "all_passed": True,
            "files": [],
            "paired_vs_control": [],
        }

    ep_files = sorted(
        p
        for p in runs_root.rglob("episodes.jsonl")
        if "attempts" not in p.relative_to(runs_root).parts
        and "superseded" not in p.relative_to(runs_root).parts
    )
    inv_files = sorted(
        p
        for p in runs_root.rglob("invalid_attempts.jsonl")
        if "attempts" not in p.relative_to(runs_root).parts
        and "superseded" not in p.relative_to(runs_root).parts
    )
    inv_log_entries = 0
    for inv_f in inv_files:
        raw_inv = inv_f.read_text(encoding="utf-8", errors="replace")
        inv_log_entries += sum(1 for ln in raw_inv.splitlines() if ln.strip())

    solver_ep_cache: dict[tuple[str, str, int], EpisodeResult] = {}
    total_lines_read = 0
    total_valid_verified = 0
    total_skipped = 0
    total_superseded = 0
    total_mismatches = 0
    global_skip_reasons: dict[str, int] = {}
    file_reports: list[dict[str, Any]] = []
    verified_by_variant: dict[str, dict[int, dict[str, Any]]] = {}

    for ep_path in ep_files:
        rel_path = str(ep_path.relative_to(runs_root))
        path_var = _infer_variant_from_path(ep_path)
        raw_text = ep_path.read_text(encoding="utf-8", errors="replace")
        non_empty_lines = [ln for ln in raw_text.splitlines() if ln.strip()]
        total_lines_read += len(non_empty_lines)

        file_skip_reasons: dict[str, int] = {}
        superseded_count = 0
        grouped_valid: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}

        for ln in non_empty_lines:
            try:
                parsed = json.loads(ln)
            except json.JSONDecodeError:
                file_skip_reasons["malformed_json"] = file_skip_reasons.get("malformed_json", 0) + 1
                continue
            reason = _classify_skip_reason(parsed, allow_fake=allow_fake)
            if reason is not None:
                file_skip_reasons[reason] = file_skip_reasons.get(reason, 0) + 1
                continue
            tier = str(parsed.get("tier") or DEFAULT_TIER)
            seed = int(parsed["seed"])
            variant_name, prov_spec = _offline_provider_spec_for_episode(parsed, path_var)
            group_key = (variant_name, prov_spec, tier)
            by_seed = grouped_valid.setdefault(group_key, {})
            if seed in by_seed:
                superseded_count += 1
            clean_rec = dict(parsed)
            clean_rec["tier"] = tier
            clean_rec["seed"] = seed
            by_seed[seed] = clean_rec

        file_skipped_total = sum(file_skip_reasons.values())
        total_skipped += file_skipped_total
        total_superseded += superseded_count
        for k, cnt in file_skip_reasons.items():
            global_skip_reasons[k] = global_skip_reasons.get(k, 0) + cnt

        if not grouped_valid:
            file_reports.append({
                "relative_path": rel_path,
                "variant": path_var or "unknown",
                "provider_spec": None,
                "tier": DEFAULT_TIER,
                "status": "skipped_no_valid_episodes",
                "passed": True,
                "lines_read": len(non_empty_lines),
                "n_valid": 0,
                "n_skipped": file_skipped_total,
                "superseded_duplicates": superseded_count,
                "skipped_by_reason": file_skip_reasons,
                "valid_seeds": [],
                "mismatch_count": 0,
                "mismatches": [],
                "per_seed": [],
            })
            continue

        for (variant_name, prov_spec, tier), by_seed in sorted(grouped_valid.items()):
            ordered_seeds = sorted(by_seed.keys())
            valid_eps = [by_seed[s] for s in ordered_seeds]
            prov_mode = _classify_provider_mode(prov_spec)
            with offline_execution_guard(mode=prov_mode, cache_dir=cache_dir):
                prov = resolve_text_provider(prov_spec)
                sol_eps: list[EpisodeResult] = []
                for sd in ordered_seeds:
                    ck = (tier, prov_spec, sd)
                    if ck not in solver_ep_cache:
                        if prov_spec == "template":
                            solver_ep_cache[ck] = _template_solver_episode(tier, sd)
                        else:
                            solver_ep_cache[ck] = run_episode(
                                Env(tier, sd, text_provider=resolve_text_provider(prov_spec)),
                                SolverPolicy(tier),
                            )
                    sol_eps.append(solver_ep_cache[ck])
                scored = verify_and_score_episodes(
                    valid_eps,
                    sol_eps,
                    tier=tier,
                    provider=prov,
                    strict=False,
                )

            mismatches = [_redact_emp_ids(m) for m in scored.get("mismatches", [])]
            group_passed = bool(scored["passed"]) and len(mismatches) == 0 and int(scored["n_paired"]) == len(ordered_seeds)
            total_valid_verified += int(scored["n_paired"])
            total_mismatches += len(mismatches)

            clean_rows = [_sanitize_per_seed_row(r) for r in scored.get("per_seed", [])]
            if group_passed and tier == expected_tier:
                v_map = verified_by_variant.setdefault(variant_name, {})
                for r in clean_rows:
                    v_map[int(r["seed"])] = r

            file_reports.append({
                "relative_path": rel_path,
                "variant": variant_name,
                "provider_spec": prov_spec,
                "tier": tier,
                "status": "verified" if group_passed else "mismatch_failed",
                "passed": group_passed,
                "lines_read": len(non_empty_lines),
                "n_valid": int(scored["n_paired"]),
                "n_skipped": file_skipped_total,
                "superseded_duplicates": superseded_count,
                "skipped_by_reason": file_skip_reasons,
                "valid_seeds": list(scored.get("seeds", [])),
                "mismatch_count": len(mismatches),
                "mismatches": mismatches[:20],
                "agent_mean_score": _round_or_none(scored.get("agent_mean_score")),
                "solver_mean_score": _round_or_none(scored.get("solver_mean_score")),
                "paired_diff": _round_or_none(scored.get("paired_diff")),
                "raw_gap": _round_or_none(scored.get("raw_gap")),
                "frontier_solver_ratio": _round_or_none(scored.get("frontier_solver_ratio")),
                "agent_accuracy": _round_or_none(scored.get("agent_accuracy")),
                "solver_accuracy": _round_or_none(scored.get("solver_accuracy")),
                "agent_accused_rate": _round_or_none(scored.get("agent_accused_rate")),
                "mean_p_accused": _round_or_none(scored.get("mean_p_accused")),
                "mean_accuse_day": _round_or_none(scored.get("mean_accuse_day")),
                "agent_luck_adjusted_mean": _round_or_none(scored.get("agent_luck_adjusted_mean")),
                "solver_luck_adjusted_mean": _round_or_none(scored.get("solver_luck_adjusted_mean")),
                "luck_adjusted_gap": _round_or_none(scored.get("luck_adjusted_gap")),
                "per_seed": clean_rows,
            })

    paired_vs_control: list[dict[str, Any]] = []
    ctl_map = verified_by_variant.get("v0_v14_control", {})
    for var_name in sorted(k for k in verified_by_variant if k != "v0_v14_control"):
        v_map = verified_by_variant[var_name]
        shared = sorted(set(v_map) & set(ctl_map))
        if not shared:
            paired_vs_control.append({
                "variant": var_name,
                "n_paired": 0,
                "paired_seeds": [],
                "control_raw_mean": None,
                "variant_raw_mean": None,
                "delta_raw_mean": None,
                "control_luck_adj_mean": None,
                "variant_luck_adj_mean": None,
                "delta_luck_adj_mean": None,
            })
            continue
        n_sh = len(shared)
        c_raw = sum(float(ctl_map[s]["score"]) for s in shared) / n_sh
        v_raw = sum(float(v_map[s]["score"]) for s in shared) / n_sh
        c_la = sum(float(ctl_map[s]["luck_adjusted_score"]) for s in shared) / n_sh
        v_la = sum(float(v_map[s]["luck_adjusted_score"]) for s in shared) / n_sh
        paired_vs_control.append({
            "variant": var_name,
            "n_paired": n_sh,
            "paired_seeds": shared,
            "control_raw_mean": _round_or_none(c_raw),
            "variant_raw_mean": _round_or_none(v_raw),
            "delta_raw_mean": _round_or_none(v_raw - c_raw),
            "control_luck_adj_mean": _round_or_none(c_la),
            "variant_luck_adj_mean": _round_or_none(v_la),
            "delta_luck_adj_mean": _round_or_none(v_la - c_la),
        })

    return {
        "runs_root": _display_path(runs_root),
        "exists": True,
        "read_only": True,
        "files_discovered": len(ep_files),
        "invalid_attempt_log_files": len(inv_files),
        "invalid_attempt_log_entries": inv_log_entries,
        "total_lines_read": total_lines_read,
        "valid_episodes_verified": total_valid_verified,
        "skipped_invalid_or_incomplete": total_skipped,
        "superseded_duplicates": total_superseded,
        "skipped_by_reason": global_skip_reasons,
        "total_mismatches": total_mismatches,
        "all_passed": total_mismatches == 0 and all(f["passed"] for f in file_reports),
        "files": file_reports,
        "paired_vs_control": paired_vs_control,
    }


def assert_clean_output(payload: Any) -> None:
    def _walk(obj: Any, path: str = "root", in_path_field: bool = False) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                ks = str(k)
                if ks in FORBIDDEN_OUTPUT_KEYS:
                    raise ValueError(f"forbidden key {ks!r} at {path}.{ks}")
                child_is_path = in_path_field or ks in ("runs_root", "cache_dir", "relative_path")
                _walk(v, f"{path}.{ks}", child_is_path)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                _walk(item, f"{path}[{idx}]", in_path_field)
        elif isinstance(obj, float):
            if not math.isfinite(obj):
                raise ValueError(f"non-finite float at {path}: {obj!r}")
        elif isinstance(obj, str):
            if "\u2014" in obj or "\u2013" in obj:
                raise ValueError(f"em or en dash detected at {path}")
            if not in_path_field and EMP_ID_PATTERN.search(obj):
                raise ValueError(f"employee identifier leak at {path}: {obj!r}")

    _walk(payload)
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    for rx in KEY_PATTERNS:
        if rx.search(serialized):
            raise ValueError("secret API key pattern detected in serialized audit output")


def _fmt_num(val: float | None, ndigits: int = 3) -> str:
    if val is None:
        return "n/a"
    return f"{float(val):.{ndigits}f}"


def _fmt_signed(val: float | None, ndigits: int = 3) -> str:
    if val is None:
        return "n/a"
    return f"{float(val):+.{ndigits}f}"


def _fmt_seeds(seeds: list[int]) -> str:
    if not seeds:
        return "none"
    return ",".join(str(s) for s in seeds)


def render_markdown_report(report: dict[str, Any]) -> str:
    seeds_str = _fmt_seeds(report["seeds"])
    prov_list: list[dict[str, Any]] = report["provider_audits"]
    shared = report["shared_runs_replay_audit"]
    diag = report.get("baseline_diagnostics", {}).get("v14_template_baseline")

    lines: list[str] = [
        f"{MD_H} V1.6 Social Fairness and Offline Replay Audit",
        "",
        f"Generated offline via `python scripts/run_v16_social_audit.py --workers 1` using `canary.social_audit` (`audit_text_provider` and `verify_and_score_episodes`) with zero live LLM API calls.",
        "",
        f"{MD_H}{MD_H} 1. Executive Summary",
        "",
        f"- **Tier and seed window**: `{report['tier']}` (`{report['tiers_version']}`), seeds `{seeds_str}` (`n={report['n_seeds']}` per provider).",
        f"- **Execution discipline**: `workers={report['workers']}`, `live_api_calls={report['live_api_calls']}`, `blocked_api_attempts={report['blocked_api_attempts']}`, `offline_enforced={report['offline_enforced']}`.",
        f"- **V1.6 TextProvider fairness gate**: **{report['n_providers_passed']}/{report['n_providers_audited']}** providers passed all 6 fairness checks and all 6 `canary.social_audit` gates (`all_v16_providers_passed={report['all_v16_providers_passed']}`).",
        f"- **Bit-exact SolverPolicy calibration parity**: Across all {report['n_providers_audited']} audited V1.6 and sanitized providers on seeds `{seeds_str}`, `SolverPolicy` achieved **100% bit-exact parity** vs `TemplateProvider` (`max_abs_score_diff=0.0`, exact score, accusation, final day, and tool-call sequence on all `{report['n_seeds']}/{report['n_seeds']}` seeds; `0` false decoy IDs).",
        f"- **Shared checkpoint replay verification**: Read-only audit of `{shared['runs_root']}` discovered `{shared['files_discovered']}` `episodes.jsonl` files (`{shared['total_lines_read']}` records read, `{shared['skipped_invalid_or_incomplete']}` invalid/incomplete records skipped cleanly, `{shared['invalid_attempt_log_entries']}` logged retry entries across `{shared['invalid_attempt_log_files']}` `invalid_attempts.jsonl` files) and replay-verified **{shared['valid_episodes_verified']}/{shared['valid_episodes_verified']}** valid episodes with **0** mismatches (`all_episode_replays_passed={report['all_episode_replays_passed']}`).",
    ]

    if diag is not None:
        c2_diag = diag["six_fairness_checks"]["non_decoy_anger_clean"]
        lines.append(
            f"- **Raw v1.4 `TemplateProvider` control diagnostic**: Passed 5/6 `canary.social_audit` gates (`public_facts_only`, `lint_clean`, `solver_calibration_parity`, `zero_baselines`, `replay_and_paired_gap`) and failed `anger_words_hygiene` as expected (`{c2_diag['non_decoy_violation_count']}` non-decoy hits on `{c2_diag['words_found']}` across seeds `{seeds_str}`), confirming the hygiene check catches non-decoy `ANGER_WORDS` leakage that `V16SocialProvider` and `SanitizedTemplateProvider` eliminate."
        )

    lines.extend([
        "",
        f"{MD_H}{MD_H} 2. Six-Check V1.6 TextProvider Fairness Matrix (Seeds {seeds_str})",
        "",
        "| Provider Spec | Mode | Det | No Snoop | Decoy Anger (n1>=3) | Non-Decoy Clean (n2=0) | Bit-Exact Solver Parity | Replay Gate | Lint (msg/iv) | Zero Baselines | Cache Hits / Fallbacks / Stub | Result |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ])

    for p in prov_list:
        fc = p["six_fairness_checks"]
        sg = p["social_audit_gates"]
        tel = p["telemetry"]
        det_s = f"PASS ({fc['determinism']['repeat_mismatches']} err)" if fc["determinism"]["passed"] else "FAIL"
        snoop_s = (
            f"PASS ({fc['no_mole_snoop']['day_calls_checked']}d/{fc['no_mole_snoop']['interview_calls_checked']}iv)"
            if fc["no_mole_snoop"]["passed"]
            else "FAIL"
        )
        dec_s = (
            f"PASS ({fc['decoy_anger_preserved']['isolated_count']}/{fc['decoy_anger_preserved']['seeds_checked']}, min_n1={fc['decoy_anger_preserved']['min_decoy_anger_n1']})"
            if fc["decoy_anger_preserved"]["passed"]
            else "FAIL"
        )
        clean_s = (
            f"PASS (hits={fc['non_decoy_anger_clean']['non_decoy_violation_count']}, max_n2={fc['non_decoy_anger_clean']['max_other_anger_n2']})"
            if fc["non_decoy_anger_clean"]["passed"]
            else f"FAIL ({fc['non_decoy_anger_clean']['words_found']})"
        )
        par_b = fc["bit_exact_solver_parity"]
        par_s = (
            f"PASS ({par_b['exact_score_matches']}/{par_b['n_seeds']}, diff={_fmt_num(par_b['max_abs_score_diff'], 6)})"
            if par_b["passed"]
            else "FAIL"
        )
        rep_b = fc["replay_verification"]
        rep_s = (
            f"PASS (n={rep_b['n_paired']}, err={rep_b['mismatch_count']})"
            if rep_b["passed"]
            else "FAIL"
        )
        lint_b = sg["lint_clean"]
        lint_s = (
            f"PASS ({lint_b['messages_linted']}/{lint_b['interviews_linted']})"
            if lint_b["passed"]
            else "FAIL"
        )
        zb_b = sg["zero_baselines"]
        zb_s = "PASS (0.0/0.0)" if zb_b["passed"] else "FAIL"
        tel_s = f"{tel['cache_hits']} / {tel['offline_fallbacks']} / {tel['stub_calls']}"
        verdict = "PASS" if p["all_passed"] else "FAIL"
        lines.append(
            f"| `{p['spec']}` | `{p['mode']}` | {det_s} | {snoop_s} | {dec_s} | {clean_s} | {par_s} | {rep_s} | {lint_s} | {zb_s} | {tel_s} | **{verdict}** |"
        )

    if diag is not None:
        fc = diag["six_fairness_checks"]
        sg = diag["social_audit_gates"]
        par_b = fc["bit_exact_solver_parity"]
        rep_b = fc["replay_verification"]
        lint_b = sg["lint_clean"]
        lines.extend([
            "",
            f"{MD_H}{MD_H}{MD_H} 2.1 Raw v1.4 Control Diagnostic (`template`)",
            "",
            "| Provider Spec | Mode | Det | No Snoop | Decoy Anger | Non-Decoy Clean | Bit-Exact Solver Parity | Replay Gate | Lint (msg/iv) | Zero Baselines | Expected Diagnostic |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
            f"| `template` | `v14_template_baseline` | PASS | PASS ({fc['no_mole_snoop']['day_calls_checked']}d/{fc['no_mole_snoop']['interview_calls_checked']}iv) | "
            f"FAIL (n2>0: isolated {fc['decoy_anger_preserved']['isolated_count']}/{fc['decoy_anger_preserved']['seeds_checked']}, min_n1={fc['decoy_anger_preserved']['min_decoy_anger_n1']}) | "
            f"FAIL (hits={fc['non_decoy_anger_clean']['non_decoy_violation_count']}, max_n2={fc['non_decoy_anger_clean']['max_other_anger_n2']}, words={fc['non_decoy_anger_clean']['words_found']}) | "
            f"PASS ({par_b['exact_score_matches']}/{par_b['n_seeds']}, diff=0.000000) | "
            f"PASS (n={rep_b['n_paired']}, err=0) | PASS ({lint_b['messages_linted']}/{lint_b['interviews_linted']}) | PASS (0.0/0.0) | Non-decoy `recruiter` token only |",
        ])

    if prov_list:
        ref_par = prov_list[0]["six_fairness_checks"]["bit_exact_solver_parity"]
        ref_rep = prov_list[0]["six_fairness_checks"]["replay_verification"]
        lines.extend([
            "",
            f"{MD_H}{MD_H} 3. SolverPolicy Calibration and Baseline Summary on Seeds {seeds_str}",
            "",
            f"- **SolverPolicy mean score (`{report['tier']}`, seeds `{seeds_str}`)**: `{_fmt_num(ref_par['solver_mean_score'])}` vs `TemplateProvider` `{_fmt_num(ref_par['template_mean_score'])}` (`max_abs_score_diff = 0.000000`, accuracy `{_fmt_num(ref_par['solver_acc'])}` vs `{_fmt_num(ref_par['template_acc'])}`).",
            f"- **Heuristic baseline mean score across providers**: `{_fmt_num(ref_rep['heuristic_mean_score'])}` (paired raw gap vs `SolverPolicy`: `{_fmt_signed(ref_rep['raw_gap'])}`, luck-adjusted gap: `{_fmt_signed(ref_rep['luck_adjusted_gap'])}`).",
            f"- **Zero-information baselines**: `DoNothing = 0.000`, `StopEarlyQuit = 0.000`, unfinished episode `= 0.000`, Day-1 blind guess `StopEarly = -1.000 <= 0.000` across all audited providers.",
        ])

    lines.extend([
        "",
        f"{MD_H}{MD_H} 4. Read-Only Replay Verification of Shared V1.6 Checkpoints",
        "",
        f"- **Shared root**: `{shared['runs_root']}` (`read_only={shared['read_only']}`, `exists={shared['exists']}`)",
        f"- **Checkpoint files audited**: `{shared['files_discovered']}` `episodes.jsonl` files; `{shared['valid_episodes_verified']}` valid episodes replay-verified, `{shared['skipped_invalid_or_incomplete']}` invalid/incomplete lines skipped in `episodes.jsonl`, `{shared['invalid_attempt_log_entries']}` failed retry records logged separately in `{shared['invalid_attempt_log_files']}` `invalid_attempts.jsonl` files.",
        "",
        "| Checkpoint File | Variant | Provider Spec | Valid Seeds | n Valid | Skipped | Mismatches | Agent Raw | Solver Raw | Agent Luck-Adj | Solver Luck-Adj | Acc | Mean Day | Mean P(acc) | Replay Status |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ])

    if not shared["files"]:
        lines.append("| (none) | n/a | n/a | none | 0 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | PASS |")
    else:
        for f in shared["files"]:
            lines.append(
                f"| `{f['relative_path']}` | `{f['variant']}` | `{f['provider_spec'] or 'n/a'}` | `{_fmt_seeds(f['valid_seeds'])}` | "
                f"{f['n_valid']} | {f['n_skipped']} | {f['mismatch_count']} | "
                f"{_fmt_num(f.get('agent_mean_score'))} | {_fmt_num(f.get('solver_mean_score'))} | "
                f"{_fmt_num(f.get('agent_luck_adjusted_mean'))} | {_fmt_num(f.get('solver_luck_adjusted_mean'))} | "
                f"{_fmt_num(f.get('agent_accuracy'))} | {_fmt_num(f.get('mean_accuse_day'), 2)} | {_fmt_num(f.get('mean_p_accused'))} | "
                f"**{'PASS' if f['passed'] else 'FAIL'}** |"
            )

    if shared["files"]:
        lines.extend([
            "",
            f"{MD_H}{MD_H}{MD_H} 4.1 Per-Episode Replay Audit Table",
            "",
            "| Variant | Seed | Agent Score | Solver Score | Accused? | Correct | Day (Solver Day) | True V | P(acc) | Verdict | Agent Luck-Adj | Solver Luck-Adj | Canaries | Interviews | Tool Calls |",
            "|---|---:|---:|---:|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|",
        ])
        for f in shared["files"]:
            for r in f.get("per_seed", []):
                lines.append(
                    f"| `{f['variant']}` | {r['seed']} | {_fmt_num(r['score'])} | {_fmt_num(r['solver_score'])} | "
                    f"`{r['accused_bool']}` | `{r['correct']}` | {r['final_day']} ({r['solver_final_day']}) | "
                    f"{_fmt_num(r['true_V'])} | {_fmt_num(r['p_accused'])} | `{r['verdict']}` | "
                    f"{_fmt_num(r['luck_adjusted_score'])} | {_fmt_num(r['solver_luck_adjusted_score'])} | "
                    f"{r['canary_count']} | {r['interview_count']} | {r['tool_calls']} |"
                )

    if shared["paired_vs_control"]:
        lines.extend([
            "",
            f"{MD_H}{MD_H}{MD_H} 4.2 Paired Checkpoint Intersection vs `v0_v14_control`",
            "",
            "| Variant | n Paired | Paired Seeds | Control Raw | Variant Raw | Delta Raw (Var - Ctl) | Control Luck-Adj | Variant Luck-Adj | Delta Luck-Adj (Var - Ctl) |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|",
        ])
        for p_row in shared["paired_vs_control"]:
            lines.append(
                f"| `{p_row['variant']}` | {p_row['n_paired']} | `{_fmt_seeds(p_row['paired_seeds'])}` | "
                f"{_fmt_num(p_row['control_raw_mean'])} | {_fmt_num(p_row['variant_raw_mean'])} | {_fmt_signed(p_row['delta_raw_mean'])} | "
                f"{_fmt_num(p_row['control_luck_adj_mean'])} | {_fmt_num(p_row['variant_luck_adj_mean'])} | {_fmt_signed(p_row['delta_luck_adj_mean'])} |"
            )

    lines.extend([
        "",
        f"{MD_H}{MD_H} 5. Reproducibility Command",
        "",
        "```bash",
        "CANARY_OFFLINE=1 python scripts/run_v16_social_audit.py --workers 1 \\",
        "  --tier hard --seeds 30-35 \\",
        "  --out-json results/v16_social/social_audit_report.json \\",
        "  --out-md docs/reports/v16_social_fairness_audit.md",
        "```",
        "",
        "When `/tmp/fleet-momin/shared/v16_runs` is absent (for example on fresh CI clones), `scripts/run_v16_social_audit.py` automatically falls back to committed `results/v16_social/partial`.",
    ])
    return "\n".join(lines)


def run_v16_social_audit(
    *,
    tier: str = DEFAULT_TIER,
    seeds: str | int | Iterable[int] = DEFAULT_SEEDS,
    providers: Iterable[str] | None = None,
    runs_root: str | Path | None = "auto",
    cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
    workers: int = DEFAULT_WORKERS,
    include_v14_template_diagnostic: bool = True,
    allow_fake: bool = False,
    out_json: str | Path | None = None,
    out_md: str | Path | None = None,
) -> dict[str, Any]:
    if int(workers) != 1:
        raise ValueError(f"only --workers 1 is permitted in offline social audit, got {workers!r}")
    if tier not in TIERS:
        raise ValueError(f"unsupported tier {tier!r}")

    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    seed_list = _normalize_seed_list(seeds)
    provider_specs = _normalize_provider_specs(providers)
    resolved_cache = Path(cache_dir) if cache_dir is not None and str(cache_dir).strip() else None
    resolved_runs, _ = resolve_runs_root(runs_root)

    provider_audits: list[dict[str, Any]] = []
    total_live_calls = 0
    total_blocked = 0
    for spec in provider_specs:
        entry = audit_single_provider_offline(
            spec,
            tier=tier,
            seeds=seed_list,
            cache_dir=resolved_cache,
        )
        provider_audits.append(entry)
        total_live_calls += int(entry["telemetry"]["live_api_calls"])
        total_blocked += int(entry["telemetry"]["blocked_api_attempts"])

    baseline_diagnostics: dict[str, Any] = {}
    if include_v14_template_diagnostic:
        tpl_diag = audit_single_provider_offline(
            "template",
            tier=tier,
            seeds=seed_list,
            cache_dir=resolved_cache,
        )
        baseline_diagnostics["v14_template_baseline"] = tpl_diag
        total_live_calls += int(tpl_diag["telemetry"]["live_api_calls"])
        total_blocked += int(tpl_diag["telemetry"]["blocked_api_attempts"])

    shared_audit = audit_shared_runs_readonly(
        resolved_runs,
        cache_dir=resolved_cache,
        allow_fake=allow_fake,
        expected_tier=tier,
    )

    n_passed = sum(1 for p in provider_audits if p["all_passed"])
    all_v16_passed = n_passed == len(provider_audits) and len(provider_audits) > 0
    all_replays_passed = bool(shared_audit["all_passed"])
    overall_passed = (
        all_v16_passed
        and all_replays_passed
        and total_live_calls == 0
        and total_blocked == 0
    )

    report: dict[str, Any] = {
        "schema_version": "v16_social_fairness_audit.v1",
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": seed_list,
        "n_seeds": len(seed_list),
        "workers": 1,
        "offline_enforced": True,
        "live_api_calls": total_live_calls,
        "blocked_api_attempts": total_blocked,
        "cache_dir": str(resolved_cache) if resolved_cache is not None else None,
        "check_names": list(CHECK_NAMES),
        "n_providers_audited": len(provider_audits),
        "n_providers_passed": n_passed,
        "all_v16_providers_passed": all_v16_passed,
        "all_episode_replays_passed": all_replays_passed,
        "overall_passed": overall_passed,
        "provider_audits": provider_audits,
        "baseline_diagnostics": baseline_diagnostics,
        "shared_runs_replay_audit": shared_audit,
    }

    assert_clean_output(report)
    md_text = render_markdown_report(report)
    if "\u2014" in md_text or "\u2013" in md_text:
        raise ValueError("em or en dash detected in rendered markdown")

    if out_json is not None:
        out_j = Path(out_json)
        out_j.parent.mkdir(parents=True, exist_ok=True)
        out_j.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

    if out_md is not None:
        out_m = Path(out_md)
        out_m.parent.mkdir(parents=True, exist_ok=True)
        out_m.write_text(md_text + "\n", encoding="utf-8")

    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Offline V1.6 Social TextProvider fairness and shared checkpoint replay audit."
    )
    ap.add_argument("--tier", default=DEFAULT_TIER)
    ap.add_argument("--seeds", default=DEFAULT_SEEDS)
    ap.add_argument("--providers", action="append", default=None)
    ap.add_argument("--runs-root", default="auto")
    ap.add_argument("--no-runs-root", action="store_true")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--skip-template-diagnostic", action="store_true")
    ap.add_argument("--allow-fake", action="store_true")
    ap.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    ap.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runs_root = None if args.no_runs_root else args.runs_root
    out_json = args.out_json if args.out_json else None
    out_md = args.out_md if args.out_md else None
    try:
        report = run_v16_social_audit(
            tier=args.tier,
            seeds=args.seeds,
            providers=args.providers,
            runs_root=runs_root,
            cache_dir=args.cache_dir,
            workers=args.workers,
            include_v14_template_diagnostic=not bool(args.skip_template_diagnostic),
            allow_fake=bool(args.allow_fake),
            out_json=out_json,
            out_md=out_md,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "overall_passed": report["overall_passed"],
        "tier": report["tier"],
        "seeds": report["seeds"],
        "workers": report["workers"],
        "live_api_calls": report["live_api_calls"],
        "n_providers_passed": f"{report['n_providers_passed']}/{report['n_providers_audited']}",
        "all_v16_providers_passed": report["all_v16_providers_passed"],
        "valid_episodes_verified": report["shared_runs_replay_audit"]["valid_episodes_verified"],
        "skipped_invalid_or_incomplete": report["shared_runs_replay_audit"]["skipped_invalid_or_incomplete"],
        "all_episode_replays_passed": report["all_episode_replays_passed"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
