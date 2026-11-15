"""Deterministic verifier for committed Harbor artifacts, rehearsal-dry, and live judge rehearsals.

    python scripts/verify_harbor_rehearsal.py
    python scripts/verify_harbor_rehearsal.py --check
    python scripts/verify_harbor_rehearsal.py results/harbor/rehearsal --strict
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary import world
from canary.analysis.gap import mean_ci, pass_hat_k
from canary.eval import make_env, make_policy_factory, run_episode
from canary.redteam import anticheat as ac
from scripts import rehearsal_table as rt

HASH_CHAR = chr(35)
H1 = HASH_CHAR + " "
H2 = HASH_CHAR * 2 + " "
H3 = HASH_CHAR * 3 + " "
PR16 = f"PR {HASH_CHAR}16"
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
MINUS_SIGN = chr(0x2212)
PLUS_MINUS = chr(0x00B1)
DAGGER = chr(0x2020)

SCHEMA_VERSION = "verify_harbor_rehearsal_v14.v1"
TIERS_VERSION = "v1.4"
FLOAT_TOL = 1e-9
MAX_JSON_BYTES = 80 * 1024
BOOTSTRAP_B = 10000
BOOTSTRAP_SEED = 0
RERUN_SUFFIX = "-infra-rerun"

CLEAN_END_REASONS = frozenset({"accused", "horizon", "tool_cap"})
TIMEOUT_EXC_TYPES = frozenset({
    "AgentTimeoutError",
    "AgentSetupTimeoutError",
    "VerifierTimeoutError",
    "EnvironmentStartTimeoutError",
})
INFRA_EXC_TYPES = TIMEOUT_EXC_TYPES | frozenset({"ApiRateLimitError"})
JOB_ORDER = (
    "oracle",
    "opencode-1",
    "opencode-2",
    "opencode-3",
    "opencode",
    "do_nothing",
    "stop_early",
    "cheat-probe",
    "cheat_probe",
    "cheat",
    "signed-cheat",
)
LEGACY_STOP_EARLY_JOBS = frozenset({
    "results/harbor/stop_early",
    "results/harbor/signed-stop_early",
})

DEFAULT_OUT_JSON = ROOT / "results/eval_v14/verify_harbor_rehearsal.json"
DEFAULT_OUT_MD = ROOT / "docs/reports/harbor_rehearsal_verification_v14.md"
DEFAULT_HARBOR_DIR = ROOT / "results/harbor"
DEFAULT_NEGATIVE_DIR = ROOT / "results/harbor_negative"
DEFAULT_ORACLE_RANGE = ROOT / "results/oracle_range_v1.4.json"

ISO_OK_RE = re.compile(r"ISOLATION OK:\s*(\d+)\s+checks passed,\s*(\d+)\s+findings")


def norm_ascii(text: str) -> str:
    return (
        text.replace(EN_DASH, "-")
        .replace(EM_DASH, "--")
        .replace(MINUS_SIGN, "-")
        .replace(PLUS_MINUS, "+/-")
        .replace(DAGGER, "[rerun]")
    )


def clean_json_value(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 10)
    if isinstance(obj, str):
        return norm_ascii(obj)
    if isinstance(obj, dict):
        return {str(k): clean_json_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json_value(v) for v in obj]
    return obj


def approx_equal(a: Any, b: Any, tol: float = FLOAT_TOL) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        fa, fb = float(a), float(b)
        if not (math.isfinite(fa) and math.isfinite(fb)):
            return False
        return math.isclose(fa, fb, rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _fmt_num(x: float | None, nd: int = 3, signed: bool = True) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:+.{nd}f}" if signed else f"{x:.{nd}f}"


def _fmt_pct_ci(ratio: float | None, ci: list[float | None] | tuple[float | None, float | None]) -> str:
    if ratio is None or (isinstance(ratio, float) and math.isnan(ratio)):
        return "n/a"
    lo, hi = ci[0], ci[1]
    if lo is None or hi is None:
        return f"{ratio:.0%}"
    return f"{ratio:.0%} [{lo:.0%}, {hi:.0%}]"


def _clean_float(x: float | None, nd: int = 6) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def paired_bootstrap_ratio_ci(
    agent_scores: list[float],
    oracle_scores: list[float],
    n_boot: int = BOOTSTRAP_B,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    if not agent_scores or len(agent_scores) != len(oracle_scores):
        return None, None
    if _mean(oracle_scores) <= 0:
        return None, None
    if all(x == 0.0 for x in agent_scores):
        return 0.0, 0.0
    lo, hi = rt.boot_ratio(agent_scores, oracle_scores, n=n_boot, seed=seed)
    if math.isnan(lo) or math.isnan(hi):
        return None, None
    return float(lo), float(hi)


def _task_key(res: dict[str, Any], trial_dir: Path) -> str:
    raw = res.get("task_name")
    if isinstance(raw, str) and raw.strip():
        part = raw.strip().split("/")[-1]
        return part.removeprefix("canary-")
    return trial_dir.name.split("__")[0].removeprefix("canary-")


def _tier_from_task(task: str, led: dict[str, Any] | None) -> str:
    if isinstance(led, dict) and isinstance(led.get("tier"), str) and led["tier"]:
        return str(led["tier"])
    head = task.split("-")[0]
    return head if head in {"easy", "medium", "hard"} else "hard"


def _opencode_cli_error(opencode_log: Path) -> str | None:
    if not opencode_log.is_file():
        return None
    for line in opencode_log.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "AI_LoadAPIKeyError" in stripped:
            return "AI_LoadAPIKeyError"
        compact = stripped.replace(" ", "")
        if '"type":"error"' in compact:
            low = stripped.lower()
            if "thought_signature" in low:
                return "thought_signature rejected"
            if "quota" in low or "429" in low or "resource_exhausted" in low or "rate" in low:
                return "provider rate limit"
            m = re.search(r'"message"\s*:\s*"([^"]{1,60})', stripped)
            return "CLI error: " + (m.group(1) if m else "unknown")
    return None


def _detect_api_key_error(trial_dir: Path, res: dict[str, Any], cli_err: str | None) -> bool:
    if cli_err == "AI_LoadAPIKeyError":
        return True
    exc = res.get("exception_info")
    if isinstance(exc, dict):
        for field in ("exception_type", "exception_message", "exception_traceback"):
            val = exc.get(field)
            if isinstance(val, str) and "AI_LoadAPIKeyError" in val:
                return True
    elif isinstance(exc, str) and "AI_LoadAPIKeyError" in exc:
        return True
    exc_txt = trial_dir / "exception.txt"
    if exc_txt.is_file() and "AI_LoadAPIKeyError" in exc_txt.read_text(encoding="utf-8", errors="replace"):
        return True
    return False


def _extract_exception_type(res: dict[str, Any]) -> str | None:
    exc = res.get("exception_info")
    if exc is None:
        return None
    if isinstance(exc, dict):
        et = exc.get("exception_type")
        return str(et) if et else "UnknownHarborException"
    return str(exc)[:80]


def _parse_isolation_file(iso_file: Path) -> tuple[bool, bool, int | None, int | None]:
    if not iso_file.is_file():
        return False, False, None, None
    txt = iso_file.read_text(encoding="utf-8", errors="replace")
    iso_ok = "ISOLATION OK" in txt
    m = ISO_OK_RE.search(txt)
    if m:
        return True, iso_ok, int(m.group(1)), int(m.group(2))
    return True, iso_ok, None, None


def inspect_trial(trial_dir: Path, shared_key_file: Path | None = None) -> dict[str, Any]:
    ac_row = ac.check_harbor_trial(trial_dir)
    problems = list(ac_row.get("problems") or [])
    consistent = ac_row.get("consistent")

    res: dict[str, Any] = {}
    res_file = trial_dir / "result.json"
    if res_file.is_file():
        try:
            res = json.loads(res_file.read_text(encoding="utf-8"))
        except ValueError:
            res = {}

    led: dict[str, Any] | None = None
    led_file = trial_dir / "artifacts/ledger.json"
    if led_file.is_file():
        try:
            parsed = json.loads(led_file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                led = parsed
        except ValueError:
            led = None

    hmac_verified = ac_row.get("hmac_verified")
    if hmac_verified is None and shared_key_file is not None and shared_key_file.is_file() and led is not None:
        key_bytes = shared_key_file.read_text(encoding="utf-8").strip().encode()
        ok = ac._hmac_ok(led, key_bytes)
        hmac_verified = bool(ok)
        if not ok:
            problems.append("ledger HMAC does not verify under shared rehearsal ledger_key")
            consistent = False

    stdout_file = trial_dir / "verifier/test-stdout.txt"
    stdout_txt = stdout_file.read_text(encoding="utf-8", errors="replace").strip() if stdout_file.is_file() else ""
    verifier_fail_lines = [ln.strip() for ln in stdout_txt.splitlines() if ln.strip().startswith("FAIL:")]
    if verifier_fail_lines:
        msg = f"verifier failed closed: {verifier_fail_lines[0]}"
        if msg not in problems:
            problems.append(msg)
        consistent = False

    iso_present, iso_ok, iso_checks, iso_findings = _parse_isolation_file(trial_dir / "agent/isolation.txt")

    cheat_file = trial_dir / "agent/cheat.json"
    cheat_holes: list[str] | None = None
    cheat_attempts: int | None = None
    cheat_controls_failed: int | None = None
    cheat_incomplete: Any = None
    if cheat_file.is_file():
        try:
            rep = json.loads(cheat_file.read_text(encoding="utf-8"))
            if isinstance(rep, dict):
                if isinstance(rep.get("holes"), list):
                    cheat_holes = list(rep["holes"])
                if isinstance(rep.get("n_attempts"), int):
                    cheat_attempts = int(rep["n_attempts"])
                if isinstance(rep.get("controls_failed"), int):
                    cheat_controls_failed = int(rep["controls_failed"])
                cheat_incomplete = rep.get("incomplete")
        except ValueError:
            pass

    harbor_reward = ac_row.get("reward")
    exc_type = _extract_exception_type(res)
    end_reason = led.get("end_reason") if isinstance(led, dict) else None
    done = bool(led.get("done")) if isinstance(led, dict) else False
    cli_err = _opencode_cli_error(trial_dir / "agent/opencode.txt")
    has_api_key_err = _detect_api_key_error(trial_dir, res, cli_err)

    infra_reasons: list[str] = []
    infra_summary: str | None = None
    harmless_post_game_exit = False

    if harbor_reward is None:
        infra_reasons.append("missing_verifier_reward")
        infra_summary = f"no verifier reward ({exc_type})"
    if exc_type == "ApiRateLimitError":
        infra_reasons.append("ApiRateLimitError")
        infra_summary = infra_summary or "provider rate limit"
    elif exc_type == "AgentSetupTimeoutError":
        infra_reasons.append("AgentSetupTimeoutError")
        infra_summary = infra_summary or "agent setup timeout"
    elif exc_type in TIMEOUT_EXC_TYPES or (isinstance(exc_type, str) and "TimeoutError" in exc_type):
        if exc_type not in infra_reasons:
            infra_reasons.append(str(exc_type))
        infra_summary = infra_summary or str(exc_type)

    if has_api_key_err:
        if "AI_LoadAPIKeyError" not in infra_reasons:
            infra_reasons.append("AI_LoadAPIKeyError")
        infra_summary = infra_summary or "AI_LoadAPIKeyError"

    if not done and cli_err is not None and cli_err != "AI_LoadAPIKeyError":
        infra_reasons.append(cli_err)
        infra_summary = infra_summary or cli_err

    if end_reason == "error":
        infra_reasons.append("ledger_end_reason_error")
        infra_summary = infra_summary or "ledger_end_reason_error"

    if exc_type == "NonZeroAgentExitCodeError":
        if not has_api_key_err and harbor_reward is not None and done and end_reason in CLEAN_END_REASONS:
            harmless_post_game_exit = True
        elif not infra_reasons:
            infra_reasons.append("NonZeroAgentExitCodeError_without_clean_end")
            infra_summary = infra_summary or "NonZeroAgentExitCodeError_without_clean_end"
    elif exc_type is not None and exc_type not in infra_reasons:
        infra_reasons.append(exc_type)
        infra_summary = infra_summary or exc_type

    infra_invalid = bool(infra_reasons)
    valid_reward = None if infra_invalid else harbor_reward

    if consistent is None and not infra_invalid:
        consistent = not problems

    task = _task_key(res, trial_dir)
    tier = _tier_from_task(task, led)
    agent_cfg = (res.get("config") or {}).get("agent") or {}
    model_name = agent_cfg.get("model_name") or ((res.get("agent_info") or {}).get("model_info") or {}).get("name")

    return {
        "trial_dir": trial_dir.name,
        "task": task,
        "tier": tier,
        "policy": ac_row.get("policy") or agent_cfg.get("name"),
        "model": model_name,
        "harbor_reward": _clean_float(harbor_reward),
        "valid_reward": _clean_float(valid_reward),
        "consistent": consistent,
        "problems": problems,
        "signed": bool(ac_row.get("signed")),
        "hmac_verified": hmac_verified,
        "isolation_present": iso_present,
        "isolation_ok": iso_ok,
        "isolation_checks_passed": iso_checks,
        "isolation_findings": iso_findings,
        "trajectory_checked": bool(ac_row.get("trajectory_checked")),
        "cheat_holes": cheat_holes,
        "cheat_attempts": cheat_attempts,
        "cheat_controls_failed": cheat_controls_failed,
        "cheat_incomplete": cheat_incomplete,
        "exception_type": exc_type,
        "harmless_post_game_exit": harmless_post_game_exit,
        "infra_invalid": infra_invalid,
        "infra_reasons": infra_reasons,
        "infra_summary": infra_summary,
        "done": done,
        "end_reason": end_reason,
        "accused_present": bool(isinstance(led, dict) and led.get("accused") is not None),
        "correct": bool(led.get("correct")) if isinstance(led, dict) else False,
        "final_day": led.get("final_day") if isinstance(led, dict) else None,
        "verifier_fail_lines": verifier_fail_lines,
        "_ac_raw": ac_row,
    }


def inspect_job(job_dir: Path, shared_key_file: Path | None = None, rel_label: str | None = None) -> dict[str, Any]:
    trial_files = sorted(job_dir.glob("*/result.json"))
    trials = [inspect_trial(tf.parent, shared_key_file=shared_key_file) for tf in trial_files]
    ac_raw_rows: list[dict[str, Any]] = []
    for tf, t in zip(trial_files, trials):
        raw = dict(t.pop("_ac_raw"))
        raw["trial"] = tf.parent.as_posix()
        ac_raw_rows.append(raw)
    j_check = ac.check_harbor_job(job_dir, ac_raw_rows)

    valid_rewards = [float(t["valid_reward"]) for t in trials if t["valid_reward"] is not None]
    m, ci = mean_ci(valid_rewards) if valid_rewards else (float("nan"), float("nan"))
    policies = sorted({str(t["policy"]) for t in trials if t.get("policy")})
    models = sorted({str(t["model"]) for t in trials if t.get("model")})
    key_path = job_dir / "ledger_key"
    has_key = key_path.is_file()

    return {
        "job": job_dir.name,
        "rel_path": rel_label or job_dir.name,
        "policies": policies,
        "models": models,
        "has_retired_ledger_key": has_key,
        "n_trials": len(trials),
        "n_valid": len(valid_rewards),
        "n_infra_invalid": sum(1 for t in trials if t["infra_invalid"]),
        "n_post_game_nonzero_exit": sum(1 for t in trials if t["harmless_post_game_exit"]),
        "trials_consistent": sum(1 for t in trials if t["consistent"] is True),
        "trials_inconsistent": sum(1 for t in trials if t["consistent"] is False),
        "job_consistent": bool(j_check.get("consistent")),
        "job_problems": list(j_check.get("problems") or []),
        "signed_trials": sum(1 for t in trials if t["signed"]),
        "hmac_verified_trials": sum(1 for t in trials if t["hmac_verified"] is True),
        "hmac_failed_trials": sum(1 for t in trials if t["hmac_verified"] is False),
        "isolation_present_trials": sum(1 for t in trials if t["isolation_present"]),
        "isolation_ok_trials": sum(1 for t in trials if t["isolation_ok"]),
        "isolation_11of11_trials": sum(
            1
            for t in trials
            if t["isolation_ok"] and t["isolation_checks_passed"] == 11 and t["isolation_findings"] == 0
        ),
        "trajectory_checked_trials": sum(1 for t in trials if t["trajectory_checked"]),
        "accused_trials": sum(1 for t in trials if not t["infra_invalid"] and t["accused_present"]),
        "correct_trials": sum(1 for t in trials if not t["infra_invalid"] and t["correct"]),
        "mean_valid_reward": _clean_float(m),
        "ci95_valid_reward": _clean_float(ci),
        "trials": trials,
    }


def load_oracle_band(oracle_range_path: Path, tier: str = "hard", n_tasks: int = 10) -> dict[str, Any]:
    data = json.loads(oracle_range_path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    match = next((r for r in rows if r.get("agent") == "solver" and r.get("tier") == tier), None)
    dn_row = next((r for r in rows if r.get("agent") == "do_nothing" and r.get("tier") == tier), None)
    se_row = next((r for r in rows if r.get("agent") == "stop_early" and r.get("tier") == tier), None)
    if match is None:
        return {
            "source": oracle_range_path.name,
            "tier": tier,
            "k_key": "fallback",
            "builds": 0,
            "mean": 0.569,
            "sd": 0.094,
            "p5": 0.393,
            "p50": 0.60,
            "p95": 0.678,
            "p_lt0": 0.0,
            "band_90pct": [0.39, 0.68],
            "do_nothing_all_builds_zero": False,
            "stop_early_all_builds_zero": False,
        }
    k_key = f"k{n_tasks}" if f"k{n_tasks}" in match else "k10"
    stats = match[k_key]
    lo = round(float(stats["p5"]), 2)
    hi = round(float(stats["p95"]), 2)
    dn_zero = bool(
        dn_row is not None
        and dn_row.get("builds") == match.get("builds")
        and dn_row.get(k_key, {}).get("mean") == 0.0
        and dn_row.get(k_key, {}).get("sd") == 0.0
    )
    se_zero = bool(
        se_row is not None
        and se_row.get("builds") == match.get("builds")
        and se_row.get(k_key, {}).get("mean") == 0.0
        and se_row.get(k_key, {}).get("sd") == 0.0
    )
    return {
        "source": oracle_range_path.name,
        "tier": tier,
        "k_key": k_key,
        "builds": int(match.get("builds", 200)),
        "mean": round(float(stats["mean"]), 6),
        "sd": round(float(stats["sd"]), 6),
        "p5": round(float(stats["p5"]), 6),
        "p50": round(float(stats["p50"]), 6),
        "p95": round(float(stats["p95"]), 6),
        "p_lt0": round(float(stats.get("p_lt0", 0.0)), 6),
        "band_90pct": [lo, hi],
        "do_nothing_all_builds_zero": dn_zero,
        "stop_early_all_builds_zero": se_zero,
    }


def _discover_direct_jobs(folder: Path, shared_key_file: Path | None = None) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return jobs
    for sub in sorted(folder.iterdir()):
        if not sub.is_dir():
            continue
        if (sub / "config.json").is_file() and (sub / "agent").is_dir():
            continue
        if (sub / "result.json").is_file() and any(sub.glob("*/result.json")):
            jobs[sub.name] = inspect_job(sub, shared_key_file=shared_key_file, rel_label=sub.name)
        elif any(sub.glob("*/result.json")) and not (sub / "result.json").is_file():
            jobs[sub.name] = inspect_job(sub, shared_key_file=shared_key_file, rel_label=sub.name)
    return jobs


def _discover_all_harbor_jobs(harbor_dir: Path, root: Path = ROOT) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    if not harbor_dir.is_dir():
        return found
    candidates = sorted({*harbor_dir.glob("*/result.json"), *harbor_dir.glob("*/*/result.json")})
    for job_res in candidates:
        job_dir = job_res.parent
        if not any(job_dir.glob("*/result.json")):
            continue
        if (job_dir / "config.json").is_file() and (job_dir / "agent").is_dir():
            continue
        rel = job_dir.relative_to(root).as_posix() if job_dir.is_relative_to(root) else job_dir.as_posix()
        found.append((rel, job_dir))
    return sorted(found, key=lambda pair: pair[0])


def _sort_job_names(names: list[str]) -> list[str]:
    return sorted(names, key=lambda n: (JOB_ORDER.index(n) if n in JOB_ORDER else 50, n))


def _render_rehearsal_table_txt(folder: Path) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rt.main([str(folder)])
    return buf.getvalue()


def verify_rehearsal(
    rehearsal_dir: Path,
    expected_tasks: int = 10,
    min_agent_runs: int = 3,
    strict: bool = False,
    oracle_range_path: Path = DEFAULT_ORACLE_RANGE,
    n_boot: int = BOOTSTRAP_B,
) -> dict[str, Any]:
    rehearsal_dir = Path(rehearsal_dir)
    shared_key = rehearsal_dir / "ledger_key"
    shared_key_arg = shared_key if shared_key.is_file() else None
    raw_jobs = _discover_direct_jobs(rehearsal_dir, shared_key_file=shared_key_arg)
    raw_ordered = _sort_job_names(list(raw_jobs.keys()))

    published_keys: dict[str, str] = {}
    for jn in raw_ordered:
        kf = rehearsal_dir / jn / "ledger_key"
        if kf.is_file():
            published_keys[jn] = kf.read_text(encoding="utf-8").strip()
    same_build_key_ok = len(set(published_keys.values())) <= 1

    base_names = [jn for jn in raw_ordered if not jn.endswith(RERUN_SUFFIX)]
    rerun_names = [jn for jn in raw_ordered if jn.endswith(RERUN_SUFFIX)]

    rerun_protocol_violations: list[str] = []
    disclosed_infra_reruns: list[dict[str, Any]] = []
    effective_trials_by_job: dict[str, dict[str, dict[str, Any]]] = {}
    primary_trials_by_job: dict[str, dict[str, dict[str, Any]]] = {}

    for jn in base_names:
        by_t = {t["task"]: dict(t, rerun=False, first_infra_reason=None) for t in raw_jobs[jn]["trials"]}
        primary_trials_by_job[jn] = {tk: dict(tv) for tk, tv in by_t.items()}
        effective_trials_by_job[jn] = by_t

    for rjn in rerun_names:
        target = rjn[: -len(RERUN_SUFFIX)]
        if target not in effective_trials_by_job:
            rerun_protocol_violations.append(f"{rjn}: base job {target!r} missing")
            continue
        base_map = effective_trials_by_job[target]
        for rt_trial in raw_jobs[rjn]["trials"]:
            tk = rt_trial["task"]
            if tk not in base_map:
                rerun_protocol_violations.append(f"{rjn}/{tk}: task was not present in primary {target}")
                continue
            orig = base_map[tk]
            if not orig["infra_invalid"]:
                rerun_protocol_violations.append(
                    f"{rjn}/{tk}: attempted to replace already-valid primary trial in {target}"
                )
                continue
            reason_str = str(orig["infra_summary"] or ", ".join(orig["infra_reasons"]))
            merged = dict(rt_trial, rerun=True, first_infra_reason=reason_str)
            base_map[tk] = merged
            disclosed_infra_reruns.append({
                "job": target,
                "rerun_job": rjn,
                "task": tk,
                "first_infra_reason": reason_str,
                "rerun_valid": not rt_trial["infra_invalid"],
                "rerun_reward": rt_trial["valid_reward"],
                "rerun_correct": rt_trial["correct"],
                "rerun_day": rt_trial["final_day"],
            })

    opencode_names = [n for n in base_names if n.startswith("opencode")]
    cheat_probe_names = [
        n
        for n in base_names
        if n in {"cheat-probe", "cheat_probe"}
        or (raw_jobs[n]["policies"] == ["cheat_probe"] and raw_jobs[n]["n_trials"] > 0)
    ]
    cheat_names = [
        n
        for n in base_names
        if n in {"cheat", "signed-cheat"}
        or (raw_jobs[n]["policies"] == ["cheat"] and raw_jobs[n]["n_trials"] > 0)
    ]

    missing_required: list[str] = []
    for req in ("oracle", "do_nothing", "stop_early"):
        if req not in effective_trials_by_job:
            missing_required.append(req)
    if len(opencode_names) < min_agent_runs:
        missing_required.append(f"opencode* (found {len(opencode_names)}, need >= {min_agent_runs})")

    required_job_list = [n for n in ("oracle", "do_nothing", "stop_early") if n in effective_trials_by_job] + opencode_names

    oracle_trials_by_task: dict[str, dict[str, Any]] = {}
    oracle_tier = "hard"
    if "oracle" in effective_trials_by_job:
        for tk, t in effective_trials_by_job["oracle"].items():
            oracle_trials_by_task[tk] = t
            oracle_tier = str(t["tier"])
    oracle_task_set = set(oracle_trials_by_task.keys())

    task_count_errors: list[str] = []
    if expected_tasks > 0:
        for jn in required_job_list:
            tmap = effective_trials_by_job[jn]
            raw_n = raw_jobs[jn]["n_trials"]
            if raw_n != expected_tasks or len(tmap) != expected_tasks:
                task_count_errors.append(
                    f"{jn}: has {raw_n} trials ({len(tmap)} unique tasks), expected {expected_tasks}"
                )
            elif oracle_task_set and set(tmap.keys()) != oracle_task_set:
                task_count_errors.append(f"{jn}: task set mismatch vs oracle")

    trial_consistency_failures: list[str] = []
    job_consistency_failures: list[str] = []
    for jn in raw_ordered:
        j = raw_jobs[jn]
        if not j["job_consistent"]:
            job_consistency_failures.append(f"{jn}: {'; '.join(j['job_problems'])}")
        for t in j["trials"]:
            if t["consistent"] is False:
                trial_consistency_failures.append(f"{jn}/{t['trial_dir']}: {'; '.join(t['problems'])}")

    if not same_build_key_ok:
        job_consistency_failures.append("published job ledger_key files disagree within rehearsal folder")

    unresolved_infra_failures: list[str] = []
    for jn in base_names:
        for tk, t in sorted(effective_trials_by_job[jn].items()):
            if t["infra_invalid"]:
                unresolved_infra_failures.append(f"{jn}/{tk}: {', '.join(t['infra_reasons'])}")

    zero_baseline_failures: list[str] = []
    for zname in ["do_nothing", "stop_early"] + cheat_probe_names:
        if zname not in effective_trials_by_job:
            continue
        for tk, t in sorted(effective_trials_by_job[zname].items()):
            vr = t["valid_reward"]
            if vr is None or abs(float(vr)) > 1e-9:
                zero_baseline_failures.append(f"{zname}/{tk}: valid_reward={vr} (expected 0.0)")
            if zname in cheat_probe_names:
                if t["cheat_holes"] is None or len(t["cheat_holes"]) > 0:
                    zero_baseline_failures.append(f"{zname}/{tk}: cheat_holes={t['cheat_holes']}")

    cheat_failures: list[str] = []
    for cname in cheat_names:
        vals = [float(t["valid_reward"]) for t in effective_trials_by_job[cname].values() if t["valid_reward"] is not None]
        if not vals or _mean(vals) > 0.0:
            cheat_failures.append(f"{cname}: mean={_fmt_num(_mean(vals) if vals else None)} (expected <= 0.0)")

    band_n = expected_tasks if expected_tasks > 0 else max(1, len(oracle_trials_by_task))
    oracle_band = load_oracle_band(oracle_range_path, tier=oracle_tier, n_tasks=band_n)
    oracle_valid_scores = [
        float(t["valid_reward"])
        for _, t in sorted(oracle_trials_by_task.items())
        if t["valid_reward"] is not None
    ]
    oracle_mean = _mean(oracle_valid_scores) if oracle_valid_scores else float("nan")
    band_lo, band_hi = oracle_band["band_90pct"]
    oracle_in_band = (
        bool(oracle_valid_scores)
        and not math.isnan(oracle_mean)
        and (band_lo <= oracle_mean <= band_hi)
    )
    oracle_z = (
        (oracle_mean - float(oracle_band["mean"])) / float(oracle_band["sd"])
        if oracle_valid_scores and float(oracle_band["sd"]) > 0
        else float("nan")
    )

    paired_runs: list[dict[str, Any]] = []
    for jn in base_names:
        if jn == "oracle":
            continue
        eff_map = effective_trials_by_job[jn]
        prim_map = primary_trials_by_job[jn]
        paired_tasks = sorted(
            tk
            for tk in eff_map
            if eff_map[tk]["valid_reward"] is not None
            and tk in oracle_trials_by_task
            and oracle_trials_by_task[tk]["valid_reward"] is not None
        )
        ra = [float(eff_map[tk]["valid_reward"]) for tk in paired_tasks]
        rb = [float(oracle_trials_by_task[tk]["valid_reward"]) for tk in paired_tasks]
        ma = _mean(ra) if ra else float("nan")
        mb = _mean(rb) if rb else float("nan")
        ratio = (ma / mb) if (ra and mb > 0) else float("nan")
        ci_lo, ci_hi = paired_bootstrap_ratio_ci(ra, rb, n_boot=n_boot) if (ra and mb > 0) else (None, None)

        eff_vals = list(eff_map.values())
        prim_valid = [float(t["valid_reward"]) for t in prim_map.values() if t["valid_reward"] is not None]
        prim_as_zero = [0.0 if t["infra_invalid"] or t["valid_reward"] is None else float(t["valid_reward"]) for t in prim_map.values()]
        eff_as_zero = [0.0 if t["infra_invalid"] or t["valid_reward"] is None else float(t["valid_reward"]) for t in eff_vals]

        paired_runs.append({
            "job": jn,
            "n_paired_valid": len(paired_tasks),
            "n_infra_invalid": sum(1 for t in eff_vals if t["infra_invalid"]),
            "n_infra_reruns_used": sum(1 for t in eff_vals if t.get("rerun")),
            "n_primary_valid": len(prim_valid),
            "primary_valid_mean": _clean_float(_mean(prim_valid) if prim_valid else float("nan")),
            "primary_infra_as_zero_mean": _clean_float(_mean(prim_as_zero) if prim_as_zero else float("nan")),
            "effective_infra_as_zero_mean": _clean_float(_mean(eff_as_zero) if eff_as_zero else float("nan")),
            "n_post_game_nonzero_exit": sum(1 for t in eff_vals if t["harmless_post_game_exit"]),
            "correct": sum(1 for t in eff_vals if not t["infra_invalid"] and t["correct"]),
            "accused": sum(1 for t in eff_vals if not t["infra_invalid"] and t["accused_present"]),
            "mean": _clean_float(ma),
            "oracle_paired_mean": _clean_float(mb),
            "diff_vs_oracle": _clean_float(ma - mb if ra else float("nan")),
            "ratio_vs_oracle": _clean_float(ratio),
            "ratio_ci95": [_clean_float(ci_lo), _clean_float(ci_hi)],
        })

    opencode_paired = [r for r in paired_runs if r["job"] in opencode_names and r["mean"] is not None]
    run_means = [float(r["mean"]) for r in opencode_paired]
    run_ratios = [float(r["ratio_vs_oracle"]) for r in opencode_paired if r["ratio_vs_oracle"] is not None]

    successes_by_task: dict[str, list[bool]] = {}
    for jn in opencode_names:
        for tk, t in sorted(effective_trials_by_job[jn].items()):
            if not t["infra_invalid"] and t["valid_reward"] is not None:
                successes_by_task.setdefault(tk, []).append(bool(t["correct"]))
    p3 = pass_hat_k(successes_by_task, 3)

    if len(run_means) >= 2:
        mm = _mean(run_means)
        sd_runs = math.sqrt(sum((x - mm) ** 2 for x in run_means) / (len(run_means) - 1))
        spread_range = max(run_means) - min(run_means)
    elif len(run_means) == 1:
        mm = run_means[0]
        sd_runs = 0.0
        spread_range = 0.0
    else:
        mm = float("nan")
        sd_runs = float("nan")
        spread_range = float("nan")

    agent_summary = {
        "n_runs": len(opencode_names),
        "run_jobs": opencode_names,
        "run_means": [_clean_float(x) for x in run_means],
        "mean_of_means": _clean_float(mm),
        "sd_across_runs": _clean_float(sd_runs),
        "range_across_runs": _clean_float(spread_range),
        "mean_ratio_vs_oracle": _clean_float(_mean(run_ratios) if run_ratios else float("nan")),
        "pass_hat_3": _clean_float(p3),
        "tasks_with_3plus_runs": sum(1 for v in successes_by_task.values() if len(v) >= 3),
        "per_task_successes": {
            tk: {"correct_runs": sum(v), "valid_runs": len(v)}
            for tk, v in sorted(successes_by_task.items())
        },
    }

    table_md_file = rehearsal_dir / "TABLE.md"
    table_md_present = table_md_file.is_file()
    table_md_matches: bool | None = None
    if table_md_present and raw_jobs:
        rendered_tbl = _render_rehearsal_table_txt(rehearsal_dir).strip()
        disk_tbl = table_md_file.read_text(encoding="utf-8").strip()
        table_md_matches = rendered_tbl == disk_tbl

    checks: dict[str, bool] = {
        "required_jobs_present": not missing_required,
        "expected_tasks_complete": not task_count_errors,
        "anticheat_trials_consistent": not trial_consistency_failures,
        "anticheat_jobs_consistent": not job_consistency_failures,
        "rerun_protocol_clean": not rerun_protocol_violations,
        "chief_data_rule_clean": not unresolved_infra_failures,
        "baselines_exact_zero": not zero_baseline_failures and not cheat_failures,
        "oracle_in_90pct_band": oracle_in_band,
    }
    if table_md_matches is not None:
        checks["committed_table_md_matches"] = table_md_matches

    strict_failures: list[str] = []
    if strict:
        unsigned = [
            f"{jn}/{t['trial_dir']}"
            for jn in raw_ordered
            for t in raw_jobs[jn]["trials"]
            if not t["signed"]
        ]
        unisolated = [
            f"{jn}/{t['trial_dir']}"
            for jn in ("oracle", "do_nothing", "stop_early")
            if jn in raw_jobs
            for t in raw_jobs[jn]["trials"]
            if not (t["isolation_ok"] and t["isolation_checks_passed"] == 11 and t["isolation_findings"] == 0)
        ]
        checks["strict_all_trials_signed"] = not unsigned
        checks["strict_baseline_isolation_11of11"] = not unisolated
        if unsigned:
            strict_failures.append(f"unsigned trials: {', '.join(unsigned[:5])}")
        if unisolated:
            strict_failures.append(f"missing ISOLATION OK 11/11: {', '.join(unisolated[:5])}")

    all_tasks = sorted({t["task"] for j in raw_jobs.values() for t in j["trials"]})
    n_raw_trials = sum(j["n_trials"] for j in raw_jobs.values())
    rel_dir = rehearsal_dir.relative_to(ROOT).as_posix() if rehearsal_dir.is_relative_to(ROOT) else rehearsal_dir.as_posix()

    compact_raw_jobs: dict[str, dict[str, Any]] = {}
    for jn in raw_ordered:
        j = raw_jobs[jn]
        compact_raw_jobs[jn] = {
            "job": j["job"],
            "policies": j["policies"],
            "models": j["models"],
            "n_trials": j["n_trials"],
            "n_valid": j["n_valid"],
            "n_infra_invalid": j["n_infra_invalid"],
            "n_post_game_nonzero_exit": j["n_post_game_nonzero_exit"],
            "trials_consistent": j["trials_consistent"],
            "job_consistent": j["job_consistent"],
            "signed_trials": j["signed_trials"],
            "hmac_verified_trials": j["hmac_verified_trials"],
            "isolation_11of11_trials": j["isolation_11of11_trials"],
            "trajectory_checked_trials": j["trajectory_checked_trials"],
            "mean_valid_reward": j["mean_valid_reward"],
        }

    return clean_json_value({
        "mode": "rehearsal",
        "rehearsal_dir": rel_dir,
        "strict": strict,
        "expected_tasks": expected_tasks,
        "min_agent_runs": min_agent_runs,
        "n_raw_jobs": len(raw_ordered),
        "n_raw_trials": n_raw_trials,
        "same_build_published_key_verified": same_build_key_ok and len(published_keys) == len(raw_ordered) and len(raw_ordered) > 0,
        "table_md_present": table_md_present,
        "table_md_matches": table_md_matches,
        "overall_ok": all(checks.values()),
        "checks": checks,
        "errors": {
            "missing_required": missing_required,
            "task_count_errors": task_count_errors,
            "trial_consistency_failures": trial_consistency_failures,
            "job_consistency_failures": job_consistency_failures,
            "rerun_protocol_violations": rerun_protocol_violations,
            "infra_failures": unresolved_infra_failures,
            "zero_baseline_failures": zero_baseline_failures,
            "cheat_failures": cheat_failures,
            "strict_failures": strict_failures,
        },
        "disclosed_infra_reruns": disclosed_infra_reruns,
        "oracle": {
            "mean": _clean_float(oracle_mean),
            "n_valid": len(oracle_valid_scores),
            "correct": raw_jobs["oracle"]["correct_trials"] if "oracle" in raw_jobs else 0,
            "z_vs_oracle_range": _clean_float(oracle_z),
            "in_90pct_band": oracle_in_band,
            "band_reference": oracle_band,
        },
        "paired_runs": paired_runs,
        "agent_spread": agent_summary,
        "tasks": all_tasks,
        "jobs": compact_raw_jobs,
    })


def inspect_live_rehearsal(
    rehearsal_dir: Path,
    oracle_range_path: Path = DEFAULT_ORACLE_RANGE,
) -> dict[str, Any]:
    rehearsal_dir = Path(rehearsal_dir)
    rel_dir = rehearsal_dir.relative_to(ROOT).as_posix() if rehearsal_dir.is_relative_to(ROOT) else rehearsal_dir.as_posix()
    readme_file = rehearsal_dir / "README.md"
    build_txt = rehearsal_dir / "BUILD.txt"
    table_md = rehearsal_dir / "TABLE.md"

    readme_present = readme_file.is_file()
    readme_txt = readme_file.read_text(encoding="utf-8", errors="replace") if readme_present else ""
    protocol_mentions_afterquery_final = "afterquery-final" in readme_txt
    protocol_mentions_3x10 = all(tok in readme_txt for tok in ("opencode-1", "opencode-2", "opencode-3"))
    protocol_mentions_infra_rule = "-infra-rerun" in readme_txt and "ApiRateLimitError" in readme_txt

    jobs = _discover_direct_jobs(rehearsal_dir)
    n_jobs = len(jobs)
    n_trials = sum(j["n_trials"] for j in jobs.values())

    if n_jobs == 0:
        status_consistent = readme_present and n_trials == 0
        return clean_json_value({
            "rehearsal_dir": rel_dir,
            "status": "protocol_only",
            "status_consistent": status_consistent,
            "protocol_readme_present": readme_present,
            "build_txt_present": build_txt.is_file(),
            "table_md_present": table_md.is_file(),
            "n_jobs": 0,
            "n_trials": 0,
            "protocol_spec": {
                "target_tag": "afterquery-final" if protocol_mentions_afterquery_final else "unspecified",
                "judge_seeds": "900000-900009",
                "tier": "hard",
                "expected_tasks": 10,
                "planned_jobs": ["oracle", "opencode-1", "opencode-2", "opencode-3", "do_nothing", "stop_early"],
                "declares_3x10_opencode": protocol_mentions_3x10,
                "declares_single_infra_rerun_rule": protocol_mentions_infra_rule,
            },
            "automatic_verifier_ready": True,
            "disclosure": (
                "results/harbor/rehearsal/ currently holds only the pre-registered protocol (README.md, 0 executed trials); "
                "verify_rehearsal() automatically validates full 3x10 schema, HMAC, isolation, baselines, oracle band, "
                "paired CIs, and pass^3 if trials are added."
            ),
            "verification": None,
        })

    ver = verify_rehearsal(
        rehearsal_dir=rehearsal_dir,
        expected_tasks=10,
        min_agent_runs=3,
        strict=True,
        oracle_range_path=oracle_range_path,
    )
    status = "verified_3x10_complete" if ver["overall_ok"] else "partial_or_failing_trials_present"
    return clean_json_value({
        "rehearsal_dir": rel_dir,
        "status": status,
        "status_consistent": bool(ver["overall_ok"]),
        "protocol_readme_present": readme_present,
        "build_txt_present": build_txt.is_file(),
        "table_md_present": table_md.is_file(),
        "n_jobs": n_jobs,
        "n_trials": n_trials,
        "automatic_verifier_ready": True,
        "disclosure": (
            f"results/harbor/rehearsal/ contains {n_jobs} job(s) and {n_trials} trial(s); "
            f"strict 3x10 verification status: {'PASS' if ver['overall_ok'] else 'FAIL'}."
        ),
        "verification": ver,
    })


def verify_current_harbor_package(scratch_dir: Path | None = None) -> dict[str, Any]:
    explicit_dir = scratch_dir is not None
    if explicit_dir:
        work_dir = Path(scratch_dir)
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.parent.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp_base = Path("/tmp/opencode") if Path("/tmp/opencode").is_dir() else None
        work_dir = Path(tempfile.mkdtemp(prefix="w3_harbor_pkg_", dir=str(tmp_base) if tmp_base else None))

    prev_secret = getattr(world, "_SET_SECRET", None)
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "harbor/build.py"), "--out", str(work_dir)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        task_dirs = sorted(d for d in work_dir.iterdir() if d.is_dir())
        task_names = [d.name for d in task_dirs]
        expected_names = [f"canary-hard-{s}" for s in range(900000, 900010)]

        all_separate = True
        all_timeout_10800 = True
        all_modes_0600 = True
        all_keys_match = True
        no_agent_or_solution_leak = True
        salt_bytes_len = 0
        key_bytes_len = 0
        first_salt: bytes | None = None

        for td in task_dirs:
            toml_txt = (td / "task.toml").read_text(encoding="utf-8")
            if 'environment_mode = "separate"' not in toml_txt:
                all_separate = False
            if "timeout_sec = 10800.0" not in toml_txt:
                all_timeout_10800 = False

            salt_p = td / "environment/canary-server/data/worlds/judge/SALT"
            skey_p = td / "environment/canary-server/ledger_key"
            vkey_p = td / "tests/ledger_key"
            ep_p = td / "environment/canary-server/episode.json"

            for fp in (salt_p, skey_p, vkey_p, ep_p):
                if not fp.is_file() or stat.S_IMODE(fp.stat().st_mode) != 0o600:
                    all_modes_0600 = False

            sb = salt_p.read_bytes()
            skb = skey_p.read_bytes()
            vkb = vkey_p.read_bytes()
            salt_bytes_len = len(sb)
            key_bytes_len = len(skb)
            if first_salt is None:
                first_salt = sb
            elif sb != first_salt:
                all_keys_match = False
            if skb != vkb or len(skb) < 32:
                all_keys_match = False

            env_leaks = [
                p
                for p in (td / "environment").rglob("*")
                if "canary-server" not in p.parts
                and ("SALT" in p.name or "ledger_key" in p.name or "truth" in p.name.lower())
            ]
            sol_leaks = [
                p
                for p in (td / "solution").rglob("*")
                if "SALT" in p.name or "ledger_key" in p.name or "truth" in p.name.lower()
            ]
            if env_leaks or sol_leaks:
                no_agent_or_solution_leak = False

        stop_early_scores: list[float] = []
        do_nothing_scores: list[float] = []
        if first_salt is not None:
            world.set_world_secret(first_salt)
            for s in range(900000, 900010):
                r_se = run_episode(make_env("hard", s), make_policy_factory("stop_early")(s))
                r_dn = run_episode(make_env("hard", s), make_policy_factory("do_nothing")(s))
                stop_early_scores.append(round(float(r_se.score), 6))
                do_nothing_scores.append(round(float(r_dn.score), 6))
    finally:
        world.set_world_secret(prev_secret)
        if work_dir.exists():
            shutil.rmtree(work_dir)

    scratch_deleted = not work_dir.exists()
    se_zero = len(stop_early_scores) == 10 and all(abs(x) <= 1e-9 for x in stop_early_scores)
    dn_zero = len(do_nothing_scores) == 10 and all(abs(x) <= 1e-9 for x in do_nothing_scores)

    pkg_ok = (
        task_names == expected_names
        and all_separate
        and all_timeout_10800
        and all_modes_0600
        and all_keys_match
        and no_agent_or_solution_leak
        and se_zero
        and dn_zero
        and scratch_deleted
    )
    return {
        "verified": pkg_ok,
        "build_command": "python harbor/build.py --out /tmp/opencode/w3_harbor_pkg",
        "build_summary_line": norm_ascii(proc.stdout.strip().replace(str(work_dir), "/tmp/opencode/w3_harbor_pkg")),
        "default_tiers": "hard",
        "default_seeds": "900000-900009",
        "n_tasks": len(task_names),
        "tasks": task_names,
        "verifier_environment_mode": "separate" if all_separate else "mismatch",
        "agent_timeout_sec": 10800.0 if all_timeout_10800 else None,
        "secret_and_key_permissions": "0600" if all_modes_0600 else "mismatch",
        "salt_bytes": salt_bytes_len,
        "ledger_key_bytes": key_bytes_len,
        "sidecar_and_verifier_keys_match": all_keys_match,
        "no_secret_leak_to_agent_or_solution": no_agent_or_solution_leak,
        "stop_early_inproc_scores": stop_early_scores,
        "stop_early_inproc_mean": _clean_float(_mean(stop_early_scores)),
        "do_nothing_inproc_scores": do_nothing_scores,
        "do_nothing_inproc_mean": _clean_float(_mean(do_nothing_scores)),
        "scratch_dir_deleted": scratch_deleted,
    }


def audit_existing_harbor(
    harbor_dir: Path = DEFAULT_HARBOR_DIR,
    negative_dir: Path = DEFAULT_NEGATIVE_DIR,
    oracle_range_path: Path = DEFAULT_ORACLE_RANGE,
    scratch_pkg_dir: Path | None = None,
) -> dict[str, Any]:
    harbor_dir = Path(harbor_dir)
    negative_dir = Path(negative_dir)
    oracle_range_path = Path(oracle_range_path)

    discovered = _discover_all_harbor_jobs(harbor_dir, root=ROOT)
    jobs_by_rel: dict[str, dict[str, Any]] = {}
    for rel, jdir in discovered:
        jobs_by_rel[rel] = inspect_job(jdir, shared_key_file=None, rel_label=rel)
    job_rels = sorted(jobs_by_rel.keys())

    ac_rows = ac.harbor_consistency(harbor_dir.parent.parent if harbor_dir.name == "harbor" and harbor_dir.parent.name == "results" else ROOT)
    ac_trials = [r for r in ac_rows if r.get("kind") == "trial"]
    ac_jobs = [r for r in ac_rows if r.get("kind") == "job"]
    anticheat_parity_ok = (
        len(ac_trials) == sum(jobs_by_rel[r]["n_trials"] for r in job_rels)
        and len(ac_jobs) == len(job_rels)
        and all(r.get("consistent") is True for r in ac_trials)
        and all(r.get("consistent") is True for r in ac_jobs)
    )

    all_trials = [t for rel in job_rels for t in jobs_by_rel[rel]["trials"]]
    n_trials = len(all_trials)
    n_jobs = len(job_rels)
    top_level_rels = [r for r in job_rels if r.count("/") == 2]
    nested_rels = [r for r in job_rels if r.count("/") > 2]

    trials_consistent = sum(1 for t in all_trials if t["consistent"] is True)
    jobs_consistent = sum(1 for rel in job_rels if jobs_by_rel[rel]["job_consistent"] is True)
    signed_count = sum(1 for t in all_trials if t["signed"])
    hmac_verified_count = sum(1 for t in all_trials if t["hmac_verified"] is True)
    hmac_expected_count = sum(
        jobs_by_rel[rel]["n_trials"] for rel in job_rels if jobs_by_rel[rel]["has_retired_ledger_key"]
    )
    isolation_present_count = sum(1 for t in all_trials if t["isolation_present"])
    isolation_ok_count = sum(1 for t in all_trials if t["isolation_ok"])
    isolation_11of11_count = sum(
        1
        for t in all_trials
        if t["isolation_ok"] and t["isolation_checks_passed"] == 11 and t["isolation_findings"] == 0
    )
    trajectory_checked_count = sum(1 for t in all_trials if t["trajectory_checked"])
    post_game_exit_count = sum(1 for t in all_trials if t["harmless_post_game_exit"])

    top_level_infra_invalid = sum(
        jobs_by_rel[rel]["n_infra_invalid"] for rel in top_level_rels
    )

    rehearsal_dry_dir = harbor_dir / "rehearsal-dry"
    rehearsal_dry = verify_rehearsal(
        rehearsal_dir=rehearsal_dry_dir,
        expected_tasks=10,
        min_agent_runs=1,
        strict=True,
        oracle_range_path=oracle_range_path,
    )
    rd_opencode = next((r for r in rehearsal_dry["paired_runs"] if r["job"] == "opencode"), None)
    rd_do_nothing = next((r for r in rehearsal_dry["paired_runs"] if r["job"] == "do_nothing"), None)
    rd_stop_early = next((r for r in rehearsal_dry["paired_runs"] if r["job"] == "stop_early"), None)

    rehearsal_dry_summary = {
        "rehearsal_dir": rehearsal_dry["rehearsal_dir"],
        "classification": "1_run_harness_check_not_gap_claim",
        "overall_ok": rehearsal_dry["overall_ok"],
        "n_jobs": rehearsal_dry["n_raw_jobs"],
        "n_raw_trials": rehearsal_dry["n_raw_trials"],
        "same_build_published_key_verified": rehearsal_dry["same_build_published_key_verified"],
        "table_md_matches": rehearsal_dry["table_md_matches"],
        "oracle_10task_mean": rehearsal_dry["oracle"]["mean"],
        "oracle_correct": rehearsal_dry["oracle"]["correct"],
        "oracle_in_90pct_band": rehearsal_dry["oracle"]["in_90pct_band"],
        "oracle_z_vs_200builds": rehearsal_dry["oracle"]["z_vs_oracle_range"],
        "opencode_10task_mean": rd_opencode["mean"] if rd_opencode else None,
        "opencode_correct": rd_opencode["correct"] if rd_opencode else 0,
        "opencode_accused": rd_opencode["accused"] if rd_opencode else 0,
        "opencode_diff_vs_oracle": rd_opencode["diff_vs_oracle"] if rd_opencode else None,
        "opencode_ratio_vs_oracle": rd_opencode["ratio_vs_oracle"] if rd_opencode else None,
        "opencode_ratio_ci95": rd_opencode["ratio_ci95"] if rd_opencode else [None, None],
        "opencode_primary_valid_n": rd_opencode["n_primary_valid"] if rd_opencode else 0,
        "opencode_primary_valid_mean": rd_opencode["primary_valid_mean"] if rd_opencode else None,
        "opencode_primary_infra_as_zero_mean": rd_opencode["primary_infra_as_zero_mean"] if rd_opencode else None,
        "opencode_disclosed_infra_reruns_n": rd_opencode["n_infra_reruns_used"] if rd_opencode else 0,
        "opencode_unresolved_infra_n": rd_opencode["n_infra_invalid"] if rd_opencode else 0,
        "disclosed_infra_reruns": rehearsal_dry["disclosed_infra_reruns"],
        "do_nothing_10task_mean": rd_do_nothing["mean"] if rd_do_nothing else None,
        "stop_early_10task_mean": rd_stop_early["mean"] if rd_stop_early else None,
        "checks": rehearsal_dry["checks"],
    }

    live_rehearsal = inspect_live_rehearsal(
        rehearsal_dir=harbor_dir / "rehearsal",
        oracle_range_path=oracle_range_path,
    )

    cheat_probe_rel = "results/harbor/cheat-probe"
    cp_trials = [t for t in all_trials if t["policy"] == "cheat_probe"]
    cheat_probe_summary = {
        "job": cheat_probe_rel,
        "n_trials": len(cp_trials),
        "all_zero_reward": len(cp_trials) == 6 and all(t["valid_reward"] == 0.0 for t in cp_trials),
        "probes_per_trial": cp_trials[0]["cheat_attempts"] if cp_trials else 0,
        "all_149_probes": len(cp_trials) == 6 and all(t["cheat_attempts"] == 149 for t in cp_trials),
        "total_probe_attempts": sum(t["cheat_attempts"] or 0 for t in cp_trials),
        "holes_found": sum(len(t["cheat_holes"] or []) for t in cp_trials),
        "controls_failed": sum(t["cheat_controls_failed"] or 0 for t in cp_trials),
        "all_complete": len(cp_trials) == 6 and all(t["cheat_incomplete"] is None for t in cp_trials),
        "hmac_verified_trials": sum(1 for t in cp_trials if t["hmac_verified"] is True),
        "isolation_11of11_trials": sum(
            1
            for t in cp_trials
            if t["isolation_ok"] and t["isolation_checks_passed"] == 11 and t["isolation_findings"] == 0
        ),
    }
    cheat_probe_clean = (
        cheat_probe_summary["all_zero_reward"]
        and cheat_probe_summary["all_149_probes"]
        and cheat_probe_summary["holes_found"] == 0
        and cheat_probe_summary["controls_failed"] == 0
        and cheat_probe_summary["all_complete"]
        and cheat_probe_summary["hmac_verified_trials"] == 6
        and cheat_probe_summary["isolation_11of11_trials"] == 6
    )

    active_cheat_trials = [t for t in all_trials if t["policy"] == "cheat"]
    active_cheat_clean = len(active_cheat_trials) == 9 and all(
        t["valid_reward"] is not None and float(t["valid_reward"]) <= 0.0 for t in active_cheat_trials
    )

    do_nothing_trials = [t for t in all_trials if t["policy"] == "do_nothing"]
    do_nothing_clean = len(do_nothing_trials) == 13 and all(t["valid_reward"] == 0.0 for t in do_nothing_trials)

    current_se_trials = (
        jobs_by_rel["results/harbor/rehearsal-dry/stop_early"]["trials"]
        if "results/harbor/rehearsal-dry/stop_early" in jobs_by_rel
        else []
    )
    current_stop_early_clean = len(current_se_trials) == 10 and all(
        t["valid_reward"] == 0.0 and not t["accused_present"] for t in current_se_trials
    )

    legacy_se_jobs: list[dict[str, Any]] = []
    legacy_se_explained = True
    for lj_rel in sorted(LEGACY_STOP_EARLY_JOBS):
        if lj_rel not in jobs_by_rel:
            legacy_se_explained = False
            continue
        lj = jobs_by_rel[lj_rel]
        t_ok = all(
            t["consistent"] is True
            and t["harbor_reward"] == -1.0
            and t["end_reason"] == "accused"
            and t["final_day"] == 1
            and not t["correct"]
            for t in lj["trials"]
        )
        if not t_ok:
            legacy_se_explained = False
        legacy_se_jobs.append({
            "job": lj_rel,
            "n_trials": lj["n_trials"],
            "signed": lj["signed_trials"] == lj["n_trials"],
            "hmac_verified": lj["hmac_verified_trials"] == lj["n_trials"] if lj["has_retired_ledger_key"] else None,
            "rewards": [t["harbor_reward"] for t in lj["trials"]],
            "tasks": [t["task"] for t in lj["trials"]],
            "end_reasons": [t["end_reason"] for t in lj["trials"]],
            "final_days": [t["final_day"] for t in lj["trials"]],
        })

    tamper_job_dir = negative_dir / "c1-tamper"
    neg_summary: dict[str, Any] = {"present": tamper_job_dir.is_dir(), "failed_closed_ok": False}
    if tamper_job_dir.is_dir():
        neg_job = inspect_job(tamper_job_dir, shared_key_file=None, rel_label="results/harbor_negative/c1-tamper")
        nt = neg_job["trials"][0] if neg_job["trials"] else None
        if nt is not None:
            led_path = tamper_job_dir / nt["trial_dir"] / "artifacts/ledger.json"
            led_obj = json.loads(led_path.read_text(encoding="utf-8")) if led_path.is_file() else {}
            reward_txt_path = tamper_job_dir / nt["trial_dir"] / "verifier/reward.txt"
            reward_txt_val = (
                float(reward_txt_path.read_text(encoding="utf-8").strip()) if reward_txt_path.is_file() else None
            )
            bad_sig_logged = any("bad ledger signature" in ln for ln in nt["verifier_fail_lines"])
            neg_iso_11 = (
                nt["isolation_ok"] and nt["isolation_checks_passed"] == 11 and nt["isolation_findings"] == 0
            )
            failed_closed_ok = (
                nt["harbor_reward"] == 0.0
                and reward_txt_val == 0.0
                and led_obj.get("score") == 1.0
                and bad_sig_logged
                and nt["consistent"] is False
                and neg_job["job_consistent"] is True
                and neg_iso_11
            )
            neg_summary = {
                "present": True,
                "job": "results/harbor_negative/c1-tamper",
                "trial": nt["trial_dir"],
                "task": nt["task"],
                "tampered_ledger_score": led_obj.get("score"),
                "true_accusation_V": led_obj.get("V"),
                "verifier_reward_txt": reward_txt_val,
                "harbor_result_reward": nt["harbor_reward"],
                "verifier_fail_lines": nt["verifier_fail_lines"],
                "isolation_checks_passed": nt["isolation_checks_passed"],
                "isolation_findings": nt["isolation_findings"],
                "offline_anticheat_consistent": nt["consistent"],
                "job_summary_consistent": neg_job["job_consistent"],
                "failed_closed_ok": failed_closed_ok,
            }

    gemini_demo: dict[str, Any] = {}
    g_or_rel = "results/harbor/g-oracle"
    g_rest_rel = "results/harbor/g-gemini-rest"
    g_try2_rel = "results/harbor/g-gemini-try2"
    if g_or_rel in jobs_by_rel and g_rest_rel in jobs_by_rel and g_try2_rel in jobs_by_rel:
        g_or = {t["task"]: t for t in jobs_by_rel[g_or_rel]["trials"]}
        g_ag: dict[str, dict[str, Any]] = {}
        for jn in (g_try2_rel, g_rest_rel):
            for t in jobs_by_rel[jn]["trials"]:
                g_ag[t["task"]] = t
        paired_tasks = sorted(set(g_or) & set(g_ag))
        ra = [float(g_ag[tk]["valid_reward"]) for tk in paired_tasks]
        rb = [float(g_or[tk]["valid_reward"]) for tk in paired_tasks]
        ci_lo, ci_hi = paired_bootstrap_ratio_ci(ra, rb)
        hard_tasks = [tk for tk in paired_tasks if tk.startswith("hard-")]
        med_tasks = [tk for tk in paired_tasks if tk.startswith("medium-")]
        gemini_demo = {
            "n_paired_tasks": len(paired_tasks),
            "tasks": paired_tasks,
            "gemini_mean": _clean_float(_mean(ra)),
            "oracle_mean": _clean_float(_mean(rb)),
            "diff_vs_oracle": _clean_float(_mean(ra) - _mean(rb)),
            "ratio_vs_oracle": _clean_float(_mean(ra) / _mean(rb)),
            "ratio_ci95": [_clean_float(ci_lo), _clean_float(ci_hi)],
            "hard_3task_gemini_mean": _clean_float(_mean([float(g_ag[tk]["valid_reward"]) for tk in hard_tasks])),
            "hard_3task_oracle_mean": _clean_float(_mean([float(g_or[tk]["valid_reward"]) for tk in hard_tasks])),
            "medium_3task_gemini_mean": _clean_float(_mean([float(g_ag[tk]["valid_reward"]) for tk in med_tasks])),
            "medium_3task_oracle_mean": _clean_float(_mean([float(g_or[tk]["valid_reward"]) for tk in med_tasks])),
            "post_game_nonzero_exit_trials": sum(1 for tk in paired_tasks if g_ag[tk]["harmless_post_game_exit"]),
            "infra_invalid_trials": sum(1 for tk in paired_tasks if g_ag[tk]["infra_invalid"]),
        }

    pkg_verification = verify_current_harbor_package(scratch_dir=scratch_pkg_dir)
    oracle_band_hard = load_oracle_band(oracle_range_path, tier="hard", n_tasks=10)
    oracle_band_medium = load_oracle_band(oracle_range_path, tier="medium", n_tasks=10)

    compact_jobs: list[dict[str, Any]] = []
    for rel in job_rels:
        j = jobs_by_rel[rel]
        if rel in LEGACY_STOP_EARLY_JOBS:
            note = f"legacy pre-{PR16} (2bb67295) day-1 random accusation (now guess_day1); current stop_early scores 0.000"
        elif rel == "results/harbor/rehearsal-dry/opencode":
            note = "rehearsal-dry primary run: 7/10 completed + 3 infra (2 ApiRateLimitError, 1 thought_signature) rerun in opencode-infra-rerun"
        elif rel == "results/harbor/rehearsal-dry/opencode-infra-rerun":
            note = "disclosed 1x infra rerun for hard-900006, hard-900007, hard-900009 on identical retired build"
        elif j["n_post_game_nonzero_exit"] > 0:
            note = f"{j['n_post_game_nonzero_exit']}/{j['n_trials']} harmless post-game NonZeroAgentExitCodeError with clean ledger"
        elif j["has_retired_ledger_key"]:
            note = "signed verifier + published retired ledger_key HMAC verified"
        elif j["signed_trials"] == j["n_trials"]:
            note = "signed verifier (signature=ok)"
        else:
            note = "pre-C1 unsigned verifier; ledger/reward/isolation consistent"

        compact_jobs.append({
            "job": rel,
            "policies": j["policies"],
            "models": j["models"],
            "n_trials": j["n_trials"],
            "n_valid": j["n_valid"],
            "n_infra_invalid": j["n_infra_invalid"],
            "n_post_game_nonzero_exit": j["n_post_game_nonzero_exit"],
            "trials_consistent": j["trials_consistent"],
            "job_consistent": j["job_consistent"],
            "signed_trials": j["signed_trials"],
            "has_retired_ledger_key": j["has_retired_ledger_key"],
            "hmac_verified_trials": j["hmac_verified_trials"],
            "isolation_11of11_trials": j["isolation_11of11_trials"],
            "trajectory_checked_trials": j["trajectory_checked_trials"],
            "mean_valid_reward": j["mean_valid_reward"],
            "note": note,
        })

    total_iso_files = isolation_present_count + (1 if neg_summary.get("present") else 0)
    total_iso_11of11 = isolation_11of11_count + (
        1
        if neg_summary.get("isolation_checks_passed") == 11 and neg_summary.get("isolation_findings") == 0
        else 0
    )

    checks = {
        "harbor_80_trials_consistent": trials_consistent == 80 and n_trials == 80,
        "harbor_18_jobs_consistent": jobs_consistent == 18 and n_jobs == 18,
        "anticheat_harbor_consistency_parity": anticheat_parity_ok,
        "rehearsal_dry_verified": bool(
            rehearsal_dry_summary["overall_ok"]
            and approx_equal(rehearsal_dry_summary["oracle_10task_mean"], 0.467, tol=1e-6)
            and approx_equal(rehearsal_dry_summary["opencode_10task_mean"], 0.398, tol=1e-6)
            and rehearsal_dry_summary["opencode_disclosed_infra_reruns_n"] == 3
            and rehearsal_dry_summary["opencode_unresolved_infra_n"] == 0
            and rehearsal_dry_summary["do_nothing_10task_mean"] == 0.0
            and rehearsal_dry_summary["stop_early_10task_mean"] == 0.0
        ),
        "oracle_range_v14_crosschecked": bool(
            oracle_band_hard["builds"] == 200
            and oracle_band_hard["band_90pct"] == [0.39, 0.68]
            and approx_equal(oracle_band_hard["mean"], 0.56938, tol=1e-6)
            and approx_equal(oracle_band_hard["sd"], 0.094469, tol=1e-6)
            and oracle_band_hard["do_nothing_all_builds_zero"]
            and oracle_band_hard["stop_early_all_builds_zero"]
            and rehearsal_dry_summary["oracle_in_90pct_band"]
        ),
        "do_nothing_and_stop_early_zero": bool(
            do_nothing_clean and current_stop_early_clean and legacy_se_explained
        ),
        "cheat_probe_6of6_zero_149_probes": bool(cheat_probe_clean and active_cheat_clean),
        "negative_c1_tamper_failed_closed_zero": bool(neg_summary.get("failed_closed_ok")),
        "check_isolation_11of11_passed": bool(
            isolation_11of11_count == isolation_present_count
            and isolation_present_count == 61
            and total_iso_11of11 == total_iso_files
            and total_iso_files == 62
        ),
        "retired_keys_hmac_57of57_verified": bool(
            hmac_verified_count == hmac_expected_count and hmac_expected_count == 57
        ),
        "top_level_zero_infra_invalid": top_level_infra_invalid == 0,
        "live_rehearsal_status_honest": bool(live_rehearsal["status_consistent"]),
        "current_harbor_build_package_verified": bool(pkg_verification.get("verified")),
    }

    return clean_json_value({
        "schema_version": SCHEMA_VERSION,
        "mode": "audit_existing",
        "rules_version": TIERS_VERSION,
        "harbor_dir": "results/harbor",
        "negative_dir": "results/harbor_negative/c1-tamper",
        "overall_ok": all(checks.values()),
        "checks": checks,
        "totals": {
            "n_jobs": n_jobs,
            "n_top_level_jobs": len(top_level_rels),
            "n_rehearsal_dry_jobs": len(nested_rels),
            "n_trials": n_trials,
            "n_top_level_trials": sum(jobs_by_rel[r]["n_trials"] for r in top_level_rels),
            "n_rehearsal_dry_trials": sum(jobs_by_rel[r]["n_trials"] for r in nested_rels),
            "trials_consistent": trials_consistent,
            "jobs_consistent": jobs_consistent,
            "signed_trials": signed_count,
            "unsigned_legacy_trials": n_trials - signed_count,
            "hmac_expected_trials": hmac_expected_count,
            "hmac_verified_trials": hmac_verified_count,
            "isolation_harbor_trials": isolation_present_count,
            "isolation_harbor_11of11": isolation_11of11_count,
            "isolation_including_negative_total": total_iso_files,
            "isolation_including_negative_11of11": total_iso_11of11,
            "isolation_checks_per_trial": 11,
            "trajectory_checked_trials": trajectory_checked_count,
            "post_game_nonzero_exit_trials": post_game_exit_count,
            "rehearsal_dry_initial_infra_trials": 3,
            "rehearsal_dry_unresolved_infra_trials": rehearsal_dry_summary["opencode_unresolved_infra_n"],
            "do_nothing_trials_zero": len(do_nothing_trials),
            "current_stop_early_trials_zero": len(current_se_trials),
            "cheat_probe_trials": cheat_probe_summary["n_trials"],
            "cheat_probe_probes_per_trial": cheat_probe_summary["probes_per_trial"],
            "cheat_probe_total_attempts": cheat_probe_summary["total_probe_attempts"],
            "active_cheat_trials_nonpositive": len(active_cheat_trials),
        },
        "rehearsal_dry": rehearsal_dry_summary,
        "live_rehearsal": live_rehearsal,
        "cheat_probe": cheat_probe_summary,
        "negative_control": neg_summary,
        "oracle_range_v14": {
            "hard_k10": oracle_band_hard,
            "medium_k10": oracle_band_medium,
        },
        "paired_gemini_demo": gemini_demo,
        "legacy_stop_early_audit": {
            "legacy_jobs": legacy_se_jobs,
            "pr16_merge_commit": "2bb67295",
            "explanation": (
                f"Legacy results/harbor/stop_early and results/harbor/signed-stop_early were recorded before {PR16} "
                "(commit 2bb67295), when canary.baselines named the day-1 random accusation policy stop_early "
                f"(end_reason='accused' on day 1, wrong accusation -> -1.0). {PR16} renamed day-1 random accusation "
                "to guess_day1 and redefined stop_early to stop on day 1 without accusing (exact 0.000, verified "
                "across 10/10 rehearsal-dry/stop_early Harbor trials and 200/200 oracle_range_v1.4 builds)."
            ),
        },
        "current_package_verification": pkg_verification,
        "jobs": compact_jobs,
    })


def render_rehearsal_md(report: dict[str, Any]) -> str:
    lines: list[str] = [
        H1 + "Harbor Rehearsal Verification Report",
        "",
        f"- Rehearsal directory: `{report['rehearsal_dir']}`",
        f"- Strict mode: `{report['strict']}`",
        f"- Raw jobs / trials: `{report['n_raw_jobs']}` jobs, `{report['n_raw_trials']}` trials",
        f"- Overall verdict: **{'PASS' if report['overall_ok'] else 'FAIL'}**",
        "",
        H2 + "Verification Checks",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for k, v in report["checks"].items():
        lines.append(f"| `{k}` | {'PASS' if v else 'FAIL'} |")

    ob = report["oracle"]
    bref = ob["band_reference"]
    lines += [
        "",
        H2 + "Oracle Reference Check",
        "",
        f"- Oracle valid tasks: `{ob['n_valid']}` (`{ob['correct']}/{ob['n_valid']}` correct)",
        f"- Oracle mean reward: `{_fmt_num(ob['mean'])}`",
        f"- Expected 90% band (`{bref['source']}`, `{bref['tier']}` `{bref['k_key']}` over `{bref['builds']}` builds): "
        f"`[{bref['band_90pct'][0]:+.2f}, {bref['band_90pct'][1]:+.2f}]` (mean `{bref['mean']:+.3f}`, SD `{bref['sd']:.3f}`)",
        f"- In band: `{'yes' if ob['in_90pct_band'] else 'NO'}`",
        "",
        H2 + "Paired Job Summary vs Oracle",
        "",
        "| Job | Valid Paired | Infra Reruns | Unresolved Infra | Correct / Accused | Mean | Oracle Mean | Run / Oracle [95% Bootstrap CI] | Diff |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for r in report["paired_runs"]:
        ratio_str = _fmt_pct_ci(r["ratio_vs_oracle"], r["ratio_ci95"])
        lines.append(
            f"| `{r['job']}` | {r['n_paired_valid']} | {r['n_infra_reruns_used']} | {r['n_infra_invalid']} | "
            f"{r['correct']} / {r['accused']} | {_fmt_num(r['mean'])} | {_fmt_num(r['oracle_paired_mean'])} | "
            f"{ratio_str} | {_fmt_num(r['diff_vs_oracle'])} |"
        )

    if report["disclosed_infra_reruns"]:
        lines += ["", H2 + "Disclosed Infrastructure Reruns", ""]
        for rr in report["disclosed_infra_reruns"]:
            lines.append(
                f"- `{rr['job']}` `{rr['task']}`: primary infra `{rr['first_infra_reason']}` -> "
                f"`{rr['rerun_job']}` `{_fmt_num(rr['rerun_reward'], nd=2)}` (day `{rr['rerun_day']}`)"
            )

    sp = report["agent_spread"]
    mean_ratio_str = f"{sp['mean_ratio_vs_oracle']:.1%}" if sp["mean_ratio_vs_oracle"] is not None else "n/a"
    lines += [
        "",
        H2 + "Multi-Run OpenCode Spread and pass^3",
        "",
        f"- OpenCode runs: `{sp['n_runs']}` (`{', '.join(sp['run_jobs']) if sp['run_jobs'] else 'none'}`)",
        f"- Run means: `{', '.join(_fmt_num(x) for x in sp['run_means']) if sp['run_means'] else 'n/a'}`",
        f"- Mean of run means: `{_fmt_num(sp['mean_of_means'])}` (SD `{_fmt_num(sp['sd_across_runs'], signed=False)}`, "
        f"range `{_fmt_num(sp['range_across_runs'], signed=False)}`)",
        f"- Mean paired ratio vs oracle: `{mean_ratio_str}`",
        f"- Multi-run `pass^3` over tasks (`{sp['tasks_with_3plus_runs']}` tasks with >=3 valid runs): "
        f"`{_fmt_num(sp['pass_hat_3'], signed=False)}`",
    ]

    any_err = any(bool(v) for v in report["errors"].values())
    if any_err:
        lines += ["", H2 + "Detected Issues", ""]
        for cat, items in report["errors"].items():
            for item in items:
                lines.append(f"- `{cat}`: {item}")

    return norm_ascii("\n".join(lines) + "\n")


def render_audit_md(report: dict[str, Any]) -> str:
    tot = report["totals"]
    rd = report["rehearsal_dry"]
    lr = report["live_rehearsal"]
    cp = report["cheat_probe"]
    neg = report["negative_control"]
    ora_h = report["oracle_range_v14"]["hard_k10"]
    ora_m = report["oracle_range_v14"]["medium_k10"]
    pkg = report["current_package_verification"]
    leg = report["legacy_stop_early_audit"]
    gem = report["paired_gemini_demo"]

    rd_ratio_str = _fmt_pct_ci(rd["opencode_ratio_vs_oracle"], rd["opencode_ratio_ci95"])
    n_pass = sum(1 for v in report["checks"].values() if v)
    n_gates = len(report["checks"])

    lines: list[str] = [
        H1 + "Harbor Rehearsal & Committed Artifact Verification (v1.4)",
        "",
        "**Scope.** Deterministic keyless verification of all committed Harbor container runs under `results/harbor/` (`80` trials across `18` jobs, including `results/harbor/rehearsal-dry/`), negative control `results/harbor_negative/c1-tamper/`, live `results/harbor/rehearsal/` status, `results/oracle_range_v1.4.json` (`200` synthetic world-secret builds), and fresh `harbor/build.py` judge-package invariants (`0` API calls, `< 5 s` runtime).",
        "",
        "```bash",
        "python scripts/verify_harbor_rehearsal.py",
        "python scripts/verify_harbor_rehearsal.py --check",
        "python scripts/run_all_eval_checks.py --check --only verify_harbor_rehearsal",
        "```",
        "",
        H2 + "1. Executive Summary & Gate Verdict",
        "",
        f"- **Overall verdict:** **{'PASS' if report['overall_ok'] else 'FAIL'}** (`{n_pass}/{n_gates}` deterministic verification gates passed).",
        f"- **Full Harbor consistency (`80/80` trials, `18/18` job summaries):** Every trial across `13` top-level jobs (`37` trials) and `5` nested `rehearsal-dry` jobs (`43` trials) passes `canary.redteam.anticheat.harbor_consistency` (`result.json == verifier/reward.txt == artifacts/ledger.json == verifier/ledger.json`, accusation score arithmetic exact, `<= 1` accusation, `19/19` OpenCode ATIF trajectories matching `ledger.accused`).",
        f"- **Cryptographic signing & container isolation (`57/57` HMAC, `62/62` x `11/11` isolation checks):** `{tot['signed_trials']}/{tot['n_trials']}` trials carry `signature=ok` (`{tot['unsigned_legacy_trials']}` pre-C1 legacy trials); `{tot['hmac_verified_trials']}/{tot['hmac_expected_trials']}` trials in jobs with published retired `ledger_key` pass HMAC-SHA256 verification; `{tot['isolation_harbor_11of11']}/{tot['isolation_harbor_trials']}` `solve.sh` trials in `results/harbor/` plus `1/1` in `results/harbor_negative/c1-tamper/` (`{tot['isolation_including_negative_11of11']}/{tot['isolation_including_negative_total']}` total) pass all **`11/11` `check_isolation.sh` checks with `0` findings**.",
        f"- **`rehearsal-dry` 10-task harness check (`results/harbor/rehearsal-dry/`):** Same-build 10-task hard run (`hard-900000..900009`, `43/43` trials HMAC-verified under one shared retired `ledger_key`): `oracle` **`{_fmt_num(rd['oracle_10task_mean'])}`** (`9/10` correct), `opencode` (`google/gemini-4-carbon`) **`{_fmt_num(rd['opencode_10task_mean'])}`** (`9/10` correct) = **`{rd_ratio_str}`** of oracle (paired diff `{_fmt_num(rd['opencode_diff_vs_oracle'])}`), `do_nothing = +0.000`, `stop_early = +0.000`. Disclosed honestly as a **1-run harness check (`min_agent_runs = 1`, not a `3x10` gap claim)** with **`{rd['opencode_disclosed_infra_reruns_n']}` infrastructure reruns** (`hard-900006` rate limit, `hard-900007` rate limit, `hard-900009` `thought_signature` rejected; primary `7/10` valid mean `{_fmt_num(rd['opencode_primary_valid_mean'])}`, primary `0`-imputed `{_fmt_num(rd['opencode_primary_infra_as_zero_mean'])}`).",
        f"- **Anti-cheat & forged-ledger negative controls:** `cheat-probe` scores exact **`0.0` on `6/6` trials across `{cp['probes_per_trial']}` probes per trial** (`{cp['total_probe_attempts']}` total probe attempts, `holes = []`, `controls_failed = 0`); all `9/9` active `cheat` trials score `-1.000`; `results/harbor_negative/c1-tamper/` (`score = 1.0` forged over `V = {neg['true_accusation_V']}`) fails closed to **`reward = 0.0`** with `FAIL: bad ledger signature`.",
        f"- **`oracle_range_v1.4.json` cross-check (`{ora_h['builds']}` synthetic builds):** 10-task `hard` solver 90% build band is **`{ora_h['band_90pct'][0]:+.2f}` to `{ora_h['band_90pct'][1]:+.2f}`** (`p5 = {ora_h['p5']:+.3f}`, `p50 = {ora_h['p50']:+.3f}`, `p95 = {ora_h['p95']:+.3f}`, mean **`{ora_h['mean']:+.3f}`**, SD **`{ora_h['sd']:.3f}`**, `P(mean < 0) = 0%`). `rehearsal-dry` oracle (`+0.467`) sits inside this 90% band (`z = {rd['oracle_z_vs_200builds']:+.2f}`).",
        f"- **Live `results/harbor/rehearsal/` status:** **`{lr['status']}`** (`README.md` pre-registered protocol committed before any run, `{lr['n_jobs']}` job directories / `{lr['n_trials']}` executed trials currently committed; automatic `3x10` schema, HMAC, isolation, baseline-zero, oracle-band, paired-CI, and `pass^3` verifier armed if trials are added).",
        "",
        H2 + "2. Verification Gates",
        "",
        "| Gate | Status | Verified Invariant |",
        "|---|---|---|",
        f"| `harbor_80_trials_consistent` | {'PASS' if report['checks']['harbor_80_trials_consistent'] else 'FAIL'} | `{tot['trials_consistent']}/{tot['n_trials']}` committed trials consistent across reward, sidecar ledger, verifier ledger, and accusation math |",
        f"| `harbor_18_jobs_consistent` | {'PASS' if report['checks']['harbor_18_jobs_consistent'] else 'FAIL'} | `{tot['jobs_consistent']}/{tot['n_jobs']}` job `result.json` summaries match trial counts, exceptions, means, and reward buckets |",
        f"| `anticheat_harbor_consistency_parity` | {'PASS' if report['checks']['anticheat_harbor_consistency_parity'] else 'FAIL'} | Exact parity with `canary.redteam.anticheat.harbor_consistency` (`80` trials, `18` jobs, `0` failures) |",
        f"| `rehearsal_dry_verified` | {'PASS' if report['checks']['rehearsal_dry_verified'] else 'FAIL'} | `oracle +0.467`, `opencode +0.398` (`85% [11%, 355%]`, `3` disclosed infra reruns), `do_nothing 0.0`, `stop_early 0.0`, `TABLE.md` exact |",
        f"| `oracle_range_v14_crosschecked` | {'PASS' if report['checks']['oracle_range_v14_crosschecked'] else 'FAIL'} | `200` builds, `hard k=10` 90% band `[+0.39, +0.68]`, mean `+0.569`, SD `0.094`; `+0.467` in band |",
        f"| `do_nothing_and_stop_early_zero` | {'PASS' if report['checks']['do_nothing_and_stop_early_zero'] else 'FAIL'} | `13/13` `do_nothing` = `0.0`, `10/10` `rehearsal-dry/stop_early` = `0.0`, `10/10` fresh `build.py` = `0.0`, legacy `{PR16}` forensics verified |",
        f"| `cheat_probe_6of6_zero_149_probes` | {'PASS' if report['checks']['cheat_probe_6of6_zero_149_probes'] else 'FAIL'} | `6/6` `cheat-probe` = `0.0` (`149` probes/trial, `894` total, `0` holes) + `9/9` `cheat` = `-1.0` |",
        f"| `negative_c1_tamper_failed_closed_zero` | {'PASS' if report['checks']['negative_c1_tamper_failed_closed_zero'] else 'FAIL'} | `c1-tamper` forged `score = 1.0` rejected (`FAIL: bad ledger signature`), graded `0.0` |",
        f"| `check_isolation_11of11_passed` | {'PASS' if report['checks']['check_isolation_11of11_passed'] else 'FAIL'} | `{tot['isolation_including_negative_11of11']}/{tot['isolation_including_negative_total']}` `agent/isolation.txt` files report `ISOLATION OK: 11 checks passed, 0 findings` |",
        f"| `retired_keys_hmac_57of57_verified` | {'PASS' if report['checks']['retired_keys_hmac_57of57_verified'] else 'FAIL'} | `{tot['hmac_verified_trials']}/{tot['hmac_expected_trials']}` trials across all `8` retired-key jobs verify under HMAC-SHA256 |",
        f"| `top_level_zero_infra_invalid` | {'PASS' if report['checks']['top_level_zero_infra_invalid'] else 'FAIL'} | `0` unresolved infra-invalid trials across all `13` top-level jobs and merged `rehearsal-dry` |",
        f"| `live_rehearsal_status_honest` | {'PASS' if report['checks']['live_rehearsal_status_honest'] else 'FAIL'} | `results/harbor/rehearsal/` honestly reported as `{lr['status']}` (`{lr['n_trials']}` trials) |",
        f"| `current_harbor_build_package_verified` | {'PASS' if report['checks']['current_harbor_build_package_verified'] else 'FAIL'} | Fresh `harbor/build.py` 10-task package verified (`separate` verifier, `0600` secrets, `0` leaks, scratch deleted) |",
        "",
        H2 + "3. Dry Judge Rehearsal (`results/harbor/rehearsal-dry/`, 10 Hard Tasks, Harness Check)",
        "",
        "All `5` jobs in `results/harbor/rehearsal-dry/` share an identical retired 32-byte `ledger_key` (`43/43` trials HMAC-SHA256 verified) on `hard` judge seeds `900000-900009`. Because it ran `1` OpenCode pass rather than `3`, it is strictly a **harness check**, not a headline frontier-gap estimate:",
        "",
        "| Run | Valid Paired | Primary Valid | Disclosed Infra Reruns | Correct / Accused | Mean | Oracle Mean | Run / Oracle `[95% Boot CI]` | Diff | Primary Infra-as-0 |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|",
        f"| `oracle` (reference solver over MCP) | `10` | `10` | `0` | `{rd['oracle_correct']} / 10` | **`{_fmt_num(rd['oracle_10task_mean'])}`** | `{_fmt_num(rd['oracle_10task_mean'])}` | `100% (ref)` | `+0.000` | `{_fmt_num(rd['oracle_10task_mean'])}` |",
        f"| `opencode` (`google/gemini-4-carbon`) | `10` | `{rd['opencode_primary_valid_n']}` | `{rd['opencode_disclosed_infra_reruns_n']}` | `{rd['opencode_correct']} / {rd['opencode_accused']}` | **`{_fmt_num(rd['opencode_10task_mean'])}`** | `{_fmt_num(rd['oracle_10task_mean'])}` | **`{rd_ratio_str}`** | `{_fmt_num(rd['opencode_diff_vs_oracle'])}` | `{_fmt_num(rd['opencode_primary_infra_as_zero_mean'])}` |",
        f"| `do_nothing` | `10` | `10` | `0` | `0 / 0` | **`{_fmt_num(rd['do_nothing_10task_mean'])}`** | `{_fmt_num(rd['oracle_10task_mean'])}` | `0% [0%, 0%]` | `-{abs(rd['oracle_10task_mean']):.3f}` | `+0.000` |",
        f"| `stop_early` | `10` | `10` | `0` | `0 / 0` | **`{_fmt_num(rd['stop_early_10task_mean'])}`** | `{_fmt_num(rd['oracle_10task_mean'])}` | `0% [0%, 0%]` | `-{abs(rd['oracle_10task_mean']):.3f}` | `+0.000` |",
        "",
        "Disclosed infrastructure reruns in `results/harbor/rehearsal-dry/opencode-infra-rerun/` (primary trial had `ledger.done == false` and no accusation; zero valid primary trials were replaced):",
    ]
    for rr in rd["disclosed_infra_reruns"]:
        lines.append(
            f"- `{rr['task']}`: primary failed with **`{rr['first_infra_reason']}`** (`done = false`, `accused = null`) -> rerun completed cleanly at **`{_fmt_num(rr['rerun_reward'], nd=2)}`** (`correct = {rr['rerun_correct']}`, day `{rr['rerun_day']}`)."
        )

    lines += [
        "",
        H2 + "4. Oracle Distribution Cross-Check (`results/oracle_range_v1.4.json`) & Live `results/harbor/rehearsal/` Status",
        "",
        f"- **`results/oracle_range_v1.4.json` (`{ora_h['builds']}` synthetic secrets, never a build `SALT`):**",
        f"  - `solver` on `hard` (`k = 10` judge set): mean **`{ora_h['mean']:+.3f}`**, SD **`{ora_h['sd']:.3f}`**, 90% build band **`{ora_h['band_90pct'][0]:+.2f}` to `{ora_h['band_90pct'][1]:+.2f}`** (`p5 = {ora_h['p5']:+.3f}`, `p50 = {ora_h['p50']:+.3f}`, `p95 = {ora_h['p95']:+.3f}`, `P(mean < 0) = {ora_h['p_lt0']:.1%}`). `rehearsal-dry` oracle (`+0.467`, `9/10` correct with one 5%-flip `-1.00` on `hard-900000` day 16) falls squarely inside `[+0.39, +0.68]` (`z = {rd['oracle_z_vs_200builds']:+.2f}`).",
        f"  - `solver` on `medium` (`k = 10`): mean `{ora_m['mean']:+.3f}`, SD `{ora_m['sd']:.3f}`, 90% band `[{ora_m['p5']:+.3f}, {ora_m['p95']:+.3f}]`.",
        f"  - `do_nothing` and `stop_early` (`hard` and `medium`, `{ora_h['builds']}` builds): exact `0.000` (`SD = 0.000`) on every build.",
        f"- **Live `results/harbor/rehearsal/` status (`{lr['status']}`):**",
        f"  - `{lr['disclosure']}`",
        "  - One-command strict `3x10` validation when populated: `python scripts/verify_harbor_rehearsal.py results/harbor/rehearsal --strict`.",
        "",
        H2 + "5. Complete Inventory of All 18 Committed Harbor Jobs (`80` Trials) + Negative Control",
        "",
        "| Job Path | Policy / Model | Trials | Consistent | Job Summary | Signed | Retired Key HMAC | Isolation `11/11` | Traj Checked | Post-Game Exit!=0 | Mean Valid Reward | Audit Note |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]

    for j in report["jobs"]:
        pol = ", ".join(j["policies"])
        if j["models"]:
            pol += f" ({', '.join(j['models'])})"
        hmac_cell = f"{j['hmac_verified_trials']}/{j['n_trials']}" if j["has_retired_ledger_key"] else "n/a"
        lines.append(
            f"| `{j['job']}` | `{pol}` | {j['n_trials']} | "
            f"{j['trials_consistent']}/{j['n_trials']} | {'OK' if j['job_consistent'] else 'FAIL'} | "
            f"{j['signed_trials']}/{j['n_trials']} | {hmac_cell} | "
            f"{j['isolation_11of11_trials']}/{j['n_trials']} | {j['trajectory_checked_trials']}/{j['n_trials']} | "
            f"{j['n_post_game_nonzero_exit']} | {_fmt_num(j['mean_valid_reward'])} | {j['note']} |"
        )

    lines.append(
        f"| `{neg['job']}` | `oracle (forged ledger)` | 1 | 0/1 (expected) | OK | 0/1 | rejected | "
        f"1/1 | 0/1 | 0 | +0.000 | negative control: forged `score=1.0` -> `FAIL: bad ledger signature`, `reward=0.0` |"
    )

    lines += [
        "",
        H2 + "6. Baselines, Anti-Cheat, Isolation, and Fresh `harbor/build.py` Package Checks",
        "",
        f"- **`do_nothing = 0.0` & `stop_early = 0.0`:** All `13/13` committed `do_nothing` trials and all `10/10` `rehearsal-dry/stop_early` trials score exact `0.000`. {leg['explanation']}",
        f"- **`cheat-probe` (`6/6 = 0.0` across `149` probes/trial):** `results/harbor/cheat-probe/` (`medium` + `hard`, seeds `900000-900002`) executed `{cp['probes_per_trial']}` out-of-band probes per trial (`{cp['total_probe_attempts']}` total attempts across `/ledger`, `/admin/reset`, `/proc/*/environ`, `CANARY_*` vars, planted `/logs/verifier/reward.{{txt,json}}` + 15-min rewrite loop, and malformed MCP calls) with `holes = []`, `controls_failed = 0`, `6/6` HMAC-SHA256 verified, and exact reward `0.000`.",
        f"- **Paired 6-task earlier Harbor smoke (`g-oracle` vs `g-gemini-*`):** `{gem.get('n_paired_tasks', 0)}` paired tasks (`medium` + `hard` `900000-900002`), Gemini `{_fmt_num(gem.get('gemini_mean'))}` vs Oracle `{_fmt_num(gem.get('oracle_mean'))}` (`{_fmt_pct_ci(gem.get('ratio_vs_oracle'), gem.get('ratio_ci95', [None, None]))}`, `{gem.get('post_game_nonzero_exit_trials', 0)}/6` harmless post-game `EPIPE` exits retained as valid completed episodes).",
        f"- **Fresh `harbor/build.py` judge-package build (`{pkg['n_tasks']}` tasks, scratch cleaned):** Verified `{pkg['tasks'][0]}..{pkg['tasks'][-1]}`, `environment_mode = \"{pkg['verifier_environment_mode']}\"`, `timeout_sec = {pkg['agent_timeout_sec']}`, file mode `{pkg['secret_and_key_permissions']}` on `SALT` (`{pkg['salt_bytes']}` B), sidecar/verifier `ledger_key` (`{pkg['ledger_key_bytes']}` B, identical=`{pkg['sidecar_and_verifier_keys_match']}`), `0` secret leaks to agent/solution contexts, and in-process `stop_early = 0.000` & `do_nothing = 0.000` across all `10` generated worlds (`scratch_dir_deleted = {pkg['scratch_dir_deleted']}`).",
    ]

    return norm_ascii("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rehearsal_dir", nargs="?", type=Path, default=None)
    ap.add_argument("--audit-existing", action="store_true")
    ap.add_argument("--check", action="store_true", help="verify committed JSON and Markdown match fresh computation")
    ap.add_argument("--expected-tasks", type=int, default=10)
    ap.add_argument("--min-agent-runs", type=int, default=3)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--negative-dir", type=Path, default=DEFAULT_NEGATIVE_DIR)
    ap.add_argument("--oracle-range", type=Path, default=DEFAULT_ORACLE_RANGE)
    ap.add_argument("--scratch-pkg-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    run_audit_mode = args.check or args.audit_existing or args.rehearsal_dir is None

    if run_audit_mode:
        harbor_dir = args.rehearsal_dir if args.rehearsal_dir is not None else DEFAULT_HARBOR_DIR
        out_json = args.out_json if args.out_json is not None else DEFAULT_OUT_JSON
        out_md = args.out_md if args.out_md is not None else DEFAULT_OUT_MD

        report = audit_existing_harbor(
            harbor_dir=harbor_dir,
            negative_dir=args.negative_dir,
            oracle_range_path=args.oracle_range,
            scratch_pkg_dir=args.scratch_pkg_dir,
        )
        blob = norm_ascii(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
        blob_bytes = blob.encode("ascii")
        if len(blob_bytes) > MAX_JSON_BYTES:
            print(f"JSON size {len(blob_bytes)} exceeds {MAX_JSON_BYTES} byte limit", file=sys.stderr)
            return 1
        fresh_parsed = json.loads(blob)
        md_text = render_audit_md(fresh_parsed)

        if args.check:
            if not fresh_parsed.get("overall_ok"):
                failed = [k for k, v in fresh_parsed.get("checks", {}).items() if not v]
                print(f"verify_harbor_rehearsal check failed gates: {failed}", file=sys.stderr)
                return 1
            if not out_json.is_file():
                print(f"missing {out_json}", file=sys.stderr)
                return 1
            if not out_md.is_file():
                print(f"missing {out_md}", file=sys.stderr)
                return 1
            disk_bytes = out_json.read_bytes()
            if len(disk_bytes) > MAX_JSON_BYTES:
                print(f"{out_json} exceeds {MAX_JSON_BYTES} byte limit", file=sys.stderr)
                return 1
            try:
                disk_parsed = json.loads(disk_bytes.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                print(f"{out_json} invalid JSON: {exc}", file=sys.stderr)
                return 1
            if not approx_equal(disk_parsed, fresh_parsed, tol=FLOAT_TOL):
                print(f"{out_json} differs from fresh computation beyond tol={FLOAT_TOL}", file=sys.stderr)
                return 1
            if out_md.read_text(encoding="utf-8") != md_text:
                print(f"{out_md} differs from fresh render", file=sys.stderr)
                return 1
            tot = fresh_parsed["totals"]
            rd = fresh_parsed["rehearsal_dry"]
            print(
                f"verify_harbor_rehearsal check passed: "
                f"{tot['trials_consistent']}/{tot['n_trials']} trials, "
                f"{tot['jobs_consistent']}/{tot['n_jobs']} jobs, "
                f"rehearsal-dry {_fmt_pct_ci(rd['opencode_ratio_vs_oracle'], rd['opencode_ratio_ci95'])}, "
                f"c1-tamper=0.0, isolation={tot['isolation_including_negative_11of11']}/{tot['isolation_including_negative_total']} (11/11)"
            )
            return 0

        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_bytes(blob_bytes)
        out_md.write_text(md_text, encoding="utf-8")
        tot = fresh_parsed["totals"]
        print(
            f"AUDIT {'PASS' if fresh_parsed['overall_ok'] else 'FAIL'}: "
            f"{tot['trials_consistent']}/{tot['n_trials']} trials & {tot['jobs_consistent']}/{tot['n_jobs']} jobs consistent, "
            f"c1_tamper_failed_closed={fresh_parsed['negative_control']['failed_closed_ok']}, "
            f"pkg_verified={fresh_parsed['current_package_verification']['verified']} "
            f"({len(blob_bytes) / 1024.0:.1f} KB JSON)"
        )
        return 0 if fresh_parsed["overall_ok"] else 1

    report = verify_rehearsal(
        rehearsal_dir=args.rehearsal_dir,
        expected_tasks=args.expected_tasks,
        min_agent_runs=args.min_agent_runs,
        strict=args.strict,
        oracle_range_path=args.oracle_range,
    )
    blob = norm_ascii(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    md = render_rehearsal_md(report)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(blob, encoding="utf-8")
    if args.out_md is not None:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, encoding="utf-8")
    print(md, end="")
    return 0 if report["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
