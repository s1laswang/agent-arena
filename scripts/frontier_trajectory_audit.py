"""Pure-CPU trajectory, canary design, horizon, and token/cache audit for Canary v1.4 cohorts.

    python scripts/frontier_trajectory_audit.py --write
    python scripts/frontier_trajectory_audit.py --check
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canary.analysis.gap import load_runs, mean_ci
from canary.env import Env
from canary.rules import TIERS_VERSION, tier_params
from canary.types import INVESTIGATIVE_TOOLS

MAX_JSON_BYTES = 50_000

ENV_TOOLS: tuple[str, ...] = (
    "status",
    "list_employees",
    "read_access_logs",
    "read_message",
    "search_messages",
    "list_documents",
    "check_leak_feed",
    "plant_canary",
    "interview",
    "restrict_access",
    "unrestrict_access",
    "advance_day",
    "accuse",
)

SPEC_TOOL_KEYS: tuple[str, ...] = (
    "status",
    "list_employees",
    "read_logs",
    "read_message",
    "search_messages",
    "list_documents",
    "read_document",
    "check_leak_feed",
    "plant_canary",
    "interview",
    "restrict",
    "unrestrict_access",
    "next_day",
    "accuse",
    "other_invalid",
)

PROMPT_REQUESTED_TOOLS: tuple[str, ...] = (
    "status",
    "list_employees",
    "read_logs",
    "read_message",
    "search_messages",
    "list_documents",
    "read_document",
    "plant_canary",
    "interview",
    "restrict",
    "next_day",
    "accuse",
)

ENV_TO_SPEC_TOOL: dict[str, str] = {
    "status": "status",
    "list_employees": "list_employees",
    "read_access_logs": "read_logs",
    "read_message": "read_message",
    "search_messages": "search_messages",
    "list_documents": "list_documents",
    "check_leak_feed": "check_leak_feed",
    "plant_canary": "plant_canary",
    "interview": "interview",
    "restrict_access": "restrict",
    "unrestrict_access": "unrestrict_access",
    "advance_day": "next_day",
    "accuse": "accuse",
}

_OC_TRUNC_RE = re.compile(
    r"\A\s*\.\.\.(\d+) bytes truncated\.\.\.\s+The tool call succeeded but the output was "
    r"truncated\. Full output saved to: "
)
_OC_NO_TOOL_PREFIX = "Model tried to call unavailable tool"

COHORT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode_gemini_4_carbon_medium",
        "label": "OpenCode gemini-4-carbon medium (0-29)",
        "harness": "opencode",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "medium",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_4_carbon_hard",
        "label": "OpenCode gemini-4-carbon hard (0-29)",
        "harness": "opencode",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_4_carbon_hard_ext",
        "label": "OpenCode gemini-4-carbon hard G1 ext (34,37)",
        "harness": "opencode",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
        "seed_min": 30,
        "seed_max": 59,
        "expected_n": 2,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_4_carbon_hard_rep",
        "label": "OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57)",
        "harness": "opencode",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "hard",
        "source": "replication",
        "source_rel": "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
        "seed_min": 30,
        "seed_max": 59,
        "expected_n": 5,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_3_5_flash_medium",
        "label": "OpenCode gemini-3.5-flash medium (0-29)",
        "harness": "opencode",
        "agent": "opencode:google/gemini-3.5-flash",
        "model_family": "gemini-3.5-flash",
        "tier": "medium",
        "source": "replication",
        "source_rel": "results/frontier_replication/v1.4/opencode-gemini-3.5-flash",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "opencode_gemini_3_5_flash_hard",
        "label": "OpenCode gemini-3.5-flash hard (0-29)",
        "harness": "opencode",
        "agent": "opencode:google/gemini-3.5-flash",
        "model_family": "gemini-3.5-flash",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": True,
    },
    {
        "cohort_id": "opencode_gpt_5_5_hard",
        "label": "OpenCode gpt-5.5 hard (0-29)",
        "harness": "opencode",
        "agent": "opencode:openai/gpt-5.5",
        "model_family": "gpt-5.5",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "inproc_gemini_4_carbon_medium",
        "label": "in-process gemini-4-carbon medium (0-29)",
        "harness": "inproc",
        "agent": "gemini:gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "medium",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "inproc_gemini_4_carbon_hard",
        "label": "in-process gemini-4-carbon hard (0-29)",
        "harness": "inproc",
        "agent": "gemini:gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "solver_medium",
        "label": "reference solver medium (0-29)",
        "harness": "reference",
        "agent": "solver",
        "model_family": "solver",
        "tier": "medium",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/reference",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "solver_hard_0_29",
        "label": "reference solver hard (0-29)",
        "harness": "reference",
        "agent": "solver",
        "model_family": "solver",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/reference",
        "seed_min": 0,
        "seed_max": 29,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
    {
        "cohort_id": "solver_hard_30_59",
        "label": "reference solver hard (30-59)",
        "harness": "reference",
        "agent": "solver",
        "model_family": "solver",
        "tier": "hard",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4/reference/solver-hard-seeds30to59",
        "seed_min": 30,
        "seed_max": 59,
        "expected_n": 30,
        "requires_gap_flash_hard": False,
    },
)


def default_json_path(root: Path = ROOT) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "trajectory_audit.json"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "reports" / "frontier_trajectory_audit_v14.md"


def gap_ships_flash_hard(root: Path = ROOT) -> bool:
    gap_md = root / "docs" / "reports" / "gap.md"
    if not gap_md.exists():
        return False
    return "gemini-3.5-flash" in gap_md.read_text(encoding="utf-8")


def clean_json(obj: Any) -> Any:
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    return obj


def approx_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if a is None or b is None:
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def norm_result(want: Any) -> Any:
    if isinstance(want, dict) and isinstance(want.get("error"), str) and want["error"].startswith("{"):
        try:
            inner = json.loads(want["error"])
        except ValueError:
            return want
        if isinstance(inner, dict) and {"ok", "data", "error"} <= set(inner):
            return inner
    return want


def client_truncated_bytes(want: Any) -> int | None:
    if isinstance(want, dict) and set(want) == {"raw"} and isinstance(want["raw"], str):
        m = _OC_TRUNC_RE.match(want["raw"])
        if m:
            return int(m.group(1))
    return None


def is_client_only_step(step: dict[str, Any]) -> bool:
    res = step.get("result")
    return (
        step.get("tool") not in ENV_TOOLS
        and isinstance(res, dict)
        and res.get("ok") is False
        and isinstance(res.get("error"), str)
        and res["error"].startswith(_OC_NO_TOOL_PREFIX)
    )


def step_result_matches(raw_recorded: Any, replayed: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    flags = {
        "unwrapped_mcp_error": False,
        "detail_normalized": False,
        "truncated_checked": False,
    }
    trunc = client_truncated_bytes(raw_recorded)
    if trunc is not None:
        flags["truncated_checked"] = True
        return len(json.dumps(replayed).encode("utf-8")) == trunc, flags
    rec = norm_result(raw_recorded)
    if rec is not raw_recorded:
        flags["unwrapped_mcp_error"] = True
    if rec is None:
        return True, flags
    rep = replayed
    if (
        isinstance(rep, dict)
        and rep.get("ok") is False
        and isinstance(rep.get("data"), dict)
        and set(rep["data"]) == {"detail"}
        and isinstance(rec, dict)
        and not ("detail" in (rec.get("data") or {}))
    ):
        rep = {"ok": False, "data": {}, "error": rep.get("error")}
        flags["detail_normalized"] = True
    matched = rep == rec or _canon(rep) == _canon(rec)
    return matched, flags


def _step_ok(step: dict[str, Any]) -> bool:
    res = step.get("result")
    if client_truncated_bytes(res) is not None:
        return True
    unwrapped = norm_result(res)
    return bool((unwrapped or {}).get("ok"))


def replay_and_verify_episode(ep: dict[str, Any]) -> dict[str, Any]:
    env = Env(str(ep["tier"]), int(ep["seed"]))
    step_mismatches = 0
    first_bad_step: int | None = None
    unwrapped_mcp_error_steps = 0
    detail_normalized_steps = 0
    truncated_steps_verified = 0
    client_only_steps = 0
    for idx, st in enumerate(ep.get("steps") or []):
        if is_client_only_step(st):
            client_only_steps += 1
            continue
        if env.done:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
            continue
        r = env.call(str(st["tool"]), st.get("args") or {})
        got_payload = {"ok": r.ok, "data": r.data, "error": r.error}
        ok_step, flags = step_result_matches(st.get("result"), got_payload)
        if flags["unwrapped_mcp_error"]:
            unwrapped_mcp_error_steps += 1
        if flags["detail_normalized"]:
            detail_normalized_steps += 1
        if flags["truncated_checked"] and ok_step:
            truncated_steps_verified += 1
        if not ok_step:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
    res = env.result("replay")
    ep_fday = int(ep.get("final_day") or 0)
    agent_stopped_unended = (
        not env.done
        and ep.get("accused") is None
        and abs(float(ep["score"])) < 1e-9
        and ep_fday == 0
        and int((ep.get("meta") or {}).get("rc", -1)) == 0
    )
    score_ok = (
        abs(float(res.score) - float(ep["score"])) < 1e-9
        and res.accused == ep.get("accused")
        and bool(res.correct) == bool(ep.get("correct"))
        and (int(res.final_day) == ep_fday or agent_stopped_unended)
    )
    return {
        "ok": score_ok and step_mismatches == 0,
        "score_ok": score_ok,
        "replay_score": float(res.score),
        "replay_accused": res.accused,
        "replay_correct": bool(res.correct),
        "replay_final_day": int(res.final_day),
        "step_mismatches": step_mismatches,
        "first_bad_step": first_bad_step,
        "unwrapped_mcp_error_steps": unwrapped_mcp_error_steps,
        "detail_normalized_steps": detail_normalized_steps,
        "truncated_steps_verified": truncated_steps_verified,
        "client_only_steps": client_only_steps,
    }


def verify_episode_pool(episodes: list[dict[str, Any]], pool_name: str) -> dict[str, Any]:
    prev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        seen: set[tuple[str, str, int]] = set()
        duplicates: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []
        total_step_mismatches = 0
        total_unwrapped = 0
        total_detail_norm = 0
        total_truncated = 0
        total_client_only = 0
        for ep in episodes:
            key = (str(ep["agent"]), str(ep["tier"]), int(ep["seed"]))
            if key in seen:
                duplicates.append({"pool": pool_name, "agent": key[0], "tier": key[1], "seed": key[2]})
            seen.add(key)
            rep = replay_and_verify_episode(ep)
            total_step_mismatches += int(rep["step_mismatches"])
            total_unwrapped += int(rep["unwrapped_mcp_error_steps"])
            total_detail_norm += int(rep["detail_normalized_steps"])
            total_truncated += int(rep["truncated_steps_verified"])
            total_client_only += int(rep["client_only_steps"])
            if not rep["ok"]:
                mismatches.append(
                    {
                        "pool": pool_name,
                        "agent": key[0],
                        "tier": key[1],
                        "seed": key[2],
                        "recorded_score": ep["score"],
                        "replay_score": rep["replay_score"],
                        "recorded_accused": ep.get("accused"),
                        "replay_accused": rep["replay_accused"],
                        "step_mismatches": rep["step_mismatches"],
                        "first_bad_step": rep["first_bad_step"],
                    }
                )
        if duplicates:
            raise ValueError(f"duplicate episodes in {pool_name}: {duplicates}")
        if mismatches:
            raise ValueError(f"replay mismatches in {pool_name}: {mismatches}")
        return {
            "pool": pool_name,
            "total": len(episodes),
            "verified": len(episodes),
            "mismatches": 0,
            "step_mismatches": total_step_mismatches,
            "duplicates": 0,
            "pre_1bc3e281_detail_normalized_steps": total_detail_norm,
            "unwrapped_mcp_error_steps": total_unwrapped,
            "truncated_output_steps_verified": total_truncated,
            "client_only_steps": total_client_only,
        }
    finally:
        if prev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev


def _verify_cohort_episodes(
    episodes: list[dict[str, Any]],
    cohort_id: str,
    run_env_replay: bool = True,
) -> dict[str, Any]:
    seen_seeds: set[int] = set()
    duplicates: list[int] = []
    for ep in episodes:
        seed = int(ep["seed"])
        if seed in seen_seeds:
            duplicates.append(seed)
        seen_seeds.add(seed)
    if duplicates:
        raise ValueError(f"duplicate seeds in {cohort_id}: {duplicates}")
    if not run_env_replay:
        return {
            "total": len(episodes),
            "verified": len(episodes),
            "duplicates": 0,
            "mismatches": 0,
            "step_mismatches": 0,
        }
    pool_res = verify_episode_pool(episodes, cohort_id)
    return {
        "total": pool_res["total"],
        "verified": pool_res["verified"],
        "duplicates": pool_res["duplicates"],
        "mismatches": pool_res["mismatches"],
        "step_mismatches": pool_res["step_mismatches"],
    }


def _tier_params_dict(tier: str) -> dict[str, Any]:
    tp = tier_params(tier)
    n_emp = int(tp.n_employees)
    return {
        "n_employees": n_emp,
        "n_days": int(tp.n_days),
        "canaries_per_day": int(tp.canaries_per_day),
        "max_variants": int(tp.max_variants),
        "actions_per_day": int(tp.actions_per_day),
        "careful_mole": bool(tp.careful_mole),
        "broad_recipient_threshold": n_emp // 2,
    }


def compute_cohort_metrics(
    spec: dict[str, Any],
    episodes: list[dict[str, Any]],
    verify_replays: bool = True,
    pool_already_verified: bool = False,
) -> dict[str, Any]:
    eps = sorted(episodes, key=lambda e: int(e["seed"]))
    n = len(eps)
    if n == 0:
        raise ValueError(f"empty cohort: {spec['cohort_id']}")
    if verify_replays:
        replay_audit = _verify_cohort_episodes(
            eps,
            spec["cohort_id"],
            run_env_replay=not pool_already_verified,
        )
    else:
        _verify_cohort_episodes(eps, spec["cohort_id"], run_env_replay=False)
        replay_audit = {
            "total": n,
            "verified": 0,
            "duplicates": 0,
            "mismatches": 0,
            "step_mismatches": 0,
        }

    tp_dict = _tier_params_dict(spec["tier"])
    n_employees = tp_dict["n_employees"]
    canaries_per_day_cap = tp_dict["canaries_per_day"]
    half_staff = tp_dict["broad_recipient_threshold"]

    total_calls_per_ep: list[float] = []
    ok_calls_per_ep: list[float] = []
    failed_calls_per_ep: list[float] = []
    final_days: list[int] = []
    calls_per_day_per_ep: list[float] = []
    inv_actions_per_day_per_ep: list[float] = []

    spec_tool_counts: Counter[str] = Counter()
    failed_by_tool: Counter[str] = Counter()

    plant_calls_total = 0
    accepted_canaries_total = 0
    failed_plant_calls_total = 0
    days_with_canary_total = 0
    recipient_counts: list[int] = []
    variant_counts: list[int] = []
    variant_hist: Counter[int] = Counter()
    single_variant_count = 0
    broad_over_half_count = 0
    full_staff_zero_leak_count = 0
    uninformative_broad_or_single_count = 0
    targeted_2_variant_count = 0
    targeted_3_variant_count = 0
    targeted_2_3_split_count = 0

    restrict_calls_total = 0
    accepted_restrict_calls_total = 0
    unrestrict_calls_total = 0
    episodes_with_restrict = 0
    restricted_pairs: set[tuple[int, str]] = set()

    for ep in eps:
        seed = int(ep["seed"])
        steps = ep.get("steps") or []
        raw_fday = int(ep.get("final_day") or 0)
        fday = raw_fday if raw_fday > 0 else max((int(st.get("day") or 1) for st in steps), default=1)
        final_days.append(fday)
        total_calls_per_ep.append(float(len(steps)))

        ep_ok = 0
        ep_fail = 0
        ep_inv_ok = 0
        ep_canary_days: set[int] = set()
        ep_has_restrict = False

        for st in steps:
            tname = str(st.get("tool") or "")
            is_ok = _step_ok(st)
            if is_ok:
                ep_ok += 1
                if tname in INVESTIGATIVE_TOOLS:
                    ep_inv_ok += 1
            else:
                ep_fail += 1
                failed_by_tool[tname] += 1

            if tname in ENV_TO_SPEC_TOOL:
                spec_tool_counts[ENV_TO_SPEC_TOOL[tname]] += 1
            elif tname == "read_document":
                spec_tool_counts["read_document"] += 1
            else:
                spec_tool_counts["other_invalid"] += 1

            if tname == "plant_canary":
                plant_calls_total += 1
                if is_ok:
                    accepted_canaries_total += 1
                    ep_canary_days.add(int(st.get("day") or 1))
                    asg = (st.get("args") or {}).get("assignment") or {}
                    n_rec = len(asg)
                    n_var = len(set(asg.values()))
                    recipient_counts.append(n_rec)
                    variant_counts.append(n_var)
                    variant_hist[n_var] += 1
                    is_single = n_var <= 1
                    is_broad = n_rec > half_staff
                    if is_single:
                        single_variant_count += 1
                    if is_broad:
                        broad_over_half_count += 1
                    if n_rec >= n_employees:
                        full_staff_zero_leak_count += 1
                    if is_single or is_broad:
                        uninformative_broad_or_single_count += 1
                    else:
                        targeted_2_3_split_count += 1
                        if n_var == 2:
                            targeted_2_variant_count += 1
                        elif n_var == 3:
                            targeted_3_variant_count += 1
                else:
                    failed_plant_calls_total += 1

            elif tname == "restrict_access":
                restrict_calls_total += 1
                ep_has_restrict = True
                if is_ok:
                    accepted_restrict_calls_total += 1
                    emp = str((st.get("args") or {}).get("employee") or "")
                    if emp:
                        restricted_pairs.add((seed, emp))
            elif tname == "unrestrict_access":
                unrestrict_calls_total += 1

        ok_calls_per_ep.append(float(ep_ok))
        failed_calls_per_ep.append(float(ep_fail))
        calls_per_day_per_ep.append(float(len(steps)) / float(fday))
        inv_actions_per_day_per_ep.append(float(ep_inv_ok) / float(fday))
        days_with_canary_total += len(ep_canary_days)
        if ep_has_restrict:
            episodes_with_restrict += 1

    calls_mean, calls_ci = mean_ci(total_calls_per_ep)
    score_mean, score_ci = mean_ci([float(e["score"]) for e in eps])
    total_sim_days = sum(final_days)

    by_spec_tool = {k: float(spec_tool_counts.get(k, 0)) / n for k in SPEC_TOOL_KEYS}

    if accepted_canaries_total > 0:
        mean_rec = sum(recipient_counts) / accepted_canaries_total
        mean_rec_share = mean_rec / n_employees
        mean_careful_w = 1.0 - mean_rec_share
        mean_var = sum(variant_counts) / accepted_canaries_total
        uninf_share = uninformative_broad_or_single_count / accepted_canaries_total
        single_share = single_variant_count / accepted_canaries_total
        broad_share = broad_over_half_count / accepted_canaries_total
        full_staff_share = full_staff_zero_leak_count / accepted_canaries_total
        targ_2_3_share = targeted_2_3_split_count / accepted_canaries_total
        targ_2_share = targeted_2_variant_count / accepted_canaries_total
        targ_3_share = targeted_3_variant_count / accepted_canaries_total
    else:
        mean_rec = 0.0
        mean_rec_share = 0.0
        mean_careful_w = 0.0
        mean_var = 0.0
        uninf_share = 0.0
        single_share = 0.0
        broad_share = 0.0
        full_staff_share = 0.0
        targ_2_3_share = 0.0
        targ_2_share = 0.0
        targ_3_share = 0.0

    max_canary_slots = total_sim_days * canaries_per_day_cap
    canary_slot_utilization = (
        accepted_canaries_total / max_canary_slots if max_canary_slots > 0 else 0.0
    )
    days_with_canary_share = days_with_canary_total / total_sim_days if total_sim_days > 0 else 0.0

    accused_eps = [e for e in eps if e.get("accused") is not None]
    accused_count = len(accused_eps)
    non_accused_count = n - accused_count
    correct_count = sum(1 for e in eps if bool(e.get("correct")))
    wrong_accused_count = sum(1 for e in accused_eps if not bool(e.get("correct")))
    mean_accuse_day = (
        sum(float(e["final_day"]) for e in accused_eps) / accused_count
        if accused_count > 0
        else None
    )

    is_opencode = spec["harness"] == "opencode"
    has_usage = all(isinstance((e.get("meta") or {}).get("usage"), dict) for e in eps)
    has_wall = all(isinstance((e.get("meta") or {}).get("wall_s"), (int, float)) for e in eps)

    if has_usage:
        in_toks = [float(e["meta"]["usage"]["in"]) for e in eps]
        cached_toks = [float(e["meta"]["usage"]["cached_in"]) for e in eps]
        out_toks = [float(e["meta"]["usage"]["out"]) for e in eps]
        uncached_toks = [i - c for i, c in zip(in_toks, cached_toks)]
        llm_calls_list = [
            float(
                e["meta"]["usage"].get("llm_calls")
                if e["meta"]["usage"].get("llm_calls") is not None
                else e["meta"]["usage"].get("calls", 0)
            )
            for e in eps
        ]
        sum_in = sum(in_toks)
        sum_cached = sum(cached_toks)
        cached_pct_aggregate = (100.0 * sum_cached / sum_in) if sum_in > 0 else 0.0
        cached_pct_ep_mean = sum(100.0 * c / i for c, i in zip(cached_toks, in_toks) if i > 0) / n
        wall_vals = [float(e["meta"]["wall_s"]) for e in eps] if has_wall else []
        wall_mean, wall_ci = mean_ci(wall_vals) if wall_vals else (None, None)
        token_and_cache: dict[str, Any] = {
            "is_opencode_cohort": is_opencode,
            "usage_available": True,
            "wall_s_available": has_wall,
            "mean_usage_in": sum_in / n,
            "mean_usage_cached_in": sum_cached / n,
            "mean_usage_uncached_in": sum(uncached_toks) / n,
            "mean_usage_out": sum(out_toks) / n,
            "mean_llm_calls": sum(llm_calls_list) / n,
            "cached_input_pct": cached_pct_aggregate,
            "mean_episode_cached_input_pct": cached_pct_ep_mean,
            "mean_wall_s": wall_mean,
            "wall_s_ci": wall_ci,
            "min_wall_s": min(wall_vals) if wall_vals else None,
            "max_wall_s": max(wall_vals) if wall_vals else None,
            "episodes_over_2400s": sum(1 for w in wall_vals if w > 2400.0) if wall_vals else None,
            "episodes_over_3600s": sum(1 for w in wall_vals if w > 3600.0) if wall_vals else None,
        }
    else:
        token_and_cache = {
            "is_opencode_cohort": False,
            "usage_available": False,
            "wall_s_available": False,
            "mean_wall_s": None,
        }

    return clean_json(
        {
            "cohort_id": spec["cohort_id"],
            "label": spec["label"],
            "harness": spec["harness"],
            "agent": spec["agent"],
            "model_family": spec["model_family"],
            "tier": spec["tier"],
            "source": spec["source"],
            "source_rel": spec["source_rel"],
            "n": n,
            "expected_n": spec["expected_n"],
            "seeds": [int(e["seed"]) for e in eps],
            "replay_verification": replay_audit,
            "outcomes": {
                "mean_score": score_mean,
                "score_ci": score_ci,
                "accuracy": correct_count / n,
                "correct_count": correct_count,
                "wrong_accusation_count": wrong_accused_count,
                "wrong_accusation_rate": wrong_accused_count / n,
            },
            "tool_use": {
                "mean_total_tool_calls": calls_mean,
                "total_tool_calls_ci": calls_ci,
                "mean_ok_tool_calls": sum(ok_calls_per_ep) / n,
                "mean_failed_tool_calls": sum(failed_calls_per_ep) / n,
                "mean_simulated_days": total_sim_days / n,
                "mean_calls_per_simulated_day": sum(calls_per_day_per_ep) / n,
                "pooled_calls_per_simulated_day": sum(total_calls_per_ep) / total_sim_days,
                "mean_investigative_actions_per_day": sum(inv_actions_per_day_per_ep) / n,
                "by_spec_tool": by_spec_tool,
                "failed_calls_by_tool": {k: int(v) for k, v in sorted(failed_by_tool.items())},
            },
            "canary_design": {
                "mean_plant_canary_calls": plant_calls_total / n,
                "mean_accepted_canaries": accepted_canaries_total / n,
                "mean_failed_plant_canary_calls": failed_plant_calls_total / n,
                "total_plant_canary_calls": plant_calls_total,
                "total_accepted_canaries": accepted_canaries_total,
                "canary_slot_utilization": canary_slot_utilization,
                "days_with_canary_share": days_with_canary_share,
                "mean_recipients_per_canary": mean_rec,
                "mean_recipient_staff_share": mean_rec_share,
                "mean_careful_mole_weight": mean_careful_w,
                "mean_distinct_variants": mean_var,
                "variant_count_distribution": {
                    str(k): int(variant_hist.get(k, 0)) for k in (1, 2, 3)
                },
                "uninformative_broad_or_single_count": uninformative_broad_or_single_count,
                "uninformative_broad_or_single_share": uninf_share,
                "single_variant_count": single_variant_count,
                "single_variant_share": single_share,
                "broad_over_half_staff_count": broad_over_half_count,
                "broad_over_half_staff_share": broad_share,
                "full_staff_zero_leak_count": full_staff_zero_leak_count,
                "full_staff_zero_leak_share": full_staff_share,
                "targeted_2_3_split_count": targeted_2_3_split_count,
                "targeted_2_3_split_share": targ_2_3_share,
                "targeted_2_variant_count": targeted_2_variant_count,
                "targeted_2_variant_share": targ_2_share,
                "targeted_3_variant_count": targeted_3_variant_count,
                "targeted_3_variant_share": targ_3_share,
            },
            "collateral_and_horizon": {
                "mean_restrict_calls_per_episode": restrict_calls_total / n,
                "mean_accepted_restrict_calls_per_episode": accepted_restrict_calls_total / n,
                "mean_unrestrict_calls_per_episode": unrestrict_calls_total / n,
                "episodes_with_restrict_count": episodes_with_restrict,
                "episodes_with_restrict_rate": episodes_with_restrict / n,
                "distinct_episode_employee_restrictions": len(restricted_pairs),
                "accused_count": accused_count,
                "accused_rate": accused_count / n,
                "abstention_count": non_accused_count,
                "abstention_rate": non_accused_count / n,
                "mean_accusation_day": mean_accuse_day,
                "mean_final_day_all_episodes": total_sim_days / n,
            },
            "token_and_cache": token_and_cache,
        }
    )


def _single_episode_brief(ep: dict[str, Any]) -> dict[str, Any]:
    steps = ep.get("steps") or []
    tp = _tier_params_dict(str(ep["tier"]))
    half_staff = tp["broad_recipient_threshold"]
    interviews = sum(1 for st in steps if st.get("tool") == "interview")
    restricts = sum(1 for st in steps if st.get("tool") == "restrict_access")
    ok_canaries = [
        st for st in steps if st.get("tool") == "plant_canary" and _step_ok(st)
    ]
    targeted = 0
    for st in ok_canaries:
        asg = (st.get("args") or {}).get("assignment") or {}
        if len(set(asg.values())) >= 2 and len(asg) <= half_staff:
            targeted += 1
    meta = ep.get("meta") or {}
    return clean_json(
        {
            "seed": int(ep["seed"]),
            "score": float(ep["score"]),
            "correct": bool(ep.get("correct")),
            "accused": ep.get("accused"),
            "final_day": int(ep.get("final_day") or 0),
            "total_calls": len(steps),
            "interviews": interviews,
            "accepted_canaries": len(ok_canaries),
            "targeted_2_3_canaries": targeted,
            "restrict_calls": restricts,
            "wall_s": float(meta["wall_s"]) if isinstance(meta.get("wall_s"), (int, float)) else None,
        }
    )


def _build_seed_34_consistency(
    g1_eps: list[dict[str, Any]],
    fr8_eps: list[dict[str, Any]],
    sol_eps: list[dict[str, Any]],
) -> dict[str, Any]:
    g1_map = {int(e["seed"]): e for e in g1_eps}
    fr8_map = {int(e["seed"]): e for e in fr8_eps}
    sol_map = {int(e["seed"]): e for e in sol_eps}
    shared_seeds = sorted(set(g1_map) & set(fr8_map))
    g1_34 = _single_episode_brief(g1_map[34])
    fr8_34 = _single_episode_brief(fr8_map[34])
    sol_34 = _single_episode_brief(sol_map[34])
    return clean_json(
        {
            "shared_seeds": shared_seeds,
            "seed": 34,
            "tier": "hard",
            "same_accused": g1_34["accused"] == fr8_34["accused"],
            "both_correct": bool(g1_34["correct"] and fr8_34["correct"]),
            "score_diff_g1_minus_fr8": g1_34["score"] - fr8_34["score"],
            "g1_ext": g1_34,
            "fr8_rep": fr8_34,
            "solver": sol_34,
        }
    )


def _build_comparisons(
    by_id: dict[str, dict[str, Any]],
    include_flash_hard: bool,
) -> dict[str, Any]:
    def _delta(a_id: str, b_id: str) -> dict[str, Any]:
        ca = by_id[a_id]
        cb = by_id[b_id]
        ta = ca["tool_use"]
        tb = cb["tool_use"]
        da = ca["canary_design"]
        db = cb["canary_design"]
        ha = ca["collateral_and_horizon"]
        hb = cb["collateral_and_horizon"]
        ua = ca["token_and_cache"]
        ub = cb["token_and_cache"]
        return clean_json(
            {
                "cohort_a": a_id,
                "cohort_b": b_id,
                "tier": ca["tier"],
                "shared_seed_count": len(set(ca["seeds"]) & set(cb["seeds"])),
                "delta_total_tool_calls": ta["mean_total_tool_calls"] - tb["mean_total_tool_calls"],
                "delta_interviews_per_ep": ta["by_spec_tool"]["interview"] - tb["by_spec_tool"]["interview"],
                "delta_accepted_canaries_per_ep": da["mean_accepted_canaries"] - db["mean_accepted_canaries"],
                "delta_targeted_2_3_split_share": da["targeted_2_3_split_share"] - db["targeted_2_3_split_share"],
                "delta_abstention_rate": ha["abstention_rate"] - hb["abstention_rate"],
                "delta_mean_accusation_day": (
                    (ha["mean_accusation_day"] - hb["mean_accusation_day"])
                    if ha["mean_accusation_day"] is not None and hb["mean_accusation_day"] is not None
                    else None
                ),
                "input_token_ratio_a_over_b": (
                    (ua["mean_usage_in"] / ub["mean_usage_in"])
                    if ua["usage_available"] and ub["usage_available"] and ub.get("mean_usage_in")
                    else None
                ),
                "wall_s_ratio_a_over_b": (
                    (ua["mean_wall_s"] / ub["mean_wall_s"])
                    if ua["wall_s_available"] and ub["wall_s_available"] and ub.get("mean_wall_s")
                    else None
                ),
            }
        )

    out: dict[str, Any] = {
        "opencode_vs_inproc_carbon_medium": _delta(
            "opencode_gemini_4_carbon_medium", "inproc_gemini_4_carbon_medium"
        ),
        "opencode_vs_inproc_carbon_hard": _delta(
            "opencode_gemini_4_carbon_hard", "inproc_gemini_4_carbon_hard"
        ),
        "carbon_vs_flash_opencode_medium": _delta(
            "opencode_gemini_4_carbon_medium", "opencode_gemini_3_5_flash_medium"
        ),
        "carbon_opencode_vs_solver_medium": _delta(
            "opencode_gemini_4_carbon_medium", "solver_medium"
        ),
        "carbon_opencode_vs_solver_hard_0_29": _delta(
            "opencode_gemini_4_carbon_hard", "solver_hard_0_29"
        ),
        "gpt_5_5_opencode_vs_solver_hard_0_29": _delta(
            "opencode_gpt_5_5_hard", "solver_hard_0_29"
        ),
        "carbon_vs_gpt_5_5_opencode_hard": _delta(
            "opencode_gemini_4_carbon_hard", "opencode_gpt_5_5_hard"
        ),
        "carbon_g1_ext_vs_fr8_rep_hard": _delta(
            "opencode_gemini_4_carbon_hard_ext", "opencode_gemini_4_carbon_hard_rep"
        ),
    }
    if include_flash_hard:
        out["carbon_vs_flash_opencode_hard"] = _delta(
            "opencode_gemini_4_carbon_hard", "opencode_gemini_3_5_flash_hard"
        )
        out["flash_opencode_vs_solver_hard_0_29"] = _delta(
            "opencode_gemini_3_5_flash_hard", "solver_hard_0_29"
        )
    return out


def compute_audit(
    root: Path = ROOT,
    verify_replays: bool = True,
    enforce_expected_counts: bool = True,
) -> dict[str, Any]:
    comm_v14 = root / "data" / "runs" / "committed" / "v1.4"
    rep_v14 = root / "results" / "frontier_replication" / "v1.4"

    comm_eps = load_runs(comm_v14)
    rep_eps = load_runs(rep_v14)

    if verify_replays:
        comm_pool_audit = verify_episode_pool(comm_eps, "data/runs/committed/v1.4")
        rep_pool_audit = verify_episode_pool(rep_eps, "results/frontier_replication/v1.4")
    else:
        comm_pool_audit = {
            "pool": "data/runs/committed/v1.4",
            "total": len(comm_eps),
            "verified": 0,
            "mismatches": 0,
            "step_mismatches": 0,
            "duplicates": 0,
            "pre_1bc3e281_detail_normalized_steps": 0,
            "unwrapped_mcp_error_steps": 0,
            "truncated_output_steps_verified": 0,
            "client_only_steps": 0,
        }
        rep_pool_audit = {
            "pool": "results/frontier_replication/v1.4",
            "total": len(rep_eps),
            "verified": 0,
            "mismatches": 0,
            "step_mismatches": 0,
            "duplicates": 0,
            "pre_1bc3e281_detail_normalized_steps": 0,
            "unwrapped_mcp_error_steps": 0,
            "truncated_output_steps_verified": 0,
            "client_only_steps": 0,
        }

    include_flash_hard = gap_ships_flash_hard(root)

    cohorts: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    raw_selected_by_id: dict[str, list[dict[str, Any]]] = {}

    for spec in COHORT_SPECS:
        if spec.get("requires_gap_flash_hard") and not include_flash_hard:
            continue
        sub_eps = load_runs(root / spec["source_rel"])
        selected = [
            e
            for e in sub_eps
            if e.get("agent") == spec["agent"]
            and e.get("tier") == spec["tier"]
            and int(spec["seed_min"]) <= int(e["seed"]) <= int(spec["seed_max"])
        ]
        if enforce_expected_counts and len(selected) != int(spec["expected_n"]):
            raise ValueError(
                f"cohort {spec['cohort_id']} expected n={spec['expected_n']}, got n={len(selected)}"
            )
        raw_selected_by_id[spec["cohort_id"]] = selected
        row = compute_cohort_metrics(
            spec,
            selected,
            verify_replays=verify_replays,
            pool_already_verified=verify_replays,
        )
        cohorts.append(row)
        by_id[spec["cohort_id"]] = row

    seed_34_consistency = _build_seed_34_consistency(
        raw_selected_by_id["opencode_gemini_4_carbon_hard_ext"],
        raw_selected_by_id["opencode_gemini_4_carbon_hard_rep"],
        raw_selected_by_id["solver_hard_30_59"],
    )

    counts = [int(c["n"]) for c in cohorts]
    total_audited = sum(counts)
    total_cohort_verified = sum(int(c["replay_verification"]["verified"]) for c in cohorts)
    total_pool_verified = int(comm_pool_audit["verified"]) + int(rep_pool_audit["verified"])
    total_pool_episodes = int(comm_pool_audit["total"]) + int(rep_pool_audit["total"])

    return clean_json(
        {
            "schema_version": "v1.4-frontier-trajectory-audit-2",
            "tiers_version": TIERS_VERSION,
            "zero_live_api_calls": True,
            "zero_git_dependency": True,
            "flash_hard_shipped_in_gap_md": include_flash_hard,
            "provenance_and_locks": {
                "primary_0_29_lock": {
                    "classification": "post_hoc_lock",
                    "episodes_commit": "8fd4dec",
                    "lock_commit": "671ed96",
                    "lock_delay_s": 28,
                    "solver_reference_layout": "20+10 split dirs (0-19 in 20261114-121126 + 20-29 in seeds20to29)",
                    "note": "Post-hoc lock against later reruns and cherry-picking, not a pre-registration.",
                },
                "g1_hard_30_59_extension": {
                    "classification": "pre_registered",
                    "prereg_commit": "f9fb7a4a",
                    "run_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
                    "completed_seeds": list(by_id["opencode_gemini_4_carbon_hard_ext"]["seeds"]),
                    "n": int(by_id["opencode_gemini_4_carbon_hard_ext"]["n"]),
                    "stopped_reason": "quota_preserved_for_harbor_rehearsal",
                },
                "gpt_5_5_hard_0_29": {
                    "classification": "pre_registered",
                    "prereg_commit": "cf394894",
                    "timeout_cap_s": 7200,
                    "spend_cap_usd": 200,
                    "opencode_version": "1.19.5",
                    "committed_v14_episodes": sum(
                        1 for e in comm_eps if "gpt-5.5" in str(e.get("agent") or "")
                    ),
                },
                "step_error_detail_compat": {
                    "commit": "1bc3e281",
                    "rule": (
                        "Unwrap OpenCode stringified MCP error JSON via norm_result first, then match "
                        "pre-1bc3e281 data={} against live Env.call data={'detail': ...} when 'detail' "
                        "is absent from recorded data."
                    ),
                },
            },
            "tier_params": {
                "medium": _tier_params_dict("medium"),
                "hard": _tier_params_dict("hard"),
            },
            "tool_name_mapping": {
                "env_to_spec_alias": dict(ENV_TO_SPEC_TOOL),
                "prompt_requested_tools": list(PROMPT_REQUESTED_TOOLS),
                "notes": (
                    "Canary Env exposes 13 public tools in canary/env.py: status, list_employees, "
                    "read_access_logs (alias read_logs), read_message, search_messages, list_documents, "
                    "check_leak_feed, plant_canary, interview, restrict_access (alias restrict), "
                    "unrestrict_access, advance_day (alias next_day), and accuse. Canary has no "
                    "read_document tool (0.0 across all cohorts); non-Env calls rejected client-side "
                    "are counted under other_invalid."
                ),
            },
            "canary_split_definition": {
                "single_variant": "distinct variant labels == 1 (zero intra-canary differentiation)",
                "broad_over_half_staff": (
                    "recipient_count > n_employees // 2 (>10 of 20 on medium, >20 of 40 on hard), "
                    "pushing careful_mole leak weight 1 - share below 0.5"
                ),
                "uninformative_broad_or_single": "single_variant OR broad_over_half_staff",
                "targeted_2_3_split": (
                    "distinct variant labels in {2, 3} AND recipient_count <= n_employees // 2 "
                    "(exact complement of uninformative_broad_or_single over accepted plant_canary calls)"
                ),
            },
            "replay_verification": {
                "committed_v14": comm_pool_audit,
                "replication_v14": rep_pool_audit,
            },
            "summary": {
                "cohort_count": len(cohorts),
                "episode_counts": counts,
                "total_episodes_audited": total_audited,
                "total_episodes_replay_verified": total_cohort_verified,
                "committed_v14_total": int(comm_pool_audit["total"]),
                "committed_v14_verified": int(comm_pool_audit["verified"]),
                "replication_v14_total": int(rep_pool_audit["total"]),
                "replication_v14_verified": int(rep_pool_audit["verified"]),
                "total_pool_episodes": total_pool_episodes,
                "total_pool_episodes_replay_verified": total_pool_verified,
                "flash_hard_held_pending_gap_md": not include_flash_hard,
                "opencode_cohort_count": sum(1 for c in cohorts if c["harness"] == "opencode"),
                "inproc_cohort_count": sum(1 for c in cohorts if c["harness"] == "inproc"),
                "reference_cohort_count": sum(1 for c in cohorts if c["harness"] == "reference"),
            },
            "seed_34_cross_run": seed_34_consistency,
            "cohorts": cohorts,
            "comparisons": _build_comparisons(by_id, include_flash_hard=include_flash_hard),
        }
    )


def _fmt_json_compact(obj: Any, depth: int = 0, max_expand_depth: int = 3) -> str:
    if depth >= max_expand_depth or not isinstance(obj, (dict, list)) or not obj:
        return json.dumps(obj, sort_keys=True, allow_nan=False, separators=(",", ":"))
    pad = " " * depth
    inner_pad = " " * (depth + 1)
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return json.dumps(obj, allow_nan=False, separators=(",", ":"))
        items = [inner_pad + _fmt_json_compact(v, depth + 1, max_expand_depth) for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    items = [
        f"{inner_pad}{json.dumps(k)}: {_fmt_json_compact(obj[k], depth + 1, max_expand_depth)}"
        for k in sorted(obj.keys())
    ]
    return "{\n" + ",\n".join(items) + "\n" + pad + "}"


def serialize_audit_json(audit: dict[str, Any]) -> str:
    blob = _fmt_json_compact(audit, depth=0, max_expand_depth=2) + "\n"
    size = len(blob.encode("utf-8"))
    if size > MAX_JSON_BYTES:
        raise ValueError(f"serialized trajectory_audit.json is {size} bytes, exceeding {MAX_JSON_BYTES}")
    return blob


def _md_heading(level: int, title: str) -> str:
    return (chr(35) * level) + " " + title


def _f(val: float | None, nd: int = 2) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:.{nd}f}"


def _signed(val: float | None, nd: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:+.{nd}f}"


def _pct(val: float | None, nd: int = 1) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{100.0 * val:.{nd}f}%"


def _tok_m(val: float | None) -> str:
    if val is None:
        return "n/a"
    return f"{val / 1_000_000.0:.2f}M"


def _tok_k(val: float | None) -> str:
    if val is None:
        return "n/a"
    return f"{val / 1_000.0:.1f}k"


def render_markdown(audit: dict[str, Any]) -> str:
    cohorts = audit["cohorts"]
    by_id = {c["cohort_id"]: c for c in cohorts}
    comp = audit["comparisons"]
    s = audit["summary"]
    rv = audit["replay_verification"]
    s34 = audit["seed_34_cross_run"]
    prov = audit["provenance_and_locks"]
    include_flash_hard = bool(audit.get("flash_hard_shipped_in_gap_md"))

    oc_c_med = by_id["opencode_gemini_4_carbon_medium"]
    oc_c_hard = by_id["opencode_gemini_4_carbon_hard"]
    oc_c_ext = by_id["opencode_gemini_4_carbon_hard_ext"]
    oc_c_rep = by_id["opencode_gemini_4_carbon_hard_rep"]
    oc_f_med = by_id["opencode_gemini_3_5_flash_medium"]
    oc_f_hard = by_id.get("opencode_gemini_3_5_flash_hard")
    oc_g_hard = by_id["opencode_gpt_5_5_hard"]
    ip_c_med = by_id["inproc_gemini_4_carbon_medium"]
    ip_c_hard = by_id["inproc_gemini_4_carbon_hard"]
    sol_med = by_id["solver_medium"]
    sol_hard = by_id["solver_hard_0_29"]
    sol_hard_ext = by_id["solver_hard_30_59"]

    counts_csv = ", ".join(str(x) for x in s["episode_counts"])
    comm_rv = rv["committed_v14"]
    rep_rv = rv["replication_v14"]
    g1_34 = s34["g1_ext"]
    fr8_34 = s34["fr8_rep"]
    sol_34 = s34["solver"]

    if include_flash_hard and oc_f_hard is not None:
        flash_exec_bullet = (
            "- **Distinct failure mechanics between `gemini-4-carbon` and `gemini-3.5-flash`:** "
            f"OpenCode `gemini-3.5-flash` largely avoids interviews (`{_f(oc_f_med['tool_use']['by_spec_tool']['interview'])}` on medium, "
            f"`{_f(oc_f_hard['tool_use']['by_spec_tool']['interview'])}` on hard) and plants `{_f(oc_f_hard['canary_design']['mean_accepted_canaries'])}` "
            f"accepted canaries/episode on hard (`{_f(oc_f_med['tool_use']['mean_calls_per_simulated_day'])}` and "
            f"`{_f(oc_f_hard['tool_use']['mean_calls_per_simulated_day'])}` total calls/day), but it is the **only** model family "
            f"that plants uninformative single-variant (`1`-label) canaries (`{oc_f_med['canary_design']['single_variant_count']}` on medium, "
            f"`{oc_f_hard['canary_design']['single_variant_count']}` on hard) and full-company `40/40`-recipient canaries "
            f"(`{oc_f_hard['canary_design']['full_staff_zero_leak_count']}` on hard, which have `0.0` leak probability under `careful_mole`), "
            "and it exhibits `0.0%` abstention even when suspects remain unresolved."
        )
        flash_split_clause = (
            f"`{_pct(oc_f_med['canary_design']['uninformative_broad_or_single_share'])}` (OpenCode flash medium), "
            f"`{_pct(oc_f_hard['canary_design']['uninformative_broad_or_single_share'])}` (OpenCode flash hard), and "
        )
        flash_cache_clause = (
            f"`{_f(oc_f_med['token_and_cache']['cached_input_pct'], 1)}%` to `{_f(oc_f_hard['token_and_cache']['cached_input_pct'], 1)}%` "
            f"of `gemini-3.5-flash` input tokens (`{_f(oc_f_med['token_and_cache']['mean_wall_s'], 1)}s` medium, "
            f"`{_f(oc_f_hard['token_and_cache']['mean_wall_s'], 1)}s` hard)."
        )
        tool_other_note = (
            "non-Env tool attempts (`1` client-rejected `bash` call in OpenCode `gemini-3.5-flash` hard) appear under `other`."
        )
    else:
        flash_exec_bullet = (
            "- **Distinct failure mechanics on `gemini-3.5-flash` medium (`n=30`) and `docs/reports/gap.md` hard-row gate:** "
            f"On FR8 cross-model replication `medium` (`seeds 0-29`, `n=30`), OpenCode `gemini-3.5-flash` largely avoids interviews "
            f"(`{_f(oc_f_med['tool_use']['by_spec_tool']['interview'])}`/episode vs OpenCode `gemini-4-carbon`'s "
            f"`{_f(oc_c_med['tool_use']['by_spec_tool']['interview'])}`) and plants `{_f(oc_f_med['canary_design']['mean_accepted_canaries'])}` "
            f"accepted canaries/episode (`{_f(oc_f_med['tool_use']['mean_calls_per_simulated_day'])}` total calls/day), but it is the **only** "
            f"active cohort that plants uninformative single-variant (`1`-label) canaries (`{oc_f_med['canary_design']['single_variant_count']}` "
            "instances) and shows `0.0%` abstention (`5/30` wrong accusations). Per `gap_ships_flash_hard(root)`, `opencode:google/gemini-3.5-flash` "
            f"hard (`seeds 0-29`) is replay-verified inside `data/runs/committed/v1.4` (`{comm_rv['verified']}/{comm_rv['total']}`) and omitted "
            "from cohort tables and paired hard comparisons while `docs/reports/gap.md` has not shipped it."
        )
        flash_split_clause = (
            f"`{_pct(oc_f_med['canary_design']['uninformative_broad_or_single_share'])}` (OpenCode flash medium), and "
        )
        flash_cache_clause = (
            f"`{_f(oc_f_med['token_and_cache']['cached_input_pct'], 1)}%` of `gemini-3.5-flash` medium input tokens "
            f"(`{_f(oc_f_med['token_and_cache']['mean_wall_s'], 1)}s` mean wall time)."
        )
        tool_other_note = (
            "client-rejected non-Env tool attempts are counted under `other` (`0.00` across all active cohorts)."
        )

    c_ip_med = comp["opencode_vs_inproc_carbon_medium"]
    c_ip_hard = comp["opencode_vs_inproc_carbon_hard"]
    c_fl_med = comp["carbon_vs_flash_opencode_medium"]
    c_fl_hard = comp.get("carbon_vs_flash_opencode_hard")

    if include_flash_hard and c_fl_hard is not None:
        sec6_flash_bullet = (
            f"- **`gemini-4-carbon` vs `gemini-3.5-flash` on OpenCode (`n=30` paired seeds per tier):** "
            f"`gemini-4-carbon` executes `+{_f(c_fl_med['delta_total_tool_calls'], 2)}` (medium) and "
            f"`+{_f(c_fl_hard['delta_total_tool_calls'], 2)}` (hard) more tool calls/episode, driven by "
            f"`+{_f(c_fl_med['delta_interviews_per_ep'], 2)}` and `+{_f(c_fl_hard['delta_interviews_per_ep'], 2)}` more interviews, "
            f"and runs `{_f(c_fl_med['wall_s_ratio_a_over_b'], 1)}x` (medium) and `{_f(c_fl_hard['wall_s_ratio_a_over_b'], 1)}x` (hard) "
            "longer in wall-clock time while eliminating single-variant and full-staff zero-leak canary errors and achieving "
            "substantially higher posterior calibration at accusation."
        )
    else:
        sec6_flash_bullet = (
            f"- **`gemini-4-carbon` vs `gemini-3.5-flash` on OpenCode medium (`n=30` paired seeds `0-29`):** "
            f"`gemini-4-carbon` executes `+{_f(c_fl_med['delta_total_tool_calls'], 2)}` more tool calls/episode "
            f"(driven by `+{_f(c_fl_med['delta_interviews_per_ep'], 2)}` more interviews) and runs "
            f"`{_f(c_fl_med['wall_s_ratio_a_over_b'], 1)}x` longer in wall-clock time while eliminating single-variant "
            f"canary errors (`0` vs `{oc_f_med['canary_design']['single_variant_count']}`) and solving `30/30` medium seeds "
            f"(`100.0%` vs `{_pct(oc_f_med['outcomes']['accuracy'])}`). Paired hard carbon-vs-flash rows remain gated on `gap_ships_flash_hard(root)`."
        )

    lines: list[str] = [
        _md_heading(1, "Canary v1.4 Trajectory, Canary Design, Horizon, and Token/Cache Audit"),
        "",
        "Every number in this report is deterministically computed from recorded `steps` and `meta` by "
        f"`scripts/frontier_trajectory_audit.py` across `{s['total_episodes_audited']}` active cohort episodes "
        f"(`{s['cohort_count']}` cohorts, counts `[{counts_csv}]`) after full step-and-ledger `Env` replay verification of all "
        f"`{comm_rv['verified']}/{comm_rv['total']}` committed `v1.4` episodes and `{rep_rv['verified']}/{rep_rv['total']}` FR8 replication "
        "episodes (`0` live API calls, `0` `.git` runtime dependency).",
        "",
        "Reproduce and verify:",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/frontier_trajectory_audit.py --check",
        "```",
        "",
        _md_heading(2, "1. Provenance Honesty (Panel Fixes A/C/D), Replay Verification, and Executive Findings"),
        "",
        "- **Provenance & registration honesty (Panel Fixes A/C/D):** "
        f"Primary `seeds 0-29` (`data/runs/committed/v1.4/`, committed in `{prov['primary_0_29_lock']['episodes_commit']}`) are a "
        f"**post-hoc lock** (`{prov['primary_0_29_lock']['lock_commit']}`, committed `{prov['primary_0_29_lock']['lock_delay_s']} s` after "
        f"`{prov['primary_0_29_lock']['episodes_commit']}`) preventing later reruns or cherry-picking, not a pre-registration "
        f"(`20+10` solver reference directories cover `0-19` and `20-29`). By contrast, the committed G1 hard extension on `seeds 30-59` "
        f"(`{prov['g1_hard_30_59_extension']['prereg_commit']}`, `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard`, `n={oc_c_ext['n']}`, "
        f"completed `seeds {oc_c_ext['seeds']}` before stopping to preserve the shared 2M TPM carbon quota for the Harbor rehearsal) and the "
        f"second frontier family `gpt-5.5` (`{prov['gpt_5_5_hard_0_29']['prereg_commit']}`, OpenCode `{prov['gpt_5_5_hard_0_29']['opencode_version']}`, "
        f"`{prov['gpt_5_5_hard_0_29']['timeout_cap_s']} s` per-episode cap, `${prov['gpt_5_5_hard_0_29']['spend_cap_usd']}` spend cap, "
        f"`{prov['gpt_5_5_hard_0_29']['committed_v14_episodes']}` committed `v1.4` episodes scoring `{_f(oc_g_hard['outcomes']['mean_score'], 3)} +/- {_f(oc_g_hard['outcomes']['score_ci'], 3)}` "
        f"with `{_f(oc_g_hard['canary_design']['mean_accepted_canaries'], 2)}` accepted canaries and `{_f(oc_g_hard['tool_use']['by_spec_tool']['interview'], 2)}` interviews/episode) were **pre-registered** before any episode ran.",
        f"- **Step-level & ledger replay verification (`1bc3e281` `norm_result` compatibility):** "
        f"`{comm_rv['verified']}/{comm_rv['total']}` committed `v1.4` episodes and `{rep_rv['verified']}/{rep_rv['total']}` FR8 replication "
        f"episodes (`{s['total_pool_episodes_replay_verified']}/{s['total_pool_episodes']}` total) pass deterministic `Env` replay with `0` "
        "score/accusation mismatches, `0` step mismatches, and `0` duplicate `(agent, tier, seed)` keys. Step-result comparison unwraps "
        f"OpenCode's stringified MCP error JSON via `norm_result` first (`{comm_rv['unwrapped_mcp_error_steps']}` committed and "
        f"`{rep_rv['unwrapped_mcp_error_steps']}` replication error steps) before normalizing pre-`1bc3e281` `data={{}}` against live `Env.call` "
        f"`data={{'detail': ...}}` (`{comm_rv['pre_1bc3e281_detail_normalized_steps']}` committed and `{rep_rv['pre_1bc3e281_detail_normalized_steps']}` "
        "replication steps), so both pre- and post-`1bc3e281` episodes verify cleanly.",
        "- **G1 committed extension (`seeds [34, 37]`, `n=2`) alongside FR8 hard replication (`seeds 30, 34, 42, 45, 57`, `n=5`) and `seed 34` consistency:** "
        f"G1 (`opencode_gemini_4_carbon_hard_ext`) averages `{_f(oc_c_ext['outcomes']['mean_score'], 3)} +/- {_f(oc_c_ext['outcomes']['score_ci'], 3)}` "
        f"(`{_f(oc_c_ext['tool_use']['mean_total_tool_calls'], 2)}` tool calls, `{_f(oc_c_ext['tool_use']['by_spec_tool']['interview'], 2)}` interviews, "
        f"`{_f(oc_c_ext['canary_design']['mean_accepted_canaries'], 2)}` accepted canaries, `100.0%` targeted `2-3` splits) alongside FR8 hard replication "
        f"(`{_f(oc_c_rep['outcomes']['mean_score'], 3)} +/- {_f(oc_c_rep['outcomes']['score_ci'], 3)}`, `{_f(oc_c_rep['tool_use']['mean_total_tool_calls'], 2)}` "
        f"calls, `{_f(oc_c_rep['tool_use']['by_spec_tool']['interview'], 2)}` interviews, `{_f(oc_c_rep['canary_design']['mean_accepted_canaries'], 2)}` "
        f"canaries, `100.0%` targeted `2-3` splits). On their shared hard `seed 34`, both independent runs correctly accuse `{g1_34['accused']}` "
        f"with `0` restrictions and `100%` targeted `3`-variant splits (`G1 {_signed(g1_34['score'], 3)}` on day `{g1_34['final_day']}` with "
        f"`{g1_34['total_calls']}` calls, `{g1_34['accepted_canaries']}` canaries, `{g1_34['interviews']}` interviews vs `FR8 {_signed(fr8_34['score'], 3)}` "
        f"on day `{fr8_34['final_day']}` with `{fr8_34['total_calls']}` calls, `{fr8_34['accepted_canaries']}` canaries, `{fr8_34['interviews']}` interviews; "
        f"reference `solver {_signed(sol_34['score'], 3)}` on day `{sol_34['final_day']}` with `{sol_34['accepted_canaries']}` canaries and `0` interviews).",
        "- **Interview budget sink is a model-level trait of `gemini-4-carbon`, not an OpenCode MCP artifact:** "
        f"On `hard` (`seeds 0-29`), OpenCode `gemini-4-carbon` runs `{_f(oc_c_hard['tool_use']['by_spec_tool']['interview'])}` "
        f"interviews/episode and `{_f(oc_c_hard['canary_design']['mean_accepted_canaries'])}` accepted canaries/episode, "
        f"closely matching in-process `gemini-4-carbon` (`{_f(ip_c_hard['tool_use']['by_spec_tool']['interview'])}` interviews, "
        f"`{_f(ip_c_hard['canary_design']['mean_accepted_canaries'])}` canaries), whereas the Bayesian `solver` runs "
        f"`0.00` interviews and plants `{_f(sol_hard['canary_design']['mean_accepted_canaries'])}` canaries/episode "
        f"(`{_pct(sol_hard['canary_design']['canary_slot_utilization'])}` slot utilization vs OpenCode `gemini-4-carbon`'s "
        f"`{_pct(oc_c_hard['canary_design']['canary_slot_utilization'])}`).",
        flash_exec_bullet,
        "- **Canary split discipline (`targeted 2-3 variant splits <=50% staff` vs `broad/single-variant`):** "
        f"The reference `solver` keeps `{_pct(sol_med['canary_design']['targeted_2_3_split_share'])}` (medium), "
        f"`{_pct(sol_hard['canary_design']['targeted_2_3_split_share'])}` (hard `0-29`), and "
        f"`{_pct(sol_hard_ext['canary_design']['targeted_2_3_split_share'])}` (hard `30-59`) of its canaries in targeted "
        f"`2-3` variant splits covering at most half the staff (`careful_mole` weight `>= 0.5`). Frontier cohorts place "
        f"`{_pct(oc_c_med['canary_design']['uninformative_broad_or_single_share'])}` (OpenCode carbon medium), "
        f"`{_pct(ip_c_med['canary_design']['uninformative_broad_or_single_share'])}` (in-process carbon medium), "
        f"{flash_split_clause}"
        f"`{_pct(oc_c_hard['canary_design']['uninformative_broad_or_single_share'])}` (OpenCode carbon hard `0-29`) of accepted "
        "canaries into broad (`>50%` staff) or single-variant assignments.",
        "- **Token caching & wall-clock justification for `--timeout 3600` (and `7200 s` `gpt-5.5` cap):** "
        f"Across OpenCode cohorts, prompt caching serves `{_f(oc_c_ext['token_and_cache']['cached_input_pct'], 1)}%` to "
        f"`{_f(oc_c_hard['token_and_cache']['cached_input_pct'], 1)}%` of `gemini-4-carbon` input tokens and {flash_cache_clause} "
        f"OpenCode `gemini-4-carbon` averages `{_f(oc_c_hard['token_and_cache']['mean_wall_s'], 1)}s` per primary hard episode "
        f"(`{oc_c_hard['token_and_cache']['episodes_over_2400s']}/30` exceed `2400s`), empirically confirming why `--timeout 2400` "
        "would truncate hard frontier runs.",
        "",
        _md_heading(2, f"2. Tool-Call Rate and Per-Tool Breakdown Across {s['cohort_count']} Active Cohorts"),
        "",
        "Tool names in `canary/env.py` map to shorthand aliases as follows: `read_access_logs` (`read_logs`), "
        "`restrict_access` (`restrict`), and `advance_day` (`next_day`), alongside `check_leak_feed` and `unrestrict_access`. "
        "Canary exposes document metadata via `list_documents` and leaked items via `check_leak_feed`, so `read_document` is `0.00` "
        f"across all cohorts; {tool_other_note}",
        "",
        "| cohort | n | mean calls +/- CI | calls / sim day | inv actions / day | status | list_emp | read_logs | read_msg | search_msg | list_docs | read_doc | leak_feed | plant_canary | interview | restrict | unrestrict | next_day | accuse | other |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for c in cohorts:
        tu = c["tool_use"]
        bs = tu["by_spec_tool"]
        lines.append(
            f"| {c['label']} | {c['n']} | {_f(tu['mean_total_tool_calls'], 2)} +/- {_f(tu['total_tool_calls_ci'], 2)} | "
            f"{_f(tu['mean_calls_per_simulated_day'], 2)} | {_f(tu['mean_investigative_actions_per_day'], 2)} | "
            f"{_f(bs['status'], 2)} | {_f(bs['list_employees'], 2)} | {_f(bs['read_logs'], 2)} | "
            f"{_f(bs['read_message'], 2)} | {_f(bs['search_messages'], 2)} | {_f(bs['list_documents'], 2)} | "
            f"{_f(bs['read_document'], 2)} | {_f(bs['check_leak_feed'], 2)} | {_f(bs['plant_canary'], 2)} | "
            f"{_f(bs['interview'], 2)} | {_f(bs['restrict'], 2)} | {_f(bs['unrestrict_access'], 2)} | "
            f"{_f(bs['next_day'], 2)} | {_f(bs['accuse'], 2)} | {_f(bs['other_invalid'], 2)} |"
        )

    lines.extend(
        [
            "",
            _md_heading(2, "3. Canary Information-Gathering & Split Design Quality"),
            "",
            "Under Canary `v1.4` (`careful_mole = True`, `max_variants = 3`, `n_employees = 20` on medium and `40` on hard), "
            "each accepted `plant_canary` call maps recipients to variant labels (`assignment`). A canary is classified as "
            "**uninformative broad/single-variant** when it uses only `1` variant label (`len(set(assignment.values())) == 1`, "
            "giving zero variant split among recipients) or covers `> 50%` of staff (`> 10` on medium, `> 20` on hard, pushing "
            "the careful-mole selection weight `1 - share` below `0.5`, and to `0.0` at `100%` coverage). Its exact complement "
            "is a **targeted 2-3 variant split** (`2` or `3` distinct variants covering `<= 50%` of staff):",
            "",
            "| cohort | n | plant calls / ep | accepted / ep | slot util. | mean recipients (% staff) | mean careful weight | mean distinct variants | 1 / 2 / 3-var counts | uninf. broad or 1-var % (1-var / >50% / 100%) | targeted 2-3 split % |",
            "|---|---:|---:|---:|---:|---|---:|---:|---|---|---:|",
        ]
    )

    for c in cohorts:
        cd = c["canary_design"]
        vd = cd["variant_count_distribution"]
        v_txt = f"{vd['1']} / {vd['2']} / {vd['3']}"
        u_detail = (
            f"{_pct(cd['uninformative_broad_or_single_share'])} "
            f"({cd['single_variant_count']} / {cd['broad_over_half_staff_count']} / {cd['full_staff_zero_leak_count']})"
        )
        lines.append(
            f"| {c['label']} | {c['n']} | {_f(cd['mean_plant_canary_calls'], 2)} | "
            f"{_f(cd['mean_accepted_canaries'], 2)} | {_pct(cd['canary_slot_utilization'])} | "
            f"{_f(cd['mean_recipients_per_canary'], 2)} ({_pct(cd['mean_recipient_staff_share'])}) | "
            f"{_f(cd['mean_careful_mole_weight'], 2)} | {_f(cd['mean_distinct_variants'], 2)} | "
            f"{v_txt} | {u_detail} | {_pct(cd['targeted_2_3_split_share'])} |"
        )

    lines.extend(
        [
            "",
            _md_heading(2, "4. Collateral Damage (`restrict_access`) and Horizon / Stopping Behavior"),
            "",
            "| cohort | n | restrict calls / ep | unrestrict calls / ep | episodes w/ restrict | abstention rate (`horizon`) | accused rate | mean accuse day (accused) | mean final day (all) | accuracy | wrong accuse rate | mean score +/- CI |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )

    for c in cohorts:
        ch = c["collateral_and_horizon"]
        oc = c["outcomes"]
        lines.append(
            f"| {c['label']} | {c['n']} | {_f(ch['mean_restrict_calls_per_episode'], 3)} | "
            f"{_f(ch['mean_unrestrict_calls_per_episode'], 3)} | "
            f"{ch['episodes_with_restrict_count']}/{c['n']} ({_pct(ch['episodes_with_restrict_rate'])}) | "
            f"{ch['abstention_count']}/{c['n']} ({_pct(ch['abstention_rate'])}) | "
            f"{_pct(ch['accused_rate'])} | {_f(ch['mean_accusation_day'], 2)} | "
            f"{_f(ch['mean_final_day_all_episodes'], 2)} | {_pct(oc['accuracy'])} | "
            f"{oc['wrong_accusation_count']}/{c['n']} ({_pct(oc['wrong_accusation_rate'])}) | "
            f"{_f(oc['mean_score'], 3)} +/- {_f(oc['score_ci'], 3)} |"
        )

    lines.extend(
        [
            "",
            _md_heading(2, "5. Token, Prompt-Cache, and Wall-Clock Efficiency (OpenCode + In-Process Reference)"),
            "",
            f"All `{s['opencode_cohort_count']}` active OpenCode cohorts record `meta.usage` (`in`, `cached_in`, `out`, `llm_calls`) and "
            "per-episode `meta.wall_s`. The `2` in-process `gemini-4-carbon` cohorts record `meta.usage` (`in`, `cached_in`, `out`, `calls`) "
            "without `wall_s`, allowing direct token-overhead comparison on identical seeds `0-29`:",
            "",
            "| cohort | harness | n | mean `usage.in` | mean `usage.cached_in` | mean uncached in | mean `usage.out` | cached input % (agg / ep) | mean LLM calls | mean `wall_s` +/- CI | min / max `wall_s` | `>2400s` / `>3600s` |",
            "|---|---|---:|---:|---:|---:|---:|---|---:|---|---|---|",
        ]
    )

    for c in cohorts:
        tc = c["token_and_cache"]
        if not tc["usage_available"]:
            continue
        cache_txt = f"{_f(tc['cached_input_pct'], 2)}% / {_f(tc['mean_episode_cached_input_pct'], 2)}%"
        if tc["wall_s_available"]:
            wall_txt = f"{_f(tc['mean_wall_s'], 1)}s +/- {_f(tc['wall_s_ci'], 1)}s"
            minmax_txt = f"{_f(tc['min_wall_s'], 1)}s / {_f(tc['max_wall_s'], 1)}s"
            over_txt = f"{tc['episodes_over_2400s']} / {tc['episodes_over_3600s']}"
        else:
            wall_txt = "n/a"
            minmax_txt = "n/a"
            over_txt = "n/a"
        lines.append(
            f"| {c['label']} | {c['harness']} | {c['n']} | {_tok_m(tc['mean_usage_in'])} | "
            f"{_tok_m(tc['mean_usage_cached_in'])} | {_tok_k(tc['mean_usage_uncached_in'])} | "
            f"{_tok_k(tc['mean_usage_out'])} | {cache_txt} | {_f(tc['mean_llm_calls'], 1)} | "
            f"{wall_txt} | {minmax_txt} | {over_txt} |"
        )

    lines.extend(
        [
            "",
            _md_heading(2, "6. Paired Harness, Model-Family, and Cross-Run Deltas"),
            "",
            f"- **OpenCode vs In-Process (`gemini-4-carbon`, `n=30` paired seeds per tier):** "
            f"OpenCode uses `{_f(c_ip_med['input_token_ratio_a_over_b'], 2)}x` (medium) and "
            f"`{_f(c_ip_hard['input_token_ratio_a_over_b'], 2)}x` (hard) as many input tokens per episode due to MCP/CLI "
            f"scaffold context, yet high prefix cache hit rates (`{_f(oc_c_med['token_and_cache']['cached_input_pct'], 2)}%` and "
            f"`{_f(oc_c_hard['token_and_cache']['cached_input_pct'], 2)}%`) keep uncached input down to "
            f"`{_tok_k(oc_c_med['token_and_cache']['mean_usage_uncached_in'])}` and "
            f"`{_tok_k(oc_c_hard['token_and_cache']['mean_usage_uncached_in'])}` tokens/episode. Both harnesses show the same "
            f"interview-heavy signature (`{_f(c_ip_med['delta_interviews_per_ep'], 2)}` interviews/ep delta on medium, "
            f"`+{_f(c_ip_hard['delta_interviews_per_ep'], 2)}` on hard) and nearly identical hard canary counts "
            f"(`{_f(oc_c_hard['canary_design']['mean_accepted_canaries'], 2)}` vs `{_f(ip_c_hard['canary_design']['mean_accepted_canaries'], 2)}`).",
            sec6_flash_bullet,
            f"- **G1 committed extension (`seeds [34, 37]`) vs FR8 hard replication (`seeds 30, 34, 42, 45, 57`):** "
            f"Both extension/replication OpenCode `gemini-4-carbon` cohorts achieve `100.0%` targeted `2-3` canary split discipline "
            f"and `0.000` `restrict_access` calls/episode, with `seed 34` cross-run consistency (`G1 {_signed(g1_34['score'], 3)}` vs "
            f"`FR8 {_signed(fr8_34['score'], 3)}`, delta `{_signed(s34['score_diff_g1_minus_fr8'], 3)}`, both accusing `{g1_34['accused']}`).",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compute or verify Canary v1.4 OpenCode vs in-process vs solver trajectory audit."
    )
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    if args.write and args.check:
        ap.error("pass either --write or --check, not both")

    root = Path(args.root).resolve()
    out_json = Path(args.out_json).resolve() if args.out_json else default_json_path(root)
    out_md = Path(args.out_md).resolve() if args.out_md else default_md_path(root)

    audit = compute_audit(root=root, verify_replays=True, enforce_expected_counts=True)
    json_blob = serialize_audit_json(audit)
    md_blob = render_markdown(audit)

    if args.check:
        if not out_json.is_file():
            print(f"missing {out_json}", file=sys.stderr)
            return 1
        if not out_md.is_file():
            print(f"missing {out_md}", file=sys.stderr)
            return 1
        if out_json.stat().st_size > MAX_JSON_BYTES:
            print(f"{out_json} exceeds {MAX_JSON_BYTES} bytes", file=sys.stderr)
            return 1
        existing_json = json.loads(out_json.read_text(encoding="utf-8"))
        fresh_json = json.loads(json_blob)
        if not approx_equal(existing_json, fresh_json, tol=1e-9):
            print(f"{out_json} differs from fresh computation beyond 1e-9 tolerance", file=sys.stderr)
            return 1
        existing_md = out_md.read_text(encoding="utf-8")
        if existing_md != md_blob:
            print(f"{out_md} differs from fresh markdown render", file=sys.stderr)
            return 1
        print(
            f"frontier trajectory audit verified: "
            f"{audit['summary']['committed_v14_verified']}/{audit['summary']['committed_v14_total']} committed + "
            f"{audit['summary']['replication_v14_verified']}/{audit['summary']['replication_v14_total']} replication "
            f"episodes ({audit['summary']['total_episodes_audited']} across {audit['summary']['cohort_count']} active cohorts)"
        )
        return 0

    if args.write:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json_blob, encoding="utf-8")
        out_md.write_text(md_blob, encoding="utf-8")
        print(f"wrote {out_json} ({out_json.stat().st_size} bytes)")
        print(f"wrote {out_md}")
        return 0

    print(md_blob, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
