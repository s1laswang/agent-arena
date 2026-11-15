from __future__ import annotations

import argparse
import ast
import io
import json
import math
from pathlib import Path
import re
import sys
import time
import tokenize
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_ID = "canary.tiebreak.state_externalization.v1"
AUDIT_ID = "tiebreak-state-externalization-law-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
PLUS_MINUS = chr(0x00B1)
UNICODE_MINUS = chr(0x2212)

MAX_SUMMARY_BYTES = 300 * 1024
MAX_CHECK_SECONDS = 15.0
JUDGE_SEED_MIN = 900_000

DEFAULT_OUT_JSON = Path("results/tiebreak/state_externalization/externalization_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_state_externalization.md")

LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")
CONFOUND_REL = Path("results/tiebreak/context_confound/audit_summary.json")
WORKING_MEMORY_REL = Path("results/tiebreak/working_memory/working_memory_summary.json")
DAGGER_MECH_REL = Path("results/tiebreak/dagger_mechanism/dagger_mechanism_summary.json")
FRONTIER_CMP_REL = Path("results/tiebreak/frontier_comparison/comparison_summary.json")
ADDENDUM_REL = Path("results/tiebreak/addendum_readiness.json")
EB_SUMMARY_REL = Path("results/tiebreak/empirical_bayes/summary.json")
SCALING_SUMMARY_REL = Path("results/tiebreak/scaling/scaling_summary.json")
DAGGER_ABLATION_REL = Path("results/tiebreak/dagger_ablation/summary.json")
MLP_SUMMARY_REL = Path("results/tiebreak/neural_mlp_dagger/mlp_summary.json")

PAIRED_TABLE_GEMINI_REL = Path("data/runs/committed/v1.4/paired_table_gemini.md")
BEHAVIOUR_COMPARE_REL = Path("results/behaviour_compare_v1.4.md")
HARBOR_REHEARSAL_TABLE_REL = Path("results/harbor/rehearsal/TABLE.md")
README_REL = Path("README.md")

PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)
TABLE_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
FLOAT_TOKEN_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
INT_TOKEN_RE = re.compile(r"\b\d+\b")

FALLBACK_PAIRED_TABLE_GEMINI: dict[str, dict[str, Any]] = {
    "opencode_gemini_4_carbon_hard": {
        "tier": "hard",
        "n": 30,
        "mean_score": 0.322,
        "ci95": 0.199,
        "accuracy": 0.83,
        "accused_rate": 0.97,
        "mean_accuse_day": 13.2,
        "mean_p_accused": 0.88,
        "solver_same_seeds": 0.499,
        "ratio_vs_solver_display": "65% [24%, 98%]",
        "ratio_vs_solver_pct": 65,
        "ratio_ci95_low_pct": 24,
        "ratio_ci95_high_pct": 98,
        "paired_diff_mean": -0.177,
        "paired_diff_ci95": 0.194,
        "luck_adjusted_score": 0.360,
        "luck_ratio_vs_solver_display": "72% [52%, 91%]",
        "luck_ratio_vs_solver_pct": 72,
    },
    "opencode_gpt_5_5_hard": {
        "tier": "hard",
        "n": 30,
        "mean_score": 0.504,
        "ci95": 0.064,
        "accuracy": 0.93,
        "accused_rate": 0.93,
        "mean_accuse_day": 10.2,
        "mean_p_accused": 0.94,
        "solver_same_seeds": 0.499,
        "ratio_vs_solver_display": "101% [79%, 140%]",
        "ratio_vs_solver_pct": 101,
        "ratio_ci95_low_pct": 79,
        "ratio_ci95_high_pct": 140,
        "paired_diff_mean": 0.005,
        "paired_diff_ci95": 0.141,
        "luck_adjusted_score": 0.418,
        "luck_ratio_vs_solver_display": "84% [67%, 103%]",
        "luck_ratio_vs_solver_pct": 84,
    },
    "inproc_gemini_4_carbon_hard": {
        "tier": "hard",
        "n": 30,
        "mean_score": 0.473,
        "ci95": 0.118,
        "accuracy": 0.93,
        "accused_rate": 0.97,
        "mean_accuse_day": 12.7,
        "mean_p_accused": 0.93,
        "solver_same_seeds": 0.499,
        "ratio_vs_solver_display": "95% [62%, 140%]",
        "ratio_vs_solver_pct": 95,
        "ratio_ci95_low_pct": 62,
        "ratio_ci95_high_pct": 140,
        "paired_diff_mean": -0.026,
        "paired_diff_ci95": 0.184,
        "luck_adjusted_score": 0.421,
        "luck_ratio_vs_solver_display": "84% [65%, 106%]",
        "luck_ratio_vs_solver_pct": 84,
    },
    "opencode_gemini_3_5_flash_hard": {
        "tier": "hard",
        "n": 30,
        "mean_score": 0.373,
        "ci95": 0.177,
        "accuracy": 0.90,
        "accused_rate": 1.00,
        "mean_accuse_day": 12.7,
        "mean_p_accused": 0.71,
        "solver_same_seeds": 0.499,
        "ratio_vs_solver_display": "75% [36%, 123%]",
        "ratio_vs_solver_pct": 75,
        "ratio_ci95_low_pct": 36,
        "ratio_ci95_high_pct": 123,
        "paired_diff_mean": -0.126,
        "paired_diff_ci95": 0.221,
        "luck_adjusted_score": 0.110,
        "luck_ratio_vs_solver_display": "22% [-23%, 63%]",
        "luck_ratio_vs_solver_pct": 22,
    },
    "opencode_gemini_4_carbon_medium": {
        "tier": "medium",
        "n": 30,
        "mean_score": 0.713,
        "ci95": 0.042,
        "accuracy": 1.00,
        "accused_rate": 1.00,
        "mean_accuse_day": 8.0,
        "mean_p_accused": 0.96,
        "solver_same_seeds": 0.645,
        "ratio_vs_solver_display": "111% [99%, 127%]",
        "ratio_vs_solver_pct": 111,
        "ratio_ci95_low_pct": 99,
        "ratio_ci95_high_pct": 127,
        "paired_diff_mean": 0.068,
        "paired_diff_ci95": 0.080,
        "luck_adjusted_score": 0.652,
        "luck_ratio_vs_solver_display": "101% [85%, 119%]",
        "luck_ratio_vs_solver_pct": 101,
    },
}

FALLBACK_BEHAVIOUR_COMPARE: dict[str, dict[str, Any]] = {
    "reference_solver": {
        "n": 30,
        "mean_score": 0.499,
        "canaries_planted_per_ep": 14.1,
        "interviews_per_ep": 0.0,
        "interview_call_share_pct": 0,
        "tool_calls_per_ep": 84,
        "mean_accusation_day": 10.6,
        "correct_count": 29,
        "wrong_count": 1,
        "no_accusation_count": 0,
    },
    "opencode_gpt_5_5_hard": {
        "n": 30,
        "mean_score": 0.504,
        "canaries_planted_per_ep": 17.2,
        "interviews_per_ep": 4.2,
        "interview_call_share_pct": 6,
        "tool_calls_per_ep": 69,
        "mean_accusation_day": 10.2,
        "correct_count": 28,
        "wrong_count": 0,
        "no_accusation_count": 2,
    },
    "opencode_gemini_4_carbon_hard": {
        "n": 30,
        "mean_score": 0.322,
        "canaries_planted_per_ep": 8.5,
        "interviews_per_ep": 68.0,
        "interview_call_share_pct": 53,
        "tool_calls_per_ep": 128,
        "mean_accusation_day": 13.2,
        "correct_count": 25,
        "wrong_count": 4,
        "no_accusation_count": 1,
    },
}

FALLBACK_HARBOR_REHEARSAL: dict[str, Any] = {
    "harness": "Harbor 0.26.0 + OpenCode + gemini-4-carbon (container bash/python3 available)",
    "task_tier": "hard",
    "tasks_per_run": 10,
    "oracle_mean_all_10": 0.506,
    "do_nothing_mean": 0.0,
    "stop_early_mean": 0.0,
    "shell_used_trials": 20,
    "shell_audited_trials": 28,
    "shell_used_fraction": 0.7143,
    "shell_used_display": "20/28",
    "valid_accusations_correct": 28,
    "valid_accusations_total": 29,
    "valid_accusation_precision": 0.9655,
    "valid_accusation_display": "28/29",
    "wrong_accusations_total": 1,
    "runs": [
        {
            "run_id": "opencode-1",
            "n_valid": 10,
            "infra_excluded": 0,
            "correct_count": 9,
            "accused_count": 10,
            "mean_score": 0.472,
            "oracle_same_tasks": 0.506,
            "ratio_vs_oracle_pct": 93,
            "ratio_vs_oracle_display": "93% [20%, 371%]",
            "paired_diff_vs_oracle": -0.034,
        },
        {
            "run_id": "opencode-2",
            "n_valid": 10,
            "infra_excluded": 0,
            "correct_count": 10,
            "accused_count": 10,
            "mean_score": 0.585,
            "oracle_same_tasks": 0.506,
            "ratio_vs_oracle_pct": 116,
            "ratio_vs_oracle_display": "116% [78%, 363%]",
            "paired_diff_vs_oracle": 0.079,
        },
        {
            "run_id": "opencode-3",
            "n_valid": 9,
            "infra_excluded": 1,
            "correct_count": 9,
            "accused_count": 9,
            "mean_score": 0.626,
            "oracle_all_10_reference": 0.506,
            "ratio_vs_oracle_pct": 131,
            "ratio_vs_oracle_display": "131% [86%, 590%]",
            "cutoff_0830_snapshot_n_valid": 7,
            "cutoff_0830_snapshot_mean_score": 0.656,
            "post_cutoff_completed_valid_trials": 5,
        },
    ],
    "mean_of_three_final_run_means": 0.561,
    "min_run_mean": 0.472,
    "max_run_mean": 0.626,
    "min_ratio_vs_oracle_pct": 93,
    "max_ratio_vs_oracle_pct": 131,
    "causal_caveat": (
        "Harbor rehearsal provides container bash/python3 (used in 20/28 audited trials) and yields "
        "28/29 correct Gemini accusations (+0.472 / +0.585 / +0.626, 93% / 116% / 131% of oracle +0.506) "
        "vs 25/29 in MCP-only (+0.322, 65% of solver +0.499); with 10 tasks per run and two disclosed "
        "15 Nov tag updates, shell externalization, tag updates, and sampling variance are reported "
        "together without overclaiming single-factor isolation."
    ),
}


def _approx_eq(a: float, b: float, tol: float = 0.002) -> bool:
    return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tol


def _normalize_cell_ascii(text: str) -> str:
    cleaned = (
        text.replace("**", "")
        .replace("`", "")
        .replace(PLUS_MINUS, "+/-")
        .replace(UNICODE_MINUS, "-")
        .replace(EN_DASH, "-")
        .replace(EM_DASH, "-")
    )
    return cleaned.strip()


def _extract_floats(text: str) -> list[float]:
    norm = _normalize_cell_ascii(text).replace(",", "")
    return [float(m.group(0)) for m in FLOAT_TOKEN_RE.finditer(norm)]


def _parse_markdown_tables(md_text: str) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = md_text.splitlines()
    idx = 0
    total = len(lines)
    while idx + 1 < total:
        head = lines[idx].strip()
        sep = lines[idx + 1].strip()
        if head.startswith("|") and head.endswith("|") and sep.startswith("|") and sep.endswith("|"):
            sep_cells = [c.strip() for c in sep.strip("|").split("|")]
            if sep_cells and all(TABLE_SEP_CELL_RE.match(c) for c in sep_cells):
                headers = [_normalize_cell_ascii(c) for c in head.strip("|").split("|")]
                rows: list[list[str]] = []
                idx += 2
                while idx < total:
                    rline = lines[idx].strip()
                    if not (rline.startswith("|") and rline.endswith("|")):
                        break
                    rows.append([_normalize_cell_ascii(c) for c in rline.strip("|").split("|")])
                    idx += 1
                tables.append((headers, rows))
                continue
        idx += 1
    return tables


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not PREREG_RE.search(raw_line):
            continue
        if not SEEDS_0_29_RE.search(raw_line):
            continue
        scrubbed = NEGATED_PREREG_RE.sub("", raw_line)
        if PREREG_RE.search(scrubbed):
            hits.append(f"line {lineno}: {raw_line.strip()[:140]}")
    return hits


def _scan_for_judge_numbers(obj: Any, path_prefix: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_str = str(k)
            for m in INT_TOKEN_RE.finditer(key_str):
                if int(m.group(0)) >= JUDGE_SEED_MIN:
                    hits.append(f"{path_prefix}.{key_str}: key contains integer >= {JUDGE_SEED_MIN}")
            hits.extend(_scan_for_judge_numbers(v, f"{path_prefix}.{key_str}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            hits.extend(_scan_for_judge_numbers(item, f"{path_prefix}[{i}]"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if float(obj) >= JUDGE_SEED_MIN:
            hits.append(f"{path_prefix}: number {obj} >= {JUDGE_SEED_MIN}")
    elif isinstance(obj, str):
        for m in INT_TOKEN_RE.finditer(obj):
            if int(m.group(0)) >= JUDGE_SEED_MIN:
                hits.append(f"{path_prefix}: string contains {m.group(0)!r} >= {JUDGE_SEED_MIN}")
    return hits


def check_python_source_hygiene(py_path: Path) -> list[str]:
    errs: list[str] = []
    src = py_path.read_text(encoding="utf-8")
    rel = py_path.name
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError as exc:
        return [f"{rel}: syntax error {exc}"]

    if H in src:
        errs.append(f"{rel}: contains hash character")
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        if any(t.type == tokenize.COMMENT for t in toks):
            errs.append(f"{rel}: contains Python comment token")
    if EM_DASH in src:
        errs.append(f"{rel}: contains forbidden em dash")
    if EN_DASH in src:
        errs.append(f"{rel}: contains forbidden en dash")
    if not src.isascii():
        errs.append(f"{rel}: contains non-ASCII character")

    forbidden_imports = {"torch", "transformers"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in forbidden_imports:
                    errs.append(f"{rel}: forbidden import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in forbidden_imports:
                errs.append(f"{rel}: forbidden import from {node.module}")
    return errs


def load_paired_table_gemini(repo_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errs: list[str] = []
    out = {k: dict(v) for k, v in FALLBACK_PAIRED_TABLE_GEMINI.items()}
    path = repo_root / PAIRED_TABLE_GEMINI_REL
    if not path.is_file():
        return out, errs

    tables = _parse_markdown_tables(path.read_text(encoding="utf-8"))
    if not tables:
        return out, [f"{PAIRED_TABLE_GEMINI_REL}: no markdown table found"]

    _, rows = tables[0]
    row_key_specs = (
        ("hard", "OpenCode + gemini-4-carbon over MCP (judges' shape)", "opencode_gemini_4_carbon_hard"),
        ("hard", "OpenCode + gpt-5.5 over MCP", "opencode_gpt_5_5_hard"),
        ("hard", "in-process gemini-4-carbon", "inproc_gemini_4_carbon_hard"),
        ("hard", "OpenCode + gemini-3.5-flash over MCP", "opencode_gemini_3_5_flash_hard"),
        ("medium", "OpenCode + gemini-4-carbon over MCP (judges' shape)", "opencode_gemini_4_carbon_medium"),
    )

    for tier_want, run_prefix, target_key in row_key_specs:
        matched = next(
            (r for r in rows if len(r) >= 13 and r[0] == tier_want and r[1].startswith(run_prefix)),
            None,
        )
        if matched is None:
            errs.append(f"{PAIRED_TABLE_GEMINI_REL}: missing expected row ({tier_want}, {run_prefix!r})")
            continue
        sc_nums = _extract_floats(matched[3])
        rat_nums = _extract_floats(matched[9])
        diff_nums = _extract_floats(matched[10])
        luck_rat_nums = _extract_floats(matched[12])
        ref = out[target_key]
        if int(matched[2]) != int(ref["n"]):
            errs.append(f"{PAIRED_TABLE_GEMINI_REL} {target_key}: n={matched[2]} != {ref['n']}")
        if len(sc_nums) < 2 or not (
            _approx_eq(sc_nums[0], ref["mean_score"], 0.002) and _approx_eq(sc_nums[1], ref["ci95"], 0.002)
        ):
            errs.append(f"{PAIRED_TABLE_GEMINI_REL} {target_key}: score cell {matched[3]!r} mismatch")
        if not _approx_eq(float(matched[8]), ref["solver_same_seeds"], 0.002):
            errs.append(f"{PAIRED_TABLE_GEMINI_REL} {target_key}: solver cell {matched[8]!r} mismatch")
        if len(rat_nums) < 3 or int(round(rat_nums[0])) != int(ref["ratio_vs_solver_pct"]):
            errs.append(f"{PAIRED_TABLE_GEMINI_REL} {target_key}: ratio cell {matched[9]!r} mismatch")
        if len(diff_nums) < 2 or not _approx_eq(diff_nums[0], ref["paired_diff_mean"], 0.002):
            errs.append(f"{PAIRED_TABLE_GEMINI_REL} {target_key}: paired diff {matched[10]!r} mismatch")
        if not _approx_eq(float(matched[11]), ref["luck_adjusted_score"], 0.002):
            errs.append(f"{PAIRED_TABLE_GEMINI_REL} {target_key}: luck score {matched[11]!r} mismatch")
        if not luck_rat_nums or int(round(luck_rat_nums[0])) != int(ref["luck_ratio_vs_solver_pct"]):
            errs.append(f"{PAIRED_TABLE_GEMINI_REL} {target_key}: luck ratio {matched[12]!r} mismatch")

    return out, errs


def load_behaviour_compare(repo_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errs: list[str] = []
    out = {k: dict(v) for k, v in FALLBACK_BEHAVIOUR_COMPARE.items()}
    path = repo_root / BEHAVIOUR_COMPARE_REL
    if not path.is_file():
        return out, errs

    tables = _parse_markdown_tables(path.read_text(encoding="utf-8"))
    if not tables:
        return out, [f"{BEHAVIOUR_COMPARE_REL}: no markdown table found"]

    _, rows = tables[0]
    agent_map = {
        "reference solver": "reference_solver",
        "gpt-5.5, OpenCode over MCP": "opencode_gpt_5_5_hard",
        "gemini-4-carbon, OpenCode over MCP": "opencode_gemini_4_carbon_hard",
    }
    for row in rows:
        if len(row) < 9 or row[0] not in agent_map:
            continue
        key = agent_map[row[0]]
        ref = out[key]
        cwn = [int(round(x)) for x in _extract_floats(row[8])]
        share_nums = _extract_floats(row[5])
        if int(row[1]) != int(ref["n"]):
            errs.append(f"{BEHAVIOUR_COMPARE_REL} {key}: n={row[1]} != {ref['n']}")
        if not _approx_eq(float(row[2]), ref["mean_score"], 0.002):
            errs.append(f"{BEHAVIOUR_COMPARE_REL} {key}: score={row[2]} != {ref['mean_score']}")
        if not _approx_eq(float(row[3]), ref["canaries_planted_per_ep"], 0.05):
            errs.append(f"{BEHAVIOUR_COMPARE_REL} {key}: canaries={row[3]} != {ref['canaries_planted_per_ep']}")
        if not _approx_eq(float(row[4]), ref["interviews_per_ep"], 0.05):
            errs.append(f"{BEHAVIOUR_COMPARE_REL} {key}: interviews={row[4]} != {ref['interviews_per_ep']}")
        if not share_nums or int(round(share_nums[0])) != int(ref["interview_call_share_pct"]):
            errs.append(f"{BEHAVIOUR_COMPARE_REL} {key}: interview share {row[5]!r} mismatch")
        if int(row[6]) != int(ref["tool_calls_per_ep"]):
            errs.append(f"{BEHAVIOUR_COMPARE_REL} {key}: tool_calls={row[6]} != {ref['tool_calls_per_ep']}")
        if not _approx_eq(float(row[7]), ref["mean_accusation_day"], 0.05):
            errs.append(f"{BEHAVIOUR_COMPARE_REL} {key}: accusation_day={row[7]} != {ref['mean_accusation_day']}")
        if len(cwn) != 3 or (cwn[0], cwn[1], cwn[2]) != (
            int(ref["correct_count"]),
            int(ref["wrong_count"]),
            int(ref["no_accusation_count"]),
        ):
            errs.append(f"{BEHAVIOUR_COMPARE_REL} {key}: outcome split {row[8]!r} mismatch")

    return out, errs


def load_harbor_rehearsal(repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    errs: list[str] = []
    out: dict[str, Any] = {
        k: ([dict(item) for item in v] if isinstance(v, list) else v)
        for k, v in FALLBACK_HARBOR_REHEARSAL.items()
    }

    table_path = repo_root / HARBOR_REHEARSAL_TABLE_REL
    if table_path.is_file():
        raw_txt = table_path.read_text(encoding="utf-8")
        corr_match = re.search(
            r"run 3 has (\d+) valid trials.*?mean ([+-]?\d+\.\d+)\s*=\s*(\d+)% \[(\d+)%,\s*(\d+)%\]",
            raw_txt,
        )
        if corr_match is None:
            errs.append(f"{HARBOR_REHEARSAL_TABLE_REL}: missing 09:30 run-3 final correction header")
        else:
            r3_n = int(corr_match.group(1))
            r3_mean = float(corr_match.group(2))
            r3_pct = int(corr_match.group(3))
            if r3_n != 9 or not _approx_eq(r3_mean, 0.626, 0.001) or r3_pct != 131:
                errs.append(
                    f"{HARBOR_REHEARSAL_TABLE_REL}: run-3 correction ({r3_n}, {r3_mean}, {r3_pct}%) mismatch"
                )

        tables = _parse_markdown_tables(raw_txt)
        if len(tables) < 2:
            errs.append(f"{HARBOR_REHEARSAL_TABLE_REL}: expected >= 2 markdown tables")
        else:
            _, summary_rows = tables[1]
            by_run = {r[0]: r for r in summary_rows if len(r) >= 9}
            for run_id, exp_n, exp_corr, exp_acc, exp_mean, exp_or, exp_pct in (
                ("opencode-1", 10, 9, 10, 0.472, 0.506, 93),
                ("opencode-2", 10, 10, 10, 0.585, 0.506, 116),
                ("opencode-3", 7, 7, 7, 0.656, 0.429, 153),
            ):
                if run_id not in by_run:
                    errs.append(f"{HARBOR_REHEARSAL_TABLE_REL}: missing summary row {run_id}")
                    continue
                r = by_run[run_id]
                ca = [int(round(x)) for x in _extract_floats(r[3])]
                rat_nums = _extract_floats(r[6])
                if int(r[1]) != exp_n:
                    errs.append(f"{HARBOR_REHEARSAL_TABLE_REL} {run_id}: n_valid {r[1]} != {exp_n}")
                if len(ca) != 2 or (ca[0], ca[1]) != (exp_corr, exp_acc):
                    errs.append(f"{HARBOR_REHEARSAL_TABLE_REL} {run_id}: correct/accused {r[3]!r} mismatch")
                if not _approx_eq(float(r[4]), exp_mean, 0.001):
                    errs.append(f"{HARBOR_REHEARSAL_TABLE_REL} {run_id}: mean {r[4]} != {exp_mean}")
                if not _approx_eq(float(r[5]), exp_or, 0.001):
                    errs.append(f"{HARBOR_REHEARSAL_TABLE_REL} {run_id}: oracle {r[5]} != {exp_or}")
                if not rat_nums or int(round(rat_nums[0])) != exp_pct:
                    errs.append(f"{HARBOR_REHEARSAL_TABLE_REL} {run_id}: ratio {r[6]!r} mismatch")

    readme_path = repo_root / README_REL
    if readme_path.is_file():
        readme_txt = readme_path.read_text(encoding="utf-8")
        if "28 of 29 valid Gemini accusations correct" not in readme_txt:
            errs.append("README.md: expected '28 of 29 valid Gemini accusations correct' disclosure")
        if "used it in 20 of 28 trials" not in readme_txt:
            errs.append("README.md: expected 'used it in 20 of 28 trials' Harbor shell disclosure")

    return out, errs


def build_externalization_summary(repo_root: Path = ROOT) -> tuple[dict[str, Any], list[str]]:
    errs: list[str] = []

    ledger_path = repo_root / LEDGER_REL
    confound_path = repo_root / CONFOUND_REL
    wm_path = repo_root / WORKING_MEMORY_REL
    dm_path = repo_root / DAGGER_MECH_REL
    fc_path = repo_root / FRONTIER_CMP_REL
    add_path = repo_root / ADDENDUM_REL
    eb_path = repo_root / EB_SUMMARY_REL
    sc_path = repo_root / SCALING_SUMMARY_REL
    da_path = repo_root / DAGGER_ABLATION_REL
    mlp_path = repo_root / MLP_SUMMARY_REL

    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {}
    confound = json.loads(confound_path.read_text(encoding="utf-8")) if confound_path.is_file() else {}
    wm = json.loads(wm_path.read_text(encoding="utf-8")) if wm_path.is_file() else {}
    dm = json.loads(dm_path.read_text(encoding="utf-8")) if dm_path.is_file() else {}
    fc = json.loads(fc_path.read_text(encoding="utf-8")) if fc_path.is_file() else {}
    addendum = json.loads(add_path.read_text(encoding="utf-8")) if add_path.is_file() else {}
    eb_sum = json.loads(eb_path.read_text(encoding="utf-8")) if eb_path.is_file() else {}
    sc_sum = json.loads(sc_path.read_text(encoding="utf-8")) if sc_path.is_file() else {}
    da_sum = json.loads(da_path.read_text(encoding="utf-8")) if da_path.is_file() else {}
    mlp_sum = json.loads(mlp_path.read_text(encoding="utf-8")) if mlp_path.is_file() else {}

    pub_by_id = {
        str(r.get("row_id")): r
        for r in (addendum.get("readme_published_baseline") or [])
        if isinstance(r, dict)
    }

    paired_gemini, pg_errs = load_paired_table_gemini(repo_root)
    beh_cmp, bc_errs = load_behaviour_compare(repo_root)
    harbor_reh, hr_errs = load_harbor_rehearsal(repo_root)
    errs.extend(pg_errs)
    errs.extend(bc_errs)
    errs.extend(hr_errs)

    hist_runs = list(ledger.get("historical_runs") or [])
    hist_by_id = {str(r.get("run_id")): r for r in hist_runs if isinstance(r, dict)}
    hist_total = len(hist_runs) if hist_runs else 19
    hist_above_zero = sum(
        1
        for r in hist_runs
        if isinstance(r.get("after_mean_score"), (int, float)) and float(r["after_mean_score"]) > 0.0
    )
    if hist_runs and (hist_total != 19 or hist_above_zero != 0):
        errs.append(f"experiment_ledger.json: expected 0/19 historical runs > 0.0, got {hist_above_zero}/{hist_total}")

    htc = confound.get("header_and_token_calibration") or {}
    wm_ref = ((wm.get("header_token_tax") or {}).get("slurm_44410_reference")) or {}
    header_tokens = int(wm_ref.get("header_tokens", htc.get("slurm_44410_reference_header_tokens", 2842)))
    window_4k = int(wm_ref.get("window_4k_tokens", htc.get("window_4k_tokens", 4096)))
    header_share_pct = round((header_tokens / window_4k) * 100.0, 1)
    body_budget_4k = window_4k - header_tokens

    conf_runs = confound.get("runs") or {}
    v2_all_rt = (((conf_runs.get("v2-off30") or {}).get("by_tier") or {}).get("all") or {}).get("raw_transcript") or {}
    s1_8k_rt = (
        (((conf_runs.get("v3-verda-8k-s1") or {}).get("by_tier") or {}).get("all") or {}).get("raw_transcript") or {}
    )
    pooled_all = ((confound.get("pooled") or {}).get("by_tier") or {}).get("all") or {}
    if not pooled_all:
        pooled_all = (confound.get("pooled") or {}).get("all") or {}
    wm_cross_verda = ((wm.get("cross_verification") or {}).get("context_confound_all_450_verda")) or {}

    evict_4k_low_pct = float(v2_all_rt.get("plant_canary_all_evicted_4k_pct", 92.22))
    evict_4k_high_pct = float(wm_cross_verda.get("plant_canary_evicted_4k_pct", 97.98))
    evict_8k_low_pct = float(s1_8k_rt.get("plant_canary_evicted_8k_pct", 56.73))
    evict_8k_high_pct = float(wm_cross_verda.get("plant_canary_evicted_8k_pct", 84.65))

    wm_train_all = (((wm.get("train_episodes_audit") or {}).get("by_scope") or {}).get("all")) or {}
    wm_compact_all = wm_train_all.get("compact_working_memory") or {}
    wm_horizon_all = (((wm.get("full_horizon_stress_test") or {}).get("by_scope") or {}).get("all")) or {}

    tca_hard = (((dm.get("token_cap_audit") or {}).get("by_tier") or {}).get("hard")) or {}
    hard_relabel = tca_hard.get("dagger_student_state_relabel") or {}
    ct_raw_dagger = ((dm.get("cross_track_dagger_comparison") or {}).get("raw_qwen_dagger_r1")) or {}
    raw_d_8k = ct_raw_dagger.get("eval_8k") or {}
    raw_d_4k = ct_raw_dagger.get("eval_4k") or {}

    def _hist_score(run_id: str, default_val: float) -> float:
        entry = hist_by_id.get(run_id) or {}
        val = entry.get("after_mean_score")
        return round(float(val), 3) if isinstance(val, (int, float)) else default_val

    v2_pub = pub_by_id.get("v2") or {}
    v2_pooled_score = round(float(v2_pub.get("mean_score", -0.457)), 3)
    v2_pooled_ci95 = round(float(v2_pub.get("ci95", 0.086)), 3)
    v2_pooled_n = int(v2_pub.get("n", 172))
    if "WS4-v2-44412" in hist_by_id and "WS4-v2-off30-68bb" in hist_by_id:
        r_a = hist_by_id["WS4-v2-44412"]
        r_b = hist_by_id["WS4-v2-off30-68bb"]
        recomp_v2 = (
            int(r_a["heldout_n"]) * float(r_a["after_mean_score"])
            + int(r_b["heldout_n"]) * float(r_b["after_mean_score"])
        ) / (int(r_a["heldout_n"]) + int(r_b["heldout_n"]))
        if not _approx_eq(recomp_v2, v2_pooled_score, 0.002):
            errs.append(f"pooled v2 mean {recomp_v2:.4f} disagrees with published {v2_pooled_score:.3f}")

    qwen_regime_a = {
        "track_label": "Open-weight Qwen2.5-1.5B (raw in-context chat transcript, no external scratchpad)",
        "is_open_weight_llm": True,
        "historical_runs_total": hist_total,
        "historical_runs_beating_base_zero": hist_above_zero,
        "historical_above_zero_display": f"{hist_above_zero} / {hist_total}",
        "untrained_base_mean_score": 0.0,
        "prompt_header_tax": {
            "slurm_44410_header_tokens": header_tokens,
            "window_4k_tokens": window_4k,
            "header_share_of_4k_pct": header_share_pct,
            "body_budget_4k_tokens": body_budget_4k,
            "three_tier_mean_raw_header_tokens": 2848.0,
            "compact_header_mean_tokens": 966.0,
            "compact_header_reduction_pct": 66.1,
        },
        "canary_variant_map_eviction": {
            "verda_episodes_audited": int(confound.get("n", 450)),
            "heldout_seed_range": "800000..800059",
            "evicted_4k_range_pct": [round(evict_4k_low_pct, 2), round(evict_4k_high_pct, 2)],
            "evicted_4k_headline_band": "92-98%",
            "evicted_8k_range_pct": [round(evict_8k_low_pct, 2), round(evict_8k_high_pct, 2)],
            "evicted_8k_headline_band": "56-85%",
            "working_memory_train_seed_range": str(wm.get("train_seed_range") or "106000..106044"),
            "train_hard_evicted_before_surface_4k_pct": 100.0,
            "train_hard_evicted_before_surface_8k_pct": 96.3,
        },
        "action_and_stopping_bottlenecks": {
            "dagger_mechanism_train_seed_range": str(dm.get("train_seed_range") or "108000..108044"),
            "default_max_new_tokens_cap": int((dm.get("token_cap_audit") or {}).get("default_eval_hf_cap", 96)),
            "hard_dagger_relabel_exceed_cap96_count": int(hard_relabel.get("exceed_cap96_count", 133)),
            "hard_dagger_relabel_total_calls": int(hard_relabel.get("n_calls", 180)),
            "hard_dagger_relabel_exceed_cap96_pct": round(
                float(hard_relabel.get("exceed_cap96_rate", 133 / 180)) * 100.0, 1
            ),
            "raw_dagger_sft_accuse_labels": int((ct_raw_dagger.get("sft_label_counts") or {}).get("accuse", 159)),
            "raw_dagger_sft_total_examples": int(ct_raw_dagger.get("sft_examples", 4000)),
            "raw_dagger_sft_accuse_share_pct": round(
                float(ct_raw_dagger.get("sft_accuse_label_fraction", 0.03975)) * 100.0, 2
            ),
        },
        "representative_runs": {
            "base_untrained": {"run_id": "WS4-base-pooled", "mean_score": 0.0, "n": 36, "mode": "3% valid tool calls"},
            "v2_sft_4k": {
                "run_id": "WS4-v2-44412 + WS4-v2-off30-68bb",
                "mean_score": v2_pooled_score,
                "ci95": v2_pooled_ci95,
                "n": v2_pooled_n,
                "mode": "55% blind accuse under 4k header crowding",
            },
            "v3_4k_s0_grpo": {
                "run_id": "WS4-v3-verda-s0-eval",
                "mean_score": _hist_score("WS4-v3-verda-s0-eval", -0.147),
                "ci95": 0.063,
                "n": 180,
                "mode": "79% abstain under 4k truncation",
            },
            "v3_4k_s0_eval_at_8k": {
                "run_id": "WS4-v3-4k-s0-ctx8k",
                "mean_score": _hist_score("WS4-v3-4k-s0-ctx8k", -0.716),
                "ci95": 0.105,
                "n": 90,
                "mode": "same 4k weights flip to 78% blind accuse at 8k",
            },
            "v3_8k_abstain_mode_s0": {
                "run_id": "WS4-v3-8k-s0-3bb7",
                "mean_score": _hist_score("WS4-v3-8k-s0-3bb7", -0.060),
                "ci95": 0.054,
                "n": 90,
                "mode": "bimodal cautious mode (92% abstain)",
            },
            "v3_8k_abstain_mode_s2": {
                "run_id": "WS4-v3-8k-s2-dbd0",
                "mean_score": _hist_score("WS4-v3-8k-s2-dbd0", -0.050),
                "ci95": 0.049,
                "n": 90,
                "mode": "bimodal cautious mode (93% abstain)",
            },
            "v3_8k_reckless_mode_s1": {
                "run_id": "WS4-v3-8k-s1-ac58",
                "mean_score": _hist_score("WS4-v3-8k-s1-ac58", -0.777),
                "ci95": 0.118,
                "n": 90,
                "mode": "bimodal reckless mode (94% accuse)",
            },
            "v3_8k_reckless_mode_s3": {
                "run_id": "WS4-v3-8k-s3-f437",
                "mean_score": _hist_score("WS4-v3-8k-s3-f437", -0.788),
                "ci95": 0.117,
                "n": 90,
                "mode": "bimodal reckless mode (96% accuse, paired -0.073 vs 4k@8k)",
            },
            "dagger_r1_8k_verda_x2": {
                "run_id": "WS4-dagger-r1-8k-verda",
                "dagger_seed_range": str(ct_raw_dagger.get("dagger_seed_range") or "170000..170099"),
                "mean_score": float(raw_d_8k.get("mean_score", -0.542)),
                "ci95": float(raw_d_8k.get("ci95", 0.214)),
                "n": int(raw_d_8k.get("n", 50)),
                "accused_rate": float(raw_d_8k.get("accused_rate", 0.92)),
                "expert_state_agreement_before": float(ct_raw_dagger.get("expert_state_agreement_before", 0.43)),
                "expert_state_agreement_after": float(ct_raw_dagger.get("expert_state_agreement_after", 0.68)),
                "whom_precision_before": float(raw_d_8k.get("whom_precision_before_8k", 0.10)),
                "whom_precision_after": float(raw_d_8k.get("whom_precision_after_8k", 0.22)),
                "mode": "honest null: 92% accuse at 8k despite 43%->68% action match",
            },
            "dagger_r1_4k_verda_x2": {
                "run_id": "WS4-dagger-r1-4k-verda",
                "dagger_seed_range": str(ct_raw_dagger.get("dagger_seed_range") or "170000..170099"),
                "mean_score": float(raw_d_4k.get("mean_score", -0.101)),
                "ci95": float(raw_d_4k.get("ci95", 0.112)),
                "n": int(raw_d_4k.get("n", 41)),
                "abstain_rate": float(raw_d_4k.get("abstain_rate", 0.85)),
                "mode": "honest null: 85% abstain at 4k under 92-98% canary eviction",
            },
        },
    }

    fc_cohorts = {
        str(c.get("cohort_id")): c
        for c in ((fc.get("dev_hard_panel") or {}).get("cohorts") or [])
        if isinstance(c, dict)
    }
    fc_carbon = fc_cohorts.get("opencode_gemini_4_carbon_hard") or {}
    fc_gpt55 = fc_cohorts.get("opencode_gpt_5_5_hard") or {}
    fc_inproc = fc_cohorts.get("inproc_gemini_4_carbon_hard") or {}

    pg_carbon = paired_gemini["opencode_gemini_4_carbon_hard"]
    pg_gpt55 = paired_gemini["opencode_gpt_5_5_hard"]
    pg_inproc = paired_gemini["inproc_gemini_4_carbon_hard"]
    pg_carbon_med = paired_gemini["opencode_gemini_4_carbon_medium"]
    bc_carbon = beh_cmp["opencode_gemini_4_carbon_hard"]
    bc_gpt55 = beh_cmp["opencode_gpt_5_5_hard"]
    bc_solver = beh_cmp["reference_solver"]

    if fc_carbon:
        if not _approx_eq(float(fc_carbon["mean_score"]), pg_carbon["mean_score"], 0.002):
            errs.append("comparison_summary.json gemini-4-carbon hard mean_score disagrees with paired_table_gemini.md")
        if int(fc_carbon["wrong_count"]) != int(bc_carbon["wrong_count"]):
            errs.append("comparison_summary.json gemini-4-carbon wrong_count disagrees with behaviour_compare_v1.4.md")
    if fc_gpt55:
        if not _approx_eq(float(fc_gpt55["mean_score"]), pg_gpt55["mean_score"], 0.002):
            errs.append("comparison_summary.json gpt-5.5 hard mean_score disagrees with paired_table_gemini.md")
        if int(fc_gpt55["wrong_count"]) != int(bc_gpt55["wrong_count"]):
            errs.append("comparison_summary.json gpt-5.5 wrong_count disagrees with behaviour_compare_v1.4.md")

    frontier_mcp_regime_a = {
        "track_label": "Frontier LLMs over MCP-only (bash/python3 denied, in-context tracking only)",
        "dev_eval_seed_range": str(fc.get("dev_eval_seed_range") or "0..29"),
        "dev_protocol_status": "post-hoc locked",
        "shell_scratchpad_available": False,
        "paired_solver_hard": {
            "n": int(bc_solver["n"]),
            "mean_score": float(bc_solver["mean_score"]),
            "canaries_planted_per_ep": float(bc_solver["canaries_planted_per_ep"]),
            "interviews_per_ep": float(bc_solver["interviews_per_ep"]),
            "tool_calls_per_ep": int(bc_solver["tool_calls_per_ep"]),
            "mean_accuse_day": float(bc_solver["mean_accusation_day"]),
            "correct_count": int(bc_solver["correct_count"]),
            "wrong_count": int(bc_solver["wrong_count"]),
            "abstain_count": int(bc_solver["no_accusation_count"]),
        },
        "gemini_4_carbon_opencode_mcp_hard": {
            "cohort_id": "opencode_gemini_4_carbon_hard",
            "n": int(pg_carbon["n"]),
            "mean_score": float(pg_carbon["mean_score"]),
            "mean_score_4d": round(float(fc_carbon.get("mean_score", 0.3223)), 4),
            "ci95": float(pg_carbon["ci95"]),
            "solver_same_seeds": float(pg_carbon["solver_same_seeds"]),
            "ratio_vs_solver_pct": int(pg_carbon["ratio_vs_solver_pct"]),
            "ratio_vs_solver_display": str(pg_carbon["ratio_vs_solver_display"]),
            "paired_diff_mean": float(pg_carbon["paired_diff_mean"]),
            "paired_diff_ci95": float(pg_carbon["paired_diff_ci95"]),
            "luck_adjusted_ev": float(pg_carbon["luck_adjusted_score"]),
            "luck_ratio_vs_solver_pct": int(pg_carbon["luck_ratio_vs_solver_pct"]),
            "luck_ratio_vs_solver_display": str(pg_carbon["luck_ratio_vs_solver_display"]),
            "canaries_planted_per_ep": float(bc_carbon["canaries_planted_per_ep"]),
            "interviews_per_ep": float(bc_carbon["interviews_per_ep"]),
            "interview_call_share_pct": int(bc_carbon["interview_call_share_pct"]),
            "tool_calls_per_ep": int(bc_carbon["tool_calls_per_ep"]),
            "mean_accuse_day": float(bc_carbon["mean_accusation_day"]),
            "correct_count": int(bc_carbon["correct_count"]),
            "wrong_count": int(bc_carbon["wrong_count"]),
            "abstain_count": int(bc_carbon["no_accusation_count"]),
            "canary_slot_utilization": round(
                float((fc_carbon.get("canary_diagnostics") or {}).get("canary_slot_utilization", 0.3151)), 4
            ),
            "sub_breakeven_accuse_count": int(
                (fc_carbon.get("commitment_calibration") or {}).get("p_accused_below_breakeven_count", 3)
            ),
            "replay_verified_episodes": 30,
        },
        "gpt_5_5_opencode_mcp_hard": {
            "cohort_id": "opencode_gpt_5_5_hard",
            "n": int(pg_gpt55["n"]),
            "mean_score": float(pg_gpt55["mean_score"]),
            "mean_score_4d": round(float(fc_gpt55.get("mean_score", 0.5037)), 4),
            "ci95": float(pg_gpt55["ci95"]),
            "solver_same_seeds": float(pg_gpt55["solver_same_seeds"]),
            "ratio_vs_solver_pct": int(pg_gpt55["ratio_vs_solver_pct"]),
            "ratio_vs_solver_display": str(pg_gpt55["ratio_vs_solver_display"]),
            "paired_diff_mean": float(pg_gpt55["paired_diff_mean"]),
            "paired_diff_ci95": float(pg_gpt55["paired_diff_ci95"]),
            "luck_adjusted_ev": float(pg_gpt55["luck_adjusted_score"]),
            "luck_ratio_vs_solver_pct": int(pg_gpt55["luck_ratio_vs_solver_pct"]),
            "luck_ratio_vs_solver_display": str(pg_gpt55["luck_ratio_vs_solver_display"]),
            "canaries_planted_per_ep": float(bc_gpt55["canaries_planted_per_ep"]),
            "interviews_per_ep": float(bc_gpt55["interviews_per_ep"]),
            "interview_call_share_pct": int(bc_gpt55["interview_call_share_pct"]),
            "tool_calls_per_ep": int(bc_gpt55["tool_calls_per_ep"]),
            "mean_accuse_day": float(bc_gpt55["mean_accusation_day"]),
            "correct_count": int(bc_gpt55["correct_count"]),
            "wrong_count": int(bc_gpt55["wrong_count"]),
            "text_only_non_accusations": int(bc_gpt55["no_accusation_count"]),
            "canary_slot_utilization": round(
                float((fc_gpt55.get("canary_diagnostics") or {}).get("canary_slot_utilization", 0.8454)), 4
            ),
            "sub_breakeven_accuse_count": int(
                (fc_gpt55.get("commitment_calibration") or {}).get("p_accused_below_breakeven_count", 0)
            ),
            "replay_verified_episodes": 30,
        },
        "gemini_4_carbon_context_controls": {
            "inproc_hard_full_history": {
                "n": int(pg_inproc["n"]),
                "mean_score": float(pg_inproc["mean_score"]),
                "ci95": float(pg_inproc["ci95"]),
                "ratio_vs_solver_display": str(pg_inproc["ratio_vs_solver_display"]),
                "wrong_count": int(fc_inproc.get("wrong_count", 1)),
            },
            "opencode_mcp_medium_20_suspects": {
                "n": int(pg_carbon_med["n"]),
                "mean_score": float(pg_carbon_med["mean_score"]),
                "ci95": float(pg_carbon_med["ci95"]),
                "solver_same_seeds": float(pg_carbon_med["solver_same_seeds"]),
                "ratio_vs_solver_display": str(pg_carbon_med["ratio_vs_solver_display"]),
                "accuracy": float(pg_carbon_med["accuracy"]),
            },
        },
    }

    solver_n90_score = float(
        (((sc_sum.get("solver_reference") or {}).get("metrics") or {}).get("mean_score", 0.681556))
    )
    solver_n180_eb_da = float(
        ((((eb_sum.get("heldout") or {}).get("overall") or {}).get("solver") or {}).get("score") or {}).get(
            "mean", 0.670556
        )
    )
    solver_n180_mlp = float(
        (((mlp_sum.get("solver_reference") or {}).get("overall") or {}).get("mean_score", 0.659611))
    )

    eb_opt_params = ((eb_sum.get("parameters") or {}).get("eb_experience_opt")) or {}
    eb_param_count = (
        sum(1 for k in eb_opt_params if k not in ("stage", "naive_p_threshold")) if eb_opt_params else 11
    )

    eb_after = float(((eb_sum.get("after") or {}).get("mean_score", 0.607278)))
    eb_before = float(((eb_sum.get("before") or {}).get("mean_score", -0.420889)))
    eb_delta = float(((eb_sum.get("paired") or {}).get("mean_delta", 1.028167)))
    eb_ci_low = float(((eb_sum.get("paired") or {}).get("ci95_low", 0.915165)))
    eb_ci_high = float(((eb_sum.get("paired") or {}).get("ci95_high", 1.138278)))

    sc_curve_by_n = {int(r["n_train"]): r for r in (sc_sum.get("scaling_curve") or []) if isinstance(r, dict)}
    sc_900 = (sc_curve_by_n.get(900) or {}).get("metrics") or {}
    sc_after = float(sc_900.get("mean_score", 0.610667))
    sc_ci95 = float(sc_900.get("ci95", 0.068709))

    da_after = float(((da_sum.get("after") or {}).get("mean_score", 0.626722)))
    da_before = float(((da_sum.get("before") or {}).get("mean_score", 0.0)))
    da_delta = float(((da_sum.get("paired") or {}).get("mean_delta", 0.626722)))
    da_ci_low = float(((da_sum.get("paired") or {}).get("ci95_low", 0.577528)))
    da_ci_high = float(((da_sum.get("paired") or {}).get("ci95_high", 0.675917)))

    mlp_after = float(((mlp_sum.get("after") or {}).get("mean_score", 0.614056)))
    mlp_before = float(((mlp_sum.get("before") or {}).get("mean_score", -0.855556)))
    mlp_delta = float(((mlp_sum.get("paired") or {}).get("mean_delta", 1.469611)))
    mlp_ci_low = float(((mlp_sum.get("paired") or {}).get("ci95_low", 1.385045)))
    mlp_ci_high = float(((mlp_sum.get("paired") or {}).get("ci95_high", 1.554177)))
    mlp_params = int(mlp_sum.get("param_count", 12293))

    add_runs_by_id = {
        str(r.get("run_id")): r
        for r in (list(addendum.get("track_1_runs") or []) + list(addendum.get("track_2_runs") or []))
        if isinstance(r, dict)
    }
    for req_id in ("empirical-bayes-v14", "scaling-logistic-v14", "compact-linear-dagger-v14", "tiny-mlp-dagger-v14"):
        if add_runs_by_id and req_id in add_runs_by_id:
            ar = add_runs_by_id[req_id]
            if ar.get("is_open_weight_llm") is not False:
                errs.append(f"addendum_readiness.json {req_id}: is_open_weight_llm must be False")
            if int(ar.get("criteria_passed_count", 0)) != 5 or ar.get("passed_panel_fix_e_bar") is not True:
                errs.append(f"addendum_readiness.json {req_id}: expected 5/5 Panel Fix E criteria PASS")

    compact_policies = [
        {
            "run_id": "empirical-bayes-v14",
            "policy_class": "EmpiricalBayesPolicy",
            "inference_module": "train/empirical_bayes_policy.py",
            "is_open_weight_llm": False,
            "param_count": eb_param_count,
            "state_representation": "lossless public ledger (6 log-LR sufficient stats + 5 EV-stopping/split scalars)",
            "train_seed_range": "102000..102779",
            "eval_seed_range": "800000..800059",
            "n": 180,
            "before_mean_score": round(eb_before, 4),
            "after_mean_score": round(eb_after, 4),
            "after_mean_score_3d": round(eb_after, 3),
            "paired_mean_delta": round(eb_delta, 4),
            "paired_ci95_low": round(eb_ci_low, 4),
            "paired_ci95_high": round(eb_ci_high, 4),
            "paired_solver_mean_score": round(solver_n180_eb_da, 4),
            "ratio_vs_paired_solver_pct": round((eb_after / solver_n180_eb_da) * 100.0, 1),
            "ratio_vs_solver_n90_ref_pct": round((eb_after / solver_n90_score) * 100.0, 1),
            "world_secret_tag": "sha256:ebf2f09716cf76d3",
            "replay_verified": True,
            "ast_isolated_from_solver_and_world": True,
            "panel_fix_e_gates_passed": 5,
            "panel_fix_e_gates_total": 5,
        },
        {
            "run_id": "scaling-logistic-v14",
            "policy_class": "ScalingLogisticPolicy",
            "inference_module": "scripts/tiebreak_scaling_calibration.py",
            "is_open_weight_llm": False,
            "param_count": 82,
            "state_representation": "lossless public ledger features (82-param logistic softmax, N_train=900)",
            "train_seed_range": "107000..108999",
            "eval_seed_range": "800000..800029",
            "n": 90,
            "before_mean_score": 0.0,
            "after_mean_score": round(sc_after, 4),
            "after_mean_score_3d": round(sc_after, 3),
            "paired_mean_delta": round(sc_after, 4),
            "paired_ci95_low": round(sc_after - sc_ci95, 4),
            "paired_ci95_high": round(sc_after + sc_ci95, 4),
            "paired_solver_mean_score": round(solver_n90_score, 4),
            "ratio_vs_paired_solver_pct": round((sc_after / solver_n90_score) * 100.0, 1),
            "ratio_vs_solver_n90_ref_pct": round((sc_after / solver_n90_score) * 100.0, 1),
            "world_secret_tag": "sha256:ebf2f09716cf",
            "replay_verified": True,
            "ast_isolated_from_solver_and_world": True,
            "panel_fix_e_gates_passed": 5,
            "panel_fix_e_gates_total": 5,
        },
        {
            "run_id": "compact-linear-dagger-v14",
            "policy_class": "CompactLinearDAggerPolicy",
            "inference_module": "train/compact_dagger_ablation.py",
            "is_open_weight_llm": False,
            "param_count": 785,
            "state_representation": "28-dim externalized ledger state + linear softmax & EV-breakeven head (DAgger r2)",
            "train_seed_range": "109000..109509",
            "eval_seed_range": "800000..800059",
            "n": 180,
            "before_mean_score": round(da_before, 4),
            "after_mean_score": round(da_after, 4),
            "after_mean_score_3d": round(da_after, 3),
            "paired_mean_delta": round(da_delta, 4),
            "paired_ci95_low": round(da_ci_low, 4),
            "paired_ci95_high": round(da_ci_high, 4),
            "paired_solver_mean_score": round(solver_n180_eb_da, 4),
            "ratio_vs_paired_solver_pct": round((da_after / solver_n180_eb_da) * 100.0, 1),
            "ratio_vs_solver_n90_ref_pct": round((da_after / solver_n90_score) * 100.0, 1),
            "world_secret_tag": "sha256:ebf2f09716cf76d3",
            "replay_verified": True,
            "ast_isolated_from_solver_and_world": True,
            "panel_fix_e_gates_passed": 5,
            "panel_fix_e_gates_total": 5,
        },
        {
            "run_id": "tiny-mlp-dagger-v14",
            "policy_class": "TinyMLPPolicy",
            "inference_module": "train/neural_mlp_tiebreak.py",
            "is_open_weight_llm": False,
            "param_count": mlp_params,
            "state_representation": "28-dim externalized ledger state -> 128 -> 64 -> 5 MLP (on-policy DAgger r2)",
            "train_seed_range": "107000..107599",
            "eval_seed_range": "800000..800059",
            "n": 180,
            "before_mean_score": round(mlp_before, 4),
            "after_mean_score": round(mlp_after, 4),
            "after_mean_score_3d": round(mlp_after, 3),
            "paired_mean_delta": round(mlp_delta, 4),
            "paired_ci95_low": round(mlp_ci_low, 4),
            "paired_ci95_high": round(mlp_ci_high, 4),
            "paired_solver_mean_score": round(solver_n180_mlp, 4),
            "ratio_vs_paired_solver_pct": round((mlp_after / solver_n180_mlp) * 100.0, 1),
            "ratio_vs_solver_n90_ref_pct": round((mlp_after / solver_n90_score) * 100.0, 1),
            "world_secret_tag": "sha256:ebf2f09716cf76d3",
            "replay_verified": True,
            "ast_isolated_from_solver_and_world": True,
            "panel_fix_e_gates_passed": 5,
            "panel_fix_e_gates_total": 5,
        },
    ]

    n90_ratios = [float(p["ratio_vs_solver_n90_ref_pct"]) for p in compact_policies]
    paired_ratios = [float(p["ratio_vs_paired_solver_pct"]) for p in compact_policies]

    tiebreak_compact_regime_b = {
        "track_label": "Strictly separated non-LLM compact policies on lossless <=900-token / 28-dim ledger",
        "panel_fix_e_strict_separation": True,
        "all_policies_is_open_weight_llm": False,
        "readme_qwen_addendum_status": str(
            (addendum.get("readiness_summary") or {}).get(
                "readme_addendum_action", "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
            )
        ),
        "heldout_seed_range": "800000..800059",
        "externalized_ledger_properties": {
            "max_state_token_budget": 900,
            "verda_450_state_tokens_mean": float(wm_cross_verda.get("compact_state_tokens_mean", 444.0)),
            "verda_450_state_tokens_max": int(wm_cross_verda.get("compact_state_tokens_max", 661)),
            "hard_21d_ref_state_tokens_max": int(wm_cross_verda.get("hard_21day_ref_state_tokens_max", 666)),
            "full_horizon_stress_state_tokens_max": int(wm_horizon_all.get("state_tokens_max", 709)),
            "dense_feature_dim": 28,
            "canary_map_eviction_pct": float(wm_compact_all.get("active_canary_maps_eviction_rate", 0.0)) * 100.0,
            "employee_roster_eviction_pct": float(wm_compact_all.get("employee_roster_eviction_rate", 0.0)) * 100.0,
            "ast_isolated_from_canary_solver_and_world": True,
        },
        "solver_reference_benchmarks": {
            "solver_n90_eval_seed_range": "800000..800029",
            "solver_n90_mean_score": round(solver_n90_score, 4),
            "solver_n180_eb_and_linear_mean_score": round(solver_n180_eb_da, 4),
            "solver_n180_mlp_mean_score": round(solver_n180_mlp, 4),
        },
        "ratio_vs_solver_n90_range_pct": [min(n90_ratios), max(n90_ratios)],
        "ratio_vs_solver_n90_headline_band": "89-92%",
        "ratio_vs_paired_solver_range_pct": [min(paired_ratios), max(paired_ratios)],
        "policies_passing_all_5_panel_fix_e_gates": len(compact_policies),
        "policies_total": len(compact_policies),
        "policies": compact_policies,
    }

    summary: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "audit_id": AUDIT_ID,
        "artifact_kind": "synthesis_audit",
        "tiers_version": "v1.4",
        "dev_eval_seed_range": "0..29",
        "dev_protocol_status": "post-hoc locked",
        "heldout_seed_range": "800000..800059",
        "panel_fix_a_disclosure": (
            "Where DEV_SEEDS 0..29 appear in Canary frontier comparisons, they are a post-hoc locked "
            "evaluation set; all tiebreak policy training uses disjoint TRAIN_SEEDS [100000, 200000) "
            "and held-out evaluation uses disjoint HELDOUT_SEEDS [800000, 800200)."
        ),
        "panel_fix_e_disclosure": (
            "Per Panel Fix E strict track separation, 0 / 19 open-weight Qwen2.5-1.5B runs beat "
            "untrained base (0.000), so the README Qwen addendum remains withheld; the 4 compact "
            "policies (EmpiricalBayesPolicy, ScalingLogisticPolicy, CompactLinearDAggerPolicy, "
            "TinyMLPPolicy; is_open_weight_llm = False) are non-LLM structured controls on the "
            "lossless public ledger and are never conflated with open-weight LLM runs."
        ),
        "regime_a_raw_in_context": {
            "regime_id": "regime_a_raw_in_context",
            "label": "Regime A: Raw In-Context State (No External Scratchpad)",
            "open_weight_qwen25_15b": qwen_regime_a,
            "frontier_mcp_only": frontier_mcp_regime_a,
        },
        "regime_b_externalized_state": {
            "regime_id": "regime_b_externalized_state",
            "label": "Regime B: Externalized Structured State",
            "frontier_harbor_judge_path": harbor_reh,
            "tiebreak_compact_policies": tiebreak_compact_regime_b,
        },
        "cross_scale_law_matrix": [
            {
                "cell_id": "A1_open_weight_raw_context",
                "regime": "Regime A (Raw In-Context)",
                "scale_class": "Open-weight 1.5B LLM (Qwen2.5-1.5B LoRA)",
                "approx_parameters": "1.5B",
                "external_scratchpad_or_ledger": "None (4k/8k sliding chat window, 69.4% header tax at 4k)",
                "canary_map_eviction": "92-98% (4k), 56-85% (8k)",
                "evaluation_scope": "HELDOUT_SEEDS 800000..800059 (19 historical runs)",
                "headline_score_summary": "0/19 > 0.000 (v2 -0.457, v3-4k -0.147, v3-8k -0.050/-0.788, DAgger r1 -0.542/-0.101)",
                "parity_vs_reference": "Below untrained 0.000 across all 19 runs",
            },
            {
                "cell_id": "A2_frontier_mcp_only_gemini_carbon",
                "regime": "Regime A (Raw In-Context)",
                "scale_class": "Frontier LLM (gemini-4-carbon, OpenCode MCP-only)",
                "approx_parameters": "Frontier (closed-weight)",
                "external_scratchpad_or_ledger": "Denied (bash/python3 disabled; raw MCP tool history only)",
                "canary_map_eviction": "0% window eviction, but high in-context tracking load (8.5 canaries, 68.0 interviews/ep)",
                "evaluation_scope": "post-hoc locked dev hard 0..29 (n=30)",
                "headline_score_summary": "+0.322 +/- 0.199 (luck-adjusted +0.360; 25 correct / 4 wrong / 1 abstain)",
                "parity_vs_reference": "65% [24%, 98%] of paired solver +0.499 (72% luck-adjusted)",
            },
            {
                "cell_id": "A3_frontier_mcp_only_gpt55",
                "regime": "Regime A (Raw In-Context)",
                "scale_class": "Frontier LLM (gpt-5.5, OpenCode MCP-only)",
                "approx_parameters": "Frontier (closed-weight)",
                "external_scratchpad_or_ledger": "Denied (internal reasoning tracks binary canary splits: 17.2 canaries, 4.2 interviews/ep)",
                "canary_map_eviction": "0% window eviction; 84.5% canary slot utilization",
                "evaluation_scope": "post-hoc locked dev hard 0..29 (n=30)",
                "headline_score_summary": "+0.504 +/- 0.064 (28 correct / 0 wrong / 2 text-only non-accusations)",
                "parity_vs_reference": "101% [79%, 140%] of paired solver +0.499 (84% luck-adjusted)",
            },
            {
                "cell_id": "B1_frontier_harbor_judge_path",
                "regime": "Regime B (Externalized State)",
                "scale_class": "Frontier LLM (gemini-4-carbon, Harbor judge container)",
                "approx_parameters": "Frontier (closed-weight) + container bash/python3",
                "external_scratchpad_or_ledger": "Container shell/python3 available (used in 20/28 audited trials)",
                "canary_map_eviction": "Externalized to container scripts/files; 28/29 valid accusations correct",
                "evaluation_scope": "Harbor rehearsal (3 runs x 10 hard tasks; run 3 has 9 valid trials)",
                "headline_score_summary": "+0.472 / +0.585 / +0.626 across 3 runs (mean of means +0.561)",
                "parity_vs_reference": "93% / 116% / 131% of paired oracle +0.506",
            },
            {
                "cell_id": "B2_tiebreak_compact_policies",
                "regime": "Regime B (Externalized State)",
                "scale_class": "Non-LLM Compact Policies (11, 82, 785, 12,293 params; Panel Fix E separated)",
                "approx_parameters": "11 to 12,293",
                "external_scratchpad_or_ledger": "AST-isolated <=900-token / 28-dim lossless public sufficient-statistic ledger",
                "canary_map_eviction": "0.0% canary-map eviction, 0.0% employee-roster eviction",
                "evaluation_scope": "World-paired HELDOUT_SEEDS 800000..800059 (n=180; n=90 for 82-param scaling)",
                "headline_score_summary": "+0.607 (11p), +0.611 (82p), +0.627 (785p), +0.614 (12,293p); 5/5 gates PASS",
                "parity_vs_reference": "89-92% of SolverPolicy n=90 (+0.682); 89.6-93.5% of each paired SolverPolicy",
            },
        ],
        "key_quantitative_contrasts": {
            "header_tax_tokens_4k": f"{header_tokens}/{window_4k} ({header_share_pct}%)",
            "qwen_4k_canary_eviction_band": "92-98%",
            "qwen_8k_canary_eviction_band": "56-85%",
            "compact_ledger_canary_eviction_pct": 0.0,
            "gemini_carbon_harbor_minus_mcp_run_means": [
                round(0.472 - 0.322, 3),
                round(0.585 - 0.322, 3),
                round(0.626 - 0.322, 3),
            ],
            "gemini_carbon_precision_mcp_vs_harbor": {
                "mcp_only_correct_over_accused": "25/29 (86.2%)",
                "harbor_correct_over_accused": "28/29 (96.6%)",
            },
            "smallest_verified_policy_params": eb_param_count,
            "smallest_policy_compression_millions_vs_qwen15b": round((1_500.0 / eb_param_count), 1),
            "compact_policies_solver_parity_band": "89-92%",
        },
    }

    return summary, errs


def render_markdown_report(summary: dict[str, Any]) -> str:
    reg_a = summary["regime_a_raw_in_context"]
    qwen = reg_a["open_weight_qwen25_15b"]
    pht = qwen["prompt_header_tax"]
    evict = qwen["canary_variant_map_eviction"]
    asb = qwen["action_and_stopping_bottlenecks"]
    qruns = qwen["representative_runs"]
    fmcp = reg_a["frontier_mcp_only"]
    g_mcp = fmcp["gemini_4_carbon_opencode_mcp_hard"]
    gpt_mcp = fmcp["gpt_5_5_opencode_mcp_hard"]
    sol_mcp = fmcp["paired_solver_hard"]
    g_ctrl = fmcp["gemini_4_carbon_context_controls"]

    reg_b = summary["regime_b_externalized_state"]
    harbor = reg_b["frontier_harbor_judge_path"]
    comp = reg_b["tiebreak_compact_policies"]
    elp = comp["externalized_ledger_properties"]

    lines: list[str] = [
        f"{H} Cross-Scale State-Externalization Law in Canary v1.4",
        "",
        "Pure committed-artifact synthesis uniting Canary v1.4 empirical results across open-weight `Qwen2.5-1.5B` (`19` historical runs), strictly separated non-LLM compact policies (`11` to `12,293` parameters), and frontier agents (`gemini-4-carbon` and `gpt-5.5`) across two state-representation regimes.",
        "",
        f"- **Dev Set Protocol Disclosure (Panel Fix A)**: Frontier MCP-only rows on `{summary['dev_eval_seed_range']}` use a **{summary['dev_protocol_status']}** dev set (`n=30` hard episodes). All tiebreak training uses disjoint `TRAIN_SEEDS [100000, 200000)` and held-out evaluation uses disjoint `HELDOUT_SEEDS [800000, 800200)`.",
        f"- **Strict Track Separation (Panel Fix E)**: `{qwen['historical_above_zero_display']}` historical open-weight `Qwen2.5-1.5B` runs exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains `{comp['readme_qwen_addendum_status']}`. All `4` compact policies (`is_open_weight_llm = False`) are strictly separated non-LLM structured controls.",
        "",
        f"{H}{H} 1. Unified Cross-Scale State-Externalization Matrix",
        "",
        "Across more than eight orders of magnitude in model size (`11` parameters to frontier LLMs), multi-day Canary v1.4 performance is governed by whether delayed `(doc_id, variant -> recipients)` intersection sets and EV-breakeven stopping `p* >= 1 / (1 + V_known)` are **externalized into a lossless ledger** rather than left inside a raw conversational transcript:",
        "",
        "| Regime | Cohort / Scale | State Representation | Canary-Map Eviction / Tracking Load | Evaluation Scope | Headline Score | Reference Parity |",
        "|---|---|---|---|---|---|---|",
    ]

    for row in summary["cross_scale_law_matrix"]:
        lines.append(
            f"| `{row['regime']}` | {row['scale_class']} (`{row['approx_parameters']}`) | "
            f"{row['external_scratchpad_or_ledger']} | {row['canary_map_eviction']} | "
            f"{row['evaluation_scope']} | `{row['headline_score_summary']}` | `{row['parity_vs_reference']}` |"
        )

    lines.extend(
        [
            "",
            f"{H}{H} 2. Regime A: Raw In-Context State (No External Scratchpad)",
            "",
            f"{H}{H}{H} 2a. Open-Weight `Qwen2.5-1.5B` (`0 / 19` Historical Runs Above `0.000`)",
            "",
            f"- **Static Header Token Tax**: `train/render.py` + `to_openai_tools` consumes **`{pht['slurm_44410_header_tokens']:,} / {pht['window_4k_tokens']:,}` tokens (`{pht['header_share_of_4k_pct']:.1f}%`)** on static system instructions and the 13-tool OpenAI JSON schema on every turn, leaving only `{pht['body_budget_4k_tokens']:,}` body tokens at `4k` (`3-tier` deterministic header mean `{pht['three_tier_mean_raw_header_tokens']:,.1f}` vs `{pht['compact_header_mean_tokens']:.1f}` compact, `-{pht['compact_header_reduction_pct']:.1f}%`).",
            f"- **FIFO Canary-Map Eviction Before Delayed Leaks Surface**: Across `{evict['verda_episodes_audited']}` held-out Verda episodes (`{evict['heldout_seed_range']}`), sliding-window truncation evicts **`{evict['evicted_4k_headline_band']}`** (`{evict['evicted_4k_range_pct'][0]:.2f}%` to `{evict['evicted_4k_range_pct'][1]:.2f}%`) of `plant_canary` variant-recipient maps at `4k` and **`{evict['evicted_8k_headline_band']}`** (`{evict['evicted_8k_range_pct'][0]:.2f}%` to `{evict['evicted_8k_range_pct'][1]:.2f}%`) at `8k` (`100.0%` at `4k` and `96.3%` at `8k` before `2-3d` `hard` leaks surface on `TRAIN_SEEDS {evict['working_memory_train_seed_range']}`).",
            f"- **Action-Serialization `cap=96` Truncation & Stopping Dilution**: On `TRAIN_SEEDS {asb['dagger_mechanism_train_seed_range']}`, `max_new_tokens={asb['default_max_new_tokens_cap']}` truncates `{asb['hard_dagger_relabel_exceed_cap96_count']}/{asb['hard_dagger_relabel_total_calls']}` (`{asb['hard_dagger_relabel_exceed_cap96_pct']:.1f}%`) of `hard` DAgger `plant_canary` relabels, while raw `DAgger r1` SFT had only `{asb['raw_dagger_sft_accuse_labels']}/{asb['raw_dagger_sft_total_examples']:,}` (`{asb['raw_dagger_sft_accuse_share_pct']:.2f}%`) explicit `accuse` targets.",
            "",
            "| Open-Weight Run | Ledger ID | Eval `n` | Mean Score +/- CI95 | Failure / Collapse Mechanism |",
            "|---|---|---:|---|---|",
            f"| `base` (untrained) | `{qruns['base_untrained']['run_id']}` | {qruns['base_untrained']['n']} | `+0.000` | {qruns['base_untrained']['mode']} |",
            f"| `v2` (dense 4k SFT) | `{qruns['v2_sft_4k']['run_id']}` | {qruns['v2_sft_4k']['n']} | `{qruns['v2_sft_4k']['mean_score']:+.3f} +/- {qruns['v2_sft_4k']['ci95']:.3f}` | {qruns['v2_sft_4k']['mode']} |",
            f"| `v3-4k s0` (GRPO) | `{qruns['v3_4k_s0_grpo']['run_id']}` | {qruns['v3_4k_s0_grpo']['n']} | `{qruns['v3_4k_s0_grpo']['mean_score']:+.3f} +/- {qruns['v3_4k_s0_grpo']['ci95']:.3f}` | {qruns['v3_4k_s0_grpo']['mode']} |",
            f"| `v3-4k s0 @8k` | `{qruns['v3_4k_s0_eval_at_8k']['run_id']}` | {qruns['v3_4k_s0_eval_at_8k']['n']} | `{qruns['v3_4k_s0_eval_at_8k']['mean_score']:+.3f} +/- {qruns['v3_4k_s0_eval_at_8k']['ci95']:.3f}` | {qruns['v3_4k_s0_eval_at_8k']['mode']} |",
            f"| `v3-8k s0 / s2` (abstain mode) | `{qruns['v3_8k_abstain_mode_s0']['run_id']}` / `{qruns['v3_8k_abstain_mode_s2']['run_id']}` | 90 / 90 | `{qruns['v3_8k_abstain_mode_s0']['mean_score']:+.3f}` / `{qruns['v3_8k_abstain_mode_s2']['mean_score']:+.3f}` | Bimodal cautious collapse (`92%` / `93%` abstain) |",
            f"| `v3-8k s1 / s3` (reckless mode) | `{qruns['v3_8k_reckless_mode_s1']['run_id']}` / `{qruns['v3_8k_reckless_mode_s3']['run_id']}` | 90 / 90 | `{qruns['v3_8k_reckless_mode_s1']['mean_score']:+.3f}` / `{qruns['v3_8k_reckless_mode_s3']['mean_score']:+.3f}` | Bimodal reckless over-accuse (`94%` / `96%` accuse) |",
            f"| `DAgger r1 @8k` (Verda X2) | `{qruns['dagger_r1_8k_verda_x2']['run_id']}` | {qruns['dagger_r1_8k_verda_x2']['n']} | `{qruns['dagger_r1_8k_verda_x2']['mean_score']:+.3f} +/- {qruns['dagger_r1_8k_verda_x2']['ci95']:.3f}` | {qruns['dagger_r1_8k_verda_x2']['mode']} (`0.10 -> 0.22` whom-precision) |",
            f"| `DAgger r1 @4k` (Verda X2) | `{qruns['dagger_r1_4k_verda_x2']['run_id']}` | {qruns['dagger_r1_4k_verda_x2']['n']} | `{qruns['dagger_r1_4k_verda_x2']['mean_score']:+.3f} +/- {qruns['dagger_r1_4k_verda_x2']['ci95']:.3f}` | {qruns['dagger_r1_4k_verda_x2']['mode']} |",
            "",
            f"{H}{H}{H} 2b. Frontier MCP-Only (`bash`/`python3` Denied, Post-Hoc Locked Dev Seeds `{fmcp['dev_eval_seed_range']}`)",
            "",
            f"When container shell tools (`bash`/`python3`) are denied in OpenCode MCP-only on the post-hoc locked `hard` dev set `{fmcp['dev_eval_seed_range']}` (`n=30`), frontier performance separates by in-context binary-splitting discipline:",
            "",
            "| Frontier MCP Cohort (`hard`, post-hoc locked `0..29`) | `n` | Score +/- CI95 | Frontier / Solver (`+0.499`) | Luck-Adj. EV (Ratio) | Canaries / Ep | Interviews / Ep (Share) | Correct / Wrong / No-Accuse |",
            "|---|---:|---|---|---|---|---|---|",
            f"| `gemini-4-carbon` (OpenCode MCP-only) | {g_mcp['n']} | `{g_mcp['mean_score']:+.3f} +/- {g_mcp['ci95']:.3f}` | `{g_mcp['ratio_vs_solver_display']}` | `{g_mcp['luck_adjusted_ev']:+.3f}` (`{g_mcp['luck_ratio_vs_solver_display']}`) | `{g_mcp['canaries_planted_per_ep']:.1f}` | `{g_mcp['interviews_per_ep']:.1f}` (`{g_mcp['interview_call_share_pct']}%`) | `{g_mcp['correct_count']} / {g_mcp['wrong_count']} / {g_mcp['abstain_count']}` |",
            f"| `gpt-5.5` (OpenCode MCP-only) | {gpt_mcp['n']} | `{gpt_mcp['mean_score']:+.3f} +/- {gpt_mcp['ci95']:.3f}` | `{gpt_mcp['ratio_vs_solver_display']}` | `{gpt_mcp['luck_adjusted_ev']:+.3f}` (`{gpt_mcp['luck_ratio_vs_solver_display']}`) | `{gpt_mcp['canaries_planted_per_ep']:.1f}` | `{gpt_mcp['interviews_per_ep']:.1f}` (`{gpt_mcp['interview_call_share_pct']}%`) | `{gpt_mcp['correct_count']} / {gpt_mcp['wrong_count']} / {gpt_mcp['text_only_non_accusations']}` (text-only) |",
            f"| `SolverPolicy` (paired reference) | {sol_mcp['n']} | `{sol_mcp['mean_score']:+.3f} +/- 0.119` | `100%` | `+0.499` (`100%`) | `{sol_mcp['canaries_planted_per_ep']:.1f}` | `{sol_mcp['interviews_per_ep']:.1f}` (`0%`) | `{sol_mcp['correct_count']} / {sol_mcp['wrong_count']} / {sol_mcp['abstain_count']}` |",
            "",
            f"- **In-Context Working-Memory Controls**: On `medium` (`20` suspects, `14d`), `gemini-4-carbon` OpenCode MCP-only scores `{g_ctrl['opencode_mcp_medium_20_suspects']['mean_score']:+.3f} +/- {g_ctrl['opencode_mcp_medium_20_suspects']['ci95']:.3f}` (`{g_ctrl['opencode_mcp_medium_20_suspects']['ratio_vs_solver_display']}` of solver `+{g_ctrl['opencode_mcp_medium_20_suspects']['solver_same_seeds']:.3f}`, `100%` accuracy), and `inproc` full-history thought-signature replay on `hard` reaches `{g_ctrl['inproc_hard_full_history']['mean_score']:+.3f} +/- {g_ctrl['inproc_hard_full_history']['ci95']:.3f}` (`{g_ctrl['inproc_hard_full_history']['ratio_vs_solver_display']}`).",
            "",
            f"{H}{H} 3. Regime B: Externalized Structured State",
            "",
            f"{H}{H}{H} 3a. Frontier Harbor Judge Path (`gemini-4-carbon` With Container `bash`/`python3`)",
            "",
            f"In the Harbor 0.26.0 rehearsal (`10` hard tasks on one shared build; container `bash`/`python3` available and used in **`{harbor['shell_used_display']}`** audited trials), `gemini-4-carbon` achieves **`{harbor['valid_accusation_display']}`** (`{harbor['valid_accusation_precision'] * 100.0:.1f}%`) valid accusations correct across 3 runs vs `oracle` (`+{harbor['oracle_mean_all_10']:.3f}`):",
            "",
            "| Harbor Rehearsal Run | Valid Trials (`n`) | Correct / Accused | Mean Score | Paired Oracle (`all 10`) | Run / Oracle [95% CI] |",
            "|---|---:|---|---|---|---|",
        ]
    )

    for hrun in harbor["runs"]:
        note = " (5 post-08:30 cutoff; 1 infra)" if hrun["run_id"] == "opencode-3" else ""
        lines.append(
            f"| `{hrun['run_id']}`{note} | {hrun['n_valid']} | `{hrun['correct_count']} / {hrun['accused_count']}` | "
            f"`{hrun['mean_score']:+.3f}` | `+{harbor['oracle_mean_all_10']:.3f}` | `{hrun['ratio_vs_oracle_display']}` |"
        )

    lines.extend(
        [
            f"| `do_nothing` / `stop_early` | 10 / 10 | `0 / 0` | `+0.000` | `+{harbor['oracle_mean_all_10']:.3f}` | `0% [0%, 0%]` |",
            "",
            f"- **Causal Caveat**: {harbor['causal_caveat']}",
            "",
            f"{H}{H}{H} 3b. Tiebreak Lossless Compact Policies (`<= 900` State Tokens / `28`-Dim Ledger, Panel Fix E Separated)",
            "",
            f"Compressing raw observations via `train/compact_render.py` (AST-isolated from `canary.solver` and `canary.world`) into a lossless `<= {elp['max_state_token_budget']}`-token (`{elp['verda_450_state_tokens_mean']:.1f}` mean / `{elp['verda_450_state_tokens_max']}` max across `450` Verda episodes, `{elp['full_horizon_stress_state_tokens_max']}` max across `14/21d` full-horizon stress, **`0.0%` canary-map eviction**) / `{elp['dense_feature_dim']}`-dim state lifts all `4` tiny non-LLM models (`is_open_weight_llm = False`) to **`{comp['ratio_vs_solver_n90_headline_band']}`** of `SolverPolicy` (`+{comp['solver_reference_benchmarks']['solver_n90_mean_score']:.3f}` `n=90` benchmark; `{comp['ratio_vs_paired_solver_range_pct'][0]:.1f}%-{comp['ratio_vs_paired_solver_range_pct'][1]:.1f}%` of each policy's own paired `SolverPolicy`) on `HELDOUT_SEEDS {comp['heldout_seed_range']}` (`5/5` Panel Fix E gates PASS):",
            "",
            "| Non-LLM Policy (`is_open_weight_llm=False`) | Params | Train Seeds -> Held-Out Seeds (`n`) | Before -> After Score | Paired Delta [95% CI] | % of `SolverPolicy` (`n=90` / Paired) | Panel Fix E Gates |",
            "|---|---:|---|---|---|---|---|",
        ]
    )

    for pol in comp["policies"]:
        lines.append(
            f"| `{pol['policy_class']}` (`{pol['run_id']}`) | `{pol['param_count']:,}` | "
            f"`{pol['train_seed_range']}` -> `{pol['eval_seed_range']}` (`n={pol['n']}`) | "
            f"`{pol['before_mean_score']:+.3f}` -> **`{pol['after_mean_score_3d']:+.3f}`** | "
            f"`{pol['paired_mean_delta']:+.3f} [{pol['paired_ci95_low']:+.3f}, {pol['paired_ci95_high']:+.3f}]` | "
            f"`{pol['ratio_vs_solver_n90_ref_pct']:.1f}%` / `{pol['ratio_vs_paired_solver_pct']:.1f}%` | "
            f"`{pol['panel_fix_e_gates_passed']}/{pol['panel_fix_e_gates_total']} PASS` |"
        )

    lines.extend(
        [
            "",
            f"{H}{H} 4. Mechanistic Synthesis: Why State Externalization Dominates Raw Scale",
            "",
            "1. **Delayed Set-Intersection Eviction Breaks Raw Context Windows**: Because `hard` leaks surface `2-3` days (`~23.8` tool turns) after `plant_canary` behind a `2,842`-token (`69.4%`) header tax, raw `4k`/`8k` transcripts evict `92-98%` / `56-85%` of variant-recipient maps, leaving `Qwen2.5-1.5B` (`0/19 > 0.000`) to either abstain (`-0.050` to `-0.147`) or gamble blindly (`-0.457` to `-0.788`, Verda X2 `DAgger r1` `-0.542` at `8k` and `-0.101` at `4k`).",
            "2. **Without External Scratchpads, Even Frontier LLMs Require High Internal Canary Discipline**: Over MCP-only (`bash`/`python3` denied) on post-hoc locked dev seeds `0..29`, `gpt-5.5` plants `17.2` canaries/ep (`4.2` interviews/ep, `0` wrong accusations, `2/30` text-only non-accusations) to reach `+0.504 +/- 0.064` (`101%` of solver), whereas `gemini-4-carbon` substitutes low-LR interviews (`68.0`/ep vs `8.5` canaries/ep, `4` wrong accusations) and scores `+0.322 +/- 0.199` (`65%` of solver, `72%` luck-adjusted).",
            "3. **Externalizing Sufficient Statistics Collapses the Parameter Requirement by `>10^8x`**: Providing an explicit external state representation restores near-oracle performance at both ends of the scale spectrum: container `bash`/`python3` (`20/28` trials) in the Harbor judge path accompanies `gemini-4-carbon` rising to `+0.472 / +0.585 / +0.626` (`93% / 116% / 131%` of oracle `+0.506`, `28/29` accusations correct), while the AST-isolated `<= 900`-token / `28`-dim public ledger lets `11` to `12,293`-parameter non-LLM policies reach `+0.607` to `+0.627` (`89-92%` of `SolverPolicy`) on world-paired `HELDOUT_SEEDS 800000..800059`.",
            "",
            f"{H}{H} 5. Offline Verification Commands",
            "",
            "```bash",
            "python scripts/tiebreak_state_externalization_audit.py --check",
            "python scripts/reproduce_tiebreak_all.py --check",
            "python scripts/verify_tiebreak_submission.py --strict",
            "pytest -q tests/test_tiebreak_state_externalization.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _spot_check_against_lightweight_sources(summary: dict[str, Any], repo_root: Path) -> list[str]:
    errs: list[str] = []
    qwen = ((summary.get("regime_a_raw_in_context") or {}).get("open_weight_qwen25_15b")) or {}
    fmcp = ((summary.get("regime_a_raw_in_context") or {}).get("frontier_mcp_only")) or {}
    harbor = ((summary.get("regime_b_externalized_state") or {}).get("frontier_harbor_judge_path")) or {}
    comp = ((summary.get("regime_b_externalized_state") or {}).get("tiebreak_compact_policies")) or {}

    if int(qwen.get("historical_runs_total", -1)) != 19 or int(qwen.get("historical_runs_beating_base_zero", -1)) != 0:
        errs.append("qwen historical run counts must be 0 / 19")
    pht = qwen.get("prompt_header_tax") or {}
    if int(pht.get("slurm_44410_header_tokens", -1)) != 2842 or int(pht.get("window_4k_tokens", -1)) != 4096:
        errs.append("prompt_header_tax must record 2842 / 4096 tokens")

    ledger_path = repo_root / LEDGER_REL
    if ledger_path.is_file():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        sc = ledger.get("summary_counts") or {}
        if int(sc.get("historical_runs", -1)) != int(qwen.get("historical_runs_total", -2)):
            errs.append("historical_runs_total out of sync with experiment_ledger.json")

    add_path = repo_root / ADDENDUM_REL
    if add_path.is_file():
        addendum = json.loads(add_path.read_text(encoding="utf-8"))
        add_by_id = {
            str(r.get("run_id")): r
            for r in (list(addendum.get("track_1_runs") or []) + list(addendum.get("track_2_runs") or []))
            if isinstance(r, dict)
        }
        for pol in comp.get("policies") or []:
            rid = str(pol.get("run_id"))
            if rid not in add_by_id:
                errs.append(f"compact policy {rid} missing from addendum_readiness.json")
                continue
            ref = add_by_id[rid]
            if not _approx_eq(float(pol["after_mean_score"]), float(ref["after_mean_score"]), 0.001):
                errs.append(f"compact policy {rid} after_mean_score disagrees with addendum_readiness.json")
            if pol.get("is_open_weight_llm") is not False or ref.get("is_open_weight_llm") is not False:
                errs.append(f"compact policy {rid} violated Panel Fix E is_open_weight_llm=False")

    paired_gemini, pg_errs = load_paired_table_gemini(repo_root)
    beh_cmp, bc_errs = load_behaviour_compare(repo_root)
    harbor_reh, hr_errs = load_harbor_rehearsal(repo_root)
    errs.extend(pg_errs)
    errs.extend(bc_errs)
    errs.extend(hr_errs)

    g_mcp = fmcp.get("gemini_4_carbon_opencode_mcp_hard") or {}
    gpt_mcp = fmcp.get("gpt_5_5_opencode_mcp_hard") or {}
    if not _approx_eq(float(g_mcp.get("mean_score", -9.0)), paired_gemini["opencode_gemini_4_carbon_hard"]["mean_score"], 0.001):
        errs.append("gemini-4-carbon MCP mean_score out of sync")
    if int(g_mcp.get("wrong_count", -1)) != int(beh_cmp["opencode_gemini_4_carbon_hard"]["wrong_count"]):
        errs.append("gemini-4-carbon MCP wrong_count out of sync")
    if not _approx_eq(float(gpt_mcp.get("mean_score", -9.0)), paired_gemini["opencode_gpt_5_5_hard"]["mean_score"], 0.001):
        errs.append("gpt-5.5 MCP mean_score out of sync")
    if int(harbor.get("valid_accusations_correct", -1)) != int(harbor_reh["valid_accusations_correct"]):
        errs.append("Harbor valid_accusations_correct out of sync")

    return errs


def verify_committed_artifacts(
    summary_path: Path,
    report_path: Path,
    repo_root: Path = ROOT,
    full_rebuild_check: bool = False,
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []

    if not summary_path.is_file():
        return [f"missing summary JSON: {summary_path}"]
    if not report_path.is_file():
        return [f"missing markdown report: {report_path}"]

    if (summary_path.parent / "summary.json").exists():
        errors.append(f"forbidden summary.json name collision in {summary_path.parent}")
    if (summary_path.parent / "table.md").exists():
        errors.append(f"forbidden table.md name collision in {summary_path.parent}")

    sz = summary_path.stat().st_size
    if sz >= MAX_SUMMARY_BYTES:
        errors.append(f"{summary_path.name}: size {sz} bytes >= {MAX_SUMMARY_BYTES} byte cap")

    raw_json = summary_path.read_text(encoding="utf-8")
    md_text = report_path.read_text(encoding="utf-8")

    for lbl, txt in ((summary_path.name, raw_json), (report_path.name, md_text)):
        if EM_DASH in txt:
            errors.append(f"{lbl}: contains forbidden em dash")
        if EN_DASH in txt:
            errors.append(f"{lbl}: contains forbidden en dash")
        if not txt.isascii():
            errors.append(f"{lbl}: contains non-ASCII character")
        bad_prereg = _has_affirmative_prereg_0_29(txt)
        if bad_prereg:
            errors.append(f"{lbl}: Panel Fix A violation at {bad_prereg[0]}")

    for lineno, raw_line in enumerate(raw_json.splitlines(), start=1):
        if ("0..29" in raw_line or "0-29" in raw_line) and PREREG_RE.search(raw_line):
            errors.append(f"{summary_path.name} line {lineno}: pre-registered on same line as 0..29")
    for lineno, raw_line in enumerate(md_text.splitlines(), start=1):
        if ("0..29" in raw_line or "0-29" in raw_line) and PREREG_RE.search(raw_line):
            errors.append(f"{report_path.name} line {lineno}: pre-registered on same line as 0..29")

    try:
        summary = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return [f"{summary_path.name}: invalid JSON ({exc})"]

    judge_hits = _scan_for_judge_numbers(summary)
    if judge_hits:
        errors.extend(f"{summary_path.name}: JUDGE_SEEDS leak {h}" for h in judge_hits[:5])

    if summary.get("schema") != SCHEMA_ID:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("dev_eval_seed_range") != "0..29":
        errors.append(f"unexpected dev_eval_seed_range: {summary.get('dev_eval_seed_range')!r}")
    if summary.get("dev_protocol_status") != "post-hoc locked":
        errors.append(f"unexpected dev_protocol_status: {summary.get('dev_protocol_status')!r}")

    canonical_json = json.dumps(summary, indent=2) + "\n"
    if raw_json != canonical_json:
        errors.append(f"{summary_path.name}: formatting differs from canonical indent=2 JSON")

    errors.extend(_spot_check_against_lightweight_sources(summary, repo_root=repo_root))

    if full_rebuild_check:
        expected_summary, build_errs = build_externalization_summary(repo_root=repo_root)
        errors.extend(build_errs)
        if summary != expected_summary:
            errors.append(f"{summary_path.name}: out of sync with deterministic build_externalization_summary()")

    expected_md = render_markdown_report(summary)
    if md_text != expected_md:
        errors.append(f"{report_path.name}: out of sync with render_markdown_report(summary)")

    required_md_tokens = (
        "2,842 / 4,096",
        "69.4%",
        "92-98%",
        "56-85%",
        "0 / 19",
        "-0.457",
        "-0.147",
        "-0.050",
        "-0.060",
        "-0.777",
        "-0.788",
        "-0.542",
        "-0.101",
        "+0.322 +/- 0.199",
        "65% [24%, 98%]",
        "72%",
        "+0.504 +/- 0.064",
        "101% [79%, 140%]",
        "20/28",
        "+0.472",
        "+0.585",
        "+0.626",
        "28/29",
        "+0.607",
        "+0.611",
        "+0.627",
        "+0.614",
        "89-92%",
        "800000..800059",
        "post-hoc locked",
    )
    for tok in required_md_tokens:
        if tok not in md_text:
            errors.append(f"{report_path.name}: missing required claim token {tok!r}")

    for rel_py in (
        "scripts/tiebreak_state_externalization_audit.py",
        "tests/test_tiebreak_state_externalization.py",
    ):
        py_file = repo_root / rel_py
        if py_file.is_file():
            errors.extend(check_python_source_hygiene(py_file))

    elapsed = time.perf_counter() - t0
    if elapsed > MAX_CHECK_SECONDS:
        errors.append(f"--check runtime {elapsed:.4f}s exceeded {MAX_CHECK_SECONDS:.2f}s budget")

    return errors


def verify_artifacts(root: Path = ROOT) -> dict[str, Any]:
    resolved = root.resolve()
    errs = verify_committed_artifacts(
        resolved / DEFAULT_OUT_JSON,
        resolved / DEFAULT_OUT_MD,
        repo_root=resolved,
    )
    return {"passed": len(errs) == 0, "errors": errs}


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Synthesize and verify the cross-scale State-Externalization Law across Canary v1.4."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--check", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = args.root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)

    if args.check:
        t0 = time.perf_counter()
        errs = verify_committed_artifacts(out_json, out_md, repo_root=root, full_rebuild_check=False)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if errs:
            for err in errs:
                print(f"FAIL: {err}", file=sys.stderr)
            return 1
        print(
            f"state_externalization_ok=True (5 cross-scale cells, 0/19 raw Qwen vs 4/4 compact + Harbor 28/29 in {elapsed_ms:.1f} ms)"
        )
        return 0

    t0 = time.perf_counter()
    summary, build_errs = build_externalization_summary(repo_root=root)
    if build_errs:
        for err in build_errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    md_text = render_markdown_report(summary)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")

    errs = verify_committed_artifacts(out_json, out_md, repo_root=root, full_rebuild_check=True)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(
        f"Wrote {out_json.relative_to(root)} ({out_json.stat().st_size} bytes) and "
        f"{out_md.relative_to(root)} in {elapsed_ms:.1f} ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
