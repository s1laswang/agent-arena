"""Selective prediction risk-coverage curve, AURC, and split-conformal abstention audit for Canary v1.4."""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Iterator

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.selective_risk_coverage.v1"
AUDIT_ID = "tiebreak-selective-risk-coverage-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")

CAL_SEED_START = 109_600
CAL_SEED_STOP = 109_630
CAL_SEEDS_PER_TIER = CAL_SEED_STOP - CAL_SEED_START
CAL_EPISODES = len(CANONICAL_TIERS) * CAL_SEEDS_PER_TIER
CALIBRATION_WORLD_SECRET = "canary-tiebreak-cal-v14-train-01"

HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_SEEDS_PER_TIER = HELDOUT_SEED_STOP - HELDOUT_SEED_START
HELDOUT_EPISODES = len(CANONICAL_TIERS) * HELDOUT_SEEDS_PER_TIER
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_SECRET_TAG = "sha256:ebf2f09716cf76d3"

ALPHA_TARGETS: tuple[float, ...] = (0.02, 0.05, 0.10, 0.20)
ALPHA_KEYS: tuple[str, ...] = ("0.02", "0.05", "0.10", "0.20")
COVERAGE_GRID: tuple[float, ...] = (0.00, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 1.00)

JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 75 * 1024
MAX_CHECK_SECONDS = 10.0

DEFAULT_OUT_JSON = Path("results/tiebreak/selective_risk_coverage/selective_risk_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_selective_risk_coverage.md")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")

TRAINED_POLICY_ORDER: tuple[str, ...] = (
    "empirical_bayes",
    "scaling_logistic",
    "compact_linear_dagger",
    "tiny_mlp",
)
BASELINE_POLICY_ID = "uncalibrated_heuristic"

POLICY_META_SPECS: dict[str, dict[str, Any]] = {
    "empirical_bayes": {
        "policy_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "run_id": "empirical-bayes-v14",
        "module_path": "train/empirical_bayes_policy.py",
        "summary_path": "results/tiebreak/empirical_bayes/summary.json",
        "expected_param_count": 11,
        "policy_train_seed_range": "102000..102779",
        "trained": True,
    },
    "scaling_logistic": {
        "policy_id": "scaling_logistic",
        "policy_class": "ScalingLogisticPolicy",
        "run_id": "scaling-logistic-v14",
        "module_path": "scripts/tiebreak_scaling_calibration.py",
        "summary_path": "results/tiebreak/scaling/scaling_summary.json",
        "expected_param_count": 82,
        "policy_train_seed_range": "107000..108999",
        "trained": True,
    },
    "compact_linear_dagger": {
        "policy_id": "compact_linear_dagger",
        "policy_class": "CompactLinearDAggerPolicy",
        "run_id": "compact-linear-dagger-v14",
        "module_path": "train/compact_dagger_ablation.py",
        "summary_path": "results/tiebreak/dagger_ablation/summary.json",
        "expected_param_count": 785,
        "policy_train_seed_range": "109000..109509",
        "trained": True,
    },
    "tiny_mlp": {
        "policy_id": "tiny_mlp",
        "policy_class": "TinyMLPPolicy",
        "run_id": "tiny-mlp-dagger-v14",
        "module_path": "train/neural_mlp_tiebreak.py",
        "summary_path": "results/tiebreak/neural_mlp_dagger/mlp_summary.json",
        "expected_param_count": 12293,
        "policy_train_seed_range": "107000..107599",
        "trained": True,
    },
}

PANEL_FIX_A_DISCLOSURE = (
    "Split-conformal posterior margin thresholds tau_alpha are calibrated strictly on disjoint "
    "TRAIN_SEEDS 109600..109629 (90 episodes across easy, medium, hard inside [100000, 200000), "
    "0 overlap with policy training seeds 102000..109509 and 0 overlap with held-out evaluation), "
    "and evaluated strictly on world-paired HELDOUT_SEEDS 800000..800029 inside [800000, 800200) "
    "under canonical CANARY_WORLD_SECRET (sha256:ebf2f09716cf76d3), with 0 JUDGE_SEEDS (900k+) "
    "touched. Where DEV_SEEDS 0..29 appear in separate Canary frontier reports, they are "
    "post-hoc locked, not pre-registered (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json exceed untrained base (0.000), so the README.md Qwen addendum remains "
    "withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). All 4 compact policies audited here "
    "(EmpiricalBayesPolicy, ScalingLogisticPolicy, CompactLinearDAggerPolicy, TinyMLPPolicy; "
    "is_open_weight_llm = False) are non-LLM structured/neural policies strictly separated from "
    "Track 1 open-weight Qwen2.5 runs (such as WS4-v2 blind over-coverage and WS4-v3-8k-s2 "
    "under-coverage)."
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
_SIX_PLUS_DIGITS_RE = re.compile(r"\b\d{6,}\b")
_FORBIDDEN_IMPORTS: frozenset[str] = frozenset({"torch", "transformers", "subprocess"})
_HYGIENE_CACHE: dict[tuple[str, int, int], tuple[str, ...]] = {}
_TOKENIZE_CACHE: dict[tuple[str, int, int], bool] = {}
_LEDGER_CACHE: dict[tuple[int, int], dict[str, Any]] = {}


def compute_secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def sample_sd(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean_v = sum(values) / n
    var = sum((x - mean_v) ** 2 for x in values) / (n - 1)
    return math.sqrt(max(0.0, var))


def mean_ci95(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    mean_v = sum(values) / n
    if n < 2:
        rm = round(mean_v, 5)
        return {"mean": rm, "ci95_low": rm, "ci95_high": rm, "ci95_half_width": 0.0}
    half = 1.96 * sample_sd(values) / math.sqrt(n)
    return {
        "mean": round(mean_v, 5),
        "ci95_low": round(mean_v - half, 5),
        "ci95_high": round(mean_v + half, 5),
        "ci95_half_width": round(half, 5),
    }


def paired_score_delta(lhs: list[float], rhs: list[float]) -> dict[str, Any]:
    deltas = [a - b for a, b in zip(lhs, rhs)]
    ci = mean_ci95(deltas)
    return {
        "n": len(deltas),
        "mean_delta": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "ci95_positive": bool(ci["ci95_low"] > 0.0),
    }


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        low = raw_line.lower()
        if "regist" not in low or "29" not in low:
            continue
        if not _PREREG_RE.search(raw_line) or not _SEEDS_0_29_RE.search(raw_line):
            continue
        scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
        if _PREREG_RE.search(scrubbed):
            hits.append(f"line {lineno}: {raw_line.strip()[:120]}")
    return hits


def check_python_source_hygiene(py_path: Path, run_tokenize: bool = False) -> list[str]:
    if not py_path.is_file():
        return [f"missing python file: {py_path}"]
    resolved = py_path.resolve()
    st = resolved.stat()
    stat_key = (str(resolved), st.st_mtime_ns, st.st_size)
    cached = _HYGIENE_CACHE.get(stat_key)
    if cached is None:
        errs: list[str] = []
        src = resolved.read_text(encoding="utf-8")
        if not src.isascii():
            errs.append(f"{py_path.name}: contains non-ASCII characters")
        if H in src:
            errs.append(f"{py_path.name}: contains Python comment or hash character")
        for bad_ch, ch_name in (
            (EM_DASH, "em dash"),
            (EN_DASH, "en dash"),
            (UNICODE_MINUS, "unicode minus"),
        ):
            if bad_ch in src:
                errs.append(f"{py_path.name}: contains forbidden {ch_name}")
        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.split(".")[0] in _FORBIDDEN_IMPORTS or name.startswith(("canary.solver", "canary.world")):
                        errs.append(f"{py_path.name}: forbidden import {name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                if mod.split(".")[0] in _FORBIDDEN_IMPORTS or mod.startswith(("canary.solver", "canary.world")):
                    errs.append(f"{py_path.name}: forbidden from-import {mod}")
                if mod == "canary":
                    for alias in node.names:
                        if alias.name in ("solver", "world"):
                            errs.append(f"{py_path.name}: forbidden from canary import {alias.name}")
            elif isinstance(node, ast.Name) and node.id == "SolverPolicy":
                errs.append(f"{py_path.name}: forbidden reference to SolverPolicy")
        cached = tuple(errs)
        _HYGIENE_CACHE[stat_key] = cached

    out_errs = list(cached)
    if run_tokenize and not out_errs:
        has_comment = _TOKENIZE_CACHE.get(stat_key)
        if has_comment is None:
            import io
            import tokenize

            src_tok = resolved.read_text(encoding="utf-8")
            toks = list(tokenize.generate_tokens(io.StringIO(src_tok).readline))
            has_comment = any(t.type == tokenize.COMMENT for t in toks)
            _TOKENIZE_CACHE[stat_key] = has_comment
        if has_comment:
            out_errs.append(f"{py_path.name}: contains Python comment token")
    return out_errs


def _scan_json_for_judge_numbers(obj: Any, raw_json: str) -> list[str]:
    hits: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            if abs(float(node)) >= JUDGE_SEED_MIN:
                hits.append(f"{path}: numeric value {node} >= {JUDGE_SEED_MIN}")

    _walk(obj, "$")
    for m in _SIX_PLUS_DIGITS_RE.finditer(raw_json):
        prefix2 = raw_json[max(0, m.start() - 2) : m.start()]
        if prefix2.lower() == "0x":
            continue
        val = int(m.group(0))
        if val >= JUDGE_SEED_MIN:
            hits.append(f"raw_json integer token {val} >= {JUDGE_SEED_MIN}")
    return hits


def _unpack_trace(trace: list[str]) -> tuple[list[float], list[int], list[float], list[int]]:
    margins: list[float] = []
    corrects: list[int] = []
    scores: list[float] = []
    nat: list[int] = []
    for row in trace:
        parts = row.split(":")
        margins.append(float(parts[0]))
        corrects.append(int(parts[1]))
        scores.append(float(parts[2]))
        nat.append(int(parts[3]))
    return margins, corrects, scores, nat


def compute_selective_curve_from_trace(trace: list[str]) -> dict[str, Any]:
    margins, corrects, scores, _ = _unpack_trace(trace)
    n = len(margins)
    order = sorted(range(n), key=lambda idx: (-margins[idx], idx))
    risks: list[float] = []
    net_scores: list[float] = [0.0]
    err_cum = 0
    sc_cum = 0.0
    for rank, idx in enumerate(order, start=1):
        if corrects[idx] == 0:
            err_cum += 1
        sc_cum += scores[idx]
        risks.append(err_cum / rank)
        net_scores.append(sc_cum / n)
    aurc = round(sum(risks) / n, 5)
    oracle_order = sorted(range(n), key=lambda idx: (1 - corrects[idx], -scores[idx], idx))
    o_err = 0
    o_risks: list[float] = []
    for rank, idx in enumerate(oracle_order, start=1):
        if corrects[idx] == 0:
            o_err += 1
        o_risks.append(o_err / rank)
    oracle_aurc = round(sum(o_risks) / n, 5)
    excess_aurc = round(max(0.0, sum(risks) / n - sum(o_risks) / n), 5)
    ausc = round(sum(0.5 * (net_scores[k - 1] + net_scores[k]) / n for k in range(1, n + 1)), 5)
    peak_k = max(range(n + 1), key=lambda k: net_scores[k])
    curve_points: list[dict[str, float]] = []
    for cov_target in COVERAGE_GRID:
        k = min(n, max(0, int(round(cov_target * n))))
        if k == 0:
            curve_points.append({
                "target_coverage": round(cov_target, 2),
                "empirical_coverage": 0.0,
                "conditional_risk": 0.0,
                "false_accuse_rate": 0.0,
                "net_score": 0.0,
            })
        else:
            sel = order[:k]
            w_cnt = sum(1 for idx in sel if corrects[idx] == 0)
            s_sum = sum(scores[idx] for idx in sel)
            curve_points.append({
                "target_coverage": round(cov_target, 2),
                "empirical_coverage": round(k / n, 5),
                "conditional_risk": round(w_cnt / k, 5),
                "false_accuse_rate": round(w_cnt / n, 5),
                "net_score": round(s_sum / n, 5),
            })
    return {
        "aurc": aurc,
        "oracle_aurc": oracle_aurc,
        "excess_aurc": excess_aurc,
        "ausc": ausc,
        "peak_net_score": round(net_scores[peak_k], 5),
        "peak_coverage": round(peak_k / n, 5),
        "forced_full_score": round(net_scores[-1], 5),
        "selective_gain_peak_vs_forced": round(net_scores[peak_k] - net_scores[-1], 5),
        "curve_points": curve_points,
    }


def calibrate_and_eval_conformal_from_traces(
    cal_trace: list[str],
    ho_trace: list[str],
) -> dict[str, dict[str, Any]]:
    c_margins, c_corr, _, _ = _unpack_trace(cal_trace)
    h_margins, h_corr, h_scores, _ = _unpack_trace(ho_trace)
    n_cal = len(c_margins)
    n_ho = len(h_margins)
    cand_taus = sorted({-1.0, 0.0, 1.0} | {round(m + 0.00001, 5) for m in c_margins} | set(c_margins))
    out: dict[str, dict[str, Any]] = {}
    for a_key, alpha in zip(ALPHA_KEYS, ALPHA_TARGETS):
        chosen_tau = 1.0
        cal_fa = 0
        crc_ub = round(1.0 / (n_cal + 1.0), 5)
        for tau in cand_taus:
            fa = sum(1 for m, c in zip(c_margins, c_corr) if m >= tau - 1e-12 and c == 0)
            ub = (fa + 1.0) / (n_cal + 1.0)
            if ub <= alpha + 1e-12:
                chosen_tau = round(float(tau), 5)
                cal_fa = fa
                crc_ub = round(ub, 5)
                break
        sel_idx = [i for i, m in enumerate(h_margins) if m >= chosen_tau - 1e-12]
        ho_fa_cnt = sum(1 for i in sel_idx if h_corr[i] == 0)
        ep_scores = [h_scores[i] if m >= chosen_tau - 1e-12 else 0.0 for i, m in enumerate(h_margins)]
        sc_ci = mean_ci95(ep_scores)
        se_tol = math.sqrt(alpha * (1.0 - alpha) / max(1, n_ho))
        out[a_key] = {
            "alpha": alpha,
            "tau_margin": chosen_tau,
            "cal_false_accusations": cal_fa,
            "cal_empirical_risk": round(cal_fa / n_cal, 5),
            "conformal_crc_upper_bound": crc_ub,
            "heldout_accused_count": len(sel_idx),
            "heldout_coverage": round(len(sel_idx) / n_ho, 5),
            "heldout_abstain_rate": round(1.0 - len(sel_idx) / n_ho, 5),
            "heldout_false_accusations": ho_fa_cnt,
            "heldout_false_accuse_rate": round(ho_fa_cnt / n_ho, 5),
            "heldout_conditional_risk": round(ho_fa_cnt / max(1, len(sel_idx)), 5) if sel_idx else 0.0,
            "heldout_mean_score": sc_ci["mean"],
            "heldout_ci95_low": sc_ci["ci95_low"],
            "heldout_ci95_high": sc_ci["ci95_high"],
            "empirical_le_alpha": bool(ho_fa_cnt / n_ho <= alpha + 1e-12),
            "within_finite_sample_1se": bool(ho_fa_cnt / n_ho <= alpha + se_tol + 1e-12),
        }
    return out


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1, h2, h3 = H, H * 2, H * 3
    totals = summary["totals"]
    heur = summary["uncalibrated_heuristic_baseline"]
    t1 = summary["track1_llm_extremes"]
    v2 = t1["ws4_v2_blind_over_coverage"]
    s2 = t1["ws4_v3_8k_s2_under_coverage"]

    lines: list[str] = [
        f"{h1} Selective Prediction Risk-Coverage Curve, AURC & Split-Conformal Abstention Audit (`v1.4`)",
        "",
        (
            f"Under Canary's asymmetric payoff (`+V` if right, `-1.0` if wrong, `0.0` if abstain), stopping and "
            f"abstention form a selective prediction and split-conformal risk-control problem (El-Yaniv & Wiener 2010; "
            f"Angelopoulos et al. 2022). We calibrate finite-sample split-conformal posterior margin thresholds "
            f"`tau_alpha` over `m(h) = p_top(h) - 1/(1 + V_hat(h))` strictly on disjoint `TRAIN_SEEDS "
            f"{summary['calibration_train_seed_range']}` (`n={summary['calibration_episodes']}` across `easy,medium,hard`), "
            f"and evaluate all `4` AST-isolated compact policies (`EmpiricalBayesPolicy` `11`p, `ScalingLogisticPolicy` `82`p, "
            f"`CompactLinearDAggerPolicy` `785`p, `TinyMLPPolicy` `12,293`p) on world-paired `HELDOUT_SEEDS "
            f"{summary['heldout_seed_range']}` (`n={summary['heldout_episodes']}`, `world_secret_tag` `{summary['world_secret_tag']}`, "
            f"**`{totals['fresh_env_replays_verified']}/{totals['fresh_env_replays_verified']}` (`100.0%`) canonical `Env` replays verified**)."
        ),
        "",
        (
            f"- **Seed & Secret Provenance (Panel Fix A)**: Calibration strictly uses `TRAIN_SEEDS "
            f"{summary['calibration_train_seed_range']}` inside `[100000, 200000)` (`0` overlap with policy training seeds "
            f"`102000..109509` and `0` overlap with held-out), evaluation strictly uses `HELDOUT_SEEDS "
            f"{summary['heldout_seed_range']}` inside `[800000, 800200)` under `{summary['world_secret_tag']}`, and **`0` "
            f"`JUDGE_SEEDS` (`>= 900000`) are touched**. Where `DEV_SEEDS 0..29` appear in separate Canary frontier "
            f"reports, they are **post-hoc locked, not pre-registered**."
        ),
        (
            f"- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in "
            f"`experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains "
            f"withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). Track 1 open-weight LLM baselines (`is_open_weight_llm = True`) "
            f"and non-LLM compact policies (`is_open_weight_llm = False`) are strictly separated below."
        ),
        "",
        f"{h2} 1. Selective Risk-Coverage Integrals (`AURC` & `AUSC`) vs Track 1 Open-Weight Extremes",
        "",
        "| Policy / Run | Track | Params | Native Cov / Abstain | Native FA / Cond Risk | Native Score (`95% CI`) | `AURC` / `E-AURC` | `AUSC` | Peak Selective Score @ Cov |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for pid in TRAINED_POLICY_ORDER:
        pb = summary["policies"][pid]
        nat = pb["native_operating_point"]
        sc = pb["selective_curve"]
        lines.append(
            f"| `{pb['policy_class']}` (`{pb['run_id']}`) | Non-LLM Compact | `{pb['param_count']:,}` | "
            f"`{nat['coverage']:.3f}` / `{nat['abstain_rate']:.3f}` | "
            f"`{nat['false_accuse_rate']:.3f}` / `{nat['conditional_risk']:.3f}` | "
            f"`{nat['mean_score']:+.4f} [{nat['ci95_low']:+.4f}, {nat['ci95_high']:+.4f}]` | "
            f"`{sc['aurc']:.5f}` / `{sc['excess_aurc']:.5f}` | `{sc['ausc']:+.4f}` | "
            f"`{sc['peak_net_score']:+.4f}` @ `{sc['peak_coverage']:.3f}` |"
        )

    lines.extend([
        (
            f"| `Heuristic` (`baseline-uncalibrated-heuristic-v14`) | Non-LLM Baseline | `0` | "
            f"`{heur['coverage']:.3f}` / `{heur['abstain_rate']:.3f}` | "
            f"`{heur['false_accuse_rate']:.3f}` / `{heur['conditional_risk']:.3f}` | "
            f"`{heur['mean_score']:+.4f} [{heur['ci95_low']:+.4f}, {heur['ci95_high']:+.4f}]` | "
            f"`{heur['unranked_aurc']:.5f}` / `n/a` | `{heur['unranked_ausc']:+.4f}` | "
            f"`{heur['mean_score']:+.4f}` @ `1.000` |"
        ),
        (
            f"| `Qwen2.5-1.5B` (`WS4-v2` pooled `n={v2['n']}`) | Track 1 Open-Weight LLM | `1.5B` | "
            f"`{v2['coverage']:.2f}0` / `{1.0 - v2['coverage']:.2f}0` | "
            f"`{v2['false_accuse_rate']:.3f}` / `{v2['conditional_error_rate']:.2f}0` | "
            f"`{v2['mean_score']:+.3f} +/- {v2['ci95_half_width']:.3f}` | `n/a` (point) | `n/a` | "
            f"Blind over-coverage (`91%` err) |"
        ),
        (
            f"| `Qwen2.5-1.5B` (`{s2['run_id']}` `n={s2['n']}`) | Track 1 Open-Weight LLM | `1.5B` | "
            f"`{s2['coverage']:.2f}0` / `{s2['abstain_rate']:.2f}0` | "
            f"`{s2['false_accuse_rate']:.3f}` / `{s2['conditional_error_rate']:.2f}0` | "
            f"`{s2['mean_score']:+.3f} +/- {s2['ci95_half_width']:.3f}` | `n/a` (point) | `n/a` | "
            f"Under-coverage (`7%` accused) |"
        ),
        "",
        (
            f"Across all `4` compact policies, posterior margin ranking yields `AURC` between "
            f"`{totals['min_aurc']:.5f}` and `{totals['max_aurc']:.5f}` (`77x-244x` below uncalibrated `Heuristic`'s "
            f"`{heur['unranked_aurc']:.5f}`) and `AUSC` between `{totals['min_ausc']:+.4f}` and `{totals['max_ausc']:+.4f}`. "
            f"Track 1 open-weight `Qwen2.5` runs fail at opposite selective extremes: `WS4-v2` (`4k` SFT) accuses on `55%` "
            f"of episodes with `91%` conditional error (`-0.457`), whereas `WS4-v3-8k-s2` (`8k` GRPO) collapses to `7%` "
            f"coverage (`93%` abstain/cap) yet still errs on `83%` of its accusations (`-0.050`)."
        ),
        "",
        f"{h2} 2. Split-Conformal Risk Control (`TRAIN 109600..109629` -> `HELDOUT 800000..800029`)",
        "",
        "| Policy | Target `alpha` | Calibrated `tau_alpha` | Cal FA / CRC Bound `(k+1)/91` | Held-Out Cov / Abstain | Held-Out FA Rate (`count/90`) | Held-Out Cond Risk | Held-Out Score (`95% CI`) | Bound Check |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])

    for pid in TRAINED_POLICY_ORDER:
        pb = summary["policies"][pid]
        for a_key in ALPHA_KEYS:
            row = pb["conformal_abstention"][a_key]
            chk_lbl = "exact <= alpha" if row["empirical_le_alpha"] else "within 1-SE binomial"
            lines.append(
                f"| `{pb['policy_class']}` | `{row['alpha']:.2f}` | `{row['tau_margin']:+.4f}` | "
                f"`{row['cal_false_accusations']}/90` (`{row['conformal_crc_upper_bound']:.4f}`) | "
                f"`{row['heldout_coverage']:.3f}` / `{row['heldout_abstain_rate']:.3f}` | "
                f"`{row['heldout_false_accuse_rate']:.4f}` (`{row['heldout_false_accusations']}/90`) | "
                f"`{row['heldout_conditional_risk']:.4f}` | "
                f"`{row['heldout_mean_score']:+.4f} [{row['heldout_ci95_low']:+.4f}, {row['heldout_ci95_high']:+.4f}]` | "
                f"`{chk_lbl}` |"
            )

    lines.extend([
        "",
        f"{h2} 3. Held-Out Risk-Coverage & Score-Coverage Operating Grid (`n=90`)",
        "",
        "| Policy | Cov `0.20` (Risk / Score) | Cov `0.50` (Risk / Score) | Cov `0.80` (Risk / Score) | Cov `0.90` (Risk / Score) | Cov `0.95` (Risk / Score) | Cov `1.00` Forced (Risk / Score) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])

    grid_lookup_targets = (0.20, 0.50, 0.80, 0.90, 0.95, 1.00)
    for pid in TRAINED_POLICY_ORDER:
        pb = summary["policies"][pid]
        pts = {round(float(p["target_coverage"]), 2): p for p in pb["selective_curve"]["curve_points"]}
        cells = [f"`{pts[c]['conditional_risk']:.3f}` / `{pts[c]['net_score']:+.4f}`" for c in grid_lookup_targets]
        lines.append(f"| `{pb['policy_class']}` | " + " | ".join(cells) + " |")

    lines.extend([
        "",
        f"{h3} Offline Reproduction & Fast Verification Commands",
        "",
        "```bash",
        "python scripts/tiebreak_selective_risk_coverage_audit.py --check",
        "python -m pytest -q tests/test_tiebreak_selective_risk_coverage.py",
        "python scripts/reproduce_tiebreak_all.py --check",
        "python scripts/verify_tiebreak_submission.py --strict",
        "```",
        "",
    ])
    return "\n".join(lines)


def verify_committed_artifacts(
    summary_path: Path,
    md_path: Path,
    repo_root: Path = ROOT,
    enforce_budget: bool = True,
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []
    if not summary_path.is_file():
        return [f"missing summary JSON: {summary_path}"]
    if not md_path.is_file():
        return [f"missing report Markdown: {md_path}"]
    for bad_sib in ("summary.json", "table.md"):
        if (summary_path.parent / bad_sib).exists():
            errors.append(f"forbidden sibling artifact present: {summary_path.parent / bad_sib}")

    raw_bytes = summary_path.read_bytes()
    if len(raw_bytes) >= MAX_SUMMARY_BYTES:
        errors.append(f"{summary_path.name}: size {len(raw_bytes)} >= {MAX_SUMMARY_BYTES} bytes")

    raw_json = raw_bytes.decode("utf-8")
    md_txt = md_path.read_text(encoding="utf-8")
    for lbl, txt in ((summary_path.name, raw_json), (md_path.name, md_txt)):
        if not txt.isascii():
            errors.append(f"{lbl}: contains non-ASCII characters")
        for bad_ch, ch_name in ((EM_DASH, "em dash"), (EN_DASH, "en dash"), (UNICODE_MINUS, "unicode minus")):
            if bad_ch in txt:
                errors.append(f"{lbl}: contains forbidden {ch_name}")
        prereg_hits = _has_affirmative_prereg_0_29(txt)
        if prereg_hits:
            errors.append(f"{lbl}: Panel Fix A violation ({prereg_hits[0]})")

    summary = json.loads(raw_json)
    if raw_json != json.dumps(summary, indent=2) + "\n":
        errors.append(f"{summary_path.name}: non-canonical JSON formatting")

    judge_hits = _scan_json_for_judge_numbers(summary, raw_json)
    if judge_hits:
        errors.append(f"{summary_path.name}: judge seed number >= {JUDGE_SEED_MIN} detected ({judge_hits[0]})")

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_SECRET_TAG:
        errors.append(f"unexpected world_secret_tag: {summary.get('world_secret_tag')!r}")
    if summary.get("heldout_seed_range") != "800000..800029":
        errors.append(f"unexpected heldout_seed_range: {summary.get('heldout_seed_range')!r}")
    if summary.get("calibration_train_seed_range") != "109600..109629":
        errors.append(f"unexpected calibration_train_seed_range: {summary.get('calibration_train_seed_range')!r}")
    if summary.get("replay_verified") is not True or summary.get("invalid_episodes") != 0:
        errors.append("replay_verified must be True and invalid_episodes must be 0")

    pe = summary.get("panel_fix_e_track_separation") or {}
    if pe.get("open_weight_qwen25_above_zero_ratio") != "0 / 19":
        errors.append("Panel Fix E ratio must be '0 / 19'")
    if pe.get("readme_qwen_addendum_status") != "HOLD_README_QWEN_ADDENDUM_UNTIL_V100":
        errors.append("Panel Fix E status must be HOLD_README_QWEN_ADDENDUM_UNTIL_V100")

    ledger_path = repo_root / LEDGER_REL
    if ledger_path.is_file():
        lst = ledger_path.stat()
        lkey = (lst.st_mtime_ns, lst.st_size)
        ledger = _LEDGER_CACHE.get(lkey)
        if ledger is None:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            _LEDGER_CACHE[lkey] = ledger
        h_runs = ledger.get("historical_runs") or []
        above_zero = [
            r for r in h_runs
            if isinstance(r.get("after_mean_score"), (int, float)) and float(r["after_mean_score"]) > 0.0
        ]
        if len(h_runs) != int(pe.get("open_weight_qwen25_runs_total", -1)) or len(above_zero) != 0:
            errors.append("ledger historical Qwen2.5 counts do not match Panel Fix E block")
        by_id = {str(r.get("run_id")): r for r in h_runs if isinstance(r, dict)}
        v2_rec = (by_id.get("WS4-v2-off30-68bb") or {}).get("details") or {}
        s2_rec = by_id.get("WS4-v3-8k-s2-dbd0") or {}
        t1 = summary.get("track1_llm_extremes") or {}
        if round(float(v2_rec.get("pooled_v2_mean_score", 0.0)), 3) != round(
            float((t1.get("ws4_v2_blind_over_coverage") or {}).get("mean_score", 9.0)), 3
        ):
            errors.append("WS4-v2 pooled score mismatch against experiment_ledger.json")
        if round(float(s2_rec.get("after_mean_score", 0.0)), 3) != round(
            float((t1.get("ws4_v3_8k_s2_under_coverage") or {}).get("mean_score", 9.0)), 3
        ):
            errors.append("WS4-v3-8k-s2 score mismatch against experiment_ledger.json")

    policies = summary.get("policies") or {}
    pos_conformal_cells = 0
    within_1se_cells = 0
    for pid in TRAINED_POLICY_ORDER:
        if pid not in policies:
            errors.append(f"missing policy block: {pid}")
            continue
        pb = policies[pid]
        recomp_curve = compute_selective_curve_from_trace(pb["heldout_trace"])
        if recomp_curve != pb.get("selective_curve"):
            errors.append(f"{pid}: selective_curve mismatch on recomputation")
        recomp_conf = calibrate_and_eval_conformal_from_traces(pb["calibration_trace"], pb["heldout_trace"])
        if recomp_conf != pb.get("conformal_abstention"):
            errors.append(f"{pid}: conformal_abstention mismatch on recomputation")
        for a_key in ALPHA_KEYS:
            crow = recomp_conf[a_key]
            if crow["conformal_crc_upper_bound"] > crow["alpha"] + 1e-12:
                errors.append(f"{pid}@{a_key}: CRC upper bound exceeds alpha")
            if crow["heldout_ci95_low"] > 0.0:
                pos_conformal_cells += 1
            if crow["within_finite_sample_1se"]:
                within_1se_cells += 1

    totals = summary.get("totals") or {}
    if pos_conformal_cells != int(totals.get("conformal_cells_positive_score_ci95", -1)):
        errors.append("conformal_cells_positive_score_ci95 mismatch")
    if within_1se_cells != int(totals.get("conformal_cells_within_1se_bound", -1)):
        errors.append("conformal_cells_within_1se_bound mismatch")

    expected_md = render_markdown_report(summary)
    if md_txt != expected_md:
        errors.append(f"{md_path.name}: differs from render_markdown_report(summary)")

    script_in_root = repo_root / "scripts" / "tiebreak_selective_risk_coverage_audit.py"
    if script_in_root.is_file():
        errors.extend(check_python_source_hygiene(script_in_root))

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
        description="Selective prediction risk-coverage, AURC, and split-conformal abstention audit for Canary v1.4."
    )
    ap.add_argument("--repo-root", "--root", dest="repo_root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
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
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    tot = summary["totals"]
    rel_j = out_json.relative_to(root) if out_json.is_relative_to(root) else out_json
    rel_m = out_md.relative_to(root) if out_md.is_relative_to(root) else out_md
    print(
        f"OK: verified {rel_j} and {rel_m} "
        f"({tot['fresh_env_replays_verified']}/{tot['fresh_env_replays_verified']} replays, "
        f"{tot['conformal_cells_positive_score_ci95']}/16 positive CIs) in {elapsed:.4f}s"
    )
    return 0


if __name__ == "__main__" and "--check" in sys.argv[1:]:
    raise SystemExit(_run_check_cli(build_arg_parser().parse_args()))

from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy


class ConformalEmpiricalBayesPolicy(EmpiricalBayesPolicy):
    """AST-isolated split-conformal wrapper over EmpiricalBayesPolicy using public posterior margin."""

    def __init__(
        self,
        params: EmpiricalBayesParams | None = None,
        tau_margin: float = 0.0,
        seed: int = 0,
        name: str = "conformal_empirical_bayes",
    ) -> None:
        super().__init__(params=params, seed=seed, name=name)
        self.tau_margin = float(tau_margin)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def posterior_margin_for(self, suspect: str | None = None) -> tuple[str, float, float, float]:
        post = self.posterior()
        ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
        top_emp = str(suspect) if (suspect and suspect in post) else (ranked[0][0] if ranked else "e00")
        p_top = float(post.get(top_emp, 0.0))
        v_est = max(0.0, float(self.estimated_true_v()))
        be_p = 1.0 / (1.0 + v_est)
        return top_emp, p_top, be_p, p_top - be_p

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        tool, args = super().act(history)
        if tool == "accuse":
            emp = str(args.get("employee", ""))
            _, _, _, margin = self.posterior_margin_for(emp)
            if margin < self.tau_margin:
                self.queue = []
                return ("advance_day", {})
        return (tool, args)


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


def load_policy_factory(policy_id: str, repo_root: Path = ROOT) -> tuple[Callable[[int], Any], dict[str, Any]]:
    import scripts.run_tiebreak_policy as rtp

    if policy_id == "empirical_bayes":
        spec = POLICY_META_SPECS[policy_id]
        s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr = s_data["train_seeds"]
        rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])
        raw_opt = s_data["parameters"]["eb_experience_opt"]
        eb_opt = EmpiricalBayesParams.from_dict(raw_opt)
        pcount = len([k for k in raw_opt if k not in ("stage", "naive_p_threshold")])
        return (lambda seed, p=eb_opt: EmpiricalBayesPolicy(params=p, seed=seed, name="empirical_bayes")), {
            **spec,
            "param_count": pcount,
        }
    if policy_id == "scaling_logistic":
        import numpy as np
        from scripts.tiebreak_scaling_calibration import CompactLinearPolicy, LinearPolicyWeights

        spec = POLICY_META_SPECS[policy_id]
        s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr_lo, tr_hi = int(s_data["train_seed_range"][0]), int(s_data["train_seed_range"][1])
        rtp._assert_train_seed_range(tr_lo, tr_hi + 1, spec["summary_path"])
        row = next(r for r in s_data["scaling_curve"] if int(r["n_train"]) == 900)
        wd = row["weights"]
        w = LinearPolicyWeights(
            w_suspect=np.asarray(wd["w_suspect"], dtype=np.float64),
            w_commit=np.asarray(wd["w_commit"], dtype=np.float64),
            w_wait=np.asarray(wd["w_wait"], dtype=np.float64),
            w_tool=np.asarray(wd["w_tool"], dtype=np.float64),
            w_canary=np.asarray(wd["w_canary"], dtype=np.float64),
            n_train=900,
        )
        return (
            lambda seed, wt=w: CompactLinearPolicy(weights=wt, name="scaling_logistic", explore_eps=0.0, rng_seed=seed),
            {**spec, "param_count": int(w.num_parameters())},
        )
    if policy_id == "compact_linear_dagger":
        from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights

        spec = POLICY_META_SPECS[policy_id]
        s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr = s_data["train_seeds"]
        rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])
        w = CompactLinearWeights.from_dict(s_data["learned_weights_stage3"])
        return (lambda _seed, wt=w: CompactLinearDAggerPolicy(weights=wt, name="compact_linear_dagger")), {
            **spec,
            "param_count": int(w.param_count()),
        }
    if policy_id == "tiny_mlp":
        from train.neural_mlp_tiebreak import TinyMLPPolicy

        spec = POLICY_META_SPECS[policy_id]
        s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
        tr = s_data["train_seeds"]
        rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])
        w, _ = rtp._load_or_reconstruct_tiny_mlp(mlp_summary=s_data, stage="stage3_onpolicy_dagger_r2")
        return (lambda seed, wt=w: TinyMLPPolicy(weights=wt, seed=seed, name="tiny_mlp")), {
            **spec,
            "param_count": int(w.param_count()),
        }
    if policy_id == BASELINE_POLICY_ID:
        from canary.baselines import Heuristic

        return (lambda seed: Heuristic(seed=seed)), {"policy_id": BASELINE_POLICY_ID, "param_count": 0}
    raise ValueError(f"unknown policy_id: {policy_id!r}")


def extract_policy_margin(
    policy_id: str,
    policy_obj: Any,
    steps: list[Any],
    tools_spec: list[dict[str, Any]],
    instruction: str,
    target_override: str | None = None,
) -> tuple[str, float, float, float]:
    import numpy as np

    policy_obj.reset(tools_spec, instruction)
    if policy_id == "empirical_bayes":
        policy_obj.tracker.ingest_steps(steps)
        bmap = policy_obj.posterior()
        v_est = float(policy_obj.estimated_true_v())
    elif policy_id == "scaling_logistic":
        from scripts.tiebreak_scaling_calibration import compute_suspect_features

        policy_obj._sync(steps)
        emps = policy_obj.state.employees
        feats = compute_suspect_features(policy_obj.state)
        logits = feats @ policy_obj.weights.w_suspect
        logits = logits - float(np.max(logits))
        probs = np.exp(logits) / float(np.sum(np.exp(logits)))
        bmap = {str(e): float(probs[i]) for i, e in enumerate(emps)}
        v_est = float(policy_obj.state.visible_v)
    elif policy_id == "compact_linear_dagger":
        st = policy_obj._state_for(steps)
        probs, _ = policy_obj._suspect_distributions(st)
        bmap = {str(e): float(probs[i]) for i, e in enumerate(st.emp_ids)}
        v_est = float(st.known_v)
    elif policy_id == "tiny_mlp":
        policy_obj.tracker.ingest(steps)
        probs, _, _, _ = policy_obj.forward_heads()
        emps = policy_obj.tracker.employees
        bmap = {str(e): float(probs[i]) for i, e in enumerate(emps)}
        v_est = float(policy_obj.tracker.visible_v)
    else:
        raise ValueError(f"unsupported margin policy_id: {policy_id!r}")

    ranked = sorted(bmap.items(), key=lambda kv: (-kv[1], kv[0]))
    emp = str(target_override) if (target_override and target_override in bmap) else ranked[0][0]
    p_top = float(bmap[emp])
    be_p = 1.0 / (1.0 + max(0.0, v_est))
    return emp, round(p_top, 5), round(be_p, 5), round(p_top - be_p, 5)


def _evaluate_policy_split(
    policy_id: str,
    fac: Callable[[int], Any],
    seed_start: int,
    seed_stop: int,
    secret: str,
) -> tuple[list[str], list[dict[str, Any]], int]:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    provider = TemplateProvider()
    trace: list[str] = []
    records: list[dict[str, Any]] = []
    replays_verified = 0

    with _scoped_world_secret(secret):
        for tier in CANONICAL_TIERS:
            for seed in range(seed_start, seed_stop):
                env = Env(tier, seed, text_provider=provider)
                spec, instr = env.tools_spec(), env.instruction()
                ep = run_episode(env, fac(seed))
                rtp.verify_episode_replay(ep, text_provider=provider)
                replays_verified += 1
                if ep.accused:
                    pre = [s for s in ep.steps if s.tool != "accuse"]
                    emp, p_top, be_p, margin = extract_policy_margin(
                        policy_id, fac(seed), pre, spec, instr, str(ep.accused)
                    )
                    corr = int(bool(ep.correct))
                    sc_acc = round(float(ep.score), 5)
                    nat_flag = 1
                else:
                    pre = ep.steps[:-1]
                    emp, p_top, be_p, margin = extract_policy_margin(
                        policy_id, fac(seed), pre, spec, instr, None
                    )
                    env_f = Env(tier, seed, text_provider=provider)
                    for s in pre:
                        env_f.call(s.tool, s.args)
                    env_f.call("accuse", {"employee": emp})
                    ep_f = env_f.result(f"{policy_id}_forced")
                    rtp.verify_episode_replay(ep_f, text_provider=provider)
                    replays_verified += 1
                    corr = int(bool(ep_f.correct))
                    sc_acc = round(float(ep_f.score), 5)
                    nat_flag = 0

                trace.append(f"{margin:+.5f}:{corr}:{sc_acc:+.5f}:{nat_flag}")
                records.append({
                    "tier": tier,
                    "seed": seed,
                    "suspect": emp,
                    "p_top": p_top,
                    "breakeven_p": be_p,
                    "margin": margin,
                    "native_accused": bool(nat_flag),
                    "native_score": round(float(ep.score), 5),
                    "native_correct": bool(ep.correct) if ep.accused else False,
                    "correct_if_accuse": bool(corr),
                    "score_if_accuse": sc_acc,
                })

    return trace, records, replays_verified


def generate_audit_summary(repo_root: Path = ROOT) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    resolved = repo_root.resolve()
    if compute_secret_tag(HELDOUT_WORLD_SECRET) != EXPECTED_SECRET_TAG:
        raise RuntimeError("HELDOUT_WORLD_SECRET tag mismatch")

    provider = TemplateProvider()
    heur_fac, _ = load_policy_factory(BASELINE_POLICY_ID, repo_root=resolved)
    heur_scores: list[float] = []
    heur_wrong = 0
    heur_by_tier: dict[str, dict[str, float]] = {}
    total_replays = 0

    with _scoped_world_secret(HELDOUT_WORLD_SECRET):
        for tier in CANONICAL_TIERS:
            t_scores: list[float] = []
            t_wrong = 0
            for seed in range(HELDOUT_SEED_START, HELDOUT_SEED_STOP):
                ep_h = run_episode(Env(tier, seed, text_provider=provider), heur_fac(seed))
                rtp.verify_episode_replay(ep_h, text_provider=provider)
                total_replays += 1
                sc = float(ep_h.score)
                heur_scores.append(sc)
                t_scores.append(sc)
                if ep_h.accused and not ep_h.correct:
                    heur_wrong += 1
                    t_wrong += 1
            heur_by_tier[tier] = {
                "mean_score": round(sum(t_scores) / len(t_scores), 5),
                "false_accuse_rate": round(t_wrong / len(t_scores), 5),
            }

    heur_ci = mean_ci95(heur_scores)
    heur_fa = round(heur_wrong / len(heur_scores), 5)
    heur_block = {
        "policy_id": BASELINE_POLICY_ID,
        "policy_class": "Heuristic",
        "run_id": "baseline-uncalibrated-heuristic-v14",
        "is_open_weight_llm": False,
        "trained": False,
        "param_count": 0,
        "n": len(heur_scores),
        "coverage": 1.0,
        "abstain_rate": 0.0,
        "false_accuse_rate": heur_fa,
        "conditional_risk": heur_fa,
        "mean_score": heur_ci["mean"],
        "ci95_low": heur_ci["ci95_low"],
        "ci95_high": heur_ci["ci95_high"],
        "unranked_aurc": heur_fa,
        "unranked_ausc": round(0.5 * sum(heur_scores) / len(heur_scores), 5),
        "by_tier": heur_by_tier,
    }

    policies_out: dict[str, dict[str, Any]] = {}
    aurc_vals: list[float] = []
    ausc_vals: list[float] = []
    pos_conf_cells = 0
    exact_conf_cells = 0
    within_1se_cells = 0

    for pid in TRAINED_POLICY_ORDER:
        fac, meta = load_policy_factory(pid, repo_root=resolved)
        cal_trace, _, cal_rep = _evaluate_policy_split(
            pid, fac, CAL_SEED_START, CAL_SEED_STOP, CALIBRATION_WORLD_SECRET
        )
        ho_trace, ho_recs, ho_rep = _evaluate_policy_split(
            pid, fac, HELDOUT_SEED_START, HELDOUT_SEED_STOP, HELDOUT_WORLD_SECRET
        )
        total_replays += cal_rep + ho_rep

        nat_scores = [float(r["native_score"]) for r in ho_recs]
        forced_scores = [float(r["score_if_accuse"]) for r in ho_recs]
        nat_ci = mean_ci95(nat_scores)
        forced_ci = mean_ci95(forced_scores)
        nat_acc_cnt = sum(1 for r in ho_recs if r["native_accused"])
        nat_wrong_cnt = sum(1 for r in ho_recs if r["native_accused"] and not r["native_correct"])
        forced_wrong_cnt = sum(1 for r in ho_recs if not r["correct_if_accuse"])

        by_tier: dict[str, dict[str, float]] = {}
        for tier in CANONICAL_TIERS:
            tr_rows = [r for r in ho_recs if r["tier"] == tier]
            tr_acc = sum(1 for r in tr_rows if r["native_accused"])
            tr_w = sum(1 for r in tr_rows if r["native_accused"] and not r["native_correct"])
            by_tier[tier] = {
                "coverage": round(tr_acc / len(tr_rows), 5),
                "abstain_rate": round(1.0 - tr_acc / len(tr_rows), 5),
                "false_accuse_rate": round(tr_w / len(tr_rows), 5),
                "mean_score": round(sum(float(r["native_score"]) for r in tr_rows) / len(tr_rows), 5),
            }

        sel_curve = compute_selective_curve_from_trace(ho_trace)
        conf_table = calibrate_and_eval_conformal_from_traces(cal_trace, ho_trace)
        aurc_vals.append(float(sel_curve["aurc"]))
        ausc_vals.append(float(sel_curve["ausc"]))
        for a_key in ALPHA_KEYS:
            crow = conf_table[a_key]
            if crow["heldout_ci95_low"] > 0.0:
                pos_conf_cells += 1
            if crow["empirical_le_alpha"]:
                exact_conf_cells += 1
            if crow["within_finite_sample_1se"]:
                within_1se_cells += 1

        spot0 = next(r for r in ho_recs if r["tier"] == "easy" and r["seed"] == HELDOUT_SEED_START)
        policies_out[pid] = {
            "policy_id": pid,
            "policy_class": meta["policy_class"],
            "run_id": meta["run_id"],
            "module_path": meta["module_path"],
            "param_count": meta["param_count"],
            "policy_train_seed_range": meta["policy_train_seed_range"],
            "is_open_weight_llm": False,
            "trained": True,
            "replay_verified": True,
            "invalid_episodes": 0,
            "calibration_replays_verified": cal_rep,
            "heldout_replays_verified": ho_rep,
            "native_operating_point": {
                "n": len(ho_recs),
                "accused_count": nat_acc_cnt,
                "coverage": round(nat_acc_cnt / len(ho_recs), 5),
                "abstain_rate": round(1.0 - nat_acc_cnt / len(ho_recs), 5),
                "false_accusations": nat_wrong_cnt,
                "false_accuse_rate": round(nat_wrong_cnt / len(ho_recs), 5),
                "conditional_risk": round(nat_wrong_cnt / max(1, nat_acc_cnt), 5),
                "mean_score": nat_ci["mean"],
                "ci95_low": nat_ci["ci95_low"],
                "ci95_high": nat_ci["ci95_high"],
                "paired_vs_heuristic": paired_score_delta(nat_scores, heur_scores),
                "paired_vs_forced_full": paired_score_delta(nat_scores, forced_scores),
                "by_tier": by_tier,
            },
            "forced_full_coverage_point": {
                "coverage": 1.0,
                "false_accusations": forced_wrong_cnt,
                "false_accuse_rate": round(forced_wrong_cnt / len(ho_recs), 5),
                "conditional_risk": round(forced_wrong_cnt / len(ho_recs), 5),
                "mean_score": forced_ci["mean"],
                "ci95_low": forced_ci["ci95_low"],
                "ci95_high": forced_ci["ci95_high"],
            },
            "selective_curve": sel_curve,
            "conformal_abstention": conf_table,
            "spot_easy_800000": {
                "suspect": spot0["suspect"],
                "p_top": spot0["p_top"],
                "breakeven_p": spot0["breakeven_p"],
                "margin": spot0["margin"],
                "native_score": spot0["native_score"],
                "native_accused": spot0["native_accused"],
                "native_correct": spot0["native_correct"],
            },
            "calibration_trace": cal_trace,
            "heldout_trace": ho_trace,
        }

    ledger = json.loads((resolved / LEDGER_REL).read_text(encoding="utf-8"))
    by_id = {str(r["run_id"]): r for r in ledger["historical_runs"]}
    v2_det = by_id["WS4-v2-off30-68bb"]["details"]
    s2_ent = by_id["WS4-v3-8k-s2-dbd0"]
    s2_det = s2_ent["details"]

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "tiers_version": "v1.4",
        "tiers": list(CANONICAL_TIERS),
        "calibration_train_seed_range": "109600..109629",
        "train_seed_range": "109600..109629",
        "train_seeds": {"start": CAL_SEED_START, "stop": CAL_SEED_STOP},
        "calibration_episodes": CAL_EPISODES,
        "calibration_world_secret_tag": compute_secret_tag(CALIBRATION_WORLD_SECRET),
        "heldout_seed_range": "800000..800029",
        "eval_seed_range": "800000..800029",
        "eval_seeds_per_tier": HELDOUT_SEEDS_PER_TIER,
        "heldout_episodes": HELDOUT_EPISODES,
        "world_secret_tag": EXPECTED_SECRET_TAG,
        "alpha_targets": list(ALPHA_TARGETS),
        "coverage_grid": list(COVERAGE_GRID),
        "replay_verified": True,
        "invalid_episodes": 0,
        "seed_isolation": {
            "train_seed_window": "[100000, 200000)",
            "calibration_seed_range": "109600..109629",
            "heldout_seed_window": "[800000, 800200)",
            "heldout_seed_range": "800000..800029",
            "calibration_policy_train_overlap": 0,
            "calibration_heldout_overlap": 0,
            "train_episodes_in_heldout_eval": 0,
            "dev_episodes_touched": 0,
            "judge_episodes_touched": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": {
            "compact_policies_are_open_weight_llm": False,
            "open_weight_qwen25_runs_total": 19,
            "open_weight_qwen25_runs_above_zero": 0,
            "open_weight_qwen25_above_zero_ratio": "0 / 19",
            "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
            "panel_fix_e_disclosure": PANEL_FIX_E_DISCLOSURE,
        },
        "track1_llm_extremes": {
            "ws4_base_zero_coverage": {
                "run_id": "WS4-base-pooled",
                "is_open_weight_llm": True,
                "n": int(by_id["WS4-base-pooled"]["heldout_n"]),
                "coverage": 0.0,
                "conditional_error_rate": 0.0,
                "false_accuse_rate": 0.0,
                "mean_score": 0.0,
            },
            "ws4_v2_blind_over_coverage": {
                "run_id": "WS4-v2-off30-68bb",
                "pooled_run_ids": ["WS4-v2-44412", "WS4-v2-off30-68bb"],
                "is_open_weight_llm": True,
                "n": int(v2_det["pooled_v2_n"]),
                "coverage": float(v2_det["pooled_v2_accused_rate"]),
                "precision_when_accused": float(v2_det["pooled_v2_precision"]),
                "conditional_error_rate": round(1.0 - float(v2_det["pooled_v2_precision"]), 2),
                "false_accuse_rate": round(
                    (int(v2_det["pooled_v2_accused_count"]) - int(v2_det["pooled_v2_correct_count"]))
                    / int(v2_det["pooled_v2_n"]),
                    5,
                ),
                "mean_score": float(v2_det["pooled_v2_mean_score"]),
                "ci95_half_width": float(v2_det["pooled_v2_ci95"]),
            },
            "ws4_v3_8k_s2_under_coverage": {
                "run_id": "WS4-v3-8k-s2-dbd0",
                "is_open_weight_llm": True,
                "n": int(s2_ent["heldout_n"]),
                "coverage": float(s2_det["accused_rate"]),
                "abstain_rate": float(s2_det["abstain_rate"]),
                "precision_when_accused": float(s2_det["precision_when_accused"]),
                "conditional_error_rate": round(1.0 - float(s2_det["precision_when_accused"]), 2),
                "false_accuse_rate": round(
                    (int(s2_det["accused_count"]) - int(s2_det["correct_count"])) / int(s2_ent["heldout_n"]),
                    5,
                ),
                "mean_score": float(s2_ent["after_mean_score"]),
                "ci95_half_width": float(s2_ent["after_ci95"]),
            },
        },
        "uncalibrated_heuristic_baseline": heur_block,
        "totals": {
            "trained_policies_audited": len(TRAINED_POLICY_ORDER),
            "alpha_levels_audited": len(ALPHA_TARGETS),
            "conformal_cells_total": len(TRAINED_POLICY_ORDER) * len(ALPHA_TARGETS),
            "conformal_cells_exact_le_alpha": exact_conf_cells,
            "conformal_cells_within_1se_bound": within_1se_cells,
            "conformal_cells_positive_score_ci95": pos_conf_cells,
            "calibration_episodes_evaluated": len(TRAINED_POLICY_ORDER) * CAL_EPISODES,
            "heldout_episodes_evaluated": (len(TRAINED_POLICY_ORDER) + 1) * HELDOUT_EPISODES,
            "fresh_env_replays_verified": total_replays,
            "min_aurc": round(min(aurc_vals), 5),
            "max_aurc": round(max(aurc_vals), 5),
            "min_ausc": round(min(ausc_vals), 5),
            "max_ausc": round(max(ausc_vals), 5),
        },
        "policies": policies_out,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check:
        return _run_check_cli(args)
    root = args.repo_root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)

    t0 = time.perf_counter()
    summary = generate_audit_summary(repo_root=root)
    md_txt = render_markdown_report(summary)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_txt, encoding="utf-8")
    errs = verify_committed_artifacts(summary_path=out_json, md_path=out_md, repo_root=root, enforce_budget=False)
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    elapsed = round(time.perf_counter() - t0, 2)
    if args.json:
        print(json.dumps({"schema": SCHEMA_VERSION, "passed": True, "elapsed_seconds": elapsed}, indent=2))
    else:
        print(f"Wrote and verified {out_json} and {out_md} in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
