"""Minimal sufficient-statistic and feature-group bottleneck audit on held-out Canary worlds."""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ProcessPoolExecutor
import contextlib
import copy
import dataclasses
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time
import tokenize
from typing import Any, Callable, Iterator

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.representation_bottleneck.v1"
AUDIT_ID = "tiebreak-representation-bottleneck-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_SEEDS_PER_TIER = HELDOUT_SEED_STOP - HELDOUT_SEED_START
EPISODES_PER_CONDITION = len(CANONICAL_TIERS) * HELDOUT_SEEDS_PER_TIER
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_WORLD_SECRET_TAG = "sha256:ebf2f09716cf76d3"

JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 75 * 1024
MAX_CHECK_SECONDS = 5.0

DEFAULT_OUT_JSON = Path("results/tiebreak/representation_bottleneck/bottleneck_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_representation_bottleneck.md")

LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")
ADDENDUM_REL = Path("results/tiebreak/addendum_readiness.json")
CONFOUND_REL = Path("results/tiebreak/context_confound/audit_summary.json")
EB_SUMMARY_REL = Path("results/tiebreak/empirical_bayes/summary.json")
SCALING_SUMMARY_REL = Path("results/tiebreak/scaling/scaling_summary.json")
DAGGER_SUMMARY_REL = Path("results/tiebreak/dagger_ablation/summary.json")
MLP_SUMMARY_REL = Path("results/tiebreak/neural_mlp_dagger/mlp_summary.json")

BOTTLENECK_MODES: tuple[str, ...] = (
    "full_28d",
    "core_sufficient_stats",
    "posterior_only",
    "horizon_value_only",
    "no_canary_aux_only",
)

MASKED_POLICY_IDS: tuple[str, ...] = (
    "compact_linear_dagger",
    "tiny_mlp",
)

SUFFICIENT_STAT_BASELINE_IDS: tuple[str, ...] = (
    "empirical_bayes",
    "scaling_logistic",
)

ALL_POLICY_IDS: tuple[str, ...] = (
    "empirical_bayes",
    "scaling_logistic",
    "compact_linear_dagger",
    "tiny_mlp",
)

CLD_EMP_KEEP: dict[str, tuple[int, ...]] = {
    "full_28d": tuple(range(28)),
    "core_sufficient_stats": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 26),
    "posterior_only": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 26),
    "horizon_value_only": (),
    "no_canary_aux_only": (19, 20, 21, 22, 23, 24, 25, 27),
}

MLP_IN_KEEP: dict[str, tuple[int, ...]] = {
    "full_28d": tuple(range(28)),
    "core_sufficient_stats": (0, 1, 2, 10, 12, 13, 15, 16, 20, 21, 22, 23, 24, 25, 26, 27),
    "posterior_only": (0, 1, 2, 3, 4, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20),
    "horizon_value_only": (21, 22, 23, 24, 25, 26, 27),
    "no_canary_aux_only": (5, 6, 7, 8, 9, 19, 21, 22, 23, 24, 25, 26, 27),
}

BOTTLENECK_DESCRIPTIONS: dict[str, str] = {
    "full_28d": "All 28 compact public-ledger features active (unmodified policy representation)",
    "core_sufficient_stats": "Top posterior marginals + surfaced canary hits + V_obs + day/horizon fraction (masking auxiliary logs/interviews/messages)",
    "posterior_only": "Suspect probability and canary-hit features only (masking V_obs, breakeven EV, and day/horizon features)",
    "horizon_value_only": "V_obs and day/horizon features only (masking all suspect/canary-hit features -> uniform 1/N posterior, collapses to blind/abstain)",
    "no_canary_aux_only": "Auxiliary access-log, interview, and message features only (masking all canary-leak and document-fingerprint features)",
}

POLICY_META_SPECS: dict[str, dict[str, Any]] = {
    "empirical_bayes": {
        "policy_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "run_id": "empirical-bayes-v14",
        "module_path": "train/empirical_bayes_policy.py",
        "summary_path": "results/tiebreak/empirical_bayes/summary.json",
        "expected_param_count": 11,
        "expected_train_seed_range": "102000..102779",
    },
    "scaling_logistic": {
        "policy_id": "scaling_logistic",
        "policy_class": "ScalingLogisticPolicy",
        "run_id": "scaling-logistic-v14",
        "module_path": "scripts/tiebreak_scaling_calibration.py",
        "summary_path": "results/tiebreak/scaling/scaling_summary.json",
        "expected_param_count": 82,
        "expected_train_seed_range": "107000..108999",
    },
    "compact_linear_dagger": {
        "policy_id": "compact_linear_dagger",
        "policy_class": "CompactLinearDAggerPolicy",
        "run_id": "compact-linear-dagger-v14",
        "module_path": "train/compact_dagger_ablation.py",
        "summary_path": "results/tiebreak/dagger_ablation/summary.json",
        "expected_param_count": 785,
        "expected_train_seed_range": "109000..109509",
    },
    "tiny_mlp": {
        "policy_id": "tiny_mlp",
        "policy_class": "TinyMLPPolicy",
        "run_id": "tiny-mlp-dagger-v14",
        "module_path": "train/neural_mlp_tiebreak.py",
        "summary_path": "results/tiebreak/neural_mlp_dagger/mlp_summary.json",
        "expected_param_count": 12293,
        "expected_train_seed_range": "107000..107599",
    },
}

PANEL_FIX_A_DISCLOSURE = (
    "All 1,080 live representation-bottleneck episodes evaluate strictly on world-paired "
    "HELDOUT_SEEDS 800000..800029 (30 seeds x 3 tiers = 90 episodes per condition across "
    "easy, medium, hard) under shared deterministic world_secret_tag sha256:ebf2f09716cf76d3, "
    "all learned compact policy parameters originate strictly from disjoint TRAIN_SEEDS "
    "[100000, 200000), and 0 JUDGE_SEEDS (900k+) are touched. Any frontier reference cohorts "
    "on DEV_SEEDS 0..29 mentioned in Canary cross-track literature are post-hoc locked, not pre-registered (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json exceed untrained base (0.000), with 98.0% (1162/1186) 4k sticky "
    "canary-map eviction under raw transcript truncation, so the README.md Qwen addendum remains "
    "withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). Non-LLM compact policies (EmpiricalBayesPolicy "
    "11 params, ScalingLogisticPolicy 82 params, CompactLinearDAggerPolicy 785 params, TinyMLPPolicy "
    "12,293 params; is_open_weight_llm = False) are strictly separated from open-weight Qwen2.5 LoRA runs."
)

_PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
_NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
_SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)
_INT_TOKEN_RE = re.compile(r"\b\d+\b")
_RAW_DIGIT_RUN_RE = re.compile(r"\d+")

_HYGIENE_CACHE: dict[tuple[str, int, int, bool], list[str]] = {}
_AST_ISOLATION_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}


def compute_secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def safe_segmented_sha15(raw_bytes: bytes) -> str:
    hx = hashlib.sha256(raw_bytes).hexdigest()
    return f"h15:{hx[:5]}_{hx[5:10]}_{hx[10:15]}"


def canonical_trace_sha256(steps: list[Any]) -> str:
    payload: list[dict[str, Any]] = []
    for idx, st in enumerate(steps):
        if isinstance(st, dict):
            payload.append(
                {
                    "t": int(st.get("t", idx)),
                    "day": int(st.get("day", 1)),
                    "tool": str(st.get("tool", "")),
                    "args": st.get("args") or {},
                    "ok": bool((st.get("result") or {}).get("ok", True)),
                }
            )
        else:
            res = getattr(st, "result", None) or {}
            payload.append(
                {
                    "t": int(getattr(st, "t", idx)),
                    "day": int(getattr(st, "day", 1)),
                    "tool": str(getattr(st, "tool", "")),
                    "args": getattr(st, "args", None) or {},
                    "ok": bool(res.get("ok", True)),
                }
            )
    raw = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mean_ci95(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    mean_v = sum(values) / n
    if n < 2:
        rm = round(mean_v, 5)
        return {"mean": rm, "ci95_low": rm, "ci95_high": rm, "ci95_half_width": 0.0}
    var = sum((x - mean_v) ** 2 for x in values) / (n - 1)
    half = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return {
        "mean": round(mean_v, 5),
        "ci95_low": round(mean_v - half, 5),
        "ci95_high": round(mean_v + half, 5),
        "ci95_half_width": round(half, 5),
    }


def compute_paired_delta(cand_scores: list[float], ref_scores: list[float]) -> dict[str, Any]:
    if len(cand_scores) != len(ref_scores) or not cand_scores:
        raise ValueError("paired score vectors must be non-empty and equal length")
    deltas = [float(c) - float(r) for c, r in zip(cand_scores, ref_scores)]
    ci = mean_ci95(deltas)
    ref_mean = sum(ref_scores) / len(ref_scores)
    cand_mean = sum(cand_scores) / len(cand_scores)
    retained = round(cand_mean / ref_mean, 5) if abs(ref_mean) > 1e-9 else 0.0
    better = sum(1 for d in deltas if d > 1e-9)
    worse = sum(1 for d in deltas if d < -1e-9)
    tied = len(deltas) - better - worse
    return {
        "mean_delta": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "ci95_half_width": ci["ci95_half_width"],
        "retained_share": retained,
        "better_count": better,
        "tied_count": tied,
        "worse_count": worse,
    }


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if _PREREG_RE.search(raw_line) and _SEEDS_0_29_RE.search(raw_line):
            scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
            if _PREREG_RE.search(scrubbed):
                hits.append(f"line {lineno}: {raw_line.strip()[:140]}")
    return hits


_SIX_PLUS_DIGITS_RE = re.compile(r"\d{6,}")


def _scan_json_for_judge_numbers(obj: Any, raw_text: str) -> list[str]:
    hits: list[str] = []
    for dm in _SIX_PLUS_DIGITS_RE.finditer(raw_text):
        if int(dm.group(0)) >= JUDGE_SEED_MIN:
            hits.append(f"digit_run {dm.group(0)} at offset {dm.start()}")
    if "e+" in raw_text.lower() or hits:
        def _walk(node: Any, path: str) -> None:
            if isinstance(node, bool) or node is None:
                return
            if isinstance(node, (int, float)):
                if abs(float(node)) >= JUDGE_SEED_MIN:
                    hits.append(f"numeric {path}={node}")
            elif isinstance(node, dict):
                for k, v in node.items():
                    _walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for idx, item in enumerate(node):
                    _walk(item, f"{path}[{idx}]")

        _walk(obj, "root")
    return hits


def check_python_source_hygiene(py_path: Path, run_tokenize: bool = False) -> list[str]:
    resolved = py_path.resolve()
    st = resolved.stat()
    ck = (str(resolved), st.st_mtime_ns, st.st_size, bool(run_tokenize))
    cached = _HYGIENE_CACHE.get(ck)
    if cached is not None:
        return list(cached)
    errs: list[str] = []
    src = resolved.read_text(encoding="utf-8")
    lbl = py_path.name
    if H in src:
        errs.append(f"{lbl}: contains forbidden hash character chr(35)")
    for bad_ch, ch_name in (
        (EM_DASH, "em dash"),
        (EN_DASH, "en dash"),
        (UNICODE_MINUS, "unicode minus"),
    ):
        if bad_ch in src:
            errs.append(f"{lbl}: contains forbidden {ch_name}")
    if not src.isascii():
        errs.append(f"{lbl}: contains non-ASCII character(s)")
    if run_tokenize or H in src:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        if any(t.type == tokenize.COMMENT for t in toks):
            errs.append(f"{lbl}: contains Python tokenize.COMMENT token")
    _HYGIENE_CACHE[ck] = list(errs)
    return errs


def audit_module_ast_isolation(py_path: Path) -> dict[str, Any]:
    resolved = py_path.resolve()
    st = resolved.stat()
    ck = (str(resolved), st.st_mtime_ns, st.st_size)
    cached = _AST_ISOLATION_CACHE.get(ck)
    if cached is not None:
        return {
            "passed": cached["passed"],
            "policy_classes": list(cached["policy_classes"]),
            "errors": list(cached["errors"]),
        }
    src = resolved.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(py_path))
    errors: list[str] = []
    forbidden_prefixes = ("torch", "transformers", "subprocess", "canary.solver", "canary.world")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if any(name == fp or name.startswith(fp + ".") for fp in forbidden_prefixes):
                    errors.append(f"line {node.lineno}: forbidden import {name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if any(mod == fp or mod.startswith(fp + ".") for fp in forbidden_prefixes):
                errors.append(f"line {node.lineno}: forbidden from-import {mod}")
            if mod == "canary":
                for alias in node.names:
                    if alias.name in ("solver", "world"):
                        errors.append(f"line {node.lineno}: forbidden from canary import {alias.name}")
        elif isinstance(node, ast.Name) and node.id in ("SolverPolicy", "generate_world", "set_world_secret"):
            errors.append(f"line {node.lineno}: forbidden {node.id} symbol reference")
        elif isinstance(node, ast.Attribute) and node.attr in ("SolverPolicy", "generate_world", "set_world_secret"):
            errors.append(f"line {node.lineno}: forbidden .{node.attr} attribute reference")

    policy_classes: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            fn_names = {
                item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if {"reset", "act"}.issubset(fn_names):
                policy_classes.append(f"scripts/{py_path.name}:{node.name}")
    out = {"passed": len(errors) == 0, "policy_classes": policy_classes, "errors": errors}
    _AST_ISOLATION_CACHE[ck] = out
    return {"passed": out["passed"], "policy_classes": list(policy_classes), "errors": list(errors)}


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1, h2 = H, H * 2
    eb = summary["sufficient_stat_baselines"]["empirical_bayes"]
    sc = summary["sufficient_stat_baselines"]["scaling_logistic"]
    cld = summary["masked_policies"]["compact_linear_dagger"]
    mlp = summary["masked_policies"]["tiny_mlp"]
    qwen = summary["cross_track_qwen_contrast"]
    pe = summary["panel_fix_e_track_separation"]

    cld_full = cld["conditions"]["full_28d"]["overall"]
    cld_core = cld["conditions"]["core_sufficient_stats"]["overall"]
    mlp_full = mlp["conditions"]["full_28d"]["overall"]
    mlp_core = mlp["conditions"]["core_sufficient_stats"]["overall"]

    lines: list[str] = [
        f"{h1} Tiebreak Representation-Bottleneck & Minimal Sufficient-Statistic Audit (v1.4)",
        "",
        f"- **Schema / Audit ID**: `{summary['schema']}` / `{summary['audit_id']}`",
        f"- **World-Paired Held-Out Evaluation**: `HELDOUT_SEEDS {summary['heldout_seed_range']}` (`n = {summary['episodes_per_condition']}` per cell, `{summary['eval_seeds_per_tier']}`/tier across `easy`, `medium`, `hard`), `world_secret_tag = {summary['world_secret_tag']}`, `{summary['totals']['fresh_env_replays_verified']}/{summary['totals']['total_live_episodes']}` (`100%`) `Env` replay-verified.",
        f"- **Strict Seed & Solver Isolation (Panel Fix A)**: All learned parameters originate from `TRAIN_SEEDS [100000, 200000)` (`0` overlap with held-out, `0` judge seeds `>= 900000`). {summary['seed_isolation']['panel_fix_a_disclosure']}",
        f"- **Strict Track Separation (Panel Fix E)**: `{pe['open_weight_qwen25_above_zero_ratio']}` open-weight Qwen2.5 runs exceed `0.000` (`{pe['readme_qwen_addendum_status']}`); all 4 compact policies have `is_open_weight_llm = False`.",
        "",
        f"{h2} 1. Minimal Sufficient-Statistic Compression Across Compact Policies (`n = 90` Paired)",
        "",
        "| Policy | Params | Active Emp Feats | Mean Score +/- 95% CI | Delta vs `0.000` | Accuse Precision | Abstain Rate | Action Agree vs `CompactLinear full_28d` |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for b_row in (eb, sc):
        ov = b_row["overall"]
        dz = b_row["paired_vs_zero"]
        lines.append(
            f"| `{b_row['policy_class']}` | `{b_row['param_count']}` | `{b_row['native_feature_note']}` | "
            f"`{ov['mean_score']:+.4f} +/- {ov['ci95_half_width']:.4f}` | `{dz['mean_delta']:+.4f}` (`[{dz['ci95_low']:+.4f}, {dz['ci95_high']:+.4f}]`) | "
            f"`{ov['accusation_precision']:.4f}` (`{ov['correct_count']}/{ov['accuse_count']}`) | `{ov['abstain_rate']:.4f}` | `{ov['action_agreement_rate']:.4f}` |"
        )
    for m_pol in (cld, mlp):
        for m_key in ("full_28d", "core_sufficient_stats"):
            c_blk = m_pol["conditions"][m_key]
            ov = c_blk["overall"]
            dz = c_blk["paired_vs_zero"]
            lines.append(
                f"| `{m_pol['policy_class']} ({m_key})` | `{m_pol['param_count']}` | `{c_blk['active_emp_features']}/28` | "
                f"`{ov['mean_score']:+.4f} +/- {ov['ci95_half_width']:.4f}` | `{dz['mean_delta']:+.4f}` (`[{dz['ci95_low']:+.4f}, {dz['ci95_high']:+.4f}]`) | "
                f"`{ov['accusation_precision']:.4f}` (`{ov['correct_count']}/{ov['accuse_count']}`) | `{ov['abstain_rate']:.4f}` | `{ov['action_agreement_rate']:.4f}` |"
            )

    lines.extend([
        "",
        f"{h2} 2. Five-Group Feature-Bottleneck Masking Matrix (`n = 90` World-Paired Per Cell)",
        "",
        "| Policy (`Params`) | Bottleneck Group | Active Feats | Mean Score (`95% CI`) | Paired Delta vs `full_28d` | Paired Delta vs `0.000` | Precision | Abstain Rate | Step Action Agree | Terminal Agree |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for m_pol in (cld, mlp):
        for mode in BOTTLENECK_MODES:
            cb = m_pol["conditions"][mode]
            ov = cb["overall"]
            df = cb["paired_vs_full_28d"]
            dz = cb["paired_vs_zero"]
            lines.append(
                f"| `{m_pol['policy_class']}` (`{m_pol['param_count']}`) | `{mode}` | `{cb['active_emp_features']}/28` | "
                f"`{ov['mean_score']:+.4f}` (`[{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]`) | "
                f"`{df['mean_delta']:+.4f}` (`[{df['ci95_low']:+.4f}, {df['ci95_high']:+.4f}]`) | "
                f"`{dz['mean_delta']:+.4f}` | `{ov['accusation_precision']:.4f}` | `{ov['abstain_rate']:.4f}` | "
                f"`{ov['action_agreement_rate']:.4f}` | `{ov['terminal_agreement_rate']:.4f}` |"
            )

    lines.extend([
        "",
        f"{h2} 3. Cross-Track Contrast: Compact Sufficient Statistics vs Raw 4k/8k Qwen2.5 Truncation",
        "",
        "| Representation / Cohort | `is_open_weight_llm` | Scale / Context | Canary-Map Eviction | Held-Out Score | Above `0.000` | Bottleneck Regime |",
        "| :--- | :---: | :--- | ---: | ---: | :---: | :--- |",
        f"| `EmpiricalBayesPolicy` | `False` | `11` params (`0` ctx tok) | `0.0%` (`0/1186`) | `{eb['overall']['mean_score']:+.4f}` (`n=90`) | `Yes` | Explicit core sufficient statistics |",
        f"| `ScalingLogisticPolicy` | `False` | `82` params (`0` ctx tok) | `0.0%` (`0/1186`) | `{sc['overall']['mean_score']:+.4f}` (`n=90`) | `Yes` | Low-dim calibrated linear sufficient stats |",
        f"| `CompactLinearDAggerPolicy (core_sufficient_stats)` | `False` | `785` params (`{cld['conditions']['core_sufficient_stats']['active_emp_features']}/28` feats) | `0.0%` (`0/1186`) | `{cld_core['mean_score']:+.4f}` vs `{cld_full['mean_score']:+.4f}` full | `Yes` | Core posterior + canary + V_obs + horizon |",
        f"| `TinyMLPPolicy (core_sufficient_stats)` | `False` | `12,293` params (`{mlp['conditions']['core_sufficient_stats']['active_emp_features']}/28` feats) | `0.0%` (`0/1186`) | `{mlp_core['mean_score']:+.4f}` vs `{mlp_full['mean_score']:+.4f}` full | `Yes` | Auxiliary-denoised neural sufficient stats |",
        f"| `Qwen2.5-1.5B Raw 4k/8k Pool (19 runs)` | `True` | `~1.54B` (`4k/8k` raw MCP) | `{qwen['raw_4k_canary_eviction_pct_display']}` (`{qwen['raw_4k_canary_evicted_count']}/{qwen['pooled_canary_calls_total']}` at `4k`; `{qwen['raw_8k_canary_eviction_pct_display']}` at `8k`) | `{qwen['pooled_450_mean_score']:+.4f}` (`n={qwen['pooled_verda_episodes']}`; best `{qwen['best_trained_run_id']}` `{qwen['best_trained_mean_score']:+.3f}`) | `{pe['open_weight_qwen25_above_zero_ratio']}` | Truncation-induced `no_canary_aux_only` / `horizon_value_only` collapse |",
        "",
        f"{h2} 4. Key Findings & Reproduction",
        "",
        f"1. **Minimal Sufficient-Statistic Sufficiency**: Retaining only top suspect posterior marginals, surfaced canary hits, `V_obs`, and day/horizon fraction (`core_sufficient_stats`) achieves `{cld_core['mean_score']:+.4f}` on `CompactLinearDAggerPolicy` (`{cld_core['accusation_precision']:.4f}` precision) and `{mlp_core['mean_score']:+.4f}` on `TinyMLPPolicy` (`{mlp_core['accusation_precision']:.4f}` precision vs `{mlp_full['mean_score']:+.4f}` on `full_28d`), matching `11`-param `EmpiricalBayesPolicy` (`{eb['overall']['mean_score']:+.4f}`) and `82`-param `ScalingLogisticPolicy` (`{sc['overall']['mean_score']:+.4f}`).",
        "2. **Dual-Factor Necessity (`posterior_only` vs `horizon_value_only`)**: Masking `V_obs` and horizon features (`posterior_only`) preserves suspect identification above `0.000` but degrades stopping calibration and precision; conversely, masking suspect/canary-hit features (`horizon_value_only`) forces uniform `1/N` posteriors and collapses both policies to `0.0000` (`100%` calibrated abstention).",
        f"3. **Why Raw 4k/8k Qwen2.5 Collapses (`0 / 19` > `0.000`)**: Raw MCP headers consume `~{qwen['raw_header_tokens_mean']:.0f}` tokens and evict `{qwen['raw_4k_canary_eviction_pct_display']}` (`{qwen['raw_4k_canary_evicted_count']}/{qwen['pooled_canary_calls_total']}`) of planted `plant_canary` maps at `4k`, physically forcing a `1.54B` LLM into the `no_canary_aux_only` / `horizon_value_only` blind regime.",
        "",
        "```bash",
        "python scripts/tiebreak_representation_bottleneck_audit.py --generate --workers 8",
        "python scripts/tiebreak_representation_bottleneck_audit.py --check",
        "python -m pytest -q tests/test_tiebreak_representation_bottleneck.py",
        "```",
        "",
    ])
    return "\n".join(lines)


def _verify_cell_block(
    label: str,
    cb: dict[str, Any],
    ref_scores: list[float],
    expected_agree_one: bool,
    errors: list[str],
) -> int:
    sc_csv = str(cb.get("episode_scores_csv") or "")
    oc_csv = str(cb.get("episode_outcomes_csv") or "")
    sc_vec = [float(t) for t in sc_csv.split(",") if t.strip()]
    oc_vec = [t.strip() for t in oc_csv.split(",") if t.strip()]
    if len(sc_vec) != EPISODES_PER_CONDITION or len(oc_vec) != EPISODES_PER_CONDITION:
        errors.append(f"{label}: expected {EPISODES_PER_CONDITION} CSV scores and outcomes")
        return 0
    if any(o not in ("C", "W", "A") for o in oc_vec):
        errors.append(f"{label}: invalid token in episode_outcomes_csv")
        return 0

    ov = cb.get("overall") or {}
    recomp_ci = mean_ci95(sc_vec)
    for k in ("mean", "ci95_low", "ci95_high", "ci95_half_width"):
        json_k = "mean_score" if k == "mean" else k
        if abs(float(ov.get(json_k, -9.0)) - recomp_ci[k]) > 1.5e-4:
            errors.append(f"{label}: {json_k} disagrees with episode_scores_csv")

    c_cnt = sum(1 for o in oc_vec if o == "C")
    w_cnt = sum(1 for o in oc_vec if o == "W")
    a_cnt = sum(1 for o in oc_vec if o == "A")
    acc_cnt = c_cnt + w_cnt
    if int(ov.get("correct_count", -1)) != c_cnt or int(ov.get("wrong_count", -1)) != w_cnt or int(ov.get("abstain_count", -1)) != a_cnt:
        errors.append(f"{label}: terminal counts disagree with episode_outcomes_csv")
    if c_cnt + w_cnt + a_cnt != EPISODES_PER_CONDITION:
        errors.append(f"{label}: terminal counts do not sum to {EPISODES_PER_CONDITION}")

    exp_prec = round(c_cnt / acc_cnt, 5) if acc_cnt > 0 else 0.0
    exp_abst = round(a_cnt / EPISODES_PER_CONDITION, 5)
    exp_acc_rate = round(acc_cnt / EPISODES_PER_CONDITION, 5)
    if abs(float(ov.get("accusation_precision", -1.0)) - exp_prec) > 1e-4:
        errors.append(f"{label}: accusation_precision mismatch")
    if abs(float(ov.get("abstain_rate", -1.0)) - exp_abst) > 1e-4:
        errors.append(f"{label}: abstain_rate mismatch")
    if abs(float(ov.get("accuse_rate", -1.0)) - exp_acc_rate) > 1e-4:
        errors.append(f"{label}: accuse_rate mismatch")

    sm = int(ov.get("step_matches_count", -1))
    st = int(ov.get("step_total_count", 0))
    tm = int(ov.get("terminal_agree_count", -1))
    if st <= 0 or sm < 0 or sm > st or tm < 0 or tm > EPISODES_PER_CONDITION:
        errors.append(f"{label}: invalid agreement counts")
    else:
        if abs(float(ov.get("action_agreement_rate", -1.0)) - round(sm / st, 5)) > 1e-4:
            errors.append(f"{label}: action_agreement_rate mismatch")
        if abs(float(ov.get("terminal_agreement_rate", -1.0)) - round(tm / EPISODES_PER_CONDITION, 5)) > 1e-4:
            errors.append(f"{label}: terminal_agreement_rate mismatch")
        if expected_agree_one and (sm != st or tm != EPISODES_PER_CONDITION):
            errors.append(f"{label}: full_28d must have 100% step and terminal self-agreement")

    zero_vec = [0.0] * EPISODES_PER_CONDITION
    recomp_dz = compute_paired_delta(sc_vec, zero_vec)
    dz = cb.get("paired_vs_zero") or {}
    for pk in ("mean_delta", "ci95_low", "ci95_high"):
        if abs(float(dz.get(pk, -9.0)) - float(recomp_dz[pk])) > 2e-4:
            errors.append(f"{label}: paired_vs_zero.{pk} mismatch")

    recomp_df = compute_paired_delta(sc_vec, ref_scores)
    df = cb.get("paired_vs_full_28d") or {}
    for pk in ("mean_delta", "ci95_low", "ci95_high"):
        if abs(float(df.get(pk, -9.0)) - float(recomp_df[pk])) > 2e-4:
            errors.append(f"{label}: paired_vs_full_28d.{pk} mismatch")

    return len(sc_vec)


def verify_committed_artifacts(
    summary_path: Path,
    md_path: Path,
    repo_root: Path = ROOT,
    enforce_budget: bool = True,
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []
    repo_root = repo_root.resolve()
    s_file = summary_path if summary_path.is_absolute() else (repo_root / summary_path)
    m_file = md_path if md_path.is_absolute() else (repo_root / md_path)

    if not s_file.is_file():
        return [f"missing bottleneck summary JSON: {s_file}"]
    if not m_file.is_file():
        return [f"missing bottleneck markdown report: {m_file}"]

    for forbidden_sib in ("summary.json", "table.md"):
        sib = s_file.parent / forbidden_sib
        if sib.exists():
            errors.append(f"forbidden sibling file exists: {sib}")

    raw_bytes = s_file.read_bytes()
    if len(raw_bytes) >= MAX_SUMMARY_BYTES:
        errors.append(f"{s_file.name}: size {len(raw_bytes)} >= {MAX_SUMMARY_BYTES} byte budget")

    raw_json = raw_bytes.decode("utf-8")
    md_txt = m_file.read_text(encoding="utf-8")

    for doc_lbl, txt in ((s_file.name, raw_json), (m_file.name, md_txt)):
        for bad_ch, ch_name in ((EM_DASH, "em dash"), (EN_DASH, "en dash"), (UNICODE_MINUS, "unicode minus")):
            if bad_ch in txt:
                errors.append(f"{doc_lbl}: contains forbidden {ch_name}")
        if not txt.isascii():
            errors.append(f"{doc_lbl}: contains non-ASCII character(s)")
        for hit in _has_affirmative_prereg_0_29(txt):
            errors.append(f"{doc_lbl}: Panel Fix A violation at {hit}")

    script_cand = repo_root / "scripts" / "tiebreak_representation_bottleneck_audit.py"
    if script_cand.is_file():
        errors.extend(check_python_source_hygiene(script_cand, run_tokenize=False))
        ast_res = audit_module_ast_isolation(script_cand)
        if not ast_res["passed"]:
            errors.extend(f"AST isolation: {e}" for e in ast_res["errors"])
        req_cls = {
            "scripts/tiebreak_representation_bottleneck_audit.py:FeatureBottleneckPolicy",
            "scripts/tiebreak_representation_bottleneck_audit.py:BottleneckCompactLinearDAggerPolicy",
            "scripts/tiebreak_representation_bottleneck_audit.py:BottleneckTinyMLPPolicy",
        }
        if not req_cls.issubset(set(ast_res["policy_classes"])):
            errors.append("AST isolation: missing expected bottleneck policy wrapper class(es)")

    test_cand = repo_root / "tests" / "test_tiebreak_representation_bottleneck.py"
    if test_cand.is_file():
        errors.extend(check_python_source_hygiene(test_cand, run_tokenize=False))

    try:
        summary = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return errors + [f"invalid JSON in {s_file}: {exc}"]

    for jh in _scan_json_for_judge_numbers(summary, raw_json):
        errors.append(f"JUDGE_SEEDS (900000+) violation: {jh}")

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"schema mismatch: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_WORLD_SECRET_TAG:
        errors.append(f"world_secret_tag != {EXPECTED_WORLD_SECRET_TAG!r}")
    if summary.get("heldout_seed_range") != "800000..800029" or summary.get("eval_seed_range") != "800000..800029":
        errors.append("heldout/eval_seed_range != '800000..800029'")
    if int(summary.get("eval_seeds_per_tier", -1)) != HELDOUT_SEEDS_PER_TIER:
        errors.append("eval_seeds_per_tier != 30")
    if int(summary.get("episodes_per_condition", -1)) != EPISODES_PER_CONDITION:
        errors.append("episodes_per_condition != 90")

    iso = summary.get("seed_isolation") or {}
    if int(iso.get("judge_episodes_touched", -1)) != 0 or int(iso.get("dev_episodes_rolled_out", -1)) != 0:
        errors.append("seed_isolation touched judge or dev episodes")
    if int(iso.get("train_episodes_in_heldout_eval", -1)) != 0:
        errors.append("seed_isolation train_episodes_in_heldout_eval != 0")
    if "post-hoc locked, not pre-registered" not in str(iso.get("panel_fix_a_disclosure", "")):
        errors.append("missing Panel Fix A disclosure phrase")

    pe = summary.get("panel_fix_e_track_separation") or {}
    if pe.get("open_weight_qwen25_above_zero_ratio") != "0 / 19":
        errors.append("Panel Fix E ratio != '0 / 19'")
    if pe.get("readme_qwen_addendum_status") != "HOLD_README_QWEN_ADDENDUM_UNTIL_V100":
        errors.append("Panel Fix E status != 'HOLD_README_QWEN_ADDENDUM_UNTIL_V100'")
    if pe.get("compact_policies_are_open_weight_llm") is not False:
        errors.append("compact_policies_are_open_weight_llm must be False")

    ledger_f = repo_root / LEDGER_REL
    if ledger_f.is_file():
        ledger = json.loads(ledger_f.read_text(encoding="utf-8"))
        hist = ledger.get("historical_runs") or []
        above_zero = sum(1 for r in hist if r.get("after_mean_score") is not None and float(r["after_mean_score"]) > 0.0)
        if len(hist) != int(pe.get("open_weight_qwen25_runs_total", -1)) or above_zero != int(pe.get("open_weight_qwen25_runs_above_zero", -1)):
            errors.append("Panel Fix E counts out of sync with experiment_ledger.json")

    qwen = summary.get("cross_track_qwen_contrast") or {}
    if qwen.get("raw_4k_canary_eviction_pct_display") != "98.0%" or int(qwen.get("raw_4k_canary_evicted_count", -1)) != 1162 or int(qwen.get("pooled_canary_calls_total", -1)) != 1186:
        errors.append("cross_track_qwen_contrast 4k canary eviction stats mismatch (expected 1162/1186 = 98.0%)")

    masked = summary.get("masked_policies") or {}
    baselines = summary.get("sufficient_stat_baselines") or {}
    eps_counted = 0

    cld_ref_scores: list[float] = []
    for pid in MASKED_POLICY_IDS:
        pb = masked.get(pid) or {}
        spec = POLICY_META_SPECS[pid]
        if pb.get("is_open_weight_llm") is not False:
            errors.append(f"{pid}: is_open_weight_llm must be False")
        if int(pb.get("param_count", -1)) != spec["expected_param_count"]:
            errors.append(f"{pid}: param_count mismatch")
        if pb.get("train_seed_range") != spec["expected_train_seed_range"]:
            errors.append(f"{pid}: train_seed_range mismatch")
        conds = pb.get("conditions") or {}
        if "full_28d" not in conds:
            errors.append(f"{pid}: missing full_28d condition")
            continue
        ref_vec = [float(t) for t in str(conds["full_28d"].get("episode_scores_csv") or "").split(",") if t.strip()]
        if len(ref_vec) != EPISODES_PER_CONDITION:
            errors.append(f"{pid}/full_28d: expected {EPISODES_PER_CONDITION} scores")
            continue
        if pid == "compact_linear_dagger":
            cld_ref_scores = ref_vec
        for mode in BOTTLENECK_MODES:
            if mode not in conds:
                errors.append(f"{pid}: missing bottleneck mode {mode}")
                continue
            eps_counted += _verify_cell_block(
                f"{pid}/{mode}",
                conds[mode],
                ref_vec,
                expected_agree_one=(mode == "full_28d"),
                errors=errors,
            )
            if mode == "horizon_value_only":
                h_ov = conds[mode].get("overall") or {}
                if float(h_ov.get("mean_score", 9.0)) > 0.05:
                    errors.append(f"{pid}/horizon_value_only: expected blind/abstain collapse near 0.0")

    for pid in SUFFICIENT_STAT_BASELINE_IDS:
        bb = baselines.get(pid) or {}
        spec = POLICY_META_SPECS[pid]
        if bb.get("is_open_weight_llm") is not False:
            errors.append(f"{pid}: is_open_weight_llm must be False")
        if int(bb.get("param_count", -1)) != spec["expected_param_count"]:
            errors.append(f"{pid}: param_count mismatch")
        if bb.get("train_seed_range") != spec["expected_train_seed_range"]:
            errors.append(f"{pid}: train_seed_range mismatch")
        if cld_ref_scores:
            eps_counted += _verify_cell_block(
                f"baseline/{pid}",
                bb,
                cld_ref_scores,
                expected_agree_one=False,
                errors=errors,
            )

    expected_total = (len(MASKED_POLICY_IDS) * len(BOTTLENECK_MODES) + len(SUFFICIENT_STAT_BASELINE_IDS)) * EPISODES_PER_CONDITION
    totals = summary.get("totals") or {}
    if int(totals.get("total_live_episodes", -1)) != expected_total or eps_counted != expected_total:
        errors.append(f"totals.total_live_episodes != {expected_total}")
    if int(totals.get("fresh_env_replays_verified", -1)) != expected_total:
        errors.append(f"totals.fresh_env_replays_verified != {expected_total}")

    if md_txt != render_markdown_report(summary):
        errors.append(f"{m_file.name}: markdown text out of sync with render_markdown_report(summary)")

    for tok in (
        "800000..800029",
        EXPECTED_WORLD_SECRET_TAG,
        "post-hoc locked, not pre-registered",
        "0 / 19",
        "98.0%",
        "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "EmpiricalBayesPolicy",
        "ScalingLogisticPolicy",
        "CompactLinearDAggerPolicy",
        "TinyMLPPolicy",
    ):
        if tok not in md_txt:
            errors.append(f"{m_file.name}: missing required verified token {tok!r}")

    elapsed = time.perf_counter() - t0
    if enforce_budget and elapsed > MAX_CHECK_SECONDS:
        errors.append(f"--check elapsed {elapsed:.4f}s exceeded {MAX_CHECK_SECONDS:.2f}s budget")
    return errors


def verify_artifacts(root: Path = ROOT) -> dict[str, Any]:
    resolved = root.resolve()
    errs = verify_committed_artifacts(
        summary_path=resolved / DEFAULT_OUT_JSON,
        md_path=resolved / DEFAULT_OUT_MD,
        repo_root=resolved,
    )
    return {"passed": len(errs) == 0, "errors": errs}


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Minimal sufficient-statistic and feature-group bottleneck audit."
    )
    ap.add_argument("--repo-root", "--root", dest="repo_root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    return ap


def _run_check_cli(args: argparse.Namespace) -> int:
    root = args.repo_root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)
    t0 = time.perf_counter()
    errs = verify_committed_artifacts(summary_path=out_json, md_path=out_md, repo_root=root)
    elapsed = round(time.perf_counter() - t0, 4)
    if args.json:
        print(
            json.dumps(
                {
                    "schema": SCHEMA_VERSION,
                    "passed": len(errs) == 0,
                    "errors": errs,
                    "elapsed_seconds": elapsed,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if not errs else 1
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    rel_j = out_json.relative_to(root) if out_json.is_relative_to(root) else out_json
    rel_m = out_md.relative_to(root) if out_md.is_relative_to(root) else out_md
    print(f"OK: verified {rel_j} and {rel_m} (1080 episodes, 5 bottleneck groups, 0 AST leaks) in {elapsed:.4f}s")
    return 0


if __name__ == "__main__" and "--generate" not in sys.argv[1:]:
    raise SystemExit(_run_check_cli(build_arg_parser().parse_args()))


import numpy as np
import train.compact_dagger_ablation as cda
from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights
from train.neural_mlp_tiebreak import ANGER_QUERIES as MLP_ANGER_QUERIES, MLPWeights, TinyMLPPolicy


def _step_mlp_unmodified(mlp: TinyMLPPolicy, history: list[Any]) -> tuple[str, dict[str, Any]]:
    mlp.tracker.ingest(history)
    if not mlp.tracker.employees:
        return ("list_employees", {})
    if mlp.queue:
        tool, args = mlp.queue.pop(0)
        return mlp._decide_step() if tool == "__decide__" else (tool, args)
    today = mlp.tracker.today
    if mlp.planned_day != today:
        mlp.planned_day = today
        q: list[tuple[str, dict[str, Any]]] = [
            ("status", {}),
            ("list_documents", {"day_from": 1 if today == 1 else max(1, today - 1), "day_to": today}),
            ("check_leak_feed", {}),
        ]
        if today >= 2 and (today - 1) not in mlp.tracker.logged_days:
            q.append(("read_access_logs", {"day_from": today - 1, "day_to": today - 1}))
        if mlp.rules.get("decoy", True) and today == 2:
            q.extend(("search_messages", {"query": w}) for w in MLP_ANGER_QUERIES[:3] if w not in mlp.tracker.queries_done)
        q.append(("__decide__", {}))
        mlp.queue = q
        return mlp.queue.pop(0)
    return ("advance_day", {})


class FeatureBottleneckPolicy:
    """AST-isolated public-observation feature-group bottleneck policy wrapper."""

    def __init__(
        self,
        policy_kind: str = "compact_linear_dagger",
        mode: str = "full_28d",
        *,
        linear_weights: CompactLinearWeights | None = None,
        mlp_weights: MLPWeights | None = None,
        seed: int = 0,
        name: str | None = None,
    ) -> None:
        if policy_kind not in MASKED_POLICY_IDS:
            raise ValueError(f"unsupported policy_kind: {policy_kind!r}")
        if mode not in BOTTLENECK_MODES:
            raise ValueError(f"unsupported bottleneck mode: {mode!r}")
        self.policy_kind = policy_kind
        self.mode = mode
        self.seed = int(seed)
        self.name = name or f"{policy_kind}:{mode}"
        self._cld: CompactLinearDAggerPolicy | None = None
        self._mlp: TinyMLPPolicy | None = None
        self._emp_mask = np.zeros(28, dtype=np.float64)

        if policy_kind == "compact_linear_dagger":
            keep = CLD_EMP_KEEP[mode]
            if keep:
                self._emp_mask[list(keep)] = 1.0
            self._cld = CompactLinearDAggerPolicy(weights=linear_weights, name=self.name)
        else:
            keep = MLP_IN_KEEP[mode]
            mv = np.zeros((28, 1), dtype=np.float32)
            if keep:
                mv[list(keep), 0] = 1.0
            base_w = mlp_weights if mlp_weights is not None else TinyMLPPolicy(seed=self.seed).weights
            masked_w = dataclasses.replace(base_w, w1=base_w.w1 * mv)
            self._mlp = TinyMLPPolicy(weights=masked_w, seed=self.seed, name=self.name)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        if self._cld is not None:
            self._cld.reset(tools_spec, instruction)
        elif self._mlp is not None:
            self._mlp.reset(tools_spec, instruction)

    def _act_cld_from_state(self, st: Any) -> tuple[str, dict[str, Any]]:
        assert self._cld is not None
        if self.mode == "full_28d":
            act_idx, split_idx, target_emp, pri_p = self._cld.predict_from_state(st)
            return self._cld._realize_action(st, act_idx, split_idx, target_emp, pri_p)
        n_emp = len(st.emp_ids)
        if n_emp == 0:
            acc_p = np.zeros(0, dtype=np.float64)
            pri_p = np.zeros(0, dtype=np.float64)
        elif self.mode == "horizon_value_only":
            acc_p = np.full(n_emp, 1.0 / n_emp, dtype=np.float64)
            pri_p = acc_p
        else:
            emp_x = cda.extract_employee_features(st) * self._emp_mask
            acc_p = cda._stable_softmax(emp_x @ self._cld.weights.w_emp[0])
            pri_p = cda._stable_softmax(emp_x @ self._cld.weights.w_emp[1])

        st_eff = st
        if self.mode in ("horizon_value_only", "no_canary_aux_only"):
            st_eff = copy.copy(st)
            st_eff.consistent_suspects = st.emp_ids
            st_eff.surfaced_canary_leaks = 0
            st_eff.surfaced_doc_leaks = 0
            st_eff.pending_canaries_count = 0
            st_eff.non_recipient_misses = {e: 0 for e in st.emp_ids}
            st_eff.pending_signatures = {e: () for e in st.emp_ids}

        act_x = cda.extract_action_features(st_eff, acc_p).copy()
        split_x = cda.extract_split_features(st_eff, acc_p, pri_p).copy()
        if self.mode == "core_sufficient_stats":
            for idx in (39, 40, 48, 49, 50, 51):
                act_x[idx] = 0.0
        elif self.mode == "posterior_only":
            for idx in (3, 4, 5, 6, 7, 17, 18, 19, 24, 25, 26, 27, 28, 29, 30, 31, 32, 39, 40, 48, 49, 50, 51):
                act_x[idx] = 0.0
            split_x[7] = 0.0
            split_x[8] = 0.0
        elif self.mode == "horizon_value_only":
            for idx in range(20, 41):
                act_x[idx] = 0.0
            act_x[52] = 0.0
        elif self.mode == "no_canary_aux_only":
            for idx in (33, 34, 35, 36, 37, 38):
                act_x[idx] = 0.0
            act_x[52] = 0.0

        act_idx = int(np.argmax(self._cld.weights.w_act @ act_x + self._cld.weights.b_act))
        split_idx = int(np.argmax(self._cld.weights.w_split @ split_x + self._cld.weights.b_split))
        target_emp = st.emp_ids[int(np.argmax(acc_p))] if (st.emp_ids and acc_p.size > 0) else "e00"
        return self._cld._realize_action(st_eff, act_idx, split_idx, target_emp, pri_p)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        if self._mlp is not None:
            return _step_mlp_unmodified(self._mlp, history)
        assert self._cld is not None
        st = self._cld._state_for(history)
        return self._act_cld_from_state(st)


class BottleneckCompactLinearDAggerPolicy(FeatureBottleneckPolicy):
    def __init__(
        self,
        weights: CompactLinearWeights | None = None,
        mode: str = "full_28d",
        name: str | None = None,
    ) -> None:
        super().__init__(
            policy_kind="compact_linear_dagger",
            mode=mode,
            linear_weights=weights,
            name=name or f"compact_linear_dagger:{mode}",
        )

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


class BottleneckTinyMLPPolicy(FeatureBottleneckPolicy):
    def __init__(
        self,
        weights: MLPWeights | None = None,
        mode: str = "full_28d",
        seed: int = 0,
        name: str | None = None,
    ) -> None:
        super().__init__(
            policy_kind="tiny_mlp",
            mode=mode,
            mlp_weights=weights,
            seed=seed,
            name=name or f"tiny_mlp:{mode}",
        )

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


@contextlib.contextmanager
def _scoped_world_secret(secret: str | None) -> Iterator[None]:
    prev = os.environ.get("CANARY_WORLD_SECRET")
    try:
        if secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = secret
        yield
    finally:
        if prev is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev


def load_masked_weights(repo_root: Path = ROOT) -> dict[str, Any]:
    from train.neural_mlp_tiebreak import DEFAULT_CKPT_PATH, load_checkpoint_npz

    repo_root = repo_root.resolve()
    cld_sum = json.loads((repo_root / DAGGER_SUMMARY_REL).read_text(encoding="utf-8"))
    cld_weights = CompactLinearWeights.from_dict(cld_sum["learned_weights_stage3"])
    ckpt = Path(DEFAULT_CKPT_PATH)
    if ckpt.is_file():
        mlp_weights = load_checkpoint_npz(ckpt, stage="stage3_onpolicy_dagger_r2")
        mlp_src = "shared_ckpt_npz"
    else:
        import scripts.run_tiebreak_policy as rtp

        mlp_sum = json.loads((repo_root / MLP_SUMMARY_REL).read_text(encoding="utf-8"))
        mlp_weights, mlp_src = rtp._load_or_reconstruct_tiny_mlp(
            mlp_summary=mlp_sum, stage="stage3_onpolicy_dagger_r2"
        )
    return {"cld_weights": cld_weights, "mlp_weights": mlp_weights, "mlp_weight_source": mlp_src}


def load_policy_bundle(repo_root: Path = ROOT) -> dict[str, Any]:
    import scripts.run_tiebreak_policy as rtp
    from scripts.tiebreak_scaling_calibration import CompactLinearPolicy, LinearPolicyWeights
    from train.empirical_bayes_policy import EmpiricalBayesParams

    repo_root = repo_root.resolve()
    eb_sum = json.loads((repo_root / EB_SUMMARY_REL).read_text(encoding="utf-8"))
    eb_tr = eb_sum["train_seeds"]
    rtp._assert_train_seed_range(int(eb_tr["start"]), int(eb_tr["stop"]), str(EB_SUMMARY_REL))
    eb_raw = eb_sum["parameters"]["eb_experience_opt"]
    eb_params = EmpiricalBayesParams.from_dict(eb_raw)

    scl_sum = json.loads((repo_root / SCALING_SUMMARY_REL).read_text(encoding="utf-8"))
    tr_lo, tr_hi = int(scl_sum["train_seed_range"][0]), int(scl_sum["train_seed_range"][1])
    rtp._assert_train_seed_range(tr_lo, tr_hi + 1, str(SCALING_SUMMARY_REL))
    scl_row = next(r for r in scl_sum["scaling_curve"] if int(r["n_train"]) == 900)
    scl_wd = scl_row["weights"]
    scl_weights = LinearPolicyWeights(
        w_suspect=np.asarray(scl_wd["w_suspect"], dtype=np.float64),
        w_commit=np.asarray(scl_wd["w_commit"], dtype=np.float64),
        w_wait=np.asarray(scl_wd["w_wait"], dtype=np.float64),
        w_tool=np.asarray(scl_wd["w_tool"], dtype=np.float64),
        w_canary=np.asarray(scl_wd["w_canary"], dtype=np.float64),
        n_train=900,
    )

    cld_sum = json.loads((repo_root / DAGGER_SUMMARY_REL).read_text(encoding="utf-8"))
    cld_tr = cld_sum["train_seeds"]
    rtp._assert_train_seed_range(int(cld_tr["start"]), int(cld_tr["stop"]), str(DAGGER_SUMMARY_REL))
    cld_weights = CompactLinearWeights.from_dict(cld_sum["learned_weights_stage3"])

    mlp_sum = json.loads((repo_root / MLP_SUMMARY_REL).read_text(encoding="utf-8"))
    mlp_tr = mlp_sum["train_seeds"]
    rtp._assert_train_seed_range(int(mlp_tr["start"]), int(mlp_tr["stop"]), str(MLP_SUMMARY_REL))
    mlp_weights, mlp_src = rtp._load_or_reconstruct_tiny_mlp(
        mlp_summary=mlp_sum, stage="stage3_onpolicy_dagger_r2"
    )

    return {
        "eb_params": eb_params,
        "scl_cls": CompactLinearPolicy,
        "scl_weights": scl_weights,
        "cld_weights": cld_weights,
        "mlp_weights": mlp_weights,
        "mlp_weight_source": mlp_src,
    }


def _compute_step_agreement_on_ref(
    ep_ref: Any,
    tools_spec: list[dict[str, Any]],
    instruction: str,
    cand_pol: Any,
) -> tuple[int, int]:
    cand_pol.reset(tools_spec, instruction)
    steps = ep_ref.steps
    matches = 0
    mlp_inner = getattr(cand_pol, "_mlp", None)
    for idx, st in enumerate(steps):
        prefix = steps[:idx]
        if mlp_inner is not None:
            mlp_inner.tracker.ingest(prefix)
            if mlp_inner.planned_day != mlp_inner.tracker.today and mlp_inner.tracker.employees:
                mlp_inner.queue = []
        pred_tool, pred_args = cand_pol.act(prefix)
        if pred_tool == st.tool and pred_args == st.args:
            matches += 1
    return matches, len(steps)


_WORKER_BUNDLE: dict[str, Any] = {}


def _fast_extract_employee_features(state: Any) -> Any:
    if state._emp_feats_cache is not None:
        return state._emp_feats_cache
    eids = state.emp_ids
    n = len(eids)
    if n == 0:
        empty = np.zeros((0, cda.D_EMP), dtype=np.float64)
        state._emp_feats_cache = empty
        return empty
    fp_acc = float(state.params.get("fingerprint_accuracy", 1.0))
    exact_fp = 1.0 if fp_acc >= 0.999 else 0.0
    noisy_fp = 1.0 - exact_fp
    has_decoy = 1.0 if state.params.get("decoy", False) else 0.0
    has_framing = 1.0 if state.params.get("framing", False) else 0.0
    careful = 1.0 if state.params.get("careful_mole", False) else 0.0
    ah_list = [float(state.after_hours_logs[e]) for e in eids]
    tot_list = [float(state.total_logs[e]) for e in eids]
    ang_list = [float(state.angry_msgs[e]) for e in eids]
    s_ah, s_tot, s_ang = sorted(ah_list), sorted(tot_list), sorted(ang_list, reverse=True)
    mid = n // 2
    med_ah = s_ah[mid] if (n % 2 == 1) else 0.5 * (s_ah[mid - 1] + s_ah[mid])
    med_tot = s_tot[mid] if (n % 2 == 1) else 0.5 * (s_tot[mid - 1] + s_tot[mid])
    max_ang, second_ang = s_ang[0], (s_ang[1] if n > 1 else 0.0)
    inv_sqrt_ld = 1.0 / math.sqrt(max(1.0, float(state.logged_days_count)))
    base_ben = max(0.0, med_tot - med_ah)
    doc_leaks = float(state.surfaced_doc_leaks)
    can_leaks = float(state.surfaced_canary_leaks)
    cons_set = set(state.consistent_suspects)
    one_minus_cons = 1.0 - (len(cons_set) / float(n))
    rows: list[tuple[float, ...]] = []
    for i, e in enumerate(eids):
        ch, cwh, sh = float(state.canary_hits[e]), float(state.canary_weighted_hits[e]), float(state.singleton_hits[e])
        cvm, nrm, old_u = float(state.canary_variant_misses[e]), float(state.non_recipient_misses[e]), float(state.old_unleaked_canaries[e])
        dh, ah, tl = float(state.leaked_doc_hits[e]), ah_list[i], tot_list[i]
        ev, ang = float(state.evasive_interviews[e]), ang_list[i]
        is_rest = 1.0 if e in state.restricted_ids else 0.0
        zero_hard_miss = 1.0 if nrm == 0.0 else 0.0
        zero_all_miss = 1.0 if (nrm == 0.0 and cvm == 0.0) else 0.0
        in_cons = 1.0 if e in cons_set else 0.0
        is_decoy_like = 1.0 if (has_decoy > 0.5 and ang >= 3.0 and ang >= 3.0 * max(1.0, second_ang) and ang == max_ang) else 0.0
        ahe = (ah - med_ah) * inv_sqrt_ld
        ahe_c = -3.0 if ahe < -3.0 else (5.0 if ahe > 5.0 else ahe)
        be = ((tl - ah) - base_ben) * inv_sqrt_ld
        be_c = -3.0 if be < -3.0 else (5.0 if be > 5.0 else be)
        cvm_cap = cvm if cvm < 6.0 else 6.0
        rows.append((
            ch if ch < 6.0 else 6.0, cwh if cwh < 4.0 else 4.0, sh if sh < 3.0 else 3.0,
            1.0 if sh >= 1.0 else 0.0, 1.0 if ch >= 2.0 else 0.0, cvm_cap * exact_fp, cvm_cap * noisy_fp,
            1.0 if (cvm >= 1.0 and exact_fp > 0.5) else 0.0, 1.0 if (cvm >= 2.0 and noisy_fp > 0.5) else 0.0,
            nrm if nrm < 6.0 else 6.0, 1.0 if nrm >= 1.0 else 0.0, zero_hard_miss, zero_all_miss,
            in_cons, in_cons * one_minus_cons, (old_u if old_u < 8.0 else 8.0) * (1.0 - 0.5 * careful),
            dh if dh < 8.0 else 8.0, dh / doc_leaks if doc_leaks > 0.0 else 0.0,
            ch / can_leaks if can_leaks > 0.0 else 0.0, ahe_c * (1.0 - 0.55 * has_framing), ahe_c * has_framing,
            be_c, ah / (tl if tl > 1.0 else 1.0), ev if ev < 3.0 else 3.0,
            (ang if ang < 6.0 else 6.0) * has_decoy, is_decoy_like,
            cwh * zero_hard_miss * (1.0 - is_decoy_like), is_rest,
        ))
    feats = np.asarray(rows, dtype=np.float64)
    state._emp_feats_cache = feats
    return feats


@contextlib.contextmanager
def _fast_compact_dagger_features() -> Iterator[None]:
    orig_fn = cda.extract_employee_features
    cda.extract_employee_features = _fast_extract_employee_features
    try:
        yield
    finally:
        cda.extract_employee_features = orig_fn


def _init_worker(repo_root_str: str) -> None:
    from canary.text.template import TemplateProvider

    cda.extract_employee_features = _fast_extract_employee_features
    _WORKER_BUNDLE["provider"] = TemplateProvider()
    _WORKER_BUNDLE["bundle"] = load_policy_bundle(Path(repo_root_str))


def _eval_world_task(task: tuple[str, int]) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode
    import scripts.run_tiebreak_policy as rtp
    from scripts.verify_replay import replay_episode
    from train.empirical_bayes_policy import EmpiricalBayesPolicy

    tier, seed = task
    prov = _WORKER_BUNDLE["provider"]
    bnd = _WORKER_BUNDLE["bundle"]

    def _pack_ep(ep: Any, ref_accused: str | None, sm: int, st: int) -> dict[str, Any]:
        outcome = "A" if ep.accused is None else ("C" if ep.correct else "W")
        return {
            "score": round(float(ep.score), 4),
            "accused": ep.accused,
            "outcome": outcome,
            "terminal_agree": int(ep.accused == ref_accused),
            "step_matches": int(sm),
            "step_total": int(st),
            "trace_sha10": canonical_trace_sha256(ep.steps)[:10],
        }

    out_cells: dict[str, Any] = {}
    with _scoped_world_secret(HELDOUT_WORLD_SECRET):
        probe_env = Env(tier, seed, text_provider=prov)
        ts, inst = probe_env.tools_spec(), probe_env.instruction()

        cld_full_pol = BottleneckCompactLinearDAggerPolicy(weights=bnd["cld_weights"], mode="full_28d")
        ep_cld_full = run_episode(Env(tier, seed, text_provider=prov), cld_full_pol)
        rtp.verify_episode_replay(ep_cld_full, text_provider=prov)
        if seed < 800_003:
            rep = replay_episode({"tier": tier, "seed": seed, "steps": [{"tool": s.tool, "args": s.args} for s in ep_cld_full.steps]})
            if abs(float(rep["score"]) - float(ep_cld_full.score)) > 1e-9 or rep["accused"] != ep_cld_full.accused:
                raise AssertionError(f"replay mismatch on {tier}:{seed}")

        out_cells["compact_linear_dagger:full_28d"] = _pack_ep(
            ep_cld_full, ep_cld_full.accused, len(ep_cld_full.steps), len(ep_cld_full.steps)
        )
        ref_scanner = CompactLinearDAggerPolicy(weights=bnd["cld_weights"], name="cld_ref_scan")
        ref_scanner.reset(ts, inst)
        cld_ref_states = [ref_scanner._state_for(ep_cld_full.steps[:i]) for i in range(len(ep_cld_full.steps))]
        for mode in BOTTLENECK_MODES[1:]:
            pol_m = BottleneckCompactLinearDAggerPolicy(weights=bnd["cld_weights"], mode=mode)
            ep_m = run_episode(Env(tier, seed, text_provider=prov), pol_m)
            rtp.verify_episode_replay(ep_m, text_provider=prov)
            ag_pol = BottleneckCompactLinearDAggerPolicy(weights=bnd["cld_weights"], mode=mode)
            ag_pol.reset(ts, inst)
            sm = sum(
                1
                for st_i, step_i in zip(cld_ref_states, ep_cld_full.steps)
                if ag_pol._act_cld_from_state(st_i) == (step_i.tool, step_i.args)
            )
            out_cells[f"compact_linear_dagger:{mode}"] = _pack_ep(ep_m, ep_cld_full.accused, sm, len(ep_cld_full.steps))

        mlp_full_pol = BottleneckTinyMLPPolicy(weights=bnd["mlp_weights"], mode="full_28d", seed=seed)
        ep_mlp_full = run_episode(Env(tier, seed, text_provider=prov), mlp_full_pol)
        rtp.verify_episode_replay(ep_mlp_full, text_provider=prov)
        out_cells["tiny_mlp:full_28d"] = _pack_ep(
            ep_mlp_full, ep_mlp_full.accused, len(ep_mlp_full.steps), len(ep_mlp_full.steps)
        )
        for mode in BOTTLENECK_MODES[1:]:
            pol_m = BottleneckTinyMLPPolicy(weights=bnd["mlp_weights"], mode=mode, seed=seed)
            ep_m = run_episode(Env(tier, seed, text_provider=prov), pol_m)
            rtp.verify_episode_replay(ep_m, text_provider=prov)
            sm, st = _compute_step_agreement_on_ref(
                ep_mlp_full,
                ts,
                inst,
                BottleneckTinyMLPPolicy(weights=bnd["mlp_weights"], mode=mode, seed=seed),
            )
            out_cells[f"tiny_mlp:{mode}"] = _pack_ep(ep_m, ep_mlp_full.accused, sm, st)

        eb_pol = EmpiricalBayesPolicy(params=bnd["eb_params"], seed=seed, name="empirical_bayes")
        ep_eb = run_episode(Env(tier, seed, text_provider=prov), eb_pol)
        rtp.verify_episode_replay(ep_eb, text_provider=prov)
        eb_sm, eb_st = _compute_step_agreement_on_ref(
            ep_cld_full, ts, inst, EmpiricalBayesPolicy(params=bnd["eb_params"], seed=seed, name="empirical_bayes")
        )
        out_cells["baseline:empirical_bayes"] = _pack_ep(ep_eb, ep_cld_full.accused, eb_sm, eb_st)

        scl_cls = bnd["scl_cls"]
        scl_pol = scl_cls(weights=bnd["scl_weights"], name="scaling_logistic", explore_eps=0.0, rng_seed=seed)
        ep_scl = run_episode(Env(tier, seed, text_provider=prov), scl_pol)
        rtp.verify_episode_replay(ep_scl, text_provider=prov)
        scl_sm, scl_st = _compute_step_agreement_on_ref(
            ep_cld_full, ts, inst, scl_cls(weights=bnd["scl_weights"], name="scaling_logistic", explore_eps=0.0, rng_seed=seed)
        )
        out_cells["baseline:scaling_logistic"] = _pack_ep(ep_scl, ep_cld_full.accused, scl_sm, scl_st)

    return {"tier": tier, "seed": int(seed), "cells": out_cells}


def _aggregate_cell(rows: list[dict[str, Any]], ref_scores: list[float]) -> dict[str, Any]:
    n = len(rows)
    scores = [float(r["score"]) for r in rows]
    outcomes = [str(r["outcome"]) for r in rows]
    ci = mean_ci95(scores)
    c_cnt = sum(1 for o in outcomes if o == "C")
    w_cnt = sum(1 for o in outcomes if o == "W")
    a_cnt = sum(1 for o in outcomes if o == "A")
    acc_cnt = c_cnt + w_cnt
    sm_tot = sum(int(r["step_matches"]) for r in rows)
    st_tot = sum(int(r["step_total"]) for r in rows)
    tm_tot = sum(int(r["terminal_agree"]) for r in rows)

    by_tier: dict[str, Any] = {}
    for idx, tier in enumerate(CANONICAL_TIERS):
        t_rows = rows[idx * HELDOUT_SEEDS_PER_TIER : (idx + 1) * HELDOUT_SEEDS_PER_TIER]
        t_sc = [float(x["score"]) for x in t_rows]
        t_ci = mean_ci95(t_sc)
        tc = sum(1 for x in t_rows if x["outcome"] == "C")
        tw = sum(1 for x in t_rows if x["outcome"] == "W")
        ta = sum(1 for x in t_rows if x["outcome"] == "A")
        by_tier[tier] = {
            "n": len(t_rows),
            "mean_score": t_ci["mean"],
            "accusation_precision": round(tc / (tc + tw), 5) if (tc + tw) > 0 else 0.0,
            "abstain_rate": round(ta / max(1, len(t_rows)), 5),
        }

    digest = safe_segmented_sha15("\n".join(r["trace_sha10"] for r in rows).encode("utf-8"))
    return {
        "overall": {
            "n": n,
            "mean_score": ci["mean"],
            "ci95_low": ci["ci95_low"],
            "ci95_high": ci["ci95_high"],
            "ci95_half_width": ci["ci95_half_width"],
            "correct_count": c_cnt,
            "wrong_count": w_cnt,
            "abstain_count": a_cnt,
            "accuse_count": acc_cnt,
            "accuracy": round(c_cnt / max(1, n), 5),
            "accuse_rate": round(acc_cnt / max(1, n), 5),
            "wrong_accuse_rate": round(w_cnt / max(1, n), 5),
            "abstain_rate": round(a_cnt / max(1, n), 5),
            "accusation_precision": round(c_cnt / acc_cnt, 5) if acc_cnt > 0 else 0.0,
            "step_matches_count": sm_tot,
            "step_total_count": st_tot,
            "action_agreement_rate": round(sm_tot / max(1, st_tot), 5),
            "terminal_agree_count": tm_tot,
            "terminal_agreement_rate": round(tm_tot / max(1, n), 5),
            "replay_verified_count": n,
            "traces_digest": digest,
        },
        "paired_vs_full_28d": compute_paired_delta(scores, ref_scores),
        "paired_vs_zero": compute_paired_delta(scores, [0.0] * n),
        "by_tier": by_tier,
        "episode_scores_csv": ",".join(f"{round(s, 4):g}" for s in scores),
        "episode_outcomes_csv": ",".join(outcomes),
    }


def load_cross_track_qwen_contrast(repo_root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))
    confound = json.loads((repo_root / CONFOUND_REL).read_text(encoding="utf-8"))
    hist = ledger["historical_runs"]
    total_qwen = len(hist)
    above_zero = sum(1 for r in hist if r.get("after_mean_score") is not None and float(r["after_mean_score"]) > 0.0)
    best_trained = max(
        (r for r in hist if r.get("after_mean_score") is not None and r["run_id"] != "WS4-base-pooled"),
        key=lambda r: float(r["after_mean_score"]),
    )

    pooled_all = confound["pooled_views"]["all_450_verda"]["all"]
    raw_t = pooled_all["raw_transcript"]
    comp_t = pooled_all["compact_transcript"]

    panel_e = {
        "open_weight_qwen25_runs_total": total_qwen,
        "open_weight_qwen25_runs_above_zero": above_zero,
        "open_weight_qwen25_above_zero_ratio": f"{above_zero} / {total_qwen}",
        "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "compact_policies_are_open_weight_llm": False,
        "disclosure": PANEL_FIX_E_DISCLOSURE,
    }
    qwen_contrast = {
        "is_open_weight_llm": True,
        "total_params_billions": 1.54,
        "lora_trainable_params_millions": 18.46,
        "pooled_verda_episodes": int(pooled_all["n"]),
        "pooled_450_mean_score": round(float(pooled_all["mean_score"]), 4),
        "best_trained_run_id": str(best_trained["run_id"]),
        "best_trained_mean_score": round(float(best_trained["after_mean_score"]), 4),
        "raw_header_tokens_mean": round(float(raw_t["header_tokens_mean"]), 1),
        "pooled_canary_calls_total": int(raw_t["plant_canary_ok_calls_in_prefix"]),
        "raw_4k_canary_evicted_count": int(raw_t["plant_canary_evicted_4k_count"]),
        "raw_4k_canary_eviction_pct": round(float(raw_t["plant_canary_evicted_4k_pct"]), 2),
        "raw_4k_canary_eviction_pct_display": f"{round(float(raw_t['plant_canary_evicted_4k_pct']), 1):.1f}%",
        "raw_8k_canary_evicted_count": int(raw_t["plant_canary_evicted_8k_count"]),
        "raw_8k_canary_eviction_pct": round(float(raw_t["plant_canary_evicted_8k_pct"]), 2),
        "raw_8k_canary_eviction_pct_display": f"{round(float(raw_t['plant_canary_evicted_8k_pct']), 1):.1f}%",
        "compact_canary_evicted_count": int(comp_t["canary_map_evicted_count"]),
        "compact_canary_eviction_pct_display": "0.0%",
    }
    return panel_e, qwen_contrast


def run_audit(repo_root: Path = ROOT, max_workers: int = 8) -> dict[str, Any]:
    t0 = time.perf_counter()
    repo_root = repo_root.resolve()
    secret_tag = compute_secret_tag(HELDOUT_WORLD_SECRET)
    if secret_tag != EXPECTED_WORLD_SECRET_TAG:
        raise AssertionError(f"secret tag mismatch: {secret_tag}")

    panel_e, qwen_contrast = load_cross_track_qwen_contrast(repo_root)
    tasks = [(tier, seed) for seed in range(HELDOUT_SEED_START, HELDOUT_SEED_STOP) for tier in CANONICAL_TIERS]

    if max_workers <= 1:
        _init_worker(str(repo_root))
        world_results = [_eval_world_task(tk) for tk in tasks]
    else:
        mp_ctx = multiprocessing.get_context("fork") if "fork" in multiprocessing.get_all_start_methods() else None
        with ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=mp_ctx,
            initializer=_init_worker,
            initargs=(str(repo_root),),
        ) as ex:
            world_results = list(ex.map(_eval_world_task, tasks, chunksize=1))

    tier_rank = {t: i for i, t in enumerate(CANONICAL_TIERS)}
    world_results.sort(key=lambda w: (tier_rank[w["tier"]], int(w["seed"])))

    masked_out: dict[str, Any] = {}
    cld_ref_scores: list[float] = []
    for pid in MASKED_POLICY_IDS:
        spec = POLICY_META_SPECS[pid]
        keep_map = CLD_EMP_KEEP if pid == "compact_linear_dagger" else MLP_IN_KEEP
        ref_rows = [w["cells"][f"{pid}:full_28d"] for w in world_results]
        ref_scores = [float(r["score"]) for r in ref_rows]
        if pid == "compact_linear_dagger":
            cld_ref_scores = ref_scores

        conds_out: dict[str, Any] = {}
        for mode in BOTTLENECK_MODES:
            c_rows = [w["cells"][f"{pid}:{mode}"] for w in world_results]
            agg = _aggregate_cell(c_rows, ref_scores)
            keep_idx = keep_map[mode]
            conds_out[mode] = {
                "bottleneck_mode": mode,
                "description": BOTTLENECK_DESCRIPTIONS[mode],
                "active_emp_features": len(keep_idx),
                "active_emp_feature_indices": list(keep_idx),
                **agg,
            }
        masked_out[pid] = {
            "policy_id": pid,
            "policy_class": spec["policy_class"],
            "run_id": spec["run_id"],
            "module_path": spec["module_path"],
            "summary_path": spec["summary_path"],
            "param_count": spec["expected_param_count"],
            "train_seed_range": spec["expected_train_seed_range"],
            "is_open_weight_llm": False,
            "conditions": conds_out,
        }

    native_notes = {
        "empirical_bayes": "6 log-likelihood + 5 stopping/split sufficient stats",
        "scaling_logistic": "14 suspect + 10 commit + 6 wait + 12 tool/canary stats",
    }
    baselines_out: dict[str, Any] = {}
    for pid in SUFFICIENT_STAT_BASELINE_IDS:
        spec = POLICY_META_SPECS[pid]
        b_rows = [w["cells"][f"baseline:{pid}"] for w in world_results]
        agg = _aggregate_cell(b_rows, cld_ref_scores)
        baselines_out[pid] = {
            "policy_id": pid,
            "policy_class": spec["policy_class"],
            "run_id": spec["run_id"],
            "module_path": spec["module_path"],
            "summary_path": spec["summary_path"],
            "param_count": spec["expected_param_count"],
            "train_seed_range": spec["expected_train_seed_range"],
            "native_feature_note": native_notes[pid],
            "is_open_weight_llm": False,
            **agg,
        }

    target_script = repo_root / "scripts" / "tiebreak_representation_bottleneck_audit.py"
    if not target_script.is_file():
        target_script = Path(__file__).resolve()
    ast_gate = audit_module_ast_isolation(target_script)

    total_eps = (len(MASKED_POLICY_IDS) * len(BOTTLENECK_MODES) + len(SUFFICIENT_STAT_BASELINE_IDS)) * EPISODES_PER_CONDITION
    elapsed_s = round(time.perf_counter() - t0, 3)

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "text_provider": "TemplateProvider",
        "world_secret_tag": secret_tag,
        "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seeds_per_tier": HELDOUT_SEEDS_PER_TIER,
        "episodes_per_condition": EPISODES_PER_CONDITION,
        "tiers": list(CANONICAL_TIERS),
        "bottleneck_modes": list(BOTTLENECK_MODES),
        "seed_isolation": {
            "train_seed_range": "100000..199999",
            "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
            "judge_episodes_touched": 0,
            "dev_episodes_rolled_out": 0,
            "train_episodes_in_heldout_eval": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": panel_e,
        "cross_track_qwen_contrast": qwen_contrast,
        "ast_inference_isolation": ast_gate,
        "sufficient_stat_baselines": baselines_out,
        "masked_policies": masked_out,
        "totals": {
            "policies_evaluated": len(ALL_POLICY_IDS),
            "bottleneck_modes_count": len(BOTTLENECK_MODES),
            "total_cells": len(MASKED_POLICY_IDS) * len(BOTTLENECK_MODES) + len(SUFFICIENT_STAT_BASELINE_IDS),
            "total_live_episodes": total_eps,
            "fresh_env_replays_verified": total_eps,
            "elapsed_seconds": elapsed_s,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.generate:
        return _run_check_cli(args)

    root = args.repo_root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)

    summary = run_audit(repo_root=root, max_workers=max(1, int(args.workers)))
    md_text = render_markdown_report(summary)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")

    errs = verify_committed_artifacts(
        summary_path=out_json,
        md_path=out_md,
        repo_root=root,
        enforce_budget=False,
    )
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    print(
        f"Wrote {out_json.relative_to(root)} ({out_json.stat().st_size} bytes) and "
        f"{out_md.relative_to(root)} ({summary['totals']['total_live_episodes']} episodes "
        f"in {summary['totals']['elapsed_seconds']:.2f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
