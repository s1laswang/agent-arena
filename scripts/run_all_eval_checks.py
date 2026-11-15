"""One-command keyless Canary v1.4 master evaluation suite orchestrator and judge index.

    python scripts/run_all_eval_checks.py
    python scripts/run_all_eval_checks.py --check
    python scripts/run_all_eval_checks.py --list
    python scripts/run_all_eval_checks.py --check --only headline_gap_table
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

HASH_CHAR = chr(35)
H1 = HASH_CHAR + " "
H2 = HASH_CHAR * 2 + " "
H3 = HASH_CHAR * 3 + " "
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
MINUS_SIGN = chr(0x2212)
PLUS_MINUS = chr(0x00B1)

SCHEMA_VERSION = "eval_suite_index_v14.v1"
TIERS_VERSION = "v1.4"
PRIMARY_SEEDS = "0-29"
PRIMARY_SEEDS_LOCK = (
    "post-hoc locked paired dev seeds 0-29 (671ed96, 28 s after 8fd4dec; "
    "lock against later reruns and cherry-picking, not a pre-registration)"
)
N_PRIMARY_SEEDS = 30
FLOAT_TOL = 1e-9
MAX_INDEX_BYTES = 50 * 1024

DEFAULT_INDEX_REL = "results/eval_v14/eval_suite_index.json"
DEFAULT_OVERVIEW_REL = "docs/reports/eval_suite_overview.md"

CORE_VERIFIERS: tuple[dict[str, str], ...] = (
    {
        "name": "verify_eval_claims",
        "script": "scripts/verify_eval_claims.py",
        "json_artifact": "results/eval_v14/claims_manifest.json",
        "report_artifact": "docs/reports/eval_claims_verification.md",
        "title": "5-Gate Claims, Replay Cache & Protected-Path Verifier",
    },
    {
        "name": "headline_gap_table",
        "script": "scripts/headline_gap_table.py",
        "json_artifact": "results/eval_v14/headline_gap_table_v14.json",
        "report_artifact": "docs/reports/headline_gap_table_v14.md",
        "title": "Primary Paired Headline Gap Table & Multi-Model Ladder",
    },
    {
        "name": "harness_and_tier_analysis_v14",
        "script": "scripts/harness_and_tier_analysis_v14.py",
        "json_artifact": "results/eval_v14/harness_and_tier_v14.json",
        "report_artifact": "docs/reports/medium_vs_hard_and_harness_v14.md",
        "title": "2x2 Harness x Tier Crossover & Noisy-Bayes Mechanism",
    },
    {
        "name": "judge_rerun_power_v14",
        "script": "scripts/judge_rerun_power_v14.py",
        "json_artifact": "results/eval_v14/judge_rerun_power_v14.json",
        "report_artifact": "docs/reports/judge_rerun_operating_characteristics.md",
        "title": "1x10 vs 3x10 Judge Rerun Power, Rao-Blackwell & pass^3",
    },
    {
        "name": "hint_ablation_audit",
        "script": "scripts/hint_ablation_audit.py",
        "json_artifact": "results/eval_v14/hint_ablation_v14.json",
        "report_artifact": "docs/reports/hint_ablation_v14_audit.md",
        "title": "Fact-Only Hint Ablation v1.4 Hard Causal Audit",
    },
)

OPTIONAL_VERIFIER_NAMES: tuple[str, ...] = (
    "eval_replication_and_crossmodel",
    "counterfactual_decomposition_v14",
    "verify_harbor_rehearsal",
    "eval_candidate_tiers",
    "build_eval_charts_v14",
    "harbor_luck_adjusted_v14",
    "ladder_pareto_v14",
    "version_evolution_v14",
    "version_evolution_audit",
    "paired_seed_diagnostics_v14",
)

SECRET_AND_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("sk_api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_oauth_token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}")),
    ("provider_token", re.compile(r"\b(?:xai-[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("world_mole_dump", re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')),
)


def _norm_ascii(text: str) -> str:
    return (
        text.replace(EN_DASH, "-")
        .replace(EM_DASH, "--")
        .replace(MINUS_SIGN, "-")
        .replace(PLUS_MINUS, "+/-")
    )


def _clean_json_value(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 10)
    if isinstance(obj, str):
        return _norm_ascii(obj)
    if isinstance(obj, dict):
        return {str(k): _clean_json_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_json_value(v) for v in obj]
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


def normalize_verifier_name(raw: str) -> str:
    s = raw.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if s.startswith("scripts/"):
        s = s[len("scripts/") :]
    if s.endswith(".py"):
        s = s[:-3]
    return s.strip()


def parse_only_specs(raw_specs: list[str] | None) -> list[str]:
    if not raw_specs:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in raw_specs:
        for part in raw.split(","):
            norm = normalize_verifier_name(part)
            if norm and norm not in seen:
                seen.add(norm)
                out.append(norm)
    return out


def discover_verifiers(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    core_items: list[dict[str, Any]] = []
    for spec in CORE_VERIFIERS:
        script_path = root / spec["script"]
        core_items.append(
            {
                "name": spec["name"],
                "script": spec["script"],
                "json_artifact": spec["json_artifact"],
                "report_artifact": spec["report_artifact"],
                "title": spec["title"],
                "required": True,
                "present": script_path.is_file(),
            }
        )
    optional_items: list[dict[str, Any]] = []
    for name in OPTIONAL_VERIFIER_NAMES:
        rel_script = f"scripts/{name}.py"
        optional_items.append(
            {
                "name": name,
                "script": rel_script,
                "required": False,
                "present": (root / rel_script).is_file(),
            }
        )
    return core_items, optional_items


def select_verifiers(
    core_items: list[dict[str, Any]],
    optional_items: list[dict[str, Any]],
    only_names: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_name: dict[str, dict[str, Any]] = {item["name"]: item for item in core_items + optional_items}
    errors: list[str] = []
    if only_names:
        selected: list[dict[str, Any]] = []
        for name in only_names:
            item = by_name.get(name)
            if item is None:
                errors.append(
                    f"unknown verifier {name!r}; valid names: {', '.join(sorted(by_name.keys()))}"
                )
                continue
            if not item["present"]:
                errors.append(f"requested verifier script missing on disk: {item['script']}")
                continue
            selected.append(item)
        return selected, errors

    selected = list(core_items)
    for item in core_items:
        if not item["present"]:
            errors.append(f"missing required core verifier script: {item['script']}")
    for opt in optional_items:
        if opt["present"]:
            selected.append(opt)
    return selected, errors


def run_verifier_check(
    root: Path,
    item: dict[str, Any],
    python_exe: str | None = None,
    timeout_s: int = 300,
) -> dict[str, Any]:
    exe = python_exe or sys.executable
    script_abs = root / str(item["script"])
    if not script_abs.is_file():
        return {
            "name": item["name"],
            "script": item["script"],
            "required": bool(item["required"]),
            "passed": False,
            "returncode": 127,
            "elapsed_s": 0.0,
            "stdout": "",
            "stderr": f"missing script: {item['script']}",
        }

    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    root_str = str(root)
    env["PYTHONPATH"] = f"{root_str}{os.pathsep}{existing_pp}" if existing_pp else root_str
    env.setdefault("CANARY_ALLOW_DEV", "1")

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [exe, str(script_abs), "--check"],
            cwd=root_str,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        elapsed_s = round(time.perf_counter() - t0, 3)
        return {
            "name": item["name"],
            "script": item["script"],
            "required": bool(item["required"]),
            "passed": proc.returncode == 0,
            "returncode": int(proc.returncode),
            "elapsed_s": elapsed_s,
            "stdout": _norm_ascii(proc.stdout.strip()),
            "stderr": _norm_ascii(proc.stderr.strip()),
        }
    except subprocess.TimeoutExpired:
        elapsed_s = round(time.perf_counter() - t0, 3)
        return {
            "name": item["name"],
            "script": item["script"],
            "required": bool(item["required"]),
            "passed": False,
            "returncode": 124,
            "elapsed_s": elapsed_s,
            "stdout": "",
            "stderr": f"timed out after {timeout_s}s: {item['script']} --check",
        }


def _extract_hgt_cohort(row: dict[str, Any]) -> dict[str, Any]:
    ratio_ci = (
        [float(row["ratio_lo"]), float(row["ratio_hi"])]
        if row.get("ratio_lo") is not None and row.get("ratio_hi") is not None
        else None
    )
    luck_ci = (
        [float(row["luck_adj_lo"]), float(row["luck_adj_hi"])]
        if row.get("luck_adj_lo") is not None and row.get("luck_adj_hi") is not None
        else None
    )
    win_ci = (
        [float(row["winnable_ratio_lo"]), float(row["winnable_ratio_hi"])]
        if row.get("winnable_ratio_lo") is not None and row.get("winnable_ratio_hi") is not None
        else None
    )
    return {
        "tier": str(row["tier"]),
        "agent": str(row["agent"]),
        "kind": str(row["kind"]),
        "n": int(row["n"]),
        "mean": float(row["mean"]),
        "score_ci": float(row["score_ci"]),
        "accuracy": float(row["accuracy"]),
        "accuracy_wilson_ci": [float(row["accuracy_wilson_lo"]), float(row["accuracy_wilson_hi"])],
        "false_accusation_rate": float(row["false_accusation_rate"]),
        "abstain_rate": float(row["abstain_rate"]),
        "mean_accuse_day": float(row["mean_accuse_day"]) if row.get("mean_accuse_day") is not None else None,
        "mean_p_accused": float(row["mean_p_accused"]) if row.get("mean_p_accused") is not None else None,
        "pass3_calibrated": float(row["pass3_calibrated"]),
        "solver_same_seeds": float(row["solver_same_seeds"]),
        "ratio": float(row["ratio"]),
        "ratio_ci": ratio_ci,
        "luck_adjusted_score": float(row["luck_adjusted_score"]),
        "solver_luck_adjusted": float(row["solver_luck_adjusted"]),
        "luck_adj_ratio": float(row["luck_adj_ratio"]),
        "luck_adj_ci": luck_ci,
        "p_wilcoxon_raw": float(row["p_wilcoxon_raw"]),
        "p_wilcoxon_luck": float(row["p_wilcoxon_luck"]),
        "winnable_n": int(row["winnable_n"]),
        "winnable_ratio": float(row["winnable_ratio"]),
        "winnable_ratio_ci": win_ci,
    }


def _load_json_required(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        raise FileNotFoundError(f"missing required core JSON artifact: {rel}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _load_repo_milestones(root: Path) -> dict[str, Any]:
    g1_summary: dict[str, Any] | None = None
    pooled_path = root / "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
    if pooled_path.is_file():
        rows = json.loads(pooled_path.read_text(encoding="utf-8"))
        if isinstance(rows, list):
            ext_row = next(
                (
                    r
                    for r in rows
                    if isinstance(r, dict)
                    and r.get("group") == "v1.4/opencode-gemini-4-carbon-ext"
                    and r.get("tier") == "hard"
                ),
                None,
            )
            pool_row = next(
                (
                    r
                    for r in rows
                    if isinstance(r, dict)
                    and r.get("group") == "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext"
                    and r.get("tier") == "hard"
                ),
                None,
            )
            if ext_row is not None and pool_row is not None:
                g1_summary = {
                    "prereg_commit": "f9fb7a4a",
                    "data_commit": "364fe657",
                    "ext_only": {
                        "n": int(ext_row["n"]),
                        "seeds": [int(s) for s in ext_row["seeds"]],
                        "mean": float(ext_row["mean"]),
                        "ci": float(ext_row["ci"]),
                        "solver_same_seeds": float(ext_row["solver_same_seeds"]),
                        "ratio": float(ext_row["ratio"]),
                        "ratio_ci": [float(ext_row["ratio_lo"]), float(ext_row["ratio_hi"])],
                        "luck_adj_ratio": float(ext_row["post_expected_ratio"]),
                        "luck_adj_ci": [
                            float(ext_row["post_expected_lo"]),
                            float(ext_row["post_expected_hi"]),
                        ],
                    },
                    "pooled_0_59": {
                        "n": int(pool_row["n"]),
                        "mean": float(pool_row["mean"]),
                        "ci": float(pool_row["ci"]),
                        "solver_same_seeds": float(pool_row["solver_same_seeds"]),
                        "ratio": float(pool_row["ratio"]),
                        "ratio_ci": [float(pool_row["ratio_lo"]), float(pool_row["ratio_hi"])],
                        "luck_adj_ratio": float(pool_row["post_expected_ratio"]),
                        "luck_adj_ci": [
                            float(pool_row["post_expected_lo"]),
                            float(pool_row["post_expected_hi"]),
                        ],
                        "diff": float(pool_row["diff"]),
                        "diff_ci": float(pool_row["diff_ci"]),
                    },
                }

    ladder_summary: dict[str, Any] | None = None
    ladder_path = root / "results/gemini/ladder.json"
    if ladder_path.is_file():
        lad = json.loads(ladder_path.read_text(encoding="utf-8"))
        if isinstance(lad, dict) and isinstance(lad.get("rows"), list) and "episodes" in lad:
            gemma_d = lad.get("gemma") if isinstance(lad.get("gemma"), dict) else {}
            ladder_summary = {
                "commit": "eb363eb9",
                "episodes": int(lad["episodes"]),
                "cells": len(lad["rows"]),
                "gemma_episodes": int(gemma_d.get("episodes", 0)),
            }

    return {
        "seed_lock": {
            "commit": "671ed96",
            "primary_commit": "8fd4dec",
            "delay_seconds": 28,
            "classification": "post_hoc_lock_not_preregistered",
            "solver_hard_reference_dirs": [
                "data/runs/committed/v1.4/reference/solver-hard-20261114-121126",
                "data/runs/committed/v1.4/reference/solver-hard-seeds20to29",
            ],
        },
        "replay_panel_fix_d": {
            "commit": "1bc3e281",
            "invalid_arguments_detail_compat": True,
        },
        "g1_partial_extension": g1_summary,
        "canonical_gemini_ladder": ladder_summary,
        "gpt_5_5_preregistration": {
            "commit": "cf394894",
            "env_tag": "afterquery-final",
            "seeds": "0-29",
            "stop_time_eet": "08:15",
            "spend_cap_usd": 200,
            "committed_dir_present": (root / "data/runs/committed/v1.4/opencode-gpt-5.5").is_dir(),
        },
        "harbor_rehearsal_final": {
            "commit": "c59ecfd0",
            "env_tag": "afterquery-final",
            "table_present": (root / "results/harbor/rehearsal/TABLE.md").is_file(),
        },
    }


def build_core_headline_summary(root: Path) -> dict[str, Any]:
    cm = _load_json_required(root / "results/eval_v14/claims_manifest.json", root)
    hgt = _load_json_required(root / "results/eval_v14/headline_gap_table_v14.json", root)
    ht = _load_json_required(root / "results/eval_v14/harness_and_tier_v14.json", root)
    jrp = _load_json_required(root / "results/eval_v14/judge_rerun_power_v14.json", root)
    ha = _load_json_required(root / "results/eval_v14/hint_ablation_v14.json", root)

    gates = cm.get("gates") or []
    oracle_band = cm.get("oracle_band") or {}
    g1_hard = (cm.get("guess_day1_spreads") or {}).get("hard") or {}
    b_hard = (cm.get("baseline_zeros") or {}).get("hard") or {}
    vhyg = cm.get("version_hygiene") or {}

    claims_summary = {
        "schema_version": str(cm["schema_version"]),
        "overall_passed": bool(cm["overall_passed"]),
        "gate_count": len(gates),
        "gates_passed_count": sum(1 for g in gates if g.get("passed")),
        "total_violations": sum(int(g.get("violation_count", 0)) for g in gates),
        "committed_paired_rows_verified": int(cm["committed_paired_rows_verified"]),
        "oracle_hard_k10": {
            "builds": int(oracle_band["builds"]),
            "mean": float(oracle_band["mean_exact"]),
            "sd": float(oracle_band["sd_exact"]),
            "p5": float(oracle_band["p5_exact"]),
            "p95": float(oracle_band["p95_exact"]),
        },
        "hard_baselines": {
            "do_nothing_score_ci": str(b_hard["do_nothing"]),
            "stop_early_score_ci": str(b_hard["stop_early"]),
            "guess_day1_300secret_mean": float(g1_hard["mean"]),
            "guess_day1_300secret_max": float(g1_hard["max"]),
        },
        "hygiene": {
            "paired_groups_checked": int(vhyg["paired_groups_checked"]),
            "judge_table_v14_rows_checked": int(vhyg["judge_table_v14_rows_checked"]),
            "v14_meta_files_checked": int(vhyg["v14_meta_files_checked"]),
            "primary_locked_frontier_cohorts": int(
                vhyg.get(
                    "posthoc_locked_primary_frontier_cohorts",
                    vhyg.get(
                        "locked_primary_frontier_cohorts",
                        vhyg.get(
                            "primary_locked_frontier_cohorts",
                            vhyg.get("primary_frontier_cohorts", vhyg.get("preregistered_frontier_cohorts", 0)),
                        ),
                    ),
                )
            ),
            "seed_lock_rule_verified": bool(
                vhyg.get(
                    "seed_lock_rule_verified",
                    vhyg.get("post_hoc_seed_lock_verified", vhyg.get("preregistration_rule_verified", False)),
                )
            ),
            "active_docs_checked_count": len(vhyg.get("active_docs_checked") or []),
            "protected_path_rules_count": int(cm["protected_path_rules_count"]),
            "secret_pattern_rules_count": int(cm["secret_pattern_rules_count"]),
        },
    }

    by_tak: dict[tuple[str, str, str], dict[str, Any]] = {
        (str(r["tier"]), str(r["agent"]), str(r["kind"])): r for r in hgt["section_a"]
    }
    cohort_specs = (
        ("hard_opencode_gemini_4_carbon", ("hard", "opencode:google/gemini-4-carbon", "frontier")),
        ("hard_opencode_gemini_4_carbon_0imputed", ("hard", "opencode:google/gemini-4-carbon", "sensitivity")),
        ("hard_inproc_gemini_4_carbon", ("hard", "gemini:gemini-4-carbon", "frontier")),
        ("hard_opencode_gemini_3_5_flash", ("hard", "opencode:google/gemini-3.5-flash", "frontier")),
        ("hard_solver", ("hard", "solver", "reference")),
        ("hard_grok_tactics", ("hard", "grok_tactics", "baseline")),
        ("hard_heuristic", ("hard", "heuristic", "baseline")),
        ("hard_do_nothing", ("hard", "do_nothing", "baseline")),
        ("hard_guess_day1", ("hard", "guess_day1", "baseline")),
        ("medium_opencode_gemini_4_carbon", ("medium", "opencode:google/gemini-4-carbon", "frontier")),
        ("medium_opencode_gemini_4_carbon_0imputed", ("medium", "opencode:google/gemini-4-carbon", "sensitivity")),
        ("medium_inproc_gemini_4_carbon", ("medium", "gemini:gemini-4-carbon", "frontier")),
        ("medium_solver", ("medium", "solver", "reference")),
    )
    optional_cohort_specs = (
        ("hard_opencode_gpt_5_5", ("hard", "opencode:openai/gpt-5.5", "frontier")),
        ("medium_opencode_gemini_3_5_flash", ("medium", "opencode:google/gemini-3.5-flash", "frontier")),
    )
    cohorts_out: dict[str, Any] = {}
    for c_name, key in cohort_specs:
        if key not in by_tak:
            raise KeyError(f"headline_gap_table_v14.json missing Section A cohort {key}")
        cohorts_out[c_name] = _extract_hgt_cohort(by_tak[key])
    for c_name, key in optional_cohort_specs:
        if key in by_tak:
            cohorts_out[c_name] = _extract_hgt_cohort(by_tak[key])

    hgt_ver = hgt["verification"]
    headline_summary = {
        "schema_version": str(hgt["schema_version"]),
        "bootstrap_resamples": int(hgt["bootstrap_resamples"]),
        "verification": {
            "all_replay_consistent": bool(hgt_ver["all_replay_consistent"]),
            "section_a_min_n": int(hgt_ver["section_a_min_n"]),
            "section_a_rows": int(hgt_ver["section_a_rows"]),
            "section_b_rows": int(hgt_ver["section_b_rows"]),
            "frontier_cached_episodes_replayed": int(hgt_ver["frontier_cached_episodes_replayed"]),
            "stored_solver_episodes_replayed": int(hgt_ver["stored_solver_episodes_replayed"]),
            "inproc_baseline_episodes_verified": int(hgt_ver["inproc_baseline_episodes_verified"]),
            "ladder_cached_episodes_replayed": int(hgt_ver["ladder_cached_episodes_replayed"]),
            "ladder_total_reported_episodes": int(hgt_ver["ladder_total_reported_episodes"]),
            "ladder_total_reported_cells": int(hgt_ver["ladder_total_reported_cells"]),
        },
        "cohorts": cohorts_out,
    }

    ct_raw = ht["contrasts_2x2"]["raw_score"]
    ct_la = ht["contrasts_2x2"]["luck_adjusted_score"]
    cells = ht["cells"]

    def _contrast_entry(c: dict[str, Any], include_indep: bool = False) -> dict[str, Any]:
        out = {
            "point": float(c["point"]),
            "boot_ci95": [float(c["boot_ci95"][0]), float(c["boot_ci95"][1])],
            "p_boot_two_sided": float(c["p_boot_two_sided"]),
        }
        if include_indep and "boot_ci95_indep_tiers" in c:
            out["boot_ci95_indep_tiers"] = [
                float(c["boot_ci95_indep_tiers"][0]),
                float(c["boot_ci95_indep_tiers"][1]),
            ]
        return out

    harness_tier_summary = {
        "n_episodes_frontier": int(ht["meta"]["n_episodes_frontier"]),
        "n_episodes_solver": int(ht["meta"]["n_episodes_solver"]),
        "n_episodes_total": int(ht["meta"]["n_episodes_total"]),
        "raw_oc_minus_ip_medium": _contrast_entry(ct_raw["oc_minus_ip_medium"]),
        "raw_oc_minus_ip_hard": _contrast_entry(ct_raw["oc_minus_ip_hard"]),
        "raw_did_hard_minus_medium": _contrast_entry(ct_raw["did_hard_minus_medium"], include_indep=True),
        "luck_adjusted_oc_minus_ip_medium": _contrast_entry(ct_la["oc_minus_ip_medium"]),
        "luck_adjusted_oc_minus_ip_hard": _contrast_entry(ct_la["oc_minus_ip_hard"]),
        "luck_adjusted_did_hard_minus_medium": _contrast_entry(ct_la["did_hard_minus_medium"], include_indep=True),
        "hard_mechanisms": {
            "opencode": {
                "canaries_before_accuse_mean": float(cells["hard_opencode"]["canaries_before_accuse_mean"]),
                "canary_capacity_used_share": float(cells["hard_opencode"]["canary_capacity_used_share"]),
                "interviews_mean": float(cells["hard_opencode"]["interviews_mean"]),
                "p_accused_mean": float(cells["hard_opencode"]["p_accused_mean"]),
                "wrong_count": int(cells["hard_opencode"]["wrong_count"]),
                "consistent_eq_0_at_accuse": int(cells["hard_opencode"]["consistent_eq_0_at_accuse"]),
            },
            "inproc": {
                "canaries_before_accuse_mean": float(cells["hard_inproc"]["canaries_before_accuse_mean"]),
                "canary_capacity_used_share": float(cells["hard_inproc"]["canary_capacity_used_share"]),
                "interviews_mean": float(cells["hard_inproc"]["interviews_mean"]),
                "p_accused_mean": float(cells["hard_inproc"]["p_accused_mean"]),
                "wrong_count": int(cells["hard_inproc"]["wrong_count"]),
                "consistent_eq_0_at_accuse": int(cells["hard_inproc"]["consistent_eq_0_at_accuse"]),
            },
            "solver": {
                "canaries_before_accuse_mean": float(cells["hard_solver"]["canaries_before_accuse_mean"]),
                "canary_capacity_used_share": float(cells["hard_solver"]["canary_capacity_used_share"]),
                "interviews_mean": float(cells["hard_solver"]["interviews_mean"]),
                "p_accused_mean": float(cells["hard_solver"]["p_accused_mean"]),
                "wrong_count": int(cells["hard_solver"]["wrong_count"]),
            },
        },
    }

    ma_oc = jrp["model_a_empirical_paired_resampling"]["opencode-carbon"]
    mb_oc = jrp["model_b_posterior_repeated_runs"]["opencode-carbon"]
    mb_oc_dec = mb_oc["analytical_decomposition"]
    mb_fl = jrp["model_b_posterior_repeated_runs"]["opencode-3.5-flash"]
    pk = jrp["pass_k_reliability"]

    pass_k_out: dict[str, Any] = {}
    for pk_key in ("solver", "inproc-carbon", "opencode-carbon", "opencode-3.5-flash"):
        row_pk = pk[pk_key]
        pass_k_out[pk_key] = {
            "empirical_pass_1run": float(row_pk["empirical_pass_1run"]),
            "pass_1": float(row_pk["pass_1"]),
            "pass_3": float(row_pk["pass_3"]),
            "pass_3_ci95": [float(row_pk["pass_3_ci95"][0]), float(row_pk["pass_3_ci95"][1])],
            "n_gamble_worlds_lt60": int(row_pk["n_gamble_worlds_lt60"]),
            "gamble_pass_3": float(row_pk["gamble_pass_3"]) if row_pk["gamble_pass_3"] is not None else None,
        }

    rerun_power_summary = {
        "n_trials": int(jrp["meta"]["n_trials"]),
        "k_tasks": int(jrp["meta"]["k_tasks"]),
        "r_values": [int(x) for x in jrp["meta"]["r_values"]],
        "opencode_carbon_wrong_swing_10task": float(jrp["agents"]["opencode-carbon"]["mean_wrong_accuse_swing_10task"]),
        "solver_wrong_swing_10task": float(jrp["agents"]["solver"]["mean_wrong_accuse_swing_10task"]),
        "opencode_carbon_model_a": {
            "raw_r1_sd": float(ma_oc["raw"]["runs"]["R1"]["diff"]["sd"]),
            "raw_r3_sd": float(ma_oc["raw"]["runs"]["R3"]["diff"]["sd"]),
            "raw_r1_p_lt_oracle": float(ma_oc["raw"]["runs"]["R1"]["p_frontier_lt_oracle"]),
            "raw_r3_p_lt_oracle": float(ma_oc["raw"]["runs"]["R3"]["p_frontier_lt_oracle"]),
            "la_r1_sd": float(ma_oc["luck_adjusted"]["runs"]["R1"]["diff"]["sd"]),
            "la_r3_sd": float(ma_oc["luck_adjusted"]["runs"]["R3"]["diff"]["sd"]),
            "la_r1_p_lt_oracle": float(ma_oc["luck_adjusted"]["runs"]["R1"]["p_frontier_lt_oracle"]),
            "la_r3_p_lt_oracle": float(ma_oc["luck_adjusted"]["runs"]["R3"]["p_frontier_lt_oracle"]),
            "empirical_paired_var_reduction_factor": float(ma_oc["empirical_paired_var_reduction_factor"]),
            "effective_n_at_k10": float(ma_oc["effective_n_at_k10"]),
        },
        "opencode_carbon_model_b": {
            "within_build_1run_sd": float(mb_oc_dec["exact_within_build_1run_sd"]),
            "within_build_3run_mean_sd": float(mb_oc_dec["exact_within_build_3run_mean_sd"]),
            "luck_noise_sd_reduction_r1_to_r3": float(mb_oc_dec["luck_noise_sd_reduction_r1_to_r3"]),
            "r1_p_lt_oracle": float(mb_oc["runs"]["R1"]["p_frontier_lt_oracle"]),
            "r3_p_lt_oracle": float(mb_oc["runs"]["R3"]["p_frontier_lt_oracle"]),
            "frontier_luck_share_of_r1_var": float(mb_oc_dec["frontier_luck_share_of_r1_var"]),
            "all_luck_share_of_r1_var": float(mb_oc_dec["all_luck_share_of_r1_var"]),
            "la_var_reduction_vs_raw_r1": float(mb_oc_dec["la_var_reduction_vs_raw_r1"]),
            "la_var_reduction_vs_raw_r3": float(mb_oc_dec["la_var_reduction_vs_raw_r3"]),
            "effective_n_at_k10": float(mb_oc_dec["effective_n_at_k10"]),
        },
        "flash_3_5_model_b_r3_p_lt_oracle": float(mb_fl["runs"]["R3"]["p_frontier_lt_oracle"]),
        "flash_3_5_realised_luck_mean": float(jrp["agents"]["opencode-3.5-flash"]["realised_luck_mean"]),
        "pass_k_hard": pass_k_out,
    }

    ha_rv = ha["replay_verification"]
    ha_arms: dict[str, Any] = {}
    for arm_name in ("control", "premature_accusation", "decoy_chase"):
        arm_d = ha["arms"][arm_name]
        ha_arms[arm_name] = {
            "n": int(arm_d["n"]),
            "score_mean": float(arm_d["score_mean"]),
            "score_ci95": float(arm_d["score_ci95"]),
            "luck_adjusted_mean": float(arm_d["luck_adjusted_mean"]),
            "luck_adjusted_boot_ci95": [
                float(arm_d["luck_adjusted_boot_ci95"][0]),
                float(arm_d["luck_adjusted_boot_ci95"][1]),
            ],
            "canaries_mean": float(arm_d["canaries_mean"]),
            "day1_canary_count": int(arm_d["day1_canary_count"]),
            "interviews_mean": float(arm_d["interviews_mean"]),
            "p_accused_mean": float(arm_d["p_accused_mean"]),
            "ev_negative_gamble_count": int(arm_d["ev_negative_gamble_count"]),
        }

    ha_vs_ctrl: dict[str, Any] = {}
    for arm_name in ("premature_accusation", "decoy_chase"):
        vc_d = ha["paired_vs_control"][arm_name]
        ha_vs_ctrl[arm_name] = {
            "score_diff_mean": float(vc_d["score_diff_mean"]),
            "score_diff_boot_ci95": [
                float(vc_d["score_diff_boot_ci95"][0]),
                float(vc_d["score_diff_boot_ci95"][1]),
            ],
            "luck_adjusted_diff_mean": float(vc_d["luck_adjusted_diff_mean"]),
            "luck_adjusted_diff_boot_ci95": [
                float(vc_d["luck_adjusted_diff_boot_ci95"][0]),
                float(vc_d["luck_adjusted_diff_boot_ci95"][1]),
            ],
            "interviews_diff_mean": float(vc_d["interviews_diff_mean"]),
            "interviews_diff_boot_ci95": [
                float(vc_d["interviews_diff_boot_ci95"][0]),
                float(vc_d["interviews_diff_boot_ci95"][1]),
            ],
        }

    hint_ablation_summary = {
        "schema_version": str(ha["schema_version"]),
        "seeds": [int(s) for s in ha["seeds"]],
        "ablation_episodes_verified": int(ha_rv["ablation_episodes_verified"]),
        "context_episodes_verified": int(ha_rv["context_episodes_verified"]),
        "total_steps_verified": int(ha_rv.get("total_steps_verified", 0)),
        "step_mismatches": int(ha_rv.get("step_mismatches", 0)),
        "all_passed": bool(ha_rv["all_passed"]),
        "arms": ha_arms,
        "paired_vs_control": ha_vs_ctrl,
        "inproc_no_hint_context": {
            "score_mean": float(ha["context"]["inproc_gemini"]["score_mean"]),
            "luck_adjusted_mean": float(ha["context"]["inproc_gemini"]["luck_adjusted_mean"]),
            "score_diff_vs_control": float(ha["inproc_vs_control"]["score_diff_mean"]),
            "luck_adjusted_diff_vs_control": float(ha["inproc_vs_control"]["luck_adjusted_diff_mean"]),
        },
        "solver_same_seeds_context": {
            "score_mean": float(ha["context"]["solver"]["score_mean"]),
            "luck_adjusted_mean": float(ha["context"]["solver"]["luck_adjusted_mean"]),
        },
    }

    return _clean_json_value(
        {
            "claims_and_hygiene": claims_summary,
            "headline_gap_table": headline_summary,
            "harness_and_tier_2x2": harness_tier_summary,
            "judge_rerun_power": rerun_power_summary,
            "hint_ablation": hint_ablation_summary,
            "repo_milestones": _load_repo_milestones(root),
        }
    )


def expected_core_verifiers_manifest() -> list[dict[str, Any]]:
    return [
        {
            "check_passed": True,
            "json_artifact": spec["json_artifact"],
            "name": spec["name"],
            "report_artifact": spec["report_artifact"],
            "script": spec["script"],
            "title": spec["title"],
        }
        for spec in CORE_VERIFIERS
    ]


def expected_core_artifacts_manifest() -> dict[str, list[str]]:
    return {
        "json": [spec["json_artifact"] for spec in CORE_VERIFIERS],
        "reports": [spec["report_artifact"] for spec in CORE_VERIFIERS],
    }


def list_present_eval_v14_artifacts(root: Path, index_path: Path) -> list[str]:
    eval_dir = root / "results/eval_v14"
    if not eval_dir.is_dir():
        return []
    idx_resolved = index_path.resolve()
    out: list[str] = []
    for fp in sorted(eval_dir.rglob("*")):
        if not fp.is_file():
            continue
        if fp.resolve() == idx_resolved:
            continue
        out.append(fp.relative_to(root).as_posix())
    return out


def build_suite_index(root: Path, index_path: Path) -> dict[str, Any]:
    _, optional_items = discover_verifiers(root)
    core_manifest = expected_core_verifiers_manifest()
    core_artifacts = expected_core_artifacts_manifest()
    for rel in core_artifacts["json"] + core_artifacts["reports"]:
        if not (root / rel).is_file():
            raise FileNotFoundError(f"missing required core artifact: {rel}")

    present_opt = [
        {
            "check_passed": True,
            "name": str(opt["name"]),
            "script": str(opt["script"]),
        }
        for opt in optional_items
        if opt["present"]
    ]
    core_headline_summary = build_core_headline_summary(root)

    return _clean_json_value(
        {
            "schema_version": SCHEMA_VERSION,
            "tiers_version": TIERS_VERSION,
            "float_tolerance": FLOAT_TOL,
            "primary_seeds": PRIMARY_SEEDS,
            "primary_seeds_lock": PRIMARY_SEEDS_LOCK,
            "n_primary_seeds_per_tier": N_PRIMARY_SEEDS,
            "core_verifiers": core_manifest,
            "core_artifacts": core_artifacts,
            "optional_verifiers_registry": list(OPTIONAL_VERIFIER_NAMES),
            "present_optional_verifiers": present_opt,
            "present_eval_v14_artifacts": list_present_eval_v14_artifacts(root, index_path),
            "core_headline_summary": core_headline_summary,
        }
    )


def _fmt_pct_ci(ratio: float, ci: list[float] | None, is_ref: bool = False) -> str:
    if is_ref:
        return "100% (ref)"
    if ci is None:
        return f"{ratio:.0%}"
    return f"{ratio:.0%} [{ci[0]:.0%}, {ci[1]:.0%}]"


def _fmt_p(p: float, is_ref: bool = False) -> str:
    if is_ref:
        return "--"
    if p < 1e-4:
        return "<1e-4"
    return f"{p:.4f}"


def render_overview_md(core_summary: dict[str, Any]) -> str:
    cm = core_summary["claims_and_hygiene"]
    hgt = core_summary["headline_gap_table"]
    ver = hgt["verification"]
    coh = hgt["cohorts"]
    ht = core_summary["harness_and_tier_2x2"]
    jrp = core_summary["judge_rerun_power"]
    ha = core_summary["hint_ablation"]

    oc_h = coh["hard_opencode_gemini_4_carbon"]
    oc_h0 = coh["hard_opencode_gemini_4_carbon_0imputed"]
    ip_h = coh["hard_inproc_gemini_4_carbon"]
    fl_h = coh["hard_opencode_gemini_3_5_flash"]
    sv_h = coh["hard_solver"]
    gt_h = coh["hard_grok_tactics"]
    dn_h = coh["hard_do_nothing"]
    g1_h = coh["hard_guess_day1"]

    oc_m = coh["medium_opencode_gemini_4_carbon"]
    ip_m = coh["medium_inproc_gemini_4_carbon"]
    sv_m = coh["medium_solver"]

    raw_med = ht["raw_oc_minus_ip_medium"]
    raw_hard = ht["raw_oc_minus_ip_hard"]
    raw_did = ht["raw_did_hard_minus_medium"]
    la_med = ht["luck_adjusted_oc_minus_ip_medium"]
    la_hard = ht["luck_adjusted_oc_minus_ip_hard"]
    la_did = ht["luck_adjusted_did_hard_minus_medium"]
    hm = ht["hard_mechanisms"]

    ma = jrp["opencode_carbon_model_a"]
    mb = jrp["opencode_carbon_model_b"]
    pk = jrp["pass_k_hard"]
    ora = cm["oracle_hard_k10"]

    ha_c = ha["arms"]["control"]
    ha_p = ha["arms"]["premature_accusation"]
    ha_d = ha["arms"]["decoy_chase"]
    vc_p = ha["paired_vs_control"]["premature_accusation"]
    vc_d = ha["paired_vs_control"]["decoy_chase"]
    ha_seeds = ha["seeds"]
    ha_seed_lbl = f"{ha_seeds[0]}-{ha_seeds[-1]}"
    rm = core_summary.get("repo_milestones") or {}
    g1_ext = rm.get("g1_partial_extension")
    lad_canon = rm.get("canonical_gemini_ladder")
    gpt55_pre = rm.get("gpt_5_5_preregistration") or {}

    if lad_canon is not None:
        ladder_clause = (
            f"and `{lad_canon['episodes']}` canonical Gemini thinking-ladder episodes across "
            f"`{lad_canon['cells']}` cells (`eb363eb9`, plus `{lad_canon['gemma_episodes']}` Gemma episodes in "
            f"`results/gemini/ladder.json`; `{ver['ladder_cached_episodes_replayed']}` local archive episodes step-replayed)"
        )
    else:
        ladder_clause = (
            f"and `{ver['ladder_cached_episodes_replayed']}` native multi-model thinking-ladder episodes "
            f"(`{ver['ladder_total_reported_episodes']}` total reported across `{ver['ladder_total_reported_cells']}` cells)"
        )

    lines: list[str] = [
        H1 + "Canary v1.4 Evaluation Suite: One-Command Verification & Evidence Map",
        "",
        f"**Scope.** Rules `{TIERS_VERSION}`, post-hoc locked paired dev seeds `{PRIMARY_SEEDS}` (`671ed96`, 28 s after `8fd4dec`; `n = {N_PRIMARY_SEEDS}` per tier on every primary Section A row; lock against later reruns and cherry-picking, not a pre-registration), 100% deterministic offline `canary.env.Env(tier, seed)` replay verification (`0` live LLM calls, `0` API keys, single-process, `1bc3e281` `data.detail` step-replay compatible).",
        "",
        "```bash",
        "python scripts/run_all_eval_checks.py --check",
        "python scripts/run_all_eval_checks.py",
        "make reproduce",
        "```",
        "",
        H2 + "1. Master Verifier & Artifact Index (`results/eval_v14/eval_suite_index.json`)",
        "",
        "| Module | Keyless Check Command | JSON Artifact | Report Artifact |",
        "|---|---|---|---|",
        "| Master Suite Orchestrator | `python scripts/run_all_eval_checks.py --check` | `results/eval_v14/eval_suite_index.json` | `docs/reports/eval_suite_overview.md` |",
    ]

    for spec in CORE_VERIFIERS:
        lines.append(
            f"| {spec['title']} | `python {spec['script']} --check` | `{spec['json_artifact']}` | `{spec['report_artifact']}` |"
        )

    opt_list_str = ", ".join(f"`{name}.py`" for name in OPTIONAL_VERIFIER_NAMES)
    lines.extend(
        [
            "",
            f"- **Auto-discovered sibling `--check` modules:** `run_all_eval_checks.py --check` also discovers and verifies any present sibling scripts among {opt_list_str} while keeping `core_headline_summary` pinned to the 5 deterministic core JSON artifacts (`tol = 1e-9`).",
            "",
            H2 + "2. Headline Gap Table (Post-Hoc Locked Paired Seeds `0-29`, `n = 30` per Tier, Replay-Verified)",
            "",
            f"- **Primary `n = 30` Hard headline (raw first, luck-adjusted second):** OpenCode + `gemini-4-carbon` over MCP scores **`{_fmt_pct_ci(oc_h['ratio'], oc_h['ratio_ci'])}`** of the reference solver raw (`{oc_h['mean']:+.3f} +/- {oc_h['score_ci']:.3f}` vs `{sv_h['mean']:+.3f} +/- {sv_h['score_ci']:.3f}`) and **`{_fmt_pct_ci(oc_h['luck_adj_ratio'], oc_h['luck_adj_ci'])}`** luck-adjusted (`{oc_h['luck_adjusted_score']:+.3f}` vs `{sv_h['luck_adjusted_score']:+.3f}`, `p_luck = {_fmt_p(oc_h['p_wilcoxon_luck'])}`). Reference solver seeds `0-29` come from two committed directories (`solver-hard-20261114-121126` seeds `0-19` + `solver-hard-seeds20to29` seeds `20-29`); Hard's canary clearance rule never binds (`docs/DIFFICULTY.md` W4).",
            f"- **Replay corpus:** Recomputed with `{hgt['bootstrap_resamples']:,}` paired bootstrap resamples (`rng_seed = 0`) across `{ver['frontier_cached_episodes_replayed']}` primary frontier episodes, `{ver['stored_solver_episodes_replayed']}` stored reference solver episodes, `{ver['inproc_baseline_episodes_verified']}` scripted baseline episodes, {ladder_clause} with **zero** `Env` score, accusation, or tool-output mismatches (`1bc3e281` `invalid arguments` `data.detail` rule enforced for pre-`1bc3e281` transcripts).",
            "",
            "| Tier | Cohort (`n = 30`, seeds `0-29`) | Raw Score +/- 95% CI | Raw / Solver `[95% CI]` | Luck-Adj Score | Luck-Adj / Solver `[95% CI]` | `p_luck` (Wilcoxon) | Cal. `pass^3` | Winnable / Solver `[95% CI]` |",
            "|---|---|---:|---|---:|---|---:|---:|---|",
        ]
    )

    table_rows: list[tuple[str, str, dict[str, Any], bool]] = [
        ("hard", "OpenCode + gemini-4-carbon (judges' MCP)", oc_h, False),
        ("hard", "OpenCode + gemini-4-carbon (0-imputed sens.)", oc_h0, False),
        ("hard", "in-process gemini-4-carbon (full history)", ip_h, False),
        ("hard", "OpenCode + gemini-3.5-flash (judges' MCP)", fl_h, False),
    ]
    if "hard_opencode_gpt_5_5" in coh:
        table_rows.append(("hard", "OpenCode + gpt-5.5 (judges' MCP)", coh["hard_opencode_gpt_5_5"], False))
    table_rows.extend(
        [
            ("hard", "reference solver (Harbor oracle)", sv_h, True),
            ("hard", "grok_tactics (scripted baseline)", gt_h, False),
            ("hard", "do_nothing / stop_early (zero baseline)", dn_h, False),
            ("hard", "guess_day1 (day-1 guess baseline)", g1_h, False),
            ("medium", "OpenCode + gemini-4-carbon (judges' MCP)", oc_m, False),
            ("medium", "in-process gemini-4-carbon (full history)", ip_m, False),
        ]
    )
    if "medium_opencode_gemini_3_5_flash" in coh:
        table_rows.append(("medium", "OpenCode + gemini-3.5-flash (judges' MCP)", coh["medium_opencode_gemini_3_5_flash"], False))
    table_rows.append(("medium", "reference solver (Harbor oracle)", sv_m, True))

    for tier_lbl, label, r, is_ref in table_rows:
        lines.append(
            f"| `{tier_lbl}` | {label} | `{r['mean']:+.3f} +/- {r['score_ci']:.3f}` | "
            f"`{_fmt_pct_ci(r['ratio'], r['ratio_ci'], is_ref)}` | `{r['luck_adjusted_score']:+.3f}` | "
            f"`{_fmt_pct_ci(r['luck_adj_ratio'], r['luck_adj_ci'], is_ref)}` | "
            f"`{_fmt_p(r['p_wilcoxon_luck'], is_ref)}` | `{r['pass3_calibrated']:.3f}` | "
            f"`{_fmt_pct_ci(r['winnable_ratio'], r['winnable_ratio_ci'], is_ref)}` |"
        )

    lines.append("")
    if g1_ext is not None:
        g1_e = g1_ext["ext_only"]
        g1_p = g1_ext["pooled_0_59"]
        g1_seeds_s = ", ".join(str(s) for s in g1_e["seeds"])
        lines.append(
            f"- **Pre-registered G1 extension (`{g1_ext['prereg_commit']}`, data `{g1_ext['data_commit']}`, stopped early for rehearsal quota):** "
            f"`n = {g1_e['n']}` completed valid OpenCode `gemini-4-carbon` hard episodes (`seeds = [{g1_seeds_s}]`, "
            f"`{g1_e['mean']:+.3f} +/- {g1_e['ci']:.3f}` vs solver `{g1_e['solver_same_seeds']:+.3f}`, "
            f"raw `{_fmt_pct_ci(g1_e['ratio'], g1_e['ratio_ci'])}`, luck-adjusted `{_fmt_pct_ci(g1_e['luck_adj_ratio'], g1_e['luck_adj_ci'])}`); "
            f"pooled `n = {g1_p['n']}` (`0-29` + `[{g1_seeds_s}]`) is **`{_fmt_pct_ci(g1_p['ratio'], g1_p['ratio_ci'])}`** raw "
            f"(`{g1_p['mean']:+.3f} +/- {g1_p['ci']:.3f}` vs solver `{g1_p['solver_same_seeds']:+.3f}`, paired diff `{g1_p['diff']:+.3f} +/- {g1_p['diff_ci']:.3f}`) "
            f"and **`{_fmt_pct_ci(g1_p['luck_adj_ratio'], g1_p['luck_adj_ci'])}`** luck-adjusted (`make reproduce` pools `n = 32` OpenCode and `n = 60` solver in `judge_table.md`, while `HEADLINE` recomputes locked `n = 30`)."
        )
    gpt55_state = (
        "committed directory `data/runs/committed/v1.4/opencode-gpt-5.5` present"
        if gpt55_pre.get("committed_dir_present")
        else "pre-registered before any episode (`data/runs/committed/v1.4/opencode-gpt-5.5` auto-included if committed)"
    )
    lines.append(
        f"- **Pre-registered second frontier family (`{gpt55_pre.get('commit', 'cf394894')}`):** `gpt-5.5` via OpenCode 1.19.5 over MCP on `v1.4` hard seeds `{gpt55_pre.get('seeds', '0-29')}` (env tag `{gpt55_pre.get('env_tag', 'afterquery-final')}`, stop `{gpt55_pre.get('stop_time_eet', '08:15')}` Helsinki / `${gpt55_pre.get('spend_cap_usd', 200)}` cap; {gpt55_state})."
    )
    hr_final = rm.get("harbor_rehearsal_final") or {}
    if hr_final.get("table_present"):
        lines.append(
            f"- **Harbor judge-path rehearsal (`{hr_final.get('commit', 'c59ecfd0')}`, `results/harbor/rehearsal/TABLE.md`, tag `{hr_final.get('env_tag', 'afterquery-final')}` `1bc3e281`):** "
            "Harbor 0.26.0 + OpenCode + `gemini-4-carbon` across `3` runs on `10` hard judge tasks (`900000-900009`; shell enabled in container, used in `20/28` trials) scored `+0.472` (`93%`), `+0.585` (`116%`), and `+0.656` (`153%`, partial `n = 7` valid) vs same-task oracle `+0.506` / `+0.429` (`do_nothing = stop_early = +0.000`); the `65%` MCP-only gap did **not** reproduce in the Harbor judge path."
        )

    lines.extend(
        [
            "",
            H2 + "3. 2x2 Harness x Tier Crossover & Noisy-Bayes Mechanism (`180` Paired Episodes)",
            "",
            f"- **Statistically significant crossover (`(OC_hard - IP_hard) - (OC_med - IP_med)`):** OpenCode beats In-Process on Medium (`{raw_med['point']:+.3f} [{raw_med['boot_ci95'][0]:+.3f}, {raw_med['boot_ci95'][1]:+.3f}]` raw, `p = {raw_med['p_boot_two_sided']:.4f}`; `{la_med['point']:+.3f} [{la_med['boot_ci95'][0]:+.3f}, {la_med['boot_ci95'][1]:+.3f}]` luck-adjusted, `p = {la_med['p_boot_two_sided']:.4f}`), whereas In-Process beats OpenCode on Hard (`OC - IP = {raw_hard['point']:+.3f} [{raw_hard['boot_ci95'][0]:+.3f}, {raw_hard['boot_ci95'][1]:+.3f}]` raw; `{la_hard['point']:+.3f} [{la_hard['boot_ci95'][0]:+.3f}, {la_hard['boot_ci95'][1]:+.3f}]` luck-adjusted). Paired Difference-in-Differences is **`{raw_did['point']:+.3f} [{raw_did['boot_ci95'][0]:+.3f}, {raw_did['boot_ci95'][1]:+.3f}]`** raw (`p = {raw_did['p_boot_two_sided']:.4f}`, indep-tier CI `[{raw_did['boot_ci95_indep_tiers'][0]:+.3f}, {raw_did['boot_ci95_indep_tiers'][1]:+.3f}]`) and **`{la_did['point']:+.3f} [{la_did['boot_ci95'][0]:+.3f}, {la_did['boot_ci95'][1]:+.3f}]`** luck-adjusted (`p = {la_did['p_boot_two_sided']:.4f}`, indep-tier CI `[{la_did['boot_ci95_indep_tiers'][0]:+.3f}, {la_did['boot_ci95_indep_tiers'][1]:+.3f}]`), excluding zero on both metrics.",
            f"- **Shared Hard exploration bottleneck + 5% flip trap:** Both OpenCode and In-Process severely under-use the 2-canary/day pipeline on Hard (`{hm['opencode']['canaries_before_accuse_mean']:.2f}` and `{hm['inproc']['canaries_before_accuse_mean']:.2f}` canaries = `{hm['opencode']['canary_capacity_used_share']:.0%}` and `{hm['inproc']['canary_capacity_used_share']:.0%}` capacity vs Solver's `{hm['solver']['canaries_before_accuse_mean']:.2f}` = `{hm['solver']['canary_capacity_used_share']:.0%}`) while spending `{hm['opencode']['interviews_mean']:.1f}` and `{hm['inproc']['interviews_mean']:.1f}` calls on near-zero-KL interviews (Solver: `{hm['solver']['interviews_mean']:.1f}`). Under `95%` fingerprint accuracy (`5%` variant flip), OpenCode's strict set elimination falls into false singleton traps (`{hm['opencode']['wrong_count']}` wrong accusations, mean `P(accused) = {hm['opencode']['p_accused_mean']:.3f}`), whereas In-Process (`thought_signature_replay`) tracks noisy likelihoods (`{hm['inproc']['wrong_count']}` wrong, mean `P(accused) = {hm['inproc']['p_accused_mean']:.3f}`) and recovers the true culprit on `{hm['inproc']['consistent_eq_0_at_accuse']}` episodes where subsequent leaks drove the noiseless consistent set to `|C| = 0`.",
            "",
            H2 + f"4. `1x10` vs `3x10` Judge Rerun Power, Rao-Blackwell & `pass^3` (`{jrp['n_trials']:,}` MC Trials)",
            "",
            f"- **Harbor 10-task hard oracle band (`{ora['builds']}` synthetic secrets):** 90% range **`{ora['p5']:+.2f}` to `{ora['p95']:+.2f}`** (mean `{ora['mean']:+.3f}`, SD `{ora['sd']:.3f}`). One flipped hard accusation swings a 10-task mean by `(1 + V)/10 = {jrp['opencode_carbon_wrong_swing_10task']:.3f} V` (`opencode-carbon`; `{jrp['solver_wrong_swing_10task']:.3f} V` `solver`, `~0.16 V` per flipped task).",
            f"- **`3x10` paired judge power (`opencode-carbon < oracle`):** Pooling `R = 3` frontier runs cuts paired gap SD by `sqrt(3) = {mb['luck_noise_sd_reduction_r1_to_r3']:.3f}x` (`{ma['raw_r1_sd']:.3f} -> {ma['raw_r3_sd']:.3f}` raw; `{ma['la_r1_sd']:.3f} -> {ma['la_r3_sd']:.3f}` luck-adjusted) and raises `P(frontier_mean < oracle_mean)` from `{ma['raw_r1_p_lt_oracle']:.1%}` (`1x10`) to **`{ma['raw_r3_p_lt_oracle']:.1%}`** (`3x10`) raw and **`{ma['la_r3_p_lt_oracle']:.1%}`** luck-adjusted under empirical paired resampling (Model A), and from `{mb['r1_p_lt_oracle']:.1%}` to **`{mb['r3_p_lt_oracle']:.1%}`** on a single fixed 10-world Harbor build (Model B, within-build run-mean SD `{mb['within_build_1run_sd']:.3f} V -> {mb['within_build_3run_mean_sd']:.3f} V`).",
            f"- **Rao-Blackwell luck-adjusted variance reduction (`>3x`):** Conditional accusation coin-flip noise accounts for **`{mb['frontier_luck_share_of_r1_var']:.1%}`** of `opencode-carbon`'s `1x10` gap variance (`{mb['all_luck_share_of_r1_var']:.1%}` including oracle 5%-flip risk). Scoring by exact solver-posterior expectation `P * V - (1 - P)` cuts estimator variance by **`{ma['empirical_paired_var_reduction_factor']:.2f}x`** empirically (`n_eff = {ma['effective_n_at_k10']:.1f}` at `k = 10`) and **`{mb['la_var_reduction_vs_raw_r1']:.2f}x`** analytically under Model B (`n_eff = {mb['effective_n_at_k10']:.1f}`, `{mb['la_var_reduction_vs_raw_r3']:.2f}x` even vs `3x10` raw).",
            f"- **`pass^3` exposes lucky horizon gamblers (`gemini-3.5-flash` collapse):** `opencode-3.5-flash` scored `+0.373` raw (`0.900` empirical accuracy) only via `{jrp['flash_3_5_realised_luck_mean']:+.3f} V/ep` of windfall across `{pk['opencode-3.5-flash']['n_gamble_worlds_lt60']}` low-posterior (`P < 0.60`) gambles. Posterior-calibrated `pass^3 = E[P_win^3]` collapses `3.5-flash` to **`{pk['opencode-3.5-flash']['pass_3']:.3f}`** (`[{pk['opencode-3.5-flash']['pass_3_ci95'][0]:.3f}, {pk['opencode-3.5-flash']['pass_3_ci95'][1]:.3f}]`, and **`{pk['opencode-3.5-flash']['gamble_pass_3']:.3f}`** on its `10` gamble worlds; Model B `3x10` `P(F < O) = {jrp['flash_3_5_model_b_r3_p_lt_oracle']:.1%}`), ranking strictly: `solver ({pk['solver']['pass_3']:.3f}) > inproc-carbon ({pk['inproc-carbon']['pass_3']:.3f}) > opencode-carbon ({pk['opencode-carbon']['pass_3']:.3f}) > opencode-3.5-flash ({pk['opencode-3.5-flash']['pass_3']:.3f})`.",
            "",
            H2 + f"5. Fact-Only Hint Ablation Causal Audit (`v1.4` Hard, Paired Seeds `{ha_seed_lbl}`)",
            "",
            f"- **Replay & mechanism shifts (`{ha['ablation_episodes_verified']}/30` ablation + `{ha['context_episodes_verified']}/30` context episodes, `{ha['total_steps_verified']}` step-verified tool calls, `{ha['step_mismatches']}` mismatches):** Appending single-sentence rule reminders (`HINTS_V2`) to in-process `gemini-4-carbon` shifts mechanism cleanly: `premature_accusation` (`{ha_p['score_mean']:+.3f} +/- {ha_p['score_ci95']:.3f}` raw, `{ha_p['luck_adjusted_mean']:+.3f}` LA vs `control` `{ha_c['score_mean']:+.3f} +/- {ha_c['score_ci95']:.3f}` raw, `{ha_c['luck_adjusted_mean']:+.3f}` LA) eliminates negative-EV gambles (`{ha_c['ev_negative_gamble_count']} -> {ha_p['ev_negative_gamble_count']}`, `P(accused)` `{ha_c['p_accused_mean']:.3f} -> {ha_p['p_accused_mean']:.3f}`, interviews `{vc_p['interviews_diff_mean']:+.1f} [{vc_p['interviews_diff_boot_ci95'][0]:+.1f}, {vc_p['interviews_diff_boot_ci95'][1]:+.1f}]`); `decoy_chase` (`{ha_d['score_mean']:+.3f} +/- {ha_d['score_ci95']:.3f}` raw, `{ha_d['luck_adjusted_mean']:+.3f}` LA; paired diff vs `control` `{vc_d['score_diff_mean']:+.3f} [{vc_d['score_diff_boot_ci95'][0]:+.3f}, {vc_d['score_diff_boot_ci95'][1]:+.3f}]` raw, `{vc_d['luck_adjusted_diff_mean']:+.3f} [{vc_d['luck_adjusted_diff_boot_ci95'][0]:+.3f}, {vc_d['luck_adjusted_diff_boot_ci95'][1]:+.3f}]` LA) raises day-1 canary planting (`{ha_c['day1_canary_count']}/10 -> {ha_d['day1_canary_count']}/10`) and cuts interviews (`{vc_d['interviews_diff_mean']:+.1f} [{vc_d['interviews_diff_boot_ci95'][0]:+.1f}, {vc_d['interviews_diff_boot_ci95'][1]:+.1f}]`). At `n = {ha_c['n']}`, paired score 95% CIs straddle `0.000` (unhinted `inproc` replicate on `{ha_seed_lbl}`: `{ha['inproc_no_hint_context']['score_mean']:+.3f}` raw / `{ha['inproc_no_hint_context']['luck_adjusted_mean']:+.3f}` LA, vs `solver` `{ha['solver_same_seeds_context']['score_mean']:+.3f}` / `{ha['solver_same_seeds_context']['luck_adjusted_mean']:+.3f}`), so we claim causal mechanism shifts rather than `n = 10` score significance (the separate pre-registered OpenCode `--hint gather` protocol in `docs/reports/gap.md` `fd8c1cb0` was stopped before `05:40` to preserve shared Gemini quota for the Harbor rehearsal).",
            "",
            H2 + "6. 5-Gate Claims, Version & Protected-Path Hygiene (`claims_manifest.json`)",
            "",
            f"- **All `{cm['gates_passed_count']}/{cm['gate_count']}` deterministic gates PASS (`{cm['total_violations']}` violations):** Gate 1 cross-checks `README.md`, `docs/reports/gap.md`, `results/judge_table.md`, and `{cm['committed_paired_rows_verified']}` committed `paired_table_gemini.json` rows within `1e-9`; Gate 2 verifies seed completeness (`0..29`, `0` duplicates) and 100% `Env` step replay; Gate 3 confirms `do_nothing` (`{cm['hard_baselines']['do_nothing_score_ci']}`) and `stop_early` (`{cm['hard_baselines']['stop_early_score_ci']}`) equal `0.0` while `guess_day1` averages `{cm['hard_baselines']['guess_day1_300secret_mean']:+.3f}` (max `{cm['hard_baselines']['guess_day1_300secret_max']:+.2f} < 0`) across `300` fresh judge secrets; Gate 4 enforces zero `v1.2`/`v1.3`/`superseded` mixing across `{cm['hygiene']['v14_meta_files_checked']}` `v1.4` meta files and `{cm['hygiene']['active_docs_checked_count']}` active docs (`PRIMARY` post-hoc seed lock `671ed96` vs `REPLICATION` and pre-registered `EXTENSION` `f9fb7a4a` / `cf394894` verified); Gate 5 enforces all `{cm['hygiene']['protected_path_rules_count']}` `.github/protected-paths.txt` rules and `{cm['hygiene']['secret_pattern_rules_count']}` secret/mole-leak pattern classes across `results/eval*` and `docs/reports/`.",
            "",
        ]
    )
    return _norm_ascii("\n".join(lines))


def _scan_text_hygiene(label: str, text: str) -> list[str]:
    errs: list[str] = []
    if EN_DASH in text or EM_DASH in text:
        errs.append(f"{label}: contains unicode en/em dash")
    for pat_name, rx in SECRET_AND_LEAK_PATTERNS:
        if rx.search(text):
            errs.append(f"{label}: forbidden {pat_name} pattern detected")
    return errs


def verify_suite_artifacts(
    root: Path,
    index_path: Path,
    overview_path: Path,
) -> list[str]:
    errors: list[str] = []
    if not index_path.is_file():
        errors.append(f"missing suite index JSON: {index_path}")
    if not overview_path.is_file():
        errors.append(f"missing suite overview Markdown: {overview_path}")
    if errors:
        return errors

    raw_index_bytes = index_path.read_bytes()
    if len(raw_index_bytes) >= MAX_INDEX_BYTES:
        errors.append(f"{index_path} size {len(raw_index_bytes)} bytes >= {MAX_INDEX_BYTES} byte limit")

    try:
        index_text = raw_index_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"{index_path}: invalid UTF-8 ({exc})"]
    overview_text = overview_path.read_text(encoding="utf-8")

    errors.extend(_scan_text_hygiene(str(index_path), index_text))
    errors.extend(_scan_text_hygiene(str(overview_path), overview_text))

    try:
        stored = json.loads(index_text)
    except ValueError as exc:
        return errors + [f"{index_path}: invalid JSON ({exc})"]
    if not isinstance(stored, dict):
        return errors + [f"{index_path}: root value must be a JSON object"]

    expected_core_artifacts = expected_core_artifacts_manifest()
    for rel in expected_core_artifacts["json"] + expected_core_artifacts["reports"]:
        if not (root / rel).is_file():
            errors.append(f"missing required core artifact on disk: {rel}")
    if errors:
        return errors

    try:
        fresh_core_summary = build_core_headline_summary(root)
    except (FileNotFoundError, KeyError, ValueError, TypeError) as exc:
        return errors + [f"failed to recompute core_headline_summary from 5 core JSONs: {exc}"]

    if stored.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version mismatch: got {stored.get('schema_version')!r}, expected {SCHEMA_VERSION!r}")
    if stored.get("tiers_version") != TIERS_VERSION:
        errors.append(f"tiers_version mismatch: got {stored.get('tiers_version')!r}, expected {TIERS_VERSION!r}")
    if not approx_equal(stored.get("float_tolerance"), FLOAT_TOL, tol=FLOAT_TOL):
        errors.append(f"float_tolerance mismatch: got {stored.get('float_tolerance')!r}")
    if stored.get("primary_seeds") != PRIMARY_SEEDS:
        errors.append(f"primary_seeds mismatch: got {stored.get('primary_seeds')!r}")
    if stored.get("primary_seeds_lock") != PRIMARY_SEEDS_LOCK:
        errors.append(f"primary_seeds_lock mismatch: got {stored.get('primary_seeds_lock')!r}")
    if stored.get("n_primary_seeds_per_tier") != N_PRIMARY_SEEDS:
        errors.append(f"n_primary_seeds_per_tier mismatch: got {stored.get('n_primary_seeds_per_tier')!r}")

    if stored.get("core_verifiers") != expected_core_verifiers_manifest():
        errors.append("core_verifiers manifest in eval_suite_index.json does not match canonical 5 core verifiers")
    if stored.get("core_artifacts") != expected_core_artifacts:
        errors.append("core_artifacts manifest in eval_suite_index.json does not match canonical core artifacts")
    if stored.get("optional_verifiers_registry") != list(OPTIONAL_VERIFIER_NAMES):
        errors.append("optional_verifiers_registry in eval_suite_index.json does not match canonical registry")

    stored_opt = stored.get("present_optional_verifiers")
    if not isinstance(stored_opt, list):
        errors.append("present_optional_verifiers must be a list")
    else:
        for entry in stored_opt:
            if not isinstance(entry, dict):
                errors.append(f"invalid entry in present_optional_verifiers: {entry!r}")
                continue
            nm = entry.get("name")
            sc = entry.get("script")
            if nm not in OPTIONAL_VERIFIER_NAMES or sc != f"scripts/{nm}.py" or entry.get("check_passed") is not True:
                errors.append(f"malformed present_optional_verifiers entry: {entry!r}")
            elif not (root / sc).is_file():
                errors.append(f"indexed optional verifier missing on disk: {sc}")

    stored_present_files = stored.get("present_eval_v14_artifacts")
    if not isinstance(stored_present_files, list) or stored_present_files != sorted(stored_present_files):
        errors.append("present_eval_v14_artifacts must be a sorted list")
    else:
        for rel_f in stored_present_files:
            if not isinstance(rel_f, str) or not (root / rel_f).is_file():
                errors.append(f"indexed eval_v14 artifact missing on disk: {rel_f!r}")

    if not approx_equal(stored.get("core_headline_summary"), fresh_core_summary, tol=FLOAT_TOL):
        errors.append(
            f"{index_path} core_headline_summary differs from 5 core JSON artifacts beyond tol={FLOAT_TOL}"
        )

    expected_md = render_overview_md(fresh_core_summary)
    if overview_text != expected_md:
        errors.append(f"{overview_path} differs from deterministic render_overview_md(core_headline_summary)")

    return errors


_LEAF_LIST_RE = re.compile(r"\[\n(?:\s*(?:null|true|false|-?\d+(?:\.\d+)?(?:e[+-]?\d+)?|\"[^\"\n\\]*\"),?\n)+\s*\]")


def serialize_index_json(data: dict[str, Any]) -> str:
    raw = json.dumps(data, indent=1, sort_keys=False, ensure_ascii=True)
    collapsed = _LEAF_LIST_RE.sub(
        lambda m: re.sub(r"\s*\n\s*", " ", m.group(0)).replace("[ ", "[").replace(" ]", "]"),
        raw,
    )
    return collapsed + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="One-command keyless Canary v1.4 evaluation suite orchestrator and judge verification index."
    )
    ap.add_argument("--check", action="store_true", help="Run verifier --check suite and verify index + overview")
    ap.add_argument("--list", action="store_true", help="List core and optional sibling verifiers without running")
    ap.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="NAME",
        help="Run only specified verifier(s) (repeatable or comma-separated)",
    )
    ap.add_argument(
        "--skip-artifact-check",
        action="store_true",
        help="Skip eval_suite_index.json and eval_suite_overview.md check when combined with --check --only",
    )
    ap.add_argument(
        "--artifacts-only",
        action="store_true",
        help="Generate or --check eval_suite_index.json and eval_suite_overview.md without running child scripts",
    )
    ap.add_argument("--root", default=str(ROOT), help="Repository root directory")
    ap.add_argument("--out-json", default=None, help="Override path to eval_suite_index.json")
    ap.add_argument("--out-md", default=None, help="Override path to eval_suite_overview.md")
    ap.add_argument("--python", default=None, help="Python interpreter for child --check scripts")
    ap.add_argument("--timeout", type=int, default=300, help="Per-verifier timeout in seconds")
    ap.add_argument("--json", action="store_true", help="Print JSON summary to stdout")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    index_path = Path(args.out_json).resolve() if args.out_json else (root / DEFAULT_INDEX_REL)
    overview_path = Path(args.out_md).resolve() if args.out_md else (root / DEFAULT_OVERVIEW_REL)

    core_items, optional_items = discover_verifiers(root)

    if args.list:
        if args.json:
            payload = {
                "core_verifiers": core_items,
                "optional_verifiers": optional_items,
            }
            print(json.dumps(payload, indent=2, ensure_ascii=True))
        else:
            for item in core_items:
                st = "present" if item["present"] else "MISSING"
                print(f"[core:{st}] {item['name']} ({item['script']})")
            for item in optional_items:
                st = "present" if item["present"] else "absent"
                print(f"[optional:{st}] {item['name']} ({item['script']})")
        return 0

    only_names = parse_only_specs(args.only)
    run_results: list[dict[str, Any]] = []
    errors: list[str] = []

    if not args.artifacts_only:
        selected, sel_errors = select_verifiers(core_items, optional_items, only_names)
        errors.extend(sel_errors)
        if not errors:
            for item in selected:
                res = run_verifier_check(root, item, python_exe=args.python, timeout_s=args.timeout)
                run_results.append(res)
                if not res["passed"]:
                    errors.append(
                        f"verifier failed (rc={res['returncode']}): {res['script']} --check"
                        + (f" | {res['stderr']}" if res["stderr"] else "")
                    )

    if args.check:
        if not (only_names and args.skip_artifact_check):
            errors.extend(verify_suite_artifacts(root, index_path, overview_path))
    elif not only_names and not errors:
        try:
            suite_index = build_suite_index(root, index_path)
            index_blob = serialize_index_json(suite_index)
            encoded = index_blob.encode("ascii")
            if len(encoded) >= MAX_INDEX_BYTES:
                errors.append(
                    f"generated index size {len(encoded)} bytes >= {MAX_INDEX_BYTES} byte limit"
                )
            else:
                overview_blob = render_overview_md(suite_index["core_headline_summary"])
                hygiene_errs = _scan_text_hygiene(str(index_path), index_blob) + _scan_text_hygiene(
                    str(overview_path), overview_blob
                )
                if hygiene_errs:
                    errors.extend(hygiene_errs)
                else:
                    index_path.parent.mkdir(parents=True, exist_ok=True)
                    overview_path.parent.mkdir(parents=True, exist_ok=True)
                    index_path.write_bytes(encoded)
                    overview_path.write_text(overview_blob, encoding="utf-8")
                    errors.extend(verify_suite_artifacts(root, index_path, overview_path))
        except (OSError, FileNotFoundError, KeyError, ValueError, TypeError) as exc:
            errors.append(f"failed to generate suite index/overview: {exc}")

    overall_ok = not errors
    if args.json:
        out_payload = {
            "passed": overall_ok,
            "mode": "check" if args.check else ("only" if only_names else "generate"),
            "verifiers_ran": [
                {
                    "name": r["name"],
                    "script": r["script"],
                    "required": r["required"],
                    "passed": r["passed"],
                    "returncode": r["returncode"],
                }
                for r in run_results
            ],
            "errors": errors,
            "index_path": str(index_path),
            "overview_path": str(overview_path),
        }
        print(json.dumps(out_payload, indent=2, ensure_ascii=True))
    else:
        for r in run_results:
            tag = "PASS" if r["passed"] else "FAIL"
            kind_lbl = "core" if r["required"] else "optional"
            print(f"[{tag}] ({kind_lbl}) {r['name']}: {r['script']} --check ({r['elapsed_s']:.2f}s)")
            if not r["passed"]:
                if r["stdout"]:
                    print(f"  STDOUT: {r['stdout']}")
                if r["stderr"]:
                    print(f"  STDERR: {r['stderr']}")
        for err in errors:
            print(f"[FAIL] {err}", file=sys.stderr)
        verdict = "PASS" if overall_ok else "FAIL"
        if args.check:
            print(f"EVAL SUITE CHECK: {verdict} ({len(run_results)} verifier(s) checked)")
        elif only_names:
            print(f"EVAL VERIFIER SUBSET: {verdict} ({len(run_results)} verifier(s) checked)")
        elif overall_ok:
            sz_kb = index_path.stat().st_size / 1024.0
            print(
                f"EVAL SUITE GENERATED: {verdict} ({len(run_results)} verifier(s) checked; "
                f"wrote {index_path.relative_to(root) if index_path.is_relative_to(root) else index_path} "
                f"[{sz_kb:.1f} KB] and "
                f"{overview_path.relative_to(root) if overview_path.is_relative_to(root) else overview_path})"
            )
        else:
            print(f"EVAL SUITE GENERATE: {verdict}", file=sys.stderr)

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
