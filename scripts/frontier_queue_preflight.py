from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import math
import os
import re
import shlex
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import mcp_server, rules
from canary.agents.frontier import common, opencode_run
from canary.llm import base as llm_base
from scripts.verify_replay import replay_episode

VENV_PYTHON = "/tmp/fleet-silas/shared/agent-arena-venv/bin/python"
MOMIN_PATH_PREFIX = "PATH=/home/silas/momin/bin:$PATH"
RUNNER_MODULE = "canary.agents.frontier.opencode_run"
DEFAULT_TIMEOUT_S = 3600
GPT55_TIMEOUT_S = 7200
ALLOWED_TIMEOUTS_S: tuple[int, ...] = (DEFAULT_TIMEOUT_S, GPT55_TIMEOUT_S)
DEFAULT_JOBS = 1
MAX_WORKERS_PER_WAVE = 3

EXPECTED_PERMISSION = {"*": "deny", "canary_*": "allow"}
EXPECTED_CARBON_HARD_LANDED = [30, 34, 42, 45, 57]
EXPECTED_CARBON_HARD_MISSING = [
    31, 32, 33, 35, 36, 37, 38, 39, 40, 41,
    43, 44, 46, 47, 48, 49, 50, 51, 52, 53,
    54, 55, 56, 58, 59,
]
EXPECTED_G1_COMMITTED_EXT_LANDED = [34, 37]
EXPECTED_G1_COMMITTED_EXT_QUOTA_EXCLUDED = 31
EXPECTED_GPT55_COMMITTED_LANDED = list(range(30))
EXPECTED_GPT55_CLEAN_UNENDED_SEEDS = [0, 17]
EXPECTED_GPT55_INFRA_EXCLUDED = 0
EXPECTED_COMBINED_CARBON_HARD_EXT_LANDED = [30, 34, 37, 42, 45, 57]
EXPECTED_COMBINED_CARBON_HARD_EXT_REMAINING_COUNT = 24
EXPECTED_COMMITTED_V14_EPISODES = 472
EXPECTED_REPLICATION_V14_EPISODES = 305
EXPECTED_COMBINED_V14_EPISODES = 777
EXPECTED_FLASH_MEDIUM_LANDED = list(range(30))
EXPECTED_FLASH_MEDIUM_MISSING: list[int] = []
EXPECTED_FLASH_HARD_LANDED: list[int] = []
EXPECTED_FLASH_HARD_MISSING = list(range(30, 60))

GEMINI_SESSIONS_DOC = "docs/agents/GEMINI-SESSIONS.md"
GEMINI_SESSIONS_COMMIT = "f9fb7a4a"
PANEL_DOC = "docs/agents/PANEL-0500.md"
PANEL_STATUS_COMMIT = "8b9afa61"
PANEL_FIX_A_COMMIT = "92708834"
PANEL_FIX_D_COMMIT = "1bc3e281"
GPT55_PREREG_COMMIT = "cf394894"
GPT55_COMMITTED_COMMIT = "ca0a0dc0"
GPT55_COMMITTED_DIR = "data/runs/committed/v1.4/opencode-gpt-5.5/hard"
UPSTREAM_RECONCILED_COMMIT = "5f9b3297"
PRIMARY_EPISODES_COMMIT = "8fd4dec"
PRIMARY_POST_HOC_LOCK_COMMIT = "671ed96"
PRIMARY_POST_HOC_LOCK_DELAY_S = 28

CARBON_MODEL = "google/gemini-4-carbon"
OPENAI_GPT55_MODEL = "openai/gpt-5.5"
G2_MODELS: tuple[str, ...] = (
    "google/gemini-4-argon",
    "google/gemini-4-hydrogen",
)
NON_CARBON_REHEARSAL_ALLOWED_MODELS: tuple[str, ...] = (
    "google/gemini-4-argon",
    "google/gemini-4-hydrogen",
    "openai/gpt-5.5",
)
CARBON_BLACKOUT_START_ISO = "2026-11-15T04:30:00Z"
CARBON_BLACKOUT_END_ISO = "2026-11-15T06:15:00Z"
CARBON_BLACKOUT_START_UTC = datetime(2026, 11, 15, 4, 30, 0, tzinfo=timezone.utc)
CARBON_BLACKOUT_END_UTC = datetime(2026, 11, 15, 6, 15, 0, tzinfo=timezone.utc)
CARBON_BLACKOUT_LOCAL_WINDOW = "06:30-08:15 Europe/Helsinki"
CARBON_BLACKOUT_REASON = "rehearsal_carbon_blackout_0630_0815_eet"

TARGET_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode-gemini-4-carbon-hard-30-59",
        "agent_dir": "opencode-gemini-4-carbon",
        "agent": "opencode:google/gemini-4-carbon",
        "model": "google/gemini-4-carbon",
        "tier": "hard",
        "seed_start": 30,
        "seed_end": 59,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "baseline_landed_seeds": EXPECTED_CARBON_HARD_LANDED,
        "priority": 1,
        "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
        "execution_owner": "silas_g1_ext60",
        "fr8_dispatch_enabled": False,
    },
    {
        "cohort_id": "opencode-gemini-3.5-flash-medium-0-29",
        "agent_dir": "opencode-gemini-3.5-flash",
        "agent": "opencode:google/gemini-3.5-flash",
        "model": "google/gemini-3.5-flash",
        "tier": "medium",
        "seed_start": 0,
        "seed_end": 29,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "baseline_landed_seeds": EXPECTED_FLASH_MEDIUM_LANDED,
        "priority": 2,
        "execution_owner": "fr8_frontier_complete",
        "fr8_dispatch_enabled": False,
    },
    {
        "cohort_id": "opencode-gemini-3.5-flash-hard-30-59",
        "agent_dir": "opencode-gemini-3.5-flash",
        "agent": "opencode:google/gemini-3.5-flash",
        "model": "google/gemini-3.5-flash",
        "tier": "hard",
        "seed_start": 30,
        "seed_end": 59,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "baseline_landed_seeds": EXPECTED_FLASH_HARD_LANDED,
        "priority": 3,
        "execution_owner": "fr8_frontier_paused_pure_cpu",
        "fr8_dispatch_enabled": False,
    },
)

G2_TEMPLATE_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode-gemini-4-argon-hard-0-29",
        "priority": 10,
        "agent_dir": "opencode-gemini-4-argon",
        "agent": "opencode:google/gemini-4-argon",
        "model": "google/gemini-4-argon",
        "tier": "hard",
        "seed_range": [0, 29],
        "missing_seeds": list(range(30)),
        "timeout_s": DEFAULT_TIMEOUT_S,
        "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
        "execution_owner": "silas_g2_families",
        "fr8_dispatch_enabled": False,
    },
    {
        "cohort_id": "opencode-gemini-4-hydrogen-hard-0-29",
        "priority": 11,
        "agent_dir": "opencode-gemini-4-hydrogen",
        "agent": "opencode:google/gemini-4-hydrogen",
        "model": "google/gemini-4-hydrogen",
        "tier": "hard",
        "seed_range": [0, 29],
        "missing_seeds": list(range(30)),
        "timeout_s": DEFAULT_TIMEOUT_S,
        "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
        "execution_owner": "silas_g2_families",
        "fr8_dispatch_enabled": False,
    },
)

GPT55_TEMPLATE_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode-openai-gpt-5.5-hard-0-29",
        "priority": 12,
        "agent_dir": "opencode-openai-gpt-5.5",
        "agent": "opencode:openai/gpt-5.5",
        "model": OPENAI_GPT55_MODEL,
        "tier": "hard",
        "seed_range": [0, 29],
        "missing_seeds": list(range(30)),
        "timeout_s": GPT55_TIMEOUT_S,
        "max_spend_usd": 200.0,
        "stop_launch_at": "08:15",
        "hard_drop_at": "08:45",
        "pre_registered_commit": GPT55_PREREG_COMMIT,
        "committed_commit": GPT55_COMMITTED_COMMIT,
        "committed_dir": GPT55_COMMITTED_DIR,
        "execution_owner": "silas_ca0a0dc0_committed_complete",
        "fr8_dispatch_enabled": False,
    },
)

TEMPLATE_COHORTS: tuple[dict[str, Any], ...] = G2_TEMPLATE_COHORTS + GPT55_TEMPLATE_COHORTS

PROVIDER_KEY_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
)

STRIPPED_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "OLDPWD",
    "CANARY_LEDGER_TOKEN",
    "CANARY_ADMIN_TOKEN",
    "CANARY_WORLD_SECRET",
    "CANARY_TOKEN",
    "OPENCODE_CONFIG",
)


def split_transcript(text: str) -> tuple[str, str]:
    marker_out = "\n--- stdout\n"
    marker_err = "\n--- stderr\n"
    if marker_out not in text:
        return text, ""
    _, _, after_out = text.partition(marker_out)
    if marker_err in after_out:
        stdout, _, stderr = after_out.rpartition(marker_err)
        return stdout, stderr
    if after_out.endswith("\n--- stderr"):
        return after_out[: -len("\n--- stderr")], ""
    return after_out, ""


def _with_dev_seeds_allowed():
    prev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    return prev


def _restore_dev_seeds(prev: str | None) -> None:
    if prev is None:
        os.environ.pop("CANARY_ALLOW_DEV", None)
    else:
        os.environ["CANARY_ALLOW_DEV"] = prev


_REPLAY_OUTCOME_CACHE: dict[tuple[str, int, str], dict[str, Any]] = {}


def verify_episode_replay(ep: dict[str, Any]) -> bool:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    steps_key = json.dumps(
        [(s["tool"], s.get("args") or {}) for s in (ep.get("steps") or [])],
        sort_keys=True,
        separators=(",", ":"),
    )
    cache_key = (tier, seed, steps_key)
    r = _REPLAY_OUTCOME_CACHE.get(cache_key)
    if r is None:
        prev = _with_dev_seeds_allowed()
        try:
            r = replay_episode(ep)
        finally:
            _restore_dev_seeds(prev)
        _REPLAY_OUTCOME_CACHE[cache_key] = r
    ep_final_day = int(ep.get("final_day") or 0)
    ep_rc = (ep.get("meta") or {}).get("rc", -1)
    clean_unended_exit = (
        ep.get("accused") is None
        and float(ep["score"]) == 0.0
        and ep_final_day == 0
        and not isinstance(ep_rc, bool)
        and ep_rc == 0
    )
    return (
        abs(float(r["score"]) - float(ep["score"])) < 1e-9
        and r["accused"] == ep.get("accused")
        and bool(r["correct"]) == bool(ep.get("correct"))
        and (int(r["final_day"]) == ep_final_day or clean_unended_exit)
    )


def build_runner_command(
    agent_dir: str,
    model: str,
    tier: str,
    seed: int,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> tuple[str, str, str]:
    out_rel = f"results/frontier_replication/v1.4/{agent_dir}/{tier}-s{seed}"
    cmd = (
        f"{MOMIN_PATH_PREFIX} PYTHONPATH=. {VENV_PYTHON} -m {RUNNER_MODULE} "
        f"--model {model} --tier {tier} --seeds {seed} "
        f"--timeout {timeout_s} --jobs {DEFAULT_JOBS} --out {out_rel}"
    )
    verify_cmd = f"PYTHONPATH=. {VENV_PYTHON} scripts/verify_replay.py {out_rel}"
    return out_rel, cmd, verify_cmd


def _helsinki_tz():
    try:
        return ZoneInfo("Europe/Helsinki")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=2))


def _parse_utc_timestamp(utc_epoch_or_iso: int | float | str | datetime) -> datetime:
    if isinstance(utc_epoch_or_iso, bool):
        raise ValueError("boolean is not a valid timestamp")
    if isinstance(utc_epoch_or_iso, datetime):
        if utc_epoch_or_iso.tzinfo is None:
            return utc_epoch_or_iso.replace(tzinfo=timezone.utc)
        return utc_epoch_or_iso.astimezone(timezone.utc)
    if isinstance(utc_epoch_or_iso, (int, float)):
        val = float(utc_epoch_or_iso)
        if not math.isfinite(val):
            raise ValueError(f"non-finite epoch timestamp: {utc_epoch_or_iso!r}")
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(utc_epoch_or_iso, str):
        raw = utc_epoch_or_iso.strip()
        if not raw:
            raise ValueError("empty timestamp string")
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        iso = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        parsed = datetime.fromisoformat(iso)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise TypeError(f"unsupported timestamp type: {type(utc_epoch_or_iso)!r}")


def check_carbon_quota_blackout(
    utc_epoch_or_iso: int | float | str | datetime,
    model: str = CARBON_MODEL,
) -> dict[str, Any]:
    raw_model = model.strip()
    if raw_model.startswith("opencode:"):
        raw_model = raw_model.partition(":")[2]
    norm_model = opencode_run.normalize_model(raw_model)
    dt_utc = _parse_utc_timestamp(utc_epoch_or_iso)
    in_window = CARBON_BLACKOUT_START_UTC <= dt_utc < CARBON_BLACKOUT_END_UTC
    is_carbon = norm_model == CARBON_MODEL or norm_model.endswith("/gemini-4-carbon")
    if in_window and is_carbon:
        allowed = False
        reason = CARBON_BLACKOUT_REASON
    elif in_window:
        allowed = True
        reason = "non_carbon_model_allowed_during_blackout"
    else:
        allowed = True
        reason = "outside_carbon_blackout_window"

    if dt_utc.microsecond:
        ts_utc = dt_utc.isoformat().replace("+00:00", "Z")
    else:
        ts_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_eet = dt_utc.astimezone(_helsinki_tz()).isoformat()
    return {
        "allowed": allowed,
        "reason": reason,
        "model": norm_model,
        "is_carbon_model": is_carbon,
        "in_blackout_window": in_window,
        "timestamp_utc": ts_utc,
        "timestamp_eet": ts_eet,
        "epoch_s": dt_utc.timestamp(),
        "window_start_utc": CARBON_BLACKOUT_START_ISO,
        "window_end_utc": CARBON_BLACKOUT_END_ISO,
        "window_local_eet": CARBON_BLACKOUT_LOCAL_WINDOW,
        "allowed_models_during_blackout": list(NON_CARBON_REHEARSAL_ALLOWED_MODELS),
    }


def check_carbon_quota_blackout_guard() -> dict[str, Any]:
    errors: list[str] = []
    carbon_cases = (
        ("2026-11-15T04:29:59Z", True, False, "outside_carbon_blackout_window"),
        ("2026-11-15T04:30:00Z", False, True, CARBON_BLACKOUT_REASON),
        ("2026-11-15T05:30:00Z", False, True, CARBON_BLACKOUT_REASON),
        ("2026-11-15T06:14:59Z", False, True, CARBON_BLACKOUT_REASON),
        ("2026-11-15T06:15:00Z", True, False, "outside_carbon_blackout_window"),
    )
    for ts_iso, exp_allowed, exp_in_win, exp_reason in carbon_cases:
        res = check_carbon_quota_blackout(ts_iso)
        if res["allowed"] is not exp_allowed or res["in_blackout_window"] is not exp_in_win or res["reason"] != exp_reason:
            errors.append(f"unexpected carbon blackout result at {ts_iso}: {res!r}")
        res_epoch = check_carbon_quota_blackout(int(res["epoch_s"]))
        if res_epoch["allowed"] is not exp_allowed or res_epoch["reason"] != exp_reason:
            errors.append(f"unexpected carbon epoch blackout result at {ts_iso}: {res_epoch!r}")

    non_carbon_models = (
        "gemini-4-argon",
        "gemini-4-hydrogen",
        "google/gemini-4-argon",
        "google/gemini-4-hydrogen",
        "gpt-5.5",
        "openai/gpt-5.5",
        "opencode:openai/gpt-5.5",
    )
    for alt_model in non_carbon_models:
        res_in = check_carbon_quota_blackout("2026-11-15T05:30:00Z", model=alt_model)
        if (
            res_in["allowed"] is not True
            or res_in["in_blackout_window"] is not True
            or res_in["is_carbon_model"] is not False
            or res_in["reason"] != "non_carbon_model_allowed_during_blackout"
        ):
            errors.append(f"non-carbon model {alt_model} mishandled during carbon blackout: {res_in!r}")
        res_out = check_carbon_quota_blackout("2026-11-15T06:15:00Z", model=alt_model)
        if (
            res_out["allowed"] is not True
            or res_out["in_blackout_window"] is not False
            or res_out["is_carbon_model"] is not False
        ):
            errors.append(f"non-carbon model {alt_model} mishandled outside carbon blackout: {res_out!r}")

    for cohort_spec in TARGET_COHORTS + TEMPLATE_COHORTS:
        if bool(cohort_spec.get("fr8_dispatch_enabled", False)) is not False:
            errors.append(f"cohort {cohort_spec['cohort_id']} violates FR8 0-API dispatch lock")

    return {
        "passed": not errors,
        "window_start_utc": CARBON_BLACKOUT_START_ISO,
        "window_end_utc": CARBON_BLACKOUT_END_ISO,
        "window_local_eet": CARBON_BLACKOUT_LOCAL_WINDOW,
        "blocked_model": CARBON_MODEL,
        "allowed_models_during_blackout": list(NON_CARBON_REHEARSAL_ALLOWED_MODELS),
        "fr8_zero_api_lock_enforced": True,
        "reason": CARBON_BLACKOUT_REASON,
        "synthetic_timestamps_verified": len(carbon_cases) * 2 + len(non_carbon_models) * 2,
        "errors": errors,
    }


def scan_replication_tree(
    root: Path,
    cohorts: tuple[dict[str, Any], ...] = TARGET_COHORTS,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    rep_root = root / "results" / "frontier_replication" / "v1.4"
    errors: list[str] = []
    if not rep_root.is_dir():
        return {
            "replication_root": "results/frontier_replication/v1.4",
            "total_episodes": 0,
            "replay_verified_episodes": 0,
            "cohorts": [],
            "records_by_agent_tier": {},
            "errors": [f"missing replication directory: {rep_root}"],
        }

    ep_files = sorted(rep_root.rglob("episodes.jsonl"))
    total_valid = 0
    total_replay_ok = 0
    by_agent_tier: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    invalid_by_agent_tier: dict[tuple[str, str], list[int]] = {}

    for ep_file in ep_files:
        rel_file = ep_file.relative_to(root).as_posix()
        for line_no, raw_line in enumerate(ep_file.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            ep = json.loads(raw_line)
            agent = str(ep.get("agent", ""))
            tier = str(ep.get("tier", ""))
            seed = int(ep["seed"])
            if (ep.get("meta") or {}).get("valid") is False:
                invalid_by_agent_tier.setdefault((agent, tier), []).append(seed)
                continue
            total_valid += 1
            if not verify_episode_replay(ep):
                errors.append(f"replay mismatch in {rel_file}:{line_no} ({agent} {tier} seed={seed})")
                continue
            total_replay_ok += 1
            bucket = by_agent_tier.setdefault((agent, tier), {})
            if seed in bucket:
                errors.append(
                    f"duplicate replay-verified seed {seed} for {agent} {tier}: "
                    f"{bucket[seed]['episode_file']} and {rel_file}"
                )
                continue
            tr_path = ep_file.parent / "transcripts" / f"{seed}.txt"
            bucket[seed] = {
                "episode": ep,
                "episode_file": rel_file,
                "transcript_file": tr_path.relative_to(root).as_posix() if tr_path.is_file() else None,
            }

    if enforce_expected_baseline and (
        total_valid != EXPECTED_REPLICATION_V14_EPISODES
        or total_replay_ok != EXPECTED_REPLICATION_V14_EPISODES
    ):
        errors.append(
            f"expected {EXPECTED_REPLICATION_V14_EPISODES}/{EXPECTED_REPLICATION_V14_EPISODES} "
            f"replication v1.4 episodes, got {total_replay_ok}/{total_valid}"
        )

    cohort_rows: list[dict[str, Any]] = []
    for spec in cohorts:
        key = (spec["agent"], spec["tier"])
        target_seeds = list(range(int(spec["seed_start"]), int(spec["seed_end"]) + 1))
        landed_map = by_agent_tier.get(key, {})
        landed_seeds = sorted(s for s in target_seeds if s in landed_map)
        missing_seeds = sorted(s for s in target_seeds if s not in landed_map)
        invalid_seeds = sorted(
            s for s in invalid_by_agent_tier.get(key, []) if spec["seed_start"] <= s <= spec["seed_end"]
        )
        baseline = list(spec.get("baseline_landed_seeds") or [])
        baseline_ok = set(baseline).issubset(set(landed_seeds))
        if enforce_expected_baseline and not baseline_ok:
            missing_base = sorted(set(baseline) - set(landed_seeds))
            errors.append(
                f"cohort {spec['cohort_id']} missing expected landed seeds: {missing_base}"
            )
        for s in landed_seeds:
            if landed_map[s]["transcript_file"] is None:
                errors.append(
                    f"cohort {spec['cohort_id']} seed {s} missing transcript file next to {landed_map[s]['episode_file']}"
                )
        row: dict[str, Any] = {
            "cohort_id": spec["cohort_id"],
            "priority": spec["priority"],
            "agent_dir": spec["agent_dir"],
            "agent": spec["agent"],
            "model": spec["model"],
            "tier": spec["tier"],
            "seed_range": [spec["seed_start"], spec["seed_end"]],
            "timeout_s": int(spec.get("timeout_s", DEFAULT_TIMEOUT_S)),
            "target_count": len(target_seeds),
            "landed_count": len(landed_seeds),
            "missing_count": len(missing_seeds),
            "landed_seeds": landed_seeds,
            "missing_seeds": missing_seeds,
            "invalid_seeds": invalid_seeds,
            "baseline_landed_verified": baseline_ok,
            "execution_owner": spec.get("execution_owner", "unassigned"),
            "fr8_dispatch_enabled": bool(spec.get("fr8_dispatch_enabled", False)),
        }
        if "pre_registered_commit" in spec:
            row["pre_registered_commit"] = spec["pre_registered_commit"]
        cohort_rows.append(row)

    return {
        "replication_root": "results/frontier_replication/v1.4",
        "total_episodes": total_valid,
        "replay_verified_episodes": total_replay_ok,
        "cohorts": cohort_rows,
        "records_by_agent_tier": by_agent_tier,
        "errors": errors,
    }


def scan_committed_v14_tree(
    root: Path,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    committed_root = root / "data" / "runs" / "committed" / "v1.4"
    g1_ext_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard"
    gpt55_rel = GPT55_COMMITTED_DIR
    errors: list[str] = []
    if not committed_root.is_dir():
        if enforce_expected_baseline:
            errors.append(f"missing committed v1.4 directory: {committed_root}")
        return {
            "committed_root": "data/runs/committed/v1.4",
            "present": False,
            "total_episodes": 0,
            "replay_verified_episodes": 0,
            "landed_by_agent_tier": {},
            "g1_ext_dir": g1_ext_rel,
            "g1_ext_landed_seeds": [],
            "g1_ext_landed_count": 0,
            "g1_ext_provider_quota_excluded": 0,
            "g1_ext_records": {},
            "gpt55_dir": gpt55_rel,
            "gpt55_landed_seeds": [],
            "gpt55_landed_count": 0,
            "gpt55_clean_unended_seeds": [],
            "gpt55_infra_excluded": 0,
            "gpt55_records": {},
            "errors": errors,
        }

    ep_files = sorted(committed_root.rglob("episodes.jsonl"))
    total_valid = 0
    total_replay_ok = 0
    landed_sets: dict[tuple[str, str], set[int]] = {}
    g1_ext_records: dict[int, dict[str, Any]] = {}
    gpt55_records: dict[int, dict[str, Any]] = {}
    gpt55_clean_unended_seeds: list[int] = []
    g1_ext_ep_file = root / g1_ext_rel / "episodes.jsonl"
    gpt55_ep_file = root / gpt55_rel / "episodes.jsonl"

    for ep_file in ep_files:
        rel_file = ep_file.relative_to(root).as_posix()
        ep_resolved = ep_file.resolve()
        is_g1_ext = ep_resolved == g1_ext_ep_file.resolve()
        is_gpt55 = ep_resolved == gpt55_ep_file.resolve()
        for line_no, raw_line in enumerate(ep_file.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            ep = json.loads(raw_line)
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            total_valid += 1
            seed = int(ep["seed"])
            agent = str(ep.get("agent", ""))
            tier = str(ep.get("tier", ""))
            if not verify_episode_replay(ep):
                errors.append(f"committed replay mismatch in {rel_file}:{line_no} ({agent} {tier} seed={seed})")
                continue
            total_replay_ok += 1
            landed_sets.setdefault((agent, tier), set()).add(seed)
            if is_g1_ext:
                tr_path = ep_file.parent / "transcripts" / f"{seed}.txt"
                g1_ext_records[seed] = {
                    "episode": ep,
                    "episode_file": rel_file,
                    "transcript_file": tr_path.relative_to(root).as_posix() if tr_path.is_file() else None,
                }
            if is_gpt55:
                tr_path = ep_file.parent / "transcripts" / f"{seed}.txt"
                gpt55_records[seed] = {
                    "episode": ep,
                    "episode_file": rel_file,
                    "transcript_file": tr_path.relative_to(root).as_posix() if tr_path.is_file() else None,
                }
                ep_rc = (ep.get("meta") or {}).get("rc", -1)
                if (
                    ep.get("accused") is None
                    and float(ep["score"]) == 0.0
                    and int(ep.get("final_day") or 0) == 0
                    and not isinstance(ep_rc, bool)
                    and ep_rc == 0
                ):
                    gpt55_clean_unended_seeds.append(seed)

    g1_landed_seeds = sorted(g1_ext_records.keys())
    g1_meta_path = root / g1_ext_rel / "meta.json"
    quota_excluded = 0
    if g1_meta_path.is_file():
        g1_meta = json.loads(g1_meta_path.read_text(encoding="utf-8"))
        excl = list(g1_meta.get("infra_invalid_attempts_excluded") or [])
        quota_excluded = sum(1 for item in excl if "infra:provider_quota" in str(item))

    gpt55_landed_seeds = sorted(gpt55_records.keys())
    gpt55_clean_unended_seeds = sorted(gpt55_clean_unended_seeds)
    gpt55_meta_path = root / gpt55_rel / "meta.json"
    gpt55_infra_excluded = 0
    if gpt55_meta_path.is_file():
        gpt55_meta = json.loads(gpt55_meta_path.read_text(encoding="utf-8"))
        gpt55_infra_excluded = len(list(gpt55_meta.get("infra_invalid_attempts_excluded") or []))

    if enforce_expected_baseline:
        if total_valid != EXPECTED_COMMITTED_V14_EPISODES or total_replay_ok != EXPECTED_COMMITTED_V14_EPISODES:
            errors.append(
                f"expected {EXPECTED_COMMITTED_V14_EPISODES}/{EXPECTED_COMMITTED_V14_EPISODES} "
                f"committed v1.4 episodes, got {total_replay_ok}/{total_valid}"
            )
        if g1_landed_seeds != EXPECTED_G1_COMMITTED_EXT_LANDED:
            errors.append(
                f"expected committed G1 ext landed seeds {EXPECTED_G1_COMMITTED_EXT_LANDED}, got {g1_landed_seeds}"
            )
        if quota_excluded != EXPECTED_G1_COMMITTED_EXT_QUOTA_EXCLUDED:
            errors.append(
                f"expected {EXPECTED_G1_COMMITTED_EXT_QUOTA_EXCLUDED} provider_quota excluded attempts in G1 ext, "
                f"got {quota_excluded}"
            )
        for s in g1_landed_seeds:
            if g1_ext_records[s]["transcript_file"] is None:
                errors.append(f"committed G1 ext seed {s} missing transcript file")
        if gpt55_landed_seeds != EXPECTED_GPT55_COMMITTED_LANDED:
            errors.append(
                f"expected committed gpt-5.5 hard landed seeds {EXPECTED_GPT55_COMMITTED_LANDED}, got {gpt55_landed_seeds}"
            )
        if gpt55_clean_unended_seeds != EXPECTED_GPT55_CLEAN_UNENDED_SEEDS:
            errors.append(
                f"expected committed gpt-5.5 clean unended seeds {EXPECTED_GPT55_CLEAN_UNENDED_SEEDS}, "
                f"got {gpt55_clean_unended_seeds}"
            )
        if gpt55_infra_excluded != EXPECTED_GPT55_INFRA_EXCLUDED:
            errors.append(
                f"expected {EXPECTED_GPT55_INFRA_EXCLUDED} infra excluded attempts in gpt-5.5 hard, "
                f"got {gpt55_infra_excluded}"
            )
        for s in gpt55_landed_seeds:
            if gpt55_records[s]["transcript_file"] is None:
                errors.append(f"committed gpt-5.5 hard seed {s} missing transcript file")

    return {
        "committed_root": "data/runs/committed/v1.4",
        "present": True,
        "total_episodes": total_valid,
        "replay_verified_episodes": total_replay_ok,
        "landed_by_agent_tier": {k: sorted(v) for k, v in landed_sets.items()},
        "g1_ext_dir": g1_ext_rel,
        "g1_ext_landed_seeds": g1_landed_seeds,
        "g1_ext_landed_count": len(g1_landed_seeds),
        "g1_ext_provider_quota_excluded": quota_excluded,
        "g1_ext_records": g1_ext_records,
        "gpt55_dir": gpt55_rel,
        "gpt55_landed_seeds": gpt55_landed_seeds,
        "gpt55_landed_count": len(gpt55_landed_seeds),
        "gpt55_clean_unended_seeds": gpt55_clean_unended_seeds,
        "gpt55_infra_excluded": gpt55_infra_excluded,
        "gpt55_records": gpt55_records,
        "errors": errors,
    }


def _committed_landed_lookup_from_files(root: Path) -> dict[tuple[str, str], list[int]]:
    committed_root = root / "data" / "runs" / "committed" / "v1.4"
    if not committed_root.is_dir():
        return {}
    by_key: dict[tuple[str, str], set[int]] = {}
    for ep_file in sorted(committed_root.rglob("episodes.jsonl")):
        for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            ep = json.loads(raw_line)
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            by_key.setdefault((str(ep.get("agent", "")), str(ep.get("tier", ""))), set()).add(int(ep["seed"]))
    return {k: sorted(v) for k, v in by_key.items()}


def reconcile_template_cohorts(
    template_cohorts: tuple[dict[str, Any], ...] | list[dict[str, Any]] = TEMPLATE_COHORTS,
    committed_landed_by_agent_tier: dict[tuple[str, str], list[int]] | None = None,
) -> list[dict[str, Any]]:
    lookup = committed_landed_by_agent_tier or {}
    reconciled: list[dict[str, Any]] = []
    for spec in template_cohorts:
        lo, hi = int(spec["seed_range"][0]), int(spec["seed_range"][1])
        target_seeds = list(range(lo, hi + 1))
        committed_set = set(lookup.get((str(spec["agent"]), str(spec["tier"])), []))
        landed_seeds = sorted(s for s in target_seeds if s in committed_set)
        missing_seeds = sorted(s for s in target_seeds if s not in committed_set)
        item = dict(spec)
        item["landed_seeds"] = landed_seeds
        item["missing_seeds"] = missing_seeds
        reconciled.append(item)
    return reconciled


def serialize_template_cohorts(
    template_cohorts: tuple[dict[str, Any], ...] | list[dict[str, Any]] = TEMPLATE_COHORTS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in template_cohorts:
        lo, hi = int(spec["seed_range"][0]), int(spec["seed_range"][1])
        target_count = hi - lo + 1
        missing_count = len(spec.get("missing_seeds", list(range(lo, hi + 1))))
        landed_count = target_count - missing_count
        row: dict[str, Any] = {
            "cohort_id": spec["cohort_id"],
            "priority": int(spec["priority"]),
            "agent_dir": spec["agent_dir"],
            "agent": spec["agent"],
            "model": spec["model"],
            "tier": spec["tier"],
            "seed_range": [lo, hi],
            "target_count": target_count,
            "landed_count": landed_count,
            "missing_count": missing_count,
            "timeout_s": int(spec.get("timeout_s", DEFAULT_TIMEOUT_S)),
            "pre_registered_commit": spec["pre_registered_commit"],
            "execution_owner": spec["execution_owner"],
            "fr8_dispatch_enabled": bool(spec.get("fr8_dispatch_enabled", False)),
        }
        for opt_key in ("committed_commit", "committed_dir", "max_spend_usd", "stop_launch_at", "hard_drop_at"):
            if opt_key in spec:
                row[opt_key] = spec[opt_key]
        rows.append(row)
    return rows


def partition_into_waves(
    cohort_rows: list[dict[str, Any]],
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    if max_workers_per_wave < 1 or max_workers_per_wave > MAX_WORKERS_PER_WAVE:
        raise ValueError(f"max_workers_per_wave must be in 1..{MAX_WORKERS_PER_WAVE}")
    waves: list[dict[str, Any]] = []
    ordered = sorted(cohort_rows, key=lambda c: int(c["priority"]))
    wave_id = 0
    for cohort in ordered:
        dispatch_enabled = bool(cohort.get("fr8_dispatch_enabled", True))
        if not include_disabled and not dispatch_enabled:
            continue
        missing = list(cohort["missing_seeds"])
        cohort_timeout_s = int(cohort.get("timeout_s", DEFAULT_TIMEOUT_S))
        cohort_wave = 0
        for idx in range(0, len(missing), max_workers_per_wave):
            batch = missing[idx : idx + max_workers_per_wave]
            wave_id += 1
            cohort_wave += 1
            jobs_list: list[dict[str, Any]] = []
            for slot, seed in enumerate(batch, start=1):
                out_rel, cmd, verify_cmd = build_runner_command(
                    cohort["agent_dir"],
                    cohort["model"],
                    cohort["tier"],
                    seed,
                    timeout_s=cohort_timeout_s,
                )
                jobs_list.append(
                    {
                        "worker_slot": slot,
                        "cohort_id": cohort["cohort_id"],
                        "model": cohort["model"],
                        "tier": cohort["tier"],
                        "seed": seed,
                        "seeds": [seed],
                        "timeout_s": cohort_timeout_s,
                        "jobs": DEFAULT_JOBS,
                        "out_dir": out_rel,
                        "command": cmd,
                        "verify_command": verify_cmd,
                    }
                )
            wave_entry: dict[str, Any] = {
                "wave_id": wave_id,
                "cohort_id": cohort["cohort_id"],
                "cohort_wave": cohort_wave,
                "model": cohort["model"],
                "tier": cohort["tier"],
                "timeout_s": cohort_timeout_s,
                "execution_owner": cohort.get("execution_owner", "unassigned"),
                "fr8_dispatch_enabled": dispatch_enabled,
                "worker_count": len(jobs_list),
                "ram_safe": len(jobs_list) <= MAX_WORKERS_PER_WAVE,
                "seeds": batch,
                "jobs": jobs_list,
            }
            for opt_key in ("pre_registered_commit", "max_spend_usd", "stop_launch_at", "hard_drop_at"):
                if opt_key in cohort:
                    wave_entry[opt_key] = cohort[opt_key]
            waves.append(wave_entry)
    return waves


def build_template_waves(
    cohort_rows: list[dict[str, Any]],
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
) -> list[dict[str, Any]]:
    return partition_into_waves(
        cohort_rows,
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=True,
    )


def build_g2_template_waves(
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
) -> list[dict[str, Any]]:
    return partition_into_waves(
        [dict(c) for c in G2_TEMPLATE_COHORTS],
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=True,
    )


def build_gpt55_template_waves(
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    root: Path | None = ROOT,
    committed_landed_by_agent_tier: dict[tuple[str, str], list[int]] | None = None,
    include_committed: bool = False,
) -> list[dict[str, Any]]:
    if include_committed:
        cohorts = [dict(c) for c in GPT55_TEMPLATE_COHORTS]
    else:
        lookup = (
            committed_landed_by_agent_tier
            if committed_landed_by_agent_tier is not None
            else (_committed_landed_lookup_from_files(root) if root is not None else {})
        )
        cohorts = reconcile_template_cohorts(GPT55_TEMPLATE_COHORTS, lookup)
    return partition_into_waves(
        cohorts,
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=True,
    )


def build_cross_family_template_waves(
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    root: Path | None = ROOT,
    committed_landed_by_agent_tier: dict[tuple[str, str], list[int]] | None = None,
    include_committed: bool = False,
) -> list[dict[str, Any]]:
    if include_committed:
        cohorts = [dict(c) for c in TEMPLATE_COHORTS]
    else:
        lookup = (
            committed_landed_by_agent_tier
            if committed_landed_by_agent_tier is not None
            else (_committed_landed_lookup_from_files(root) if root is not None else {})
        )
        cohorts = reconcile_template_cohorts(TEMPLATE_COHORTS, lookup)
    return partition_into_waves(
        cohorts,
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=True,
    )


def validate_wave_commands(waves: list[dict[str, Any]]) -> dict[str, Any]:
    parser = common.base_args("OpenCode frontier runner", opencode_run.DEFAULT_MODEL)
    errors: list[str] = []
    checked = 0
    for wave in waves:
        if wave["worker_count"] > MAX_WORKERS_PER_WAVE or wave["worker_count"] != len(wave["jobs"]):
            errors.append(f"wave {wave['wave_id']} violates <=3 worker constraint: {wave['worker_count']}")
        for job in wave["jobs"]:
            checked += 1
            cmd = job["command"]
            if not cmd.startswith(f"{MOMIN_PATH_PREFIX} "):
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} missing {MOMIN_PATH_PREFIX}")
            tokens = shlex.split(cmd)
            try:
                mod_idx = tokens.index(RUNNER_MODULE)
            except ValueError:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} missing {RUNNER_MODULE}")
                continue
            if mod_idx < 1 or tokens[mod_idx - 1] != "-m":
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} missing -m before {RUNNER_MODULE}")
                continue
            cli_argv = tokens[mod_idx + 1 :]
            try:
                parsed, unknown = parser.parse_known_args(cli_argv)
            except SystemExit as exc:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} failed arg parse: {exc}")
                continue
            if unknown:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} has invalid flags: {unknown}")
                continue
            norm_model = opencode_run.normalize_model(parsed.model)
            if norm_model != job["model"]:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} normalized model={norm_model} != {job['model']}")
            spec = common.spec_from(parsed, f"opencode:{norm_model}")
            expected_timeout = int(job.get("timeout_s", DEFAULT_TIMEOUT_S))
            if expected_timeout not in ALLOWED_TIMEOUTS_S:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} unsupported timeout_s={expected_timeout}")
            if parsed.timeout != expected_timeout:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} timeout={parsed.timeout} != {expected_timeout}")
            if parsed.jobs != DEFAULT_JOBS:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} jobs={parsed.jobs} != {DEFAULT_JOBS}")
            if parsed.tier not in rules.TIERS:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} unknown tier={parsed.tier}")
            if spec.seeds != [job["seed"]]:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} parsed seeds={spec.seeds}")
            if parsed.out != job["out_dir"]:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} parsed out={parsed.out}")
            if parsed.smoke or parsed.hint is not None or parsed.dry_run:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} unexpected optional flag enabled")
    return {
        "passed": not errors,
        "commands_validated": checked,
        "max_workers_per_wave": MAX_WORKERS_PER_WAVE,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "allowed_timeouts_s": list(ALLOWED_TIMEOUTS_S),
        "jobs_per_worker": DEFAULT_JOBS,
        "errors": errors,
    }


def check_tiers_gate() -> dict[str, Any]:
    errors: list[str] = []
    if rules.TIERS_VERSION != "v1.4":
        errors.append(f"expected TIERS_VERSION == 'v1.4', got {rules.TIERS_VERSION!r}")
    if set(rules.TIERS.keys()) != {"easy", "medium", "hard"}:
        errors.append(f"unexpected active tiers: {sorted(rules.TIERS.keys())}")
    return {
        "passed": not errors,
        "tiers_version": rules.TIERS_VERSION,
        "active_tiers": sorted(rules.TIERS.keys()),
        "errors": errors,
    }


def check_opencode_config_isolation() -> dict[str, Any]:
    errors: list[str] = []
    if opencode_run.PERMISSION != EXPECTED_PERMISSION:
        errors.append(f"PERMISSION mismatch: {opencode_run.PERMISSION!r}")
    test_url = "http://127.0.0.1:43210/mcp"
    cfg = opencode_run.opencode_config(test_url)
    if cfg.get("permission") != EXPECTED_PERMISSION:
        errors.append(f"opencode_config permission mismatch: {cfg.get('permission')!r}")
    cfg["permission"]["*"] = "allow"
    if opencode_run.PERMISSION != EXPECTED_PERMISSION:
        errors.append("opencode_config aliased module PERMISSION dict")
    if cfg.get("autoupdate") is not False:
        errors.append(f"expected autoupdate=False, got {cfg.get('autoupdate')!r}")
    if cfg.get("share") != "disabled":
        errors.append(f"expected share='disabled', got {cfg.get('share')!r}")
    servers = cfg.get("mcp", {}).get("servers", cfg.get("mcp", {}))
    canary_srv = servers.get("canary", {})
    if canary_srv.get("url") != test_url or canary_srv.get("enabled") is not True:
        errors.append(f"unexpected mcp canary config: {canary_srv!r}")
    for forbidden_mcp_key in ("env", "environment", "headers"):
        if forbidden_mcp_key in canary_srv:
            errors.append(f"mcp canary config unexpectedly carries {forbidden_mcp_key}")

    routing_cases = (
        ("gemini-4-carbon", "google/gemini-4-carbon"),
        ("google/gemini-4-carbon", "google/gemini-4-carbon"),
        ("gemini-4-argon", "google/gemini-4-argon"),
        ("gemini-4-hydrogen", "google/gemini-4-hydrogen"),
        ("gemini-3.5-flash", "google/gemini-3.5-flash"),
        ("gpt-5.5", "openai/gpt-5.5"),
        ("openai/gpt-5.5", "openai/gpt-5.5"),
    )
    for raw_m, exp_norm in routing_cases:
        got_norm = opencode_run.normalize_model(raw_m)
        if got_norm != exp_norm:
            errors.append(f"opencode_run.normalize_model({raw_m!r}) == {got_norm!r} != {exp_norm!r}")

    carbon_settings = opencode_run.opencode_google_settings("google/gemini-4-carbon")
    argon_settings = opencode_run.opencode_google_settings("google/gemini-4-argon")
    hydrogen_settings = opencode_run.opencode_google_settings("google/gemini-4-hydrogen")
    flash_settings = opencode_run.opencode_google_settings("google/gemini-3.5-flash")
    if "gemini-4-carbon: medium" not in carbon_settings.get("thinking", ""):
        errors.append(f"unexpected carbon thinking settings: {carbon_settings!r}")
    if "no thinkingLevel" not in argon_settings.get("thinking", ""):
        errors.append(f"unexpected argon thinking settings: {argon_settings!r}")
    if "no thinkingLevel" not in hydrogen_settings.get("thinking", ""):
        errors.append(f"unexpected hydrogen thinking settings: {hydrogen_settings!r}")
    if "thinkingLevel=high" not in flash_settings.get("thinking", ""):
        errors.append(f"unexpected flash thinking settings: {flash_settings!r}")
    if opencode_run.normalize_model("gpt-5.5").startswith("google/"):
        errors.append("openai/gpt-5.5 unexpectedly routed to google settings")
    return {
        "passed": not errors,
        "permission": dict(EXPECTED_PERMISSION),
        "autoupdate": False,
        "share": "disabled",
        "provider_routes_verified": len(routing_cases),
        "errors": errors,
    }


def check_child_env_stripping() -> dict[str, Any]:
    errors: list[str] = []
    saved = dict(os.environ)
    orig_load_env = llm_base.load_env
    orig_mkdtemp = tempfile.mkdtemp
    wd: Path | None = None
    created_temp_dirs: list[Path] = []

    def tracked_mkdtemp(*args: Any, **kwargs: Any) -> str:
        p = orig_mkdtemp(*args, **kwargs)
        created_temp_dirs.append(Path(p))
        return p

    try:
        llm_base.load_env = lambda: None
        tempfile.mkdtemp = tracked_mkdtemp
        os.environ.pop("GOOGLE_GENERATIVE_AI_API_KEY", None)
        synthetic_values: dict[str, str] = {}
        for idx, key in enumerate(STRIPPED_ENV_VARS):
            val = f"synthetic-preflight-secret-{idx}-{key.lower()}"
            synthetic_values[key] = val
            os.environ[key] = val
        for plain_var in mcp_server.PLAIN_SECRET_VARS:
            os.environ[plain_var] = f"synthetic-plain-{plain_var.lower()}"

        base_cli_env = common.child_env()
        leaked_keys = sorted(k for k in STRIPPED_ENV_VARS if k in base_cli_env)
        if leaked_keys:
            errors.append(f"child_env leaked stripped keys: {leaked_keys}")
        leaked_vals = sorted(
            k for k, v in synthetic_values.items() if any(v == str(ev_val) for ev_val in base_cli_env.values())
        )
        if leaked_vals:
            errors.append(f"child_env leaked synthetic values for: {leaked_vals}")
        if base_cli_env.get("PWD") != "":
            errors.append(f"expected child_env PWD=='', got {base_cli_env.get('PWD')!r}")

        mcp_env = mcp_server.clean_launch_env(base_cli_env)
        mcp_leaked_provider = sorted(
            k for k in (*PROVIDER_KEY_VARS, "GOOGLE_GENERATIVE_AI_API_KEY") if k in mcp_env
        )
        if mcp_leaked_provider:
            errors.append(f"MCP server env leaked provider keys: {mcp_leaked_provider}")
        mcp_leaked_secrets = sorted(k for k in mcp_server.PLAIN_SECRET_VARS if k in mcp_env)
        if mcp_leaked_secrets:
            errors.append(f"MCP server clean_launch_env leaked plain secret vars: {mcp_leaked_secrets}")

        wd = common.make_clean_workdir()
        extra_google, _ = opencode_run.child_env_extra("google/gemini-4-carbon")(wd)
        cli_google_env = {**common.child_env(), **extra_google}
        if cli_google_env.get("GOOGLE_GENERATIVE_AI_API_KEY") != synthetic_values["GEMINI_API_KEY"]:
            errors.append("google/* CLI env failed to map GEMINI_API_KEY to GOOGLE_GENERATIVE_AI_API_KEY")
        for forbidden_google in PROVIDER_KEY_VARS:
            if forbidden_google in cli_google_env:
                errors.append(f"google/* CLI env exposed {forbidden_google}")
        for flag_key in ("OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_SHARE"):
            if cli_google_env.get(flag_key) != "1":
                errors.append(f"expected {flag_key}=='1', got {cli_google_env.get(flag_key)!r}")
        oc_home = Path(cli_google_env["XDG_DATA_HOME"]).resolve().parent
        if common.REPO_ROOT.resolve() in oc_home.parents or oc_home == common.REPO_ROOT.resolve():
            errors.append("opencode per-episode XDG home is inside REPO_ROOT")
        if wd.resolve() in oc_home.parents or oc_home == wd.resolve():
            errors.append("opencode per-episode XDG home is inside agent workdir")

        for openai_alias in ("gpt-5.5", "openai/gpt-5.5"):
            extra_openai, _ = opencode_run.child_env_extra(openai_alias)(wd)
            cli_openai_env = {**common.child_env(), **extra_openai}
            if cli_openai_env.get("OPENAI_API_KEY") != synthetic_values["OPENAI_API_KEY"]:
                errors.append(f"{openai_alias} CLI env failed to pass OPENAI_API_KEY")
            for forbidden_openai in ("GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
                if forbidden_openai in cli_openai_env:
                    errors.append(f"{openai_alias} CLI env exposed {forbidden_openai}")
            oc_openai_home = Path(cli_openai_env["XDG_DATA_HOME"]).resolve().parent
            if common.REPO_ROOT.resolve() in oc_openai_home.parents or wd.resolve() in oc_openai_home.parents:
                errors.append(f"{openai_alias} per-episode XDG home violated repo/workdir isolation")

        extra_other, _ = opencode_run.child_env_extra("anthropic/unused-model")(wd)
        cli_other_env = {**common.child_env(), **extra_other}
        for any_key in (*PROVIDER_KEY_VARS, "GOOGLE_GENERATIVE_AI_API_KEY"):
            if any_key in cli_other_env:
                errors.append(f"unmapped provider CLI env unexpectedly exposed {any_key}")

        for k in PROVIDER_KEY_VARS:
            os.environ.pop(k, None)
        mcp_no_key_env = mcp_server.clean_launch_env()
        if any(k in mcp_no_key_env for k in (*PROVIDER_KEY_VARS, "GOOGLE_GENERATIVE_AI_API_KEY")):
            errors.append("keyless parent MCP server launch env unexpectedly contained provider key")
        for missing_model in ("google/gemini-4-carbon", "openai/gpt-5.5"):
            caught_missing = False
            try:
                opencode_run.child_env_extra(missing_model)(wd)
            except llm_base.MissingKeyError:
                caught_missing = True
            if not caught_missing:
                errors.append(f"child_env_extra({missing_model!r}) did not raise MissingKeyError when key unset")
    finally:
        llm_base.load_env = orig_load_env
        tempfile.mkdtemp = orig_mkdtemp
        os.environ.clear()
        os.environ.update(saved)
        if wd is not None:
            shutil.rmtree(wd, ignore_errors=True)
        for p in created_temp_dirs:
            shutil.rmtree(p, ignore_errors=True)

    return {
        "passed": not errors,
        "stripped_vars_verified": list(STRIPPED_ENV_VARS),
        "mcp_server_stripped_provider_keys": list(PROVIDER_KEY_VARS),
        "google_cli_active_key": "GOOGLE_GENERATIVE_AI_API_KEY",
        "openai_cli_active_key": "OPENAI_API_KEY",
        "isolated_xdg_home_verified": True,
        "errors": errors,
    }


def _load_gemini_runner_module():
    runner_path = ROOT / "scripts" / "gemini_runner.py"
    spec = importlib.util.spec_from_file_location("preflight_gemini_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {runner_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_gemini_runner_controls() -> dict[str, Any]:
    errors: list[str] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="canary-preflight-gr-")).resolve()
    try:
        gr = _load_gemini_runner_module()
        route_cases = (
            ("gemini-4-carbon", "google/gemini-4-carbon"),
            ("gemini-4-argon", "google/gemini-4-argon"),
            ("gemini-4-hydrogen", "google/gemini-4-hydrogen"),
            ("gemini-3.5-flash", "google/gemini-3.5-flash"),
            ("google/gemini-4-carbon", "google/gemini-4-carbon"),
            ("gpt-5.5", "openai/gpt-5.5"),
            ("openai/gpt-5.5", "openai/gpt-5.5"),
        )
        for raw_m, exp_m in route_cases:
            got_m = gr.provider_model(raw_m)
            if got_m != exp_m:
                errors.append(f"gemini_runner.provider_model({raw_m!r}) == {got_m!r} != {exp_m!r}")

        saved_override = os.environ.pop("CANARY_TIERS_OVERRIDE", None)
        try:
            job_gpt = gr.Job("opencode", "hard", 0, tmp_dir / "s0", "gpt-5.5", GPT55_TIMEOUT_S)
            cmd_gpt = job_gpt.cmd()
            if "--model" not in cmd_gpt or cmd_gpt[cmd_gpt.index("--model") + 1] != "openai/gpt-5.5":
                errors.append(f"unexpected gpt-5.5 Job.cmd model routing: {cmd_gpt!r}")
            if "--timeout" not in cmd_gpt or cmd_gpt[cmd_gpt.index("--timeout") + 1] != str(GPT55_TIMEOUT_S):
                errors.append(f"unexpected gpt-5.5 Job.cmd timeout: {cmd_gpt!r}")

            job_gem = gr.Job("opencode", "hard", 0, tmp_dir / "s0", "gemini-4-carbon", DEFAULT_TIMEOUT_S)
            cmd_gem = job_gem.cmd()
            if "--model" not in cmd_gem or cmd_gem[cmd_gem.index("--model") + 1] != "google/gemini-4-carbon":
                errors.append(f"unexpected gemini-4-carbon Job.cmd model routing: {cmd_gem!r}")
        finally:
            if saved_override is not None:
                os.environ["CANARY_TIERS_OVERRIDE"] = saved_override

        buf_mismatch = io.StringIO()
        with contextlib.redirect_stdout(buf_mismatch):
            rc_mismatch = gr.main(["--tiers-version", "v1.3", "--staging", str(tmp_dir / "mismatch"), "--dry-run"])
        if rc_mismatch != 2:
            errors.append(f"expected gemini_runner --tiers-version mismatch rc=2, got {rc_mismatch}")

        stg_stop = tmp_dir / "stop_at"
        buf_stop = io.StringIO()
        with contextlib.redirect_stdout(buf_stop):
            rc_stop = gr.main(
                [
                    "--tiers-version", "v1.4",
                    "--staging", str(stg_stop),
                    "--model", "gpt-5.5",
                    "--seeds", "0-1",
                    "--tiers", "hard",
                    "--harnesses", "opencode",
                    "--timeout", str(GPT55_TIMEOUT_S),
                    "--stop-launch-at", "00:00",
                ]
            )
        out_stop = buf_stop.getvalue()
        if rc_stop != 0 or "STOPPED LAUNCHING (stop-launch-at 00:00); 2 seed(s) never started" not in out_stop:
            errors.append(f"gemini_runner --stop-launch-at failed offline check: rc={rc_stop} out={out_stop!r}")

        stg_cap = tmp_dir / "spend_cap"
        ep0_dir = stg_cap / "opencode" / "hard" / "0"
        ep0_dir.mkdir(parents=True, exist_ok=True)
        (ep0_dir / "episodes.jsonl").write_text(
            json.dumps(
                {
                    "tier": "hard",
                    "seed": 0,
                    "agent": "opencode:openai/gpt-5.5",
                    "score": 0.6,
                    "correct": True,
                    "accused": "e01",
                    "final_day": 8,
                    "end_reason": "accused",
                    "meta": {"rc": 0, "usage": {"cost_usd_est": 200.0, "cost_usd_upper": 220.0}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        buf_cap = io.StringIO()
        with contextlib.redirect_stdout(buf_cap):
            rc_cap = gr.main(
                [
                    "--tiers-version", "v1.4",
                    "--staging", str(stg_cap),
                    "--model", "gpt-5.5",
                    "--seeds", "0-2",
                    "--tiers", "hard",
                    "--harnesses", "opencode",
                    "--timeout", str(GPT55_TIMEOUT_S),
                    "--max-spend-usd", "200",
                    "--stop-launch-at", "99:99",
                ]
            )
        out_cap = buf_cap.getvalue()
        if rc_cap != 0 or "STOPPED LAUNCHING (spend cap $200 reached (est $200.00)); 2 seed(s) never started" not in out_cap:
            errors.append(f"gemini_runner --max-spend-usd failed offline check: rc={rc_cap} out={out_cap!r}")

        stg_assume = tmp_dir / "assume_cost"
        for s_idx in (0, 1):
            sd = stg_assume / "opencode" / "hard" / str(s_idx)
            sd.mkdir(parents=True, exist_ok=True)
            (sd / "episodes.jsonl").write_text(
                json.dumps(
                    {
                        "tier": "hard",
                        "seed": s_idx,
                        "agent": "opencode:openai/gpt-5.5",
                        "score": 0.5,
                        "correct": True,
                        "accused": "e01",
                        "final_day": 9,
                        "end_reason": "accused",
                        "meta": {"rc": 0, "usage": {"cost_unknown": True}},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        buf_assume_block = io.StringIO()
        with contextlib.redirect_stdout(buf_assume_block):
            rc_ab = gr.main(
                [
                    "--tiers-version", "v1.4",
                    "--staging", str(stg_assume),
                    "--model", "gpt-5.5",
                    "--seeds", "0-2",
                    "--tiers", "hard",
                    "--harnesses", "opencode",
                    "--timeout", str(GPT55_TIMEOUT_S),
                    "--max-spend-usd", "15",
                    "--assume-cost-usd", "10.0",
                    "--stop-launch-at", "99:99",
                ]
            )
        out_ab = buf_assume_block.getvalue()
        if rc_ab != 0 or "STOPPED LAUNCHING (spend cap $15 reached (est $20.00)); 1 seed(s) never started" not in out_ab:
            errors.append(f"gemini_runner --assume-cost-usd block check failed: rc={rc_ab} out={out_ab!r}")

        buf_assume_dry = io.StringIO()
        with contextlib.redirect_stdout(buf_assume_dry):
            rc_ad = gr.main(
                [
                    "--tiers-version", "v1.4",
                    "--staging", str(stg_assume),
                    "--model", "gpt-5.5",
                    "--seeds", "0-2",
                    "--tiers", "hard",
                    "--harnesses", "opencode",
                    "--timeout", str(GPT55_TIMEOUT_S),
                    "--max-spend-usd", "25",
                    "--assume-cost-usd", "10.0",
                    "--stop-launch-at", "99:99",
                    "--dry-run",
                ]
            )
        out_ad = buf_assume_dry.getvalue()
        if rc_ad != 0 or "DRY opencode/hard/2:" not in out_ad or "--model openai/gpt-5.5" not in out_ad:
            errors.append(f"gemini_runner --assume-cost-usd dry-run check failed: rc={rc_ad} out={out_ad!r}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "passed": not errors,
        "source_commit": GPT55_PREREG_COMMIT,
        "provider_routes_verified": 7,
        "controls_verified": [
            "provider_model_google_and_openai",
            "--max-spend-usd",
            "--assume-cost-usd",
            "--stop-launch-at",
            "--tiers-version",
        ],
        "zero_live_subprocesses": True,
        "errors": errors,
    }


def check_workdir_isolation(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    wd = common.make_clean_workdir()
    bad_wd = common.make_clean_workdir()
    try:
        repo_resolved = common.REPO_ROOT.resolve()
        root_resolved = root.resolve()
        wd_resolved = wd.resolve()
        if repo_resolved in wd_resolved.parents or wd_resolved == repo_resolved:
            errors.append(f"workdir {wd_resolved} is inside REPO_ROOT {repo_resolved}")
        if root_resolved in wd_resolved.parents or wd_resolved == root_resolved:
            errors.append(f"workdir {wd_resolved} is inside target root {root_resolved}")
        if list(wd.iterdir()):
            errors.append("fresh make_clean_workdir was not empty")
        cmd_google = opencode_run.build_cmd(wd, "PROMPT", "gemini-4-carbon", "http://127.0.0.1:18765/mcp")
        expected_google = [
            "opencode", "run", "--model", "google/gemini-4-carbon", "--format", "json", "--dir", str(wd), "PROMPT"
        ]
        if cmd_google != expected_google:
            errors.append(f"unexpected google build_cmd output: {cmd_google!r}")
        cmd_openai = opencode_run.build_cmd(wd, "PROMPT", "gpt-5.5", "http://127.0.0.1:18765/mcp")
        expected_openai = [
            "opencode", "run", "--model", "openai/gpt-5.5", "--format", "json", "--dir", str(wd), "PROMPT"
        ]
        if cmd_openai != expected_openai:
            errors.append(f"unexpected openai build_cmd output: {cmd_openai!r}")
        common.assert_clean(wd, opencode_run.FILES)

        (bad_wd / "opencode.json").write_text("{}", encoding="utf-8")
        (bad_wd / "leak.py").write_text("x = 1\n", encoding="utf-8")
        caught = False
        try:
            common.assert_clean(bad_wd, opencode_run.FILES)
        except AssertionError:
            caught = True
        if not caught:
            errors.append("assert_clean failed to reject unexpected .py file in workdir")
    finally:
        shutil.rmtree(wd, ignore_errors=True)
        shutil.rmtree(bad_wd, ignore_errors=True)

    if wd.exists() or bad_wd.exists():
        errors.append("temporary workdir cleanup failed")
    return {
        "passed": not errors,
        "outside_repo_root": True,
        "allowed_files": sorted(opencode_run.FILES),
        "cleaned_up": True,
        "errors": errors,
    }


def _audit_single_transcript(
    root: Path,
    tr_rel: str,
    episode: dict[str, Any],
    unredacted_rx: re.Pattern[str],
    errors: list[str],
) -> int:
    raw_txt = (root / tr_rel).read_text(encoding="utf-8")
    if unredacted_rx.search(raw_txt):
        errors.append(f"unredacted thoughtSignature in {tr_rel}")
    stdout, stderr = split_transcript(raw_txt)
    if common.empty_final_response(stdout):
        errors.append(f"verified transcript {tr_rel} flagged empty_final_response")
    infra_tag = common.classify_infra(stdout, stderr)
    if infra_tag is not None:
        errors.append(f"verified transcript {tr_rel} flagged infra={infra_tag}")
    rebuilt = common.steps_from_events(stdout)
    recorded_steps = episode.get("steps") or []
    if len(rebuilt) != len(recorded_steps):
        errors.append(
            f"steps_from_events count mismatch on {tr_rel}: "
            f"rebuilt={len(rebuilt)} != recorded={len(recorded_steps)}"
        )
    elif [s.tool for s in rebuilt] != [s["tool"] for s in recorded_steps]:
        errors.append(f"steps_from_events tool sequence mismatch on {tr_rel}")
    elif [s.day for s in rebuilt] != [s["day"] for s in recorded_steps]:
        errors.append(f"steps_from_events day sequence mismatch on {tr_rel}")
    elif [s.args for s in rebuilt] != [s["args"] for s in recorded_steps]:
        errors.append(f"steps_from_events args mismatch on {tr_rel}")
    return len(rebuilt)


def check_transcript_redaction_and_infra(
    root: Path,
    records_by_agent_tier: dict[tuple[str, str], dict[int, dict[str, Any]]],
    committed_g1_ext_records: dict[int, dict[str, Any]] | None = None,
    committed_gpt55_records: dict[int, dict[str, Any]] | None = None,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    long_sig = "T" * 240
    short_sig = "s" * 24
    synthetic_line = json.dumps(
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "canary_status",
                "state": {"status": "completed", "input": {}, "output": '{"ok": true}'},
                "metadata": {
                    "google": {"thoughtSignature": long_sig},
                    "short": {"thoughtSignature": short_sig},
                },
            },
        }
    )
    compacted = common.compact_transcript(synthetic_line)
    if long_sig in compacted or '"thoughtSignature":"<240 chars>"' not in compacted:
        errors.append("compact_transcript failed to redact 240-char thoughtSignature blob")
    if short_sig not in compacted:
        errors.append("compact_transcript unexpectedly altered short <64-char thoughtSignature")

    empty_stop = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop", "tokens": {}}}),
        ]
    )
    normal_stop = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps({"type": "text", "part": {"type": "text", "text": "Accused e05."}}),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop", "tokens": {}}}),
        ]
    )
    tool_env_noise = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "type": "tool",
                        "tool": "canary_read_message",
                        "state": {
                            "status": "completed",
                            "input": {"id": "m1-0"},
                            "output": "UNAVAILABLE RESOURCE_EXHAUSTED database is locked usage limit has been reached",
                        },
                    },
                }
            ),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "tool-calls", "tokens": {}}}),
        ]
    )
    quota_err = json.dumps({"type": "error", "error": {"data": {"message": "usage limit has been reached"}}})
    rate_err = json.dumps({"type": "error", "error": {"data": {"message": "RESOURCE_EXHAUSTED"}}})
    unavail_err = json.dumps({"type": "error", "error": {"data": {"message": "The model is overloaded"}}})
    generic_err = json.dumps({"type": "error", "error": {"name": "SyntheticError"}})

    if not common.empty_final_response(empty_stop):
        errors.append("empty_final_response missed synthetic empty stop turn")
    if common.classify_infra(empty_stop, "") != "empty_model_response":
        errors.append("classify_infra missed empty_model_response")
    if common.empty_final_response(normal_stop) or common.classify_infra(normal_stop, "") is not None:
        errors.append("normal stop turn misclassified as infra/empty")
    if common.classify_infra(tool_env_noise, "") is not None:
        errors.append("tool output text misclassified as infra error")
    if common.classify_infra(quota_err, "") != "provider_quota":
        errors.append("classify_infra missed provider_quota")
    if common.classify_infra(rate_err, "") != "provider_rate_limit":
        errors.append("classify_infra missed provider_rate_limit")
    if common.classify_infra(unavail_err, "") != "provider_unavailable":
        errors.append("classify_infra missed provider_unavailable")
    if common.classify_infra("", "Error: database is locked") != "opencode_db_locked":
        errors.append("classify_infra missed opencode_db_locked")
    if common.classify_infra(generic_err, "") != "cli_error_event":
        errors.append("classify_infra missed cli_error_event")

    unredacted_rx = re.compile(r'"thoughtSignature":\s?"[^"<]{64,}"')
    real_transcripts_checked = 0
    carbon_step_counts: dict[str, int] = {}
    committed_g1_ext_step_counts: dict[str, int] = {}
    committed_g1_ext_checked = 0
    flash_medium_s28_steps: int | None = None

    carbon_records = records_by_agent_tier.get(("opencode:google/gemini-4-carbon", "hard"), {})
    flash_medium_records = records_by_agent_tier.get(("opencode:google/gemini-3.5-flash", "medium"), {})
    if enforce_expected_baseline:
        for req_seed in EXPECTED_CARBON_HARD_LANDED:
            if req_seed not in carbon_records:
                errors.append(f"missing verified carbon hard replication record for seed {req_seed}")
        for req_seed in EXPECTED_FLASH_MEDIUM_LANDED:
            if req_seed not in flash_medium_records:
                errors.append(f"missing verified flash medium replication record for seed {req_seed}")

    for (agent, tier), seed_map in sorted(records_by_agent_tier.items()):
        if not agent.startswith("opencode:"):
            continue
        for seed, rec in sorted(seed_map.items()):
            tr_rel = rec["transcript_file"]
            if not tr_rel:
                continue
            real_transcripts_checked += 1
            step_n = _audit_single_transcript(root, tr_rel, rec["episode"], unredacted_rx, errors)
            if agent == "opencode:google/gemini-4-carbon" and tier == "hard" and 30 <= seed <= 59:
                carbon_step_counts[str(seed)] = step_n
            if agent == "opencode:google/gemini-3.5-flash" and tier == "medium" and seed == 28:
                flash_medium_s28_steps = step_n

    for seed, rec in sorted((committed_g1_ext_records or {}).items()):
        tr_rel = rec.get("transcript_file")
        if not tr_rel:
            continue
        committed_g1_ext_checked += 1
        committed_g1_ext_step_counts[str(seed)] = _audit_single_transcript(
            root, tr_rel, rec["episode"], unredacted_rx, errors
        )

    committed_gpt55_checked = 0
    committed_gpt55_total_steps = 0
    for seed, rec in sorted((committed_gpt55_records or {}).items()):
        tr_rel = rec.get("transcript_file")
        if not tr_rel:
            continue
        committed_gpt55_checked += 1
        committed_gpt55_total_steps += _audit_single_transcript(
            root, tr_rel, rec["episode"], unredacted_rx, errors
        )

    return {
        "passed": not errors,
        "synthetic_cases_verified": 9,
        "real_transcripts_checked": real_transcripts_checked,
        "committed_g1_ext_transcripts_checked": committed_g1_ext_checked,
        "committed_gpt55_transcripts_checked": committed_gpt55_checked,
        "committed_gpt55_total_steps": committed_gpt55_total_steps,
        "carbon_hard_step_counts": carbon_step_counts,
        "committed_g1_ext_step_counts": committed_g1_ext_step_counts,
        "flash_medium_s28_steps": flash_medium_s28_steps,
        "errors": errors,
    }


def build_provenance_honesty(
    committed_g1_seeds: list[int],
    committed_g1_quota_excluded: int,
    fr8_carbon_seeds: list[int],
    combined_carbon_ext_seeds: list[int],
    committed_gpt55_seeds: list[int],
    committed_gpt55_clean_unended_seeds: list[int],
    committed_gpt55_infra_excluded: int,
) -> dict[str, Any]:
    return {
        "panel_doc": PANEL_DOC,
        "panel_status_commit": PANEL_STATUS_COMMIT,
        "panel_fix_a_commit": PANEL_FIX_A_COMMIT,
        "panel_fix_d_commit": PANEL_FIX_D_COMMIT,
        "upstream_reconciled_commit": UPSTREAM_RECONCILED_COMMIT,
        "cohorts": {
            "primary_carbon_0_29": {
                "classification": "post_hoc_lock",
                "seed_range": [0, 29],
                "episodes_commit": PRIMARY_EPISODES_COMMIT,
                "lock_commit": PRIMARY_POST_HOC_LOCK_COMMIT,
                "lock_delay_s": PRIMARY_POST_HOC_LOCK_DELAY_S,
                "solver_reference_dirs": [
                    "data/runs/committed/v1.4/reference/solver-hard-20261114-121126",
                    "data/runs/committed/v1.4/reference/solver-hard-seeds20to29",
                ],
                "note": (
                    "Primary 0-29 seed lock (671ed96) landed 28s after episodes commit (8fd4dec); "
                    "classified as a post-hoc lock against reruns and cherry-picking, not a pre-registration."
                ),
            },
            "g1_carbon_hard_30_59": {
                "classification": "pre_registered",
                "seed_range": [30, 59],
                "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
                "committed_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
                "committed_landed_seeds": committed_g1_seeds,
                "committed_n": len(committed_g1_seeds),
                "committed_provider_quota_excluded": committed_g1_quota_excluded,
                "fr8_replication_dir": "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
                "fr8_replication_landed_seeds": fr8_carbon_seeds,
                "fr8_replication_n": len(fr8_carbon_seeds),
                "combined_distinct_seeds": combined_carbon_ext_seeds,
                "combined_distinct_n": len(combined_carbon_ext_seeds),
            },
            "g2_argon_hydrogen_hard_0_29": {
                "classification": "pre_registered",
                "models": list(G2_MODELS),
                "tier": "hard",
                "seed_range": [0, 29],
                "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
                "committed_n": 0,
            },
            "gpt_5_5_hard_0_29": {
                "classification": "pre_registered",
                "cohort_id": "opencode-openai-gpt-5.5-hard-0-29",
                "agent": "opencode:openai/gpt-5.5",
                "model": OPENAI_GPT55_MODEL,
                "tier": "hard",
                "seed_range": [0, 29],
                "timeout_s": GPT55_TIMEOUT_S,
                "max_spend_usd": 200.0,
                "stop_launch_at": "08:15",
                "hard_drop_at": "08:45",
                "pre_registered_commit": GPT55_PREREG_COMMIT,
                "committed_commit": GPT55_COMMITTED_COMMIT,
                "committed_dir": GPT55_COMMITTED_DIR,
                "execution_owner": "silas_ca0a0dc0_committed_complete",
                "committed_n": len(committed_gpt55_seeds),
                "committed_infra_excluded": committed_gpt55_infra_excluded,
                "clean_unended_rc0_seeds": committed_gpt55_clean_unended_seeds,
            },
        },
    }


def build_manifest(
    root: Path = ROOT,
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    scan = scan_replication_tree(root, TARGET_COHORTS, enforce_expected_baseline=enforce_expected_baseline)
    committed_scan = scan_committed_v14_tree(root, enforce_expected_baseline=enforce_expected_baseline)
    committed_lookup = committed_scan.get("landed_by_agent_tier", {})
    reconciled_templates = reconcile_template_cohorts(TEMPLATE_COHORTS, committed_lookup)
    waves = partition_into_waves(
        scan["cohorts"],
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=False,
    )
    template_waves = build_template_waves(scan["cohorts"], max_workers_per_wave=max_workers_per_wave)
    g2_template_waves = build_g2_template_waves(max_workers_per_wave=max_workers_per_wave)
    gpt55_template_waves = build_gpt55_template_waves(
        max_workers_per_wave=max_workers_per_wave,
        root=root,
        committed_landed_by_agent_tier=committed_lookup,
    )
    gpt55_synthetic_waves = build_gpt55_template_waves(
        max_workers_per_wave=max_workers_per_wave,
        include_committed=True,
    )
    cross_family_waves = build_cross_family_template_waves(
        max_workers_per_wave=max_workers_per_wave,
        root=root,
        committed_landed_by_agent_tier=committed_lookup,
    )

    tiers_check = check_tiers_gate()
    config_check = check_opencode_config_isolation()
    env_check = check_child_env_stripping()
    runner_check = check_gemini_runner_controls()
    workdir_check = check_workdir_isolation(root)
    transcript_check = check_transcript_redaction_and_infra(
        root,
        scan.get("records_by_agent_tier", {}),
        committed_g1_ext_records=committed_scan.get("g1_ext_records", {}),
        committed_gpt55_records=committed_scan.get("gpt55_records", {}),
        enforce_expected_baseline=enforce_expected_baseline,
    )
    active_cmd_check = validate_wave_commands(waves)
    template_cmd_check = validate_wave_commands(template_waves)
    g2_cmd_check = validate_wave_commands(g2_template_waves)
    gpt55_cmd_check = validate_wave_commands(gpt55_template_waves)
    gpt55_syn_cmd_check = validate_wave_commands(gpt55_synthetic_waves)
    cmd_errors = (
        list(active_cmd_check["errors"])
        + list(template_cmd_check["errors"])
        + list(g2_cmd_check["errors"])
        + list(gpt55_cmd_check["errors"])
        + list(gpt55_syn_cmd_check["errors"])
    )
    cohorts_by_id = {c["cohort_id"]: c for c in scan["cohorts"]}
    for w in waves:
        cohort_obj = cohorts_by_id.get(w["cohort_id"])
        if cohort_obj is not None and not cohort_obj.get("fr8_dispatch_enabled", False):
            cmd_errors.append(f"active wave {w['wave_id']} dispatches disabled cohort {w['cohort_id']}")
    tmpl_by_id = {c["cohort_id"]: c for c in reconciled_templates}
    for w in cross_family_waves:
        t_obj = tmpl_by_id.get(w["cohort_id"])
        if t_obj is not None:
            overlap = sorted(set(w["seeds"]) & set(t_obj.get("landed_seeds", [])))
            if overlap:
                cmd_errors.append(
                    f"cross-family template wave {w['wave_id']} queues committed seeds {overlap} for {w['cohort_id']}"
                )
    cmd_check = {
        "passed": not cmd_errors,
        "active_waves_validated": len(waves),
        "active_commands_validated": active_cmd_check["commands_validated"],
        "template_waves_validated": len(template_waves),
        "commands_validated": template_cmd_check["commands_validated"],
        "g2_family_waves_validated": len(g2_template_waves),
        "g2_family_commands_validated": g2_cmd_check["commands_validated"],
        "gpt55_waves_validated": len(gpt55_template_waves),
        "gpt55_commands_validated": gpt55_cmd_check["commands_validated"],
        "gpt55_synthetic_waves_validated": len(gpt55_synthetic_waves),
        "gpt55_synthetic_commands_validated": gpt55_syn_cmd_check["commands_validated"],
        "cross_family_waves_validated": len(cross_family_waves),
        "cross_family_commands_validated": g2_cmd_check["commands_validated"] + gpt55_cmd_check["commands_validated"],
        "max_workers_per_wave": max_workers_per_wave,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "gpt55_timeout_s": GPT55_TIMEOUT_S,
        "jobs_per_worker": DEFAULT_JOBS,
        "errors": cmd_errors,
    }
    blackout_check = check_carbon_quota_blackout_guard()

    carbon_cohort = cohorts_by_id.get("opencode-gemini-4-carbon-hard-30-59", {})
    fr8_carbon_seeds = list(carbon_cohort.get("landed_seeds", []))
    committed_g1_seeds = list(committed_scan["g1_ext_landed_seeds"])
    committed_gpt55_seeds = list(committed_scan["gpt55_landed_seeds"])
    committed_gpt55_clean_unended = list(committed_scan["gpt55_clean_unended_seeds"])
    committed_gpt55_infra_excluded = int(committed_scan["gpt55_infra_excluded"])
    combined_ext_seeds = sorted(set(committed_g1_seeds) | set(fr8_carbon_seeds))
    shared_ext_seeds = sorted(set(committed_g1_seeds) & set(fr8_carbon_seeds))
    combined_ext_remaining = sorted(set(range(30, 60)) - set(combined_ext_seeds))

    reconcile_errors = list(committed_scan["errors"])
    combined_total = committed_scan["total_episodes"] + scan["total_episodes"]
    combined_verified = committed_scan["replay_verified_episodes"] + scan["replay_verified_episodes"]
    if enforce_expected_baseline:
        if combined_total != EXPECTED_COMBINED_V14_EPISODES or combined_verified != EXPECTED_COMBINED_V14_EPISODES:
            reconcile_errors.append(
                f"expected {EXPECTED_COMBINED_V14_EPISODES}/{EXPECTED_COMBINED_V14_EPISODES} "
                f"combined v1.4 episodes, got {combined_verified}/{combined_total}"
            )
        if combined_ext_seeds != EXPECTED_COMBINED_CARBON_HARD_EXT_LANDED:
            reconcile_errors.append(
                f"expected combined carbon hard 30-59 coverage {EXPECTED_COMBINED_CARBON_HARD_EXT_LANDED}, "
                f"got {combined_ext_seeds}"
            )
        if len(combined_ext_remaining) != EXPECTED_COMBINED_CARBON_HARD_EXT_REMAINING_COUNT:
            reconcile_errors.append(
                f"expected {EXPECTED_COMBINED_CARBON_HARD_EXT_REMAINING_COUNT} remaining carbon hard 30-59 seeds, "
                f"got {len(combined_ext_remaining)}"
            )
        if len(gpt55_template_waves) != 0:
            reconcile_errors.append(
                f"expected 0 remaining gpt-5.5 template waves after ca0a0dc0 reconciliation, got {len(gpt55_template_waves)}"
            )

    reconcile_check = {
        "passed": not reconcile_errors,
        "committed_v14_episodes": committed_scan["total_episodes"],
        "committed_v14_replay_verified": committed_scan["replay_verified_episodes"],
        "replication_v14_episodes": scan["total_episodes"],
        "replication_v14_replay_verified": scan["replay_verified_episodes"],
        "combined_v14_episodes": combined_total,
        "combined_v14_replay_verified": combined_verified,
        "g1_committed_landed_seeds": committed_g1_seeds,
        "g1_committed_provider_quota_excluded": committed_scan["g1_ext_provider_quota_excluded"],
        "g1_fr8_landed_seeds": fr8_carbon_seeds,
        "g1_combined_distinct_seeds": combined_ext_seeds,
        "g1_combined_remaining_count": len(combined_ext_remaining),
        "gpt55_committed_landed_count": len(committed_gpt55_seeds),
        "gpt55_committed_clean_unended_seeds": committed_gpt55_clean_unended,
        "gpt55_committed_infra_excluded": committed_gpt55_infra_excluded,
        "errors": reconcile_errors,
    }

    checks = {
        "tiers_v14_gate": tiers_check,
        "opencode_config_permission": config_check,
        "child_env_isolation": env_check,
        "gemini_runner_cf394894_controls": runner_check,
        "clean_workdir_isolation": workdir_check,
        "transcript_redaction_infra_and_steps": transcript_check,
        "cli_command_validation": cmd_check,
        "carbon_quota_blackout_guard": blackout_check,
        "v14_corpus_reconciliation": reconcile_check,
    }
    all_errors = list(scan["errors"])
    for chk in checks.values():
        all_errors.extend(chk["errors"])

    total_target = sum(c["target_count"] for c in scan["cohorts"])
    total_landed = sum(c["landed_count"] for c in scan["cohorts"])
    total_missing = sum(c["missing_count"] for c in scan["cohorts"])
    template_cohort_rows = serialize_template_cohorts(reconciled_templates)
    provenance_honesty = build_provenance_honesty(
        committed_g1_seeds=committed_g1_seeds,
        committed_g1_quota_excluded=committed_scan["g1_ext_provider_quota_excluded"],
        fr8_carbon_seeds=fr8_carbon_seeds,
        combined_carbon_ext_seeds=combined_ext_seeds,
        committed_gpt55_seeds=committed_gpt55_seeds,
        committed_gpt55_clean_unended_seeds=committed_gpt55_clean_unended,
        committed_gpt55_infra_excluded=committed_gpt55_infra_excluded,
    )

    return {
        "schema_version": 1,
        "tiers_version": rules.TIERS_VERSION,
        "upstream_reconciled_commit": UPSTREAM_RECONCILED_COMMIT,
        "replication_root": scan["replication_root"],
        "corpus_reconciliation": {
            "committed_v14": {
                "root": committed_scan["committed_root"],
                "total_episodes": committed_scan["total_episodes"],
                "replay_verified_episodes": committed_scan["replay_verified_episodes"],
            },
            "fr8_replication_v14": {
                "root": scan["replication_root"],
                "total_episodes": scan["total_episodes"],
                "replay_verified_episodes": scan["replay_verified_episodes"],
                "frontier_target_episodes": total_target,
                "frontier_landed_episodes": total_landed,
                "frontier_missing_episodes": total_missing,
            },
            "combined_v14_total_episodes": combined_total,
            "combined_v14_replay_verified_episodes": combined_verified,
            "carbon_hard_30_59_extension": {
                "seed_range": [30, 59],
                "target_count": 30,
                "committed_g1_partial": {
                    "run_dir": committed_scan["g1_ext_dir"],
                    "landed_seeds": committed_g1_seeds,
                    "n": len(committed_g1_seeds),
                    "provider_quota_excluded": committed_scan["g1_ext_provider_quota_excluded"],
                },
                "fr8_replication": {
                    "run_dir": "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
                    "landed_seeds": fr8_carbon_seeds,
                    "n": len(fr8_carbon_seeds),
                    "fr8_tree_remaining_count": int(carbon_cohort.get("missing_count", 25)),
                },
                "combined_distinct_landed_seeds": combined_ext_seeds,
                "combined_distinct_count": len(combined_ext_seeds),
                "shared_overlap_seeds": shared_ext_seeds,
                "shared_overlap_count": len(shared_ext_seeds),
                "combined_remaining_seeds": combined_ext_remaining,
                "combined_remaining_count": len(combined_ext_remaining),
            },
            "gpt55_hard_0_29_committed": {
                "run_dir": committed_scan["gpt55_dir"],
                "seed_range": [0, 29],
                "target_count": 30,
                "landed_count": len(committed_gpt55_seeds),
                "remaining_count": 30 - len(committed_gpt55_seeds),
                "clean_unended_rc0_seeds": committed_gpt55_clean_unended,
                "infra_excluded": committed_gpt55_infra_excluded,
                "pre_registered_commit": GPT55_PREREG_COMMIT,
                "committed_commit": GPT55_COMMITTED_COMMIT,
            },
        },
        "provenance_honesty": provenance_honesty,
        "gemini_sessions": {
            "source_doc": GEMINI_SESSIONS_DOC,
            "source_commit": GEMINI_SESSIONS_COMMIT,
            "pure_cpu_mode": True,
            "fr8_live_gemini_dispatch_enabled": any(
                c["fr8_dispatch_enabled"] for c in scan["cohorts"] + template_cohort_rows
            ),
            "g1_carbon_hard_ext60": {
                "cohort_id": "opencode-gemini-4-carbon-hard-30-59",
                "execution_owner": "silas_g1_ext60",
                "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
                "fr8_dispatch_enabled": False,
                "model": CARBON_MODEL,
                "tier": "hard",
                "seed_range": [30, 59],
                "committed_ext_dir": committed_scan["g1_ext_dir"],
                "committed_landed_seeds": committed_g1_seeds,
                "committed_landed_count": len(committed_g1_seeds),
                "committed_provider_quota_excluded": committed_scan["g1_ext_provider_quota_excluded"],
                "fr8_landed_seeds": fr8_carbon_seeds,
                "remaining_count": int(carbon_cohort.get("missing_count", 25)),
                "combined_distinct_landed_seeds": combined_ext_seeds,
                "combined_distinct_count": len(combined_ext_seeds),
                "combined_remaining_count": len(combined_ext_remaining),
            },
            "g2_frontier_families_hard_0_29": {
                "execution_owner": "silas_g2_families",
                "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
                "fr8_dispatch_enabled": False,
                "models": list(G2_MODELS),
                "tier": "hard",
                "seed_range": [0, 29],
                "allowed_during_carbon_blackout": True,
            },
            "gpt55_hard_0_29": {
                "cohort_id": "opencode-openai-gpt-5.5-hard-0-29",
                "agent": "opencode:openai/gpt-5.5",
                "model": OPENAI_GPT55_MODEL,
                "tier": "hard",
                "seed_range": [0, 29],
                "timeout_s": GPT55_TIMEOUT_S,
                "max_spend_usd": 200.0,
                "stop_launch_at": "08:15",
                "hard_drop_at": "08:45",
                "pre_registered_commit": GPT55_PREREG_COMMIT,
                "committed_commit": GPT55_COMMITTED_COMMIT,
                "committed_dir": GPT55_COMMITTED_DIR,
                "committed_landed_count": len(committed_gpt55_seeds),
                "remaining_count": 30 - len(committed_gpt55_seeds),
                "clean_unended_rc0_seeds": committed_gpt55_clean_unended,
                "execution_owner": "silas_ca0a0dc0_committed_complete",
                "fr8_dispatch_enabled": False,
                "allowed_during_carbon_blackout": True,
            },
            "carbon_quota_blackout": {
                "window_start_utc": CARBON_BLACKOUT_START_ISO,
                "window_end_utc": CARBON_BLACKOUT_END_ISO,
                "window_local_eet": CARBON_BLACKOUT_LOCAL_WINDOW,
                "blocked_models": [CARBON_MODEL],
                "allowed_models": list(NON_CARBON_REHEARSAL_ALLOWED_MODELS),
                "reason": CARBON_BLACKOUT_REASON,
            },
        },
        "runner": {
            "module": RUNNER_MODULE,
            "python": VENV_PYTHON,
            "path_prefix": MOMIN_PATH_PREFIX,
            "timeout_s": DEFAULT_TIMEOUT_S,
            "gpt55_timeout_s": GPT55_TIMEOUT_S,
            "jobs_per_worker": DEFAULT_JOBS,
            "max_workers_per_wave": max_workers_per_wave,
        },
        "summary": {
            "passed": not all_errors,
            "pure_cpu_mode": True,
            "committed_v14_total_episodes": committed_scan["total_episodes"],
            "committed_v14_replay_verified_episodes": committed_scan["replay_verified_episodes"],
            "replication_total_episodes": scan["total_episodes"],
            "replication_replay_verified_episodes": scan["replay_verified_episodes"],
            "combined_v14_total_episodes": combined_total,
            "combined_v14_replay_verified_episodes": combined_verified,
            "target_frontier_episodes": total_target,
            "landed_frontier_episodes": total_landed,
            "missing_frontier_episodes": total_missing,
            "g1_committed_ext_episodes": len(committed_g1_seeds),
            "g1_committed_ext_provider_quota_excluded": committed_scan["g1_ext_provider_quota_excluded"],
            "g1_fr8_replication_episodes": len(fr8_carbon_seeds),
            "g1_combined_distinct_hard_ext_episodes": len(combined_ext_seeds),
            "g1_combined_remaining_hard_ext_episodes": len(combined_ext_remaining),
            "gpt55_committed_hard_episodes": len(committed_gpt55_seeds),
            "fr8_dispatch_active_episodes": sum(w["worker_count"] for w in waves),
            "wave_count": len(waves),
            "max_workers_in_any_wave": max((w["worker_count"] for w in waves), default=0),
            "template_wave_count": len(template_waves),
            "template_commands_validated": template_cmd_check["commands_validated"],
            "cross_family_template_wave_count": len(cross_family_waves),
            "cross_family_template_commands_validated": (
                g2_cmd_check["commands_validated"] + gpt55_cmd_check["commands_validated"]
            ),
            "gpt55_synthetic_template_commands_validated": gpt55_syn_cmd_check["commands_validated"],
        },
        "cohorts": scan["cohorts"],
        "template_cohorts": template_cohort_rows,
        "preflight": {
            "passed": not all_errors,
            "zero_live_llm_calls": True,
            "checks": checks,
            "errors": all_errors,
        },
        "waves": waves,
    }


def render_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2) + "\n"


def default_manifest_path(root: Path) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "queue_manifest.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline frontier runner preflight and 30-59 replication queue manifest.")
    ap.add_argument("--root", default=str(ROOT), help="repository root directory")
    ap.add_argument("--manifest", default=None, help="override output/check manifest path")
    ap.add_argument("--write", action="store_true", help="write queue_manifest.json")
    ap.add_argument("--check", action="store_true", help="verify preflight passes and queue_manifest.json is up to date")
    ap.add_argument(
        "--validate-template-waves",
        action="store_true",
        help="validate offline runner CLI syntax on synthetic/template waves while keeping active waves empty",
    )
    ap.add_argument("--check-blackout", default=None, help="evaluate carbon blackout guard at UTC epoch or ISO timestamp")
    ap.add_argument("--model", default=CARBON_MODEL, help="model id for --check-blackout")
    ap.add_argument("--json", action="store_true", help="print JSON output to stdout")
    args = ap.parse_args(argv)

    if args.check_blackout is not None:
        res = check_carbon_quota_blackout(args.check_blackout, model=args.model)
        if args.json:
            sys.stdout.write(json.dumps(res, indent=2) + "\n")
        else:
            print(
                f"blackout_check model={res['model']} ts={res['timestamp_utc']} "
                f"allowed={res['allowed']} reason={res['reason']}"
            )
        return 0 if res["allowed"] else 1

    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest).resolve() if args.manifest else default_manifest_path(root)
    enforce_baseline = root == ROOT.resolve()
    manifest = build_manifest(root=root, enforce_expected_baseline=enforce_baseline)
    rendered = render_manifest(manifest)

    if not manifest["summary"]["passed"]:
        for err in manifest["preflight"]["errors"]:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    if args.validate_template_waves:
        template_waves = build_template_waves(manifest["cohorts"])
        cross_waves = build_cross_family_template_waves(root=root)
        gpt55_syn_waves = build_gpt55_template_waves(include_committed=True)
        val_t = validate_wave_commands(template_waves)
        val_cross = validate_wave_commands(cross_waves)
        val_gpt55_syn = validate_wave_commands(gpt55_syn_waves)
        if not val_t["passed"] or not val_cross["passed"] or not val_gpt55_syn["passed"] or manifest["waves"] != []:
            for err in val_t["errors"] + val_cross["errors"] + val_gpt55_syn["errors"]:
                print(f"FAIL: {err}", file=sys.stderr)
            if manifest["waves"] != []:
                print("FAIL: active waves must be empty in pure-CPU mode", file=sys.stderr)
            return 1

    if args.write:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(rendered, encoding="utf-8")

    if args.check:
        if not manifest_path.is_file():
            print(f"FAIL: manifest missing at {manifest_path}", file=sys.stderr)
            return 1
        existing = manifest_path.read_text(encoding="utf-8")
        if existing != rendered:
            print(f"FAIL: manifest out of date at {manifest_path}; re-run with --write", file=sys.stderr)
            return 1

    if args.json:
        sys.stdout.write(rendered)
    else:
        s = manifest["summary"]
        cohort_bits = ", ".join(
            f"{c['cohort_id']}: owner={c['execution_owner']} dispatch={c['fr8_dispatch_enabled']} "
            f"landed={c['landed_count']}/{c['target_count']} missing={c['missing_count']}"
            for c in manifest["cohorts"]
        )
        print(
            f"OK preflight=PASS combined_verified={s['combined_v14_replay_verified_episodes']}/{s['combined_v14_total_episodes']} "
            f"committed={s['committed_v14_replay_verified_episodes']}/{s['committed_v14_total_episodes']} "
            f"replication={s['replication_replay_verified_episodes']}/{s['replication_total_episodes']} "
            f"fr8_landed={s['landed_frontier_episodes']}/{s['target_frontier_episodes']} "
            f"g1_combined_ext={s['g1_combined_distinct_hard_ext_episodes']}/30 "
            f"active_waves={s['wave_count']} template_cmds={s['template_commands_validated']} "
            f"cross_family_cmds={s['cross_family_template_commands_validated']} ({cohort_bits})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
