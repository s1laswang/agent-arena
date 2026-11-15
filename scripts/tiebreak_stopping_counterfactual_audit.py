"""Stopping counterfactual and exact regret decomposition audit on world-paired held-out seeds."""
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

SCHEMA_VERSION = "canary.tiebreak.stopping_counterfactual_audit.v1"
AUDIT_ID = "tiebreak-stopping-counterfactual-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_SEEDS_PER_TIER = HELDOUT_SEED_STOP - HELDOUT_SEED_START
EPISODES_PER_RULE = len(CANONICAL_TIERS) * HELDOUT_SEEDS_PER_TIER
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_WORLD_SECRET_TAG = "sha256:ebf2f09716cf76d3"

JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 75 * 1024
MAX_CHECK_SECONDS = 30.0

DEFAULT_OUT_JSON = Path("results/tiebreak/stopping_counterfactual/stopping_counterfactual_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_stopping_counterfactual.md")

LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")
ADDENDUM_REL = Path("results/tiebreak/addendum_readiness.json")
EB_SUMMARY_REL = Path("results/tiebreak/empirical_bayes/summary.json")
DAGGER_SUMMARY_REL = Path("results/tiebreak/dagger_ablation/summary.json")
VERDA_MULTISEED_REL = Path("results/tiebreak/verda_multiseed/multiseed_summary.json")
FRONTIER_CMP_REL = Path("results/tiebreak/frontier_comparison/comparison_summary.json")

INVESTIGATIVE_MCP_TOOLS: frozenset[str] = frozenset({
    "read_access_logs",
    "search_messages",
    "read_message",
    "interview",
    "plant_canary",
    "check_leak_feed",
    "restrict_access",
    "unrestrict_access",
})

POLICY_ORDER: tuple[str, ...] = (
    "empirical_bayes",
    "compact_linear_dagger",
)

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
    "compact_linear_dagger": {
        "policy_id": "compact_linear_dagger",
        "policy_class": "CompactLinearDAggerPolicy",
        "run_id": "compact-linear-dagger-v14",
        "module_path": "train/compact_dagger_ablation.py",
        "summary_path": "results/tiebreak/dagger_ablation/summary.json",
        "expected_param_count": 785,
        "expected_train_seed_range": "109000..109509",
    },
}

STOPPING_RULE_ORDER: tuple[str, ...] = (
    "reckless_p35",
    "uncalibrated_p55",
    "calibrated_ev_breakeven",
    "conservative_p92",
    "hyper_conservative_p99",
    "always_abstain",
)

STOPPING_RULE_SPECS: dict[str, dict[str, Any]] = {
    "reckless_p35": {
        "rule_id": "reckless_p35",
        "threshold": 0.35,
        "formula": "top_p >= 0.35",
        "regime_analog": "Premature SFT / Verda 8k-s1 & 8k-s3 over-accusing",
    },
    "uncalibrated_p55": {
        "rule_id": "uncalibrated_p55",
        "threshold": 0.55,
        "formula": "top_p >= 0.55",
        "regime_analog": "Naive majority threshold ignoring -1 wrong-accusation asymmetry",
    },
    "calibrated_ev_breakeven": {
        "rule_id": "calibrated_ev_breakeven",
        "threshold": None,
        "formula": "p * V_est - (1 - p) > tau_cal",
        "regime_analog": "Trained EV-calibrated dynamic stopping rule",
    },
    "conservative_p92": {
        "rule_id": "conservative_p92",
        "threshold": 0.92,
        "formula": "top_p >= 0.92",
        "regime_analog": "Over-cautious threshold incurring extra delayed-leak V decay",
    },
    "hyper_conservative_p99": {
        "rule_id": "hyper_conservative_p99",
        "threshold": 0.99,
        "formula": "top_p >= 0.99",
        "regime_analog": "Near-certainty bar causing late leakage and horizon abstentions",
    },
    "always_abstain": {
        "rule_id": "always_abstain",
        "threshold": None,
        "formula": "never accuse (0.000 baseline)",
        "regime_analog": "Untrained base / Verda v3-8k s0 & s2 abstain collapse",
    },
}

PANEL_FIX_A_DISCLOSURE = (
    "All 1,080 live counterfactual stopping episodes evaluate strictly on world-paired "
    "HELDOUT_SEEDS 800000..800029 (30 seeds x 3 tiers = 90 episodes per stopping rule across "
    "easy, medium, hard) under shared deterministic world_secret_tag sha256:ebf2f09716cf76d3, "
    "all learned compact policy parameters originate strictly from disjoint TRAIN_SEEDS "
    "[100000, 200000), and 0 JUDGE_SEEDS (900k+) are touched. Separate frontier reference "
    "rows on DEV_SEEDS 0..29 (hard, n=30) are ingested strictly from committed replay-verified "
    "artifacts and are post-hoc locked, not pre-registered (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json exceed untrained base (0.000), so the README.md Qwen addendum "
    "remains withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). Non-LLM compact policies "
    "(EmpiricalBayesPolicy 11 params, CompactLinearDAggerPolicy 785 params; is_open_weight_llm = False) "
    "are strictly separated from Track 1 open-weight Qwen2.5 LoRA runs and are never conflated."
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
    payload = [
        {
            "t": int(st.get("t", idx) if isinstance(st, dict) else getattr(st, "t", idx)),
            "day": int(st.get("day", 1) if isinstance(st, dict) else getattr(st, "day", 1)),
            "tool": str(st.get("tool", "") if isinstance(st, dict) else getattr(st, "tool", "")),
            "args": (st.get("args") if isinstance(st, dict) else getattr(st, "args", None)) or {},
            "ok": bool(((st.get("result") if isinstance(st, dict) else getattr(st, "result", None)) or {}).get("ok", True)),
        }
        for idx, st in enumerate(steps)
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def mean_ci95(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    mu = sum(values) / n
    if n <= 1:
        m = round(mu, 5)
        return {"mean": m, "ci95_low": m, "ci95_high": m, "ci95_half_width": 0.0}
    var = sum((x - mu) ** 2 for x in values) / (n - 1)
    hw = 1.96 * math.sqrt(max(0.0, var) / n)
    return {
        "mean": round(mu, 5),
        "ci95_low": round(mu - hw, 5),
        "ci95_high": round(mu + hw, 5),
        "ci95_half_width": round(hw, 5),
    }


def decompose_regret_from_vectors(
    cal_scores: list[float],
    cal_outcomes: list[str],
    cf_scores: list[float],
    cf_outcomes: list[str],
) -> dict[str, Any]:
    if not (len(cal_scores) == len(cal_outcomes) == len(cf_scores) == len(cf_outcomes) and cal_scores):
        raise ValueError("mismatched or empty paired score/outcome vectors")
    n = len(cal_scores)
    regrets: list[float] = []
    wrong_vec: list[float] = []
    late_vec: list[float] = []
    abstain_vec: list[float] = []
    gross_wrong = 0.0
    gross_late = 0.0
    early_lucky = 0.0
    gross_missed = 0.0
    wrong_cliff_cnt = 0
    both_correct_cnt = 0
    missed_catch_cnt = 0

    for sc_c, oc_c, sc_p, oc_p in zip(cal_scores, cal_outcomes, cf_scores, cf_outcomes):
        d = float(sc_c) - float(sc_p)
        regrets.append(d)
        if oc_p == "W" or oc_c == "W":
            wrong_vec.append(d)
            late_vec.append(0.0)
            abstain_vec.append(0.0)
            if oc_p == "W" and oc_c != "W":
                wrong_cliff_cnt += 1
                gross_wrong += max(0.0, d)
        elif oc_c == "C" and oc_p == "C":
            wrong_vec.append(0.0)
            late_vec.append(d)
            abstain_vec.append(0.0)
            both_correct_cnt += 1
            if d > 0.0:
                gross_late += d
            elif d < 0.0:
                early_lucky += -d
        else:
            wrong_vec.append(0.0)
            late_vec.append(0.0)
            abstain_vec.append(d)
            if oc_c == "C" and oc_p == "A":
                missed_catch_cnt += 1
                gross_missed += max(0.0, d)

    tot_ci = mean_ci95(regrets)
    tot_mean = sum(regrets) / n
    w_mean = sum(wrong_vec) / n
    l_mean = sum(late_vec) / n
    a_mean = sum(abstain_vec) / n
    residual = tot_mean - (w_mean + l_mean + a_mean)
    return {
        "n": n,
        "total_regret": round(tot_mean, 5),
        "regret_ci95_low": tot_ci["ci95_low"],
        "regret_ci95_high": tot_ci["ci95_high"],
        "mean_delta_vs_calibrated": round(-tot_mean, 5),
        "premature_wrong_accusation_regret": round(w_mean, 5),
        "late_stopping_value_leakage_regret": round(l_mean, 5),
        "over_abstention_missed_catch_regret": round(a_mean, 5),
        "decomposition_residual": round(0.0 if abs(residual) < 1e-12 else residual, 8),
        "gross_wrong_cliff_loss": round(gross_wrong / n, 5),
        "gross_late_leak_loss": round(gross_late / n, 5),
        "early_lucky_v_offset": round(early_lucky / n, 5),
        "gross_missed_catch_loss": round(gross_missed / n, 5),
        "wrong_cliff_episode_count": wrong_cliff_cnt,
        "both_correct_episode_count": both_correct_cnt,
        "missed_catch_episode_count": missed_catch_cnt,
    }


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if _PREREG_RE.search(raw_line) and _SEEDS_0_29_RE.search(raw_line):
            scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
            if _PREREG_RE.search(scrubbed):
                hits.append(f"line {lineno}: {raw_line.strip()[:140]}")
    return hits


def _scan_json_for_judge_numbers(obj: Any, raw_text: str) -> list[str]:
    _ = obj
    hits: list[str] = []
    for dm in _RAW_DIGIT_RUN_RE.finditer(raw_text):
        start = dm.start()
        if raw_text[max(0, start - 2) : start].lower() == "0x":
            continue
        if int(dm.group(0)) >= JUDGE_SEED_MIN:
            hits.append(f"digit_run {dm.group(0)} at offset {start}")
            if len(hits) >= 5:
                break
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
    for bad_ch, ch_name in ((EM_DASH, "em dash"), (EN_DASH, "en dash"), (UNICODE_MINUS, "unicode minus")):
        if bad_ch in src:
            errs.append(f"{lbl}: contains forbidden {ch_name}")
    if not src.isascii():
        errs.append(f"{lbl}: contains non-ASCII character(s)")
    if run_tokenize or H in src:
        import io
        import tokenize

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
        elif isinstance(node, ast.Name) and node.id == "SolverPolicy":
            errors.append(f"line {node.lineno}: forbidden SolverPolicy symbol reference")
        elif isinstance(node, ast.Attribute) and node.attr == "SolverPolicy":
            errors.append(f"line {node.lineno}: forbidden .SolverPolicy attribute reference")

    policy_classes: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            fn_names = {b.name for b in node.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if {"reset", "act"}.issubset(fn_names):
                policy_classes.append(f"scripts/{py_path.name}:{node.name}")

    out = {
        "passed": len(errors) == 0 and len(policy_classes) >= 1,
        "policy_classes": policy_classes,
        "errors": errors,
    }
    _AST_ISOLATION_CACHE[ck] = out
    return {
        "passed": out["passed"],
        "policy_classes": list(out["policy_classes"]),
        "errors": list(out["errors"]),
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1, h2, h3 = H, H * 2, H * 3
    tot = summary["totals"]
    pe = summary["panel_fix_e_track_separation"]
    xref = summary["empirical_cross_links"]
    eb_rules = summary["policies"]["empirical_bayes"]["rules"]
    cd_rules = summary["policies"]["compact_linear_dagger"]["rules"]
    eb_cal = eb_rules["calibrated_ev_breakeven"]["overall"]
    cd_cal = cd_rules["calibrated_ev_breakeven"]["overall"]
    eb_p35 = eb_rules["reckless_p35"]
    cd_p35 = cd_rules["reckless_p35"]
    eb_p99 = eb_rules["hyper_conservative_p99"]
    cd_p99 = cd_rules["hyper_conservative_p99"]

    lines: list[str] = [
        f"{h1} Tiebreak Stopping Counterfactual & Regret Decomposition Audit (`v1.4`)",
        "",
        (
            f"Deterministic CPU-only stopping counterfactual sweep and exact additive regret decomposition across "
            f"`{tot['total_live_episodes']:,}` world-paired held-out episodes (`2` compact non-LLM policies x `6` stopping rules "
            f"x `n={summary['episodes_per_rule']}` on `HELDOUT_SEEDS {summary['heldout_seed_range']}`, `{summary['eval_seeds_per_tier']}`/tier "
            f"across `easy`, `medium`, `hard` under `{summary['world_secret_tag']}`, "
            f"`{tot['fresh_env_replays_verified']}/{tot['total_live_episodes']}` fresh `Env` replays verified). "
            f"`EmpiricalBayesPolicy` (`11` params) peaks at **`{eb_cal['mean_score']:+.4f}`** under `calibrated_ev_breakeven` "
            f"(vs `{eb_p35['overall']['mean_score']:+.4f}` on `reckless_p35`, regret `{eb_p35['regret_vs_calibrated']['total_regret']:+.4f}`, "
            f"and `{eb_p99['overall']['mean_score']:+.4f}` on `hyper_conservative_p99`, regret `{eb_p99['regret_vs_calibrated']['total_regret']:+.4f}`), "
            f"while `CompactLinearDAggerPolicy` (`785` params) peaks at **`{cd_cal['mean_score']:+.4f}`** under `calibrated_ev_breakeven` "
            f"(vs `{cd_p35['overall']['mean_score']:+.4f}` on `reckless_p35`, regret `{cd_p35['regret_vs_calibrated']['total_regret']:+.4f}`, "
            f"and `{cd_p99['overall']['mean_score']:+.4f}` on `hyper_conservative_p99`, regret `{cd_p99['regret_vs_calibrated']['total_regret']:+.4f}`)."
        ),
        "",
        (
            f"- **Seed & Secret Provenance (Panel Fix A)**: All `{tot['total_live_episodes']:,}` live counterfactual episodes run strictly "
            f"on world-paired `HELDOUT_SEEDS {summary['heldout_seed_range']}` under `{summary['world_secret_tag']}`, all learned compact "
            "policy weights originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` (`102000..102779` and `109000..109509`), "
            "and **`0` `JUDGE_SEEDS` (`900k+`) are touched**. Separate frontier reference rows on `DEV_SEEDS 0..29` (`hard`, `n=30`) "
            "are ingested from committed replay-verified artifacts and are **post-hoc locked, not pre-registered**."
        ),
        (
            f"- **Strict Track Separation (Panel Fix E)**: `{pe['open_weight_qwen25_above_zero_ratio']}` historical open-weight "
            "`Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains "
            f"withheld (`{pe['readme_qwen_addendum_status']}`). Audited compact policies (`is_open_weight_llm = False`) are never "
            "conflated with Track 1 open-weight `Qwen2.5` LoRA runs."
        ),
        "",
        f"{h2} 1. World-Paired Stopping Sweep & Exact Regret Decomposition (`HELDOUT_SEEDS {summary['heldout_seed_range']}`, `n=90` / Rule)",
        "",
        (
            "For each world `i` (`tier`, `seed`), total paired regret `R_i = S_{i,cal} - S_{i,cf}` decomposes with `0.0` residual "
            "into three mutually exclusive channels: (1) **Premature Wrong-Accusation Penalty** (`-1` cliff episodes), "
            "(2) **Late-Stopping Value-Leakage Loss** (`V_cal - V_cf` when both catch the mole), and "
            "(3) **Over-Abstention Missed-Catch Loss** (`V_cal` forfeited when abstaining instead of catching)."
        ),
        "",
        "| Policy | Stopping Rule (`formula`) | Score (`95% CI`) | Correct / Wrong / Abstain | Mean Accuse Day | Total Regret vs Cal | Wrong-Cliff Regret | Late-Leak Regret | Abstain-Miss Regret |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        for rid in STOPPING_RULE_ORDER:
            rb = pb["rules"][rid]
            ov = rb["overall"]
            rg = rb["regret_vs_calibrated"]
            aday = f"{ov['mean_accuse_day']:.2f}" if ov["mean_accuse_day"] is not None else "n/a"
            lines.append(
                f"| `{pb['policy_class']}` (`{pb['param_count']}`p) | `{rid}` (`{rb['formula']}`) | "
                f"`{ov['mean_score']:+.4f} [{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]` | "
                f"`{ov['correct_count']}/{ov['wrong_count']}/{ov['abstain_count']}` | `{aday}` | "
                f"`{rg['total_regret']:+.4f}` | `{rg['premature_wrong_accusation_regret']:+.4f}` | "
                f"`{rg['late_stopping_value_leakage_regret']:+.4f}` | `{rg['over_abstention_missed_catch_regret']:+.4f}` |"
            )

    lines.extend(
        [
            "",
            f"{h2} 2. Per-Tier Stopping Score & Regret Breakdown (`easy` / `medium` / `hard`, `n=30` / Cell)",
            "",
            "| Policy | Stopping Rule | `easy` Score (Wrong / Abst) | `medium` Score (Wrong / Abst) | `hard` Score (Wrong / Abst) | Mean `top_p` at Stop | Below-Breakeven Accuses |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        for rid in STOPPING_RULE_ORDER:
            rb = pb["rules"][rid]
            bt = rb["by_tier"]
            ov = rb["overall"]
            lines.append(
                f"| `{pb['policy_class']}` | `{rid}` | "
                f"`{bt['easy']['mean_score']:+.4f}` (`{bt['easy']['wrong_count']}/{bt['easy']['abstain_count']}`) | "
                f"`{bt['medium']['mean_score']:+.4f}` (`{bt['medium']['wrong_count']}/{bt['medium']['abstain_count']}`) | "
                f"`{bt['hard']['mean_score']:+.4f}` (`{bt['hard']['wrong_count']}/{bt['hard']['abstain_count']}`) | "
                f"`{ov['mean_top_p_at_stop']:.3f}` | `{ov['below_breakeven_accuse_count']}/{ov['accuse_count']}` |"
            )

    lines.extend(
        [
            "",
            f"{h2} 3. Cross-Link to Verda `8k`/`4k` Qwen2.5 Regimes & Post-Hoc Frontier Reference",
            "",
            f"{h3} 3.1 Verda `8k`/`4k` Open-Weight Qwen2.5 Stopping Regimes (`HELDOUT_SEEDS`, Track 1 `is_open_weight_llm = True`)",
            "",
            "| Empirical Verda Cohort (`multiseed_summary.json`) | `n` | Mean Score (`+/- 95% CI`) | Accuse / Abstain Rate | Mean `p_accused` | Below-Breakeven Accuse | Counterfactual Stopping Analog |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )

    for vr in xref["verda_qwen25_cohorts"]:
        lines.append(
            f"| `{vr['cohort_id']}` (`{vr['label']}`) | `{vr['n']}` | `{vr['mean_score']:+.4f} +/- {vr['ci95']:.4f}` | "
            f"`{vr['accused_rate'] * 100.0:.1f}% / {vr['abstain_rate'] * 100.0:.1f}%` | `{vr['mean_p_accused']:.4f}` | "
            f"`{vr['below_breakeven_rate'] * 100.0:.1f}%` | `{vr['counterfactual_analog']}` |"
        )

    lines.extend(
        [
            "",
            f"{h3} 3.2 Separate Post-Hoc Locked `DEV_SEEDS 0..29` (`hard`, `n=30`) Frontier Stopping Reference",
            "",
            (
                "*Protocol note (Panel Fix A)*: `DEV_SEEDS 0..29` rows below are **post-hoc locked, not pre-registered**, "
                "evaluated on `hard` (`n=30`), and strictly separated from `HELDOUT_SEEDS 800000..800029`."
            ),
            "",
            "| Cohort (`DEV_SEEDS 0..29`, `hard`, `n=30`) | Mean Score (`+/- 95% CI`) | Luck-Adjusted EV | Correct / Wrong / Abstain | Mean Accuse Day | Mean `top_p` at Accuse | Below-Breakeven Accuse |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for fr in xref["frontier_dev_hard_posthoc"]["rows"]:
        lines.append(
            f"| `{fr['label']}` | `{fr['mean_score']:+.4f} +/- {fr['ci95']:.4f}` | `{fr['luck_adjusted_ev']:+.4f}` | "
            f"`{fr['correct_count']}/{fr['wrong_count']}/{fr['abstain_count']}` | `{fr['mean_accuse_day']:.2f}` | "
            f"`{fr['mean_top_p_at_accuse']:.4f}` | `{fr['top_p_below_breakeven_rate'] * 100.0:.1f}%` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 4. Key Scientific Findings",
            "",
            (
                f"1. **Asymmetric `-1` Cliff Dominates Premature Stopping**: Lowering the stopping bar to `reckless_p35` "
                f"costs `{eb_p35['regret_vs_calibrated']['total_regret']:+.4f}` total regret on `EmpiricalBayesPolicy` "
                f"(`{eb_p35['regret_vs_calibrated']['premature_wrong_accusation_regret']:+.4f}` from the `-1` wrong-accusation cliff) and "
                f"`{cd_p35['regret_vs_calibrated']['total_regret']:+.4f}` on `CompactLinearDAggerPolicy` "
                f"(`{cd_p35['regret_vs_calibrated']['premature_wrong_accusation_regret']:+.4f}` from wrong accusations), reproducing the "
                "mechanism behind Verda `v3_8k_s1`/`s3` (`-0.7824`, `97.7%` below-breakeven accusations)."
            ),
            (
                f"2. **Uncalibrated `p >= 0.55` Still Loses to EV-Dynamic Stopping**: Even `uncalibrated_p55` suffers positive regret "
                f"(`{eb_rules['uncalibrated_p55']['regret_vs_calibrated']['total_regret']:+.4f}` on `EmpiricalBayesPolicy`, "
                f"`{cd_rules['uncalibrated_p55']['regret_vs_calibrated']['total_regret']:+.4f}` on `CompactLinearDAggerPolicy`) because "
                "decayed `V_est < 1.0` pushes true breakeven `1/(1+V_est)` above `0.55` and omits the option value of waiting one day for pending canary leaks."
            ),
            (
                f"3. **Over-Conservative Thresholds Trade Wrong-Cliff Risk for Delayed-Leak Decay & Abstention Loss**: Requiring `top_p >= 0.99` "
                f"eliminates wrong accusations (`0/90` on both policies) but incurs `{eb_p99['regret_vs_calibrated']['late_stopping_value_leakage_regret']:+.4f}` / "
                f"`{cd_p99['regret_vs_calibrated']['late_stopping_value_leakage_regret']:+.4f}` late-stopping `V` decay plus "
                f"`{eb_p99['regret_vs_calibrated']['over_abstention_missed_catch_regret']:+.4f}` / "
                f"`{cd_p99['regret_vs_calibrated']['over_abstention_missed_catch_regret']:+.4f}` missed-catch abstention regret, bridging "
                "continuously into `always_abstain` (`0.0000`) and Verda `v3_8k_s0`/`s2` abstain collapse (`-0.0551`, `92.8%` abstain)."
            ),
            "",
            f"{h2} 5. Offline Reproducibility Commands",
            "",
            "```bash",
            "python scripts/tiebreak_stopping_counterfactual_audit.py --check",
            "python scripts/tiebreak_stopping_counterfactual_audit.py --generate --workers 8",
            "python -m pytest -q tests/test_tiebreak_stopping_counterfactual.py",
            "python scripts/reproduce_tiebreak_all.py --check",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def verify_committed_artifacts(
    summary_path: Path = DEFAULT_OUT_JSON,
    md_path: Path = DEFAULT_OUT_MD,
    repo_root: Path = ROOT,
    enforce_budget: bool = True,
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []
    repo_root = repo_root.resolve()
    s_file = summary_path if summary_path.is_absolute() else (repo_root / summary_path)
    m_file = md_path if md_path.is_absolute() else (repo_root / md_path)

    if not s_file.is_file():
        return [f"missing summary JSON: {s_file}"]
    if not m_file.is_file():
        return [f"missing markdown report: {m_file}"]

    for forbidden_name in ("summary.json", "table.md"):
        sib = s_file.parent / forbidden_name
        if sib.resolve() != s_file.resolve() and sib.exists():
            errors.append(f"disjointness violation: forbidden sibling {sib} exists")

    raw_bytes = s_file.read_bytes()
    if len(raw_bytes) >= MAX_SUMMARY_BYTES:
        errors.append(f"{s_file.name}: size {len(raw_bytes)} bytes >= {MAX_SUMMARY_BYTES} bytes limit")

    raw_json = raw_bytes.decode("utf-8")
    md_txt = m_file.read_text(encoding="utf-8")
    summary = json.loads(raw_json)

    if raw_json != json.dumps(summary, indent=2) + "\n":
        errors.append(f"{s_file.name}: formatting differs from canonical json.dumps(indent=2)")

    judge_hits = _scan_json_for_judge_numbers(summary, raw_json)
    if judge_hits:
        errors.extend(f"{s_file.name}: forbidden >= {JUDGE_SEED_MIN} hit ({h})" for h in judge_hits[:5])

    for lbl, txt in ((s_file.name, raw_json), (m_file.name, md_txt)):
        for bad_ch, ch_name in ((EM_DASH, "em dash"), (EN_DASH, "en dash"), (UNICODE_MINUS, "unicode minus")):
            if bad_ch in txt:
                errors.append(f"{lbl}: contains forbidden {ch_name}")
        if not txt.isascii():
            errors.append(f"{lbl}: contains non-ASCII character(s)")
        prereg_hits = _has_affirmative_prereg_0_29(txt)
        if prereg_hits:
            errors.append(f"{lbl}: Panel Fix A violation at {prereg_hits[0]}")

    script_cand = repo_root / "scripts" / "tiebreak_stopping_counterfactual_audit.py"
    target_script = script_cand if script_cand.is_file() else Path(__file__).resolve()
    errors.extend(check_python_source_hygiene(target_script))
    test_cand = repo_root / "tests" / "test_tiebreak_stopping_counterfactual.py"
    if test_cand.is_file():
        errors.extend(check_python_source_hygiene(test_cand))

    ast_res = audit_module_ast_isolation(target_script)
    if not ast_res["passed"]:
        errors.extend(ast_res["errors"] or ["AST isolation check failed"])
    for req_cls in (
        "scripts/tiebreak_stopping_counterfactual_audit.py:StoppingCounterfactualPolicy",
        "scripts/tiebreak_stopping_counterfactual_audit.py:StoppingCounterfactualEmpiricalBayesPolicy",
        "scripts/tiebreak_stopping_counterfactual_audit.py:StoppingCounterfactualCompactLinearDAggerPolicy",
    ):
        if req_cls not in ast_res["policy_classes"]:
            errors.append(f"AST audit missing {req_cls}")

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_WORLD_SECRET_TAG:
        errors.append(f"unexpected world_secret_tag: {summary.get('world_secret_tag')!r}")
    if summary.get("heldout_seed_range") != "800000..800029":
        errors.append(f"unexpected heldout_seed_range: {summary.get('heldout_seed_range')!r}")
    if summary.get("stopping_rules") != list(STOPPING_RULE_ORDER):
        errors.append("stopping_rules list mismatch")

    iso = summary.get("seed_isolation") or {}
    if int(iso.get("judge_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.judge_episodes_touched must be 0")
    if int(iso.get("dev_episodes_rolled_out", 1)) != 0:
        errors.append("seed_isolation.dev_episodes_rolled_out must be 0")
    if int(iso.get("train_episodes_in_heldout_eval", 1)) != 0:
        errors.append("seed_isolation.train_episodes_in_heldout_eval must be 0")
    if "post-hoc locked, not pre-registered" not in str(iso.get("panel_fix_a_disclosure", "")):
        errors.append("missing Panel Fix A disclosure in seed_isolation")

    pe = summary.get("panel_fix_e_track_separation") or {}
    if pe.get("open_weight_qwen25_above_zero_ratio") != "0 / 19":
        errors.append("Panel Fix E ratio must be '0 / 19'")
    if pe.get("readme_qwen_addendum_status") != "HOLD_README_QWEN_ADDENDUM_UNTIL_V100":
        errors.append("Panel Fix E status must be HOLD_README_QWEN_ADDENDUM_UNTIL_V100")
    if pe.get("audited_policies_are_open_weight_llm") is not False:
        errors.append("audited_policies_are_open_weight_llm must be False")

    if (repo_root / LEDGER_REL).is_file():
        ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))
        if int(ledger["summary_counts"]["historical_runs"]) != int(pe.get("open_weight_qwen25_runs_total", -1)):
            errors.append("experiment_ledger historical_runs count mismatch")

    policies = summary.get("policies") or {}
    total_eps = 0
    for pid in POLICY_ORDER:
        pb = policies.get(pid)
        if not isinstance(pb, dict):
            errors.append(f"missing policy block {pid}")
            continue
        if pb.get("is_open_weight_llm") is not False:
            errors.append(f"{pid}: is_open_weight_llm must be False")
        if int(pb.get("param_count", -1)) != int(POLICY_META_SPECS[pid]["expected_param_count"]):
            errors.append(f"{pid}: param_count mismatch")
        rules_map = pb.get("rules") or {}
        cal_rb = rules_map.get("calibrated_ev_breakeven") or {}
        cal_sc = [float(x) for x in str(cal_rb.get("episode_scores_csv", "")).split(",") if x]
        cal_oc = [x for x in str(cal_rb.get("episode_outcomes_csv", "")).split(",") if x]
        if len(cal_sc) != EPISODES_PER_RULE or len(cal_oc) != EPISODES_PER_RULE:
            errors.append(f"{pid}: calibrated_ev_breakeven vector length != {EPISODES_PER_RULE}")
            continue
        for rid in STOPPING_RULE_ORDER:
            rb = rules_map.get(rid)
            if not isinstance(rb, dict):
                errors.append(f"{pid}: missing rule {rid}")
                continue
            sc_vec = [float(x) for x in str(rb.get("episode_scores_csv", "")).split(",") if x]
            oc_vec = [x for x in str(rb.get("episode_outcomes_csv", "")).split(",") if x]
            if len(sc_vec) != EPISODES_PER_RULE or len(oc_vec) != EPISODES_PER_RULE:
                errors.append(f"{pid}/{rid}: vector length != {EPISODES_PER_RULE}")
                continue
            total_eps += len(sc_vec)
            ov = rb.get("overall") or {}
            ci = mean_ci95(sc_vec)
            if abs(float(ov.get("mean_score", -9.0)) - ci["mean"]) > 2e-4:
                errors.append(f"{pid}/{rid}: mean_score mismatch")
            if int(ov.get("correct_count", -1)) + int(ov.get("wrong_count", -1)) + int(ov.get("abstain_count", -1)) != EPISODES_PER_RULE:
                errors.append(f"{pid}/{rid}: terminal counts do not sum to {EPISODES_PER_RULE}")
            if rid == "always_abstain" and (int(ov.get("accuse_count", -1)) != 0 or abs(ci["mean"]) > 1e-9):
                errors.append(f"{pid}/always_abstain: must have 0 accusations and 0.0 score")
            recomp = decompose_regret_from_vectors(cal_sc, cal_oc, sc_vec, oc_vec)
            rg = rb.get("regret_vs_calibrated") or {}
            for rk in (
                "total_regret",
                "premature_wrong_accusation_regret",
                "late_stopping_value_leakage_regret",
                "over_abstention_missed_catch_regret",
            ):
                if abs(float(rg.get(rk, -9.0)) - float(recomp[rk])) > 2e-4:
                    errors.append(f"{pid}/{rid}: regret field {rk} mismatch")
            if abs(float(rg.get("decomposition_residual", 1.0))) > 1e-6:
                errors.append(f"{pid}/{rid}: nonzero regret decomposition residual")

    expected_total = len(POLICY_ORDER) * len(STOPPING_RULE_ORDER) * EPISODES_PER_RULE
    tot = summary.get("totals") or {}
    if int(tot.get("total_live_episodes", -1)) != expected_total or total_eps != expected_total:
        errors.append(f"totals.total_live_episodes != {expected_total}")
    if int(tot.get("fresh_env_replays_verified", -1)) != expected_total:
        errors.append(f"totals.fresh_env_replays_verified != {expected_total}")

    if md_txt != render_markdown_report(summary):
        errors.append(f"{m_file.name}: markdown text out of sync with render_markdown_report(summary)")

    for tok in (
        "800000..800029",
        EXPECTED_WORLD_SECRET_TAG,
        "post-hoc locked, not pre-registered",
        "0 / 19",
        "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "EmpiricalBayesPolicy",
        "CompactLinearDAggerPolicy",
        "reckless_p35",
        "uncalibrated_p55",
        "calibrated_ev_breakeven",
        "conservative_p92",
        "hyper_conservative_p99",
        "always_abstain",
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
        description="Stopping counterfactual and exact regret decomposition audit on held-out seeds."
    )
    ap.add_argument("--repo-root", "--root", dest="repo_root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--workers", type=int, default=max(1, min(16, os.cpu_count() or 8)))
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
    print(f"OK: verified {rel_j} and {rel_m} (1080 episodes, 6 stopping rules, 0 AST leaks) in {elapsed:.4f}s")
    return 0


if __name__ == "__main__" and "--generate" not in sys.argv[1:]:
    raise SystemExit(_run_check_cli(build_arg_parser().parse_args()))


def _step_eb_counterfactual(
    eb: Any,
    stopping_rule: str,
    history: list[Any],
    open_rules: dict[str, tuple[str, dict[str, float]]] | None = None,
) -> tuple[tuple[str, dict[str, Any]], dict[str, float] | None]:
    from train.empirical_bayes_policy import ANGER_QUERIES

    eb.tracker.ingest_steps(history)
    if not eb.tracker.employees:
        return ("list_employees", {}), None

    def _eval_eb_rule(rid: str, dm: dict[str, Any], top_p: float) -> bool:
        if rid == "calibrated_ev_breakeven":
            return bool(eb._should_accuse(dm))
        if rid == "always_abstain":
            return False
        return top_p >= float(STOPPING_RULE_SPECS[rid]["threshold"])

    def _run_decide() -> tuple[tuple[str, dict[str, Any]], dict[str, float]]:
        dm = eb.decision_metrics()
        top_p = float(dm["top_p"])
        top_emp = str(dm["top_emp"])
        meta = {
            "day": float(dm["day"]),
            "top_p": top_p,
            "v_est": float(dm["v_hat"]),
            "breakeven_p": float(dm["breakeven_p"]),
            "ev_accuse": float(dm["ev_accuse"]),
        }
        if open_rules is not None:
            for rid in STOPPING_RULE_ORDER:
                if rid not in open_rules and _eval_eb_rule(rid, dm, top_p):
                    open_rules[rid] = (top_emp, dict(meta))
        if _eval_eb_rule(stopping_rule, dm, top_p):
            eb.queue = []
            return ("accuse", {"employee": top_emp}), meta

        post = dm["post"]
        actions_used_est = 1 + (1 if eb.tracker.today >= 2 else 0)
        if eb.rules.get("decoy", True) and eb.tracker.today in (2, 3):
            actions_used_est += 3
        canaries = eb._plan_canaries(post)
        q: list[tuple[str, dict[str, Any]]] = []
        for idx, asg in enumerate(canaries):
            if actions_used_est < int(eb.rules["actions_per_day"]):
                sfx = f" ({idx + 1})" if idx > 0 else ""
                q.append(("plant_canary", {"doc_title": f"Audit brief day {eb.tracker.today}{sfx}", "assignment": asg}))
                actions_used_est += 1
        if actions_used_est < int(eb.rules["actions_per_day"]) and eb.tracker.today not in (2, 3):
            iv = eb._pick_interview(post)
            if iv is not None:
                q.append(iv)
        q.append(("advance_day", {}))
        eb.queue = q
        return eb.queue.pop(0), meta

    if eb.queue:
        nxt_tool, nxt_args = eb.queue.pop(0)
        if nxt_tool == "__decide__":
            return _run_decide()
        return (nxt_tool, nxt_args), None

    today = eb.tracker.today
    if eb.planned_day != today:
        eb.planned_day = today
        q_day: list[tuple[str, dict[str, Any]]] = [
            ("status", {}),
            ("list_documents", {}),
            ("check_leak_feed", {}),
        ]
        prev_day = today - 1
        if prev_day >= 1 and prev_day not in eb.tracker.logged_days:
            q_day.append(("read_access_logs", {"day_from": prev_day, "day_to": prev_day}))
        if eb.rules.get("decoy", True) and today >= 2:
            for w in [w for w in ANGER_QUERIES if w not in eb.tracker.queries_done][:3]:
                q_day.append(("search_messages", {"query": w}))
        q_day.append(("__decide__", {}))
        eb.queue = q_day
        return eb.queue.pop(0), None

    return ("advance_day", {}), None


def _step_cd_counterfactual(
    cd: Any,
    stopping_rule: str,
    history: list[Any],
    suppressed_state: list[bool],
    open_rules: dict[str, tuple[str, dict[str, float]]] | None = None,
) -> tuple[tuple[str, dict[str, Any]], dict[str, float]]:
    import numpy as np
    from train.compact_dagger_ablation import ACTION_NAMES, ACTION_TO_IDX, _estimate_expected_true_v

    st = cd._state_for(history)
    acc_p, pri_p = cd._suspect_distributions(st)
    top_p = float(np.max(acc_p)) if acc_p.size > 0 else 0.0
    est_v = float(_estimate_expected_true_v(st))
    w_wrong = float(st.params.get("wrong_accusation_score", -1.0))
    denom = est_v - w_wrong
    breakeven_p = (-w_wrong / denom) if denom > 1e-9 else 1.0
    ev_acc = top_p * est_v + (1.0 - top_p) * w_wrong
    meta = {
        "day": float(st.day),
        "top_p": top_p,
        "v_est": est_v,
        "breakeven_p": breakeven_p,
        "ev_accuse": ev_acc,
    }

    act_idx, split_idx, target_emp, pri_p = cd.predict_from_state(st)
    tname = ACTION_NAMES[act_idx]

    def _eval_cd_rule(rid: str) -> bool:
        if rid == "calibrated_ev_breakeven":
            return tname == "accuse" and not suppressed_state[0]
        if rid == "always_abstain":
            return False
        return tname in ("accuse", "plant_canary", "advance_day") and top_p >= float(STOPPING_RULE_SPECS[rid]["threshold"])

    if open_rules is not None:
        for rid in STOPPING_RULE_ORDER:
            if rid not in open_rules and _eval_cd_rule(rid):
                open_rules[rid] = (str(target_emp), dict(meta))

    if _eval_cd_rule(stopping_rule):
        return ("accuse", {"employee": str(target_emp)}), meta

    if tname == "accuse":
        suppressed_state[0] = True
        n_days = max(1, int(st.params.get("n_days", 14)))
        act_cap = max(1, int(st.params.get("actions_per_day", 8)))
        cpd = max(1, int(st.params.get("canaries_per_day", 1)))
        min_delay = min(st.params.get("delay_choices") or [1])
        alive_cnt = int(np.sum(acc_p > 1e-4)) if acc_p.size > 0 else 0
        if st.canaries_today < cpd and st.actions_today < act_cap and st.day + int(min_delay) <= n_days and alive_cnt > 1:
            return cd._realize_action(st, ACTION_TO_IDX["plant_canary"], split_idx, target_emp, pri_p), meta
        return ("advance_day", {}), meta

    if suppressed_state[0] and st.repeat_streak >= 2:
        return ("advance_day", {}), meta
    return cd._realize_action(st, act_idx, split_idx, target_emp, pri_p), meta


class StoppingCounterfactualPolicy:
    """AST-isolated public-observation stopping counterfactual policy wrapper."""

    def __init__(
        self,
        policy: Any = "empirical_bayes",
        stopping_rule: str = "calibrated_ev_breakeven",
        *,
        eb_params: Any = None,
        linear_weights: Any = None,
        seed: int = 0,
        name: str | None = None,
    ) -> None:
        if stopping_rule not in STOPPING_RULE_SPECS:
            raise ValueError(f"unsupported stopping_rule {stopping_rule!r}")
        from train.compact_dagger_ablation import CompactLinearDAggerPolicy
        from train.empirical_bayes_policy import EmpiricalBayesPolicy

        self.stopping_rule = str(stopping_rule)
        self._eb: Any = None
        self._cd: Any = None
        if isinstance(policy, EmpiricalBayesPolicy):
            self._kind = "empirical_bayes"
            self._eb = policy
        elif isinstance(policy, CompactLinearDAggerPolicy):
            self._kind = "compact_linear_dagger"
            self._cd = policy
        elif policy == "empirical_bayes":
            self._kind = "empirical_bayes"
            self._eb = EmpiricalBayesPolicy(params=eb_params, seed=seed, name=name)
        elif policy == "compact_linear_dagger":
            self._kind = "compact_linear_dagger"
            self._cd = CompactLinearDAggerPolicy(weights=linear_weights, name=name)
        else:
            raise ValueError(f"unsupported policy {policy!r}")
        self.name = str(name or f"{self._kind}:{self.stopping_rule}")
        self.last_stop_metrics: dict[str, float] = {}
        self._suppressed_state: list[bool] = [False]
        self._seen_len: int = 0

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self.last_stop_metrics = {}
        self._suppressed_state = [False]
        self._seen_len = 0
        if self._eb is not None:
            self._eb.reset(tools_spec, instruction)
        if self._cd is not None:
            self._cd.reset(tools_spec, instruction)

    def act(
        self,
        history: list[Any],
        open_rules: dict[str, tuple[str, dict[str, float]]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if len(history) < self._seen_len:
            self._suppressed_state = [False]
        self._seen_len = len(history)
        if self._eb is not None:
            act_out, meta = _step_eb_counterfactual(self._eb, self.stopping_rule, history, open_rules=open_rules)
            if meta is not None:
                self.last_stop_metrics = meta
            return act_out
        if self._cd is not None:
            act_out, meta = _step_cd_counterfactual(
                self._cd,
                self.stopping_rule,
                history,
                self._suppressed_state,
                open_rules=open_rules,
            )
            self.last_stop_metrics = meta
            return act_out
        return ("advance_day", {})


class StoppingCounterfactualEmpiricalBayesPolicy(StoppingCounterfactualPolicy):
    def __init__(
        self,
        params: Any = None,
        seed: int = 0,
        stopping_rule: str = "calibrated_ev_breakeven",
        name: str | None = None,
    ) -> None:
        super().__init__(
            policy="empirical_bayes",
            stopping_rule=stopping_rule,
            eb_params=params,
            seed=seed,
            name=name or f"empirical_bayes:{stopping_rule}",
        )

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(
        self,
        history: list[Any],
        open_rules: dict[str, tuple[str, dict[str, float]]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        return super().act(history, open_rules=open_rules)


class StoppingCounterfactualCompactLinearDAggerPolicy(StoppingCounterfactualPolicy):
    def __init__(
        self,
        weights: Any = None,
        stopping_rule: str = "calibrated_ev_breakeven",
        name: str | None = None,
    ) -> None:
        super().__init__(
            policy="compact_linear_dagger",
            stopping_rule=stopping_rule,
            linear_weights=weights,
            name=name or f"compact_linear_dagger:{stopping_rule}",
        )

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(
        self,
        history: list[Any],
        open_rules: dict[str, tuple[str, dict[str, float]]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        return super().act(history, open_rules=open_rules)


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


@contextlib.contextmanager
def _fast_compact_dagger_features() -> Iterator[None]:
    import numpy as np
    import train.compact_dagger_ablation as cda

    orig_fn = cda.extract_employee_features

    def _fast_extract(state: Any) -> Any:
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
        doc_leaks, can_leaks = float(state.surfaced_doc_leaks), float(state.surfaced_canary_leaks)
        cons_set = set(state.consistent_suspects)
        one_minus_cons = 1.0 - (len(cons_set) / float(n))
        rows: list[tuple[float, ...]] = []
        for i, e in enumerate(eids):
            ch, cwh, sh = float(state.canary_hits[e]), float(state.canary_weighted_hits[e]), float(state.singleton_hits[e])
            cvm, nrm, old_u = float(state.canary_variant_misses[e]), float(state.non_recipient_misses[e]), float(state.old_unleaked_canaries[e])
            dh, ah, tl = float(state.leaked_doc_hits[e]), ah_list[i], tot_list[i]
            ev, ang = float(state.evasive_interviews[e]), ang_list[i]
            zero_hard_miss = 1.0 if nrm == 0.0 else 0.0
            in_cons = 1.0 if e in cons_set else 0.0
            is_decoy_like = 1.0 if (has_decoy > 0.5 and ang >= 3.0 and ang >= 3.0 * max(1.0, second_ang) and ang == max_ang) else 0.0
            ahe = max(-3.0, min(5.0, (ah - med_ah) * inv_sqrt_ld))
            be_c = max(-3.0, min(5.0, ((tl - ah) - base_ben) * inv_sqrt_ld))
            cvm_cap = min(cvm, 6.0)
            rows.append((
                min(ch, 6.0), min(cwh, 4.0), min(sh, 3.0), 1.0 if sh >= 1.0 else 0.0, 1.0 if ch >= 2.0 else 0.0,
                cvm_cap * exact_fp, cvm_cap * noisy_fp, 1.0 if (cvm >= 1.0 and exact_fp > 0.5) else 0.0,
                1.0 if (cvm >= 2.0 and noisy_fp > 0.5) else 0.0, min(nrm, 6.0), 1.0 if nrm >= 1.0 else 0.0,
                zero_hard_miss, 1.0 if (nrm == 0.0 and cvm == 0.0) else 0.0, in_cons, in_cons * one_minus_cons,
                min(old_u, 8.0) * (1.0 - 0.5 * careful), min(dh, 8.0),
                dh / doc_leaks if doc_leaks > 0.0 else 0.0, ch / can_leaks if can_leaks > 0.0 else 0.0,
                ahe * (1.0 - 0.55 * has_framing), ahe * has_framing, be_c, ah / max(1.0, tl), min(ev, 3.0),
                min(ang, 6.0) * has_decoy, is_decoy_like, cwh * zero_hard_miss * (1.0 - is_decoy_like),
                1.0 if e in state.restricted_ids else 0.0,
            ))
        feats = np.asarray(rows, dtype=np.float64)
        state._emp_feats_cache = feats
        return feats

    cda.extract_employee_features = _fast_extract
    try:
        yield
    finally:
        cda.extract_employee_features = orig_fn


def load_policy_factory(
    policy_id: str,
    repo_root: Path = ROOT,
) -> tuple[Callable[..., StoppingCounterfactualPolicy], dict[str, Any]]:
    import scripts.run_tiebreak_policy as rtp
    from train.compact_dagger_ablation import CompactLinearWeights
    from train.empirical_bayes_policy import EmpiricalBayesParams

    repo_root = repo_root.resolve()
    spec = POLICY_META_SPECS[policy_id]
    s_data = json.loads((repo_root / spec["summary_path"]).read_text(encoding="utf-8"))
    tr = s_data["train_seeds"]
    rtp._assert_train_seed_range(int(tr["start"]), int(tr["stop"]), spec["summary_path"])

    if policy_id == "empirical_bayes":
        raw_params = s_data["parameters"]["eb_experience_opt"]
        params = EmpiricalBayesParams.from_dict(raw_params)
        p_count = len([k for k in raw_params if k not in ("stage", "naive_p_threshold")])
        return (
            lambda seed, stopping_rule="calibrated_ev_breakeven", name=None, p=params: StoppingCounterfactualEmpiricalBayesPolicy(
                params=p,
                seed=seed,
                stopping_rule=stopping_rule,
                name=name or f"empirical_bayes:{stopping_rule}",
            ),
            {
                **spec,
                "param_count": p_count,
                "train_seed_range": f"{int(tr['start'])}..{int(tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )
    if policy_id == "compact_linear_dagger":
        weights = CompactLinearWeights.from_dict(s_data["learned_weights_stage3"])
        return (
            lambda _seed, stopping_rule="calibrated_ev_breakeven", name=None, w=weights: StoppingCounterfactualCompactLinearDAggerPolicy(
                weights=w,
                stopping_rule=stopping_rule,
                name=name or f"compact_linear_dagger:{stopping_rule}",
            ),
            {
                **spec,
                "param_count": int(weights.param_count()),
                "train_seed_range": f"{int(tr['start'])}..{int(tr['stop']) - 1}",
                "is_open_weight_llm": False,
            },
        )
    raise ValueError(f"unknown policy_id: {policy_id!r}")


def load_empirical_cross_links(repo_root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    repo_root = repo_root.resolve()
    ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))
    addendum = json.loads((repo_root / ADDENDUM_REL).read_text(encoding="utf-8"))
    verda = json.loads((repo_root / VERDA_MULTISEED_REL).read_text(encoding="utf-8"))
    fcmp = json.loads((repo_root / FRONTIER_CMP_REL).read_text(encoding="utf-8"))

    hist_runs = list(ledger["historical_runs"])
    above_zero = sum(
        1
        for r in hist_runs
        if isinstance(r.get("after_mean_score"), (int, float)) and float(r["after_mean_score"]) > 0.0
    )
    panel_e = {
        "open_weight_qwen25_runs_total": len(hist_runs),
        "open_weight_qwen25_runs_above_zero": above_zero,
        "open_weight_qwen25_above_zero_ratio": f"{above_zero} / {len(hist_runs)}",
        "readme_qwen_addendum_status": str(addendum["readiness_summary"]["readme_addendum_action"]),
        "audited_policies_are_open_weight_llm": False,
        "disclosure": PANEL_FIX_E_DISCLOSURE,
    }

    low_8k = verda["bimodal_regime_split"]["low_step_8k_cluster"]
    high_8k = verda["bimodal_regime_split"]["high_step_8k_cluster"]
    s4k_by_id = {r["run_id"]: r for r in verda["seeds_4k"]}
    v4k_s0 = s4k_by_id["v3_4k_s0"]["overall"]
    v4k_s1 = s4k_by_id["v3_4k_s1"]["overall"]
    verda_rows = [
        {
            "cohort_id": "verda_8k_low_step_s1_s3",
            "label": "Qwen2.5-1.5B GRPO 8k low-step (s1+s3 pooled)",
            "is_open_weight_llm": True,
            "n": int(low_8k["pooled_episodes"]),
            "mean_score": round(float(low_8k["mean_score"]), 4),
            "ci95": round(float(low_8k["ci95"]), 4),
            "accused_rate": round(float(low_8k["accused_rate"]), 4),
            "abstain_rate": round(float(low_8k["abstain_rate"]), 4),
            "mean_p_accused": round(float(low_8k["belief_replay"]["mean_p_accused"]), 4),
            "below_breakeven_rate": round(float(low_8k["belief_replay"]["below_breakeven_rate"]), 4),
            "counterfactual_analog": "reckless_p35 / premature uncalibrated stopping",
        },
        {
            "cohort_id": "verda_8k_high_step_s0_s2",
            "label": "Qwen2.5-1.5B GRPO 8k high-step (s0+s2 pooled)",
            "is_open_weight_llm": True,
            "n": int(high_8k["pooled_episodes"]),
            "mean_score": round(float(high_8k["mean_score"]), 4),
            "ci95": round(float(high_8k["ci95"]), 4),
            "accused_rate": round(float(high_8k["accused_rate"]), 4),
            "abstain_rate": round(float(high_8k["abstain_rate"]), 4),
            "mean_p_accused": round(float(high_8k["belief_replay"]["mean_p_accused"]), 4),
            "below_breakeven_rate": round(float(high_8k["belief_replay"]["below_breakeven_rate"]), 4),
            "counterfactual_analog": "always_abstain / hyper_conservative_p99 abstain collapse",
        },
        {
            "cohort_id": "v3_4k_s0",
            "label": "Qwen2.5-1.5B GRPO 4k-s0 (4k truncation)",
            "is_open_weight_llm": True,
            "n": int(v4k_s0["n"]),
            "mean_score": round(float(v4k_s0["mean_score"]), 4),
            "ci95": round(float(v4k_s0["ci95"]), 4),
            "accused_rate": round(float(v4k_s0["accused_rate"]), 4),
            "abstain_rate": round(float(v4k_s0["abstain_rate"]), 4),
            "mean_p_accused": round(float(v4k_s0["belief_replay"]["mean_p_accused"]), 4),
            "below_breakeven_rate": round(float(v4k_s0["belief_replay"]["below_breakeven_rate"]), 4),
            "counterfactual_analog": "context-truncated uncalibrated stopping + abstention",
        },
        {
            "cohort_id": "v3_4k_s1",
            "label": "Qwen2.5-1.5B GRPO 4k-s1 (4k truncation)",
            "is_open_weight_llm": True,
            "n": int(v4k_s1["n"]),
            "mean_score": round(float(v4k_s1["mean_score"]), 4),
            "ci95": round(float(v4k_s1["ci95"]), 4),
            "accused_rate": round(float(v4k_s1["accused_rate"]), 4),
            "abstain_rate": round(float(v4k_s1["abstain_rate"]), 4),
            "mean_p_accused": round(float(v4k_s1["belief_replay"]["mean_p_accused"]), 4),
            "below_breakeven_rate": round(float(v4k_s1["belief_replay"]["below_breakeven_rate"]), 4),
            "counterfactual_analog": "context-truncated uncalibrated stopping + abstention",
        },
    ]

    dev_map = {c["cohort_id"]: c for c in fcmp["dev_hard_panel"]["cohorts"]}
    frontier_rows = []
    for cid in (
        "opencode_gemini_4_carbon_hard",
        "opencode_gpt_5_5_hard",
        "opencode_gemini_3_5_flash_hard",
        "solver_reference_hard",
    ):
        c = dev_map[cid]
        cc = c["commitment_calibration"]
        frontier_rows.append(
            {
                "cohort_id": cid,
                "label": str(c["label"]),
                "n": int(c["n"]),
                "mean_score": round(float(c["mean_score"]), 4),
                "ci95": round(float(c["ci95"]), 4),
                "luck_adjusted_ev": round(float(c["luck_adjusted_ev"]), 4),
                "correct_count": int(c["correct_count"]),
                "wrong_count": int(c["wrong_count"]),
                "abstain_count": int(c["abstain_count"]),
                "mean_accuse_day": round(float(c["mean_accuse_day"]), 2),
                "mean_top_p_at_accuse": round(float(cc["mean_top_p_at_accuse"]), 4),
                "top_p_below_breakeven_rate": round(float(cc["top_p_below_breakeven_rate"]), 4),
            }
        )

    return panel_e, {
        "verda_qwen25_cohorts": verda_rows,
        "frontier_dev_hard_posthoc": {
            "dev_eval_seed_range": "0..29",
            "tier": "hard",
            "protocol_status": "post-hoc locked, not pre-registered",
            "rows": frontier_rows,
        },
    }


_WORKER_CTX: dict[str, Any] = {}


def _run_world_bundle_task(task: tuple[str, str, int]) -> list[dict[str, Any]]:
    from canary.env import Env

    policy_id, tier, seed = task
    provider = _WORKER_CTX["provider"]
    pol = _WORKER_CTX["factories"][policy_id](seed, stopping_rule="always_abstain", name=f"{policy_id}:always_abstain")
    branch_stops: dict[str, tuple[int, str, dict[str, float]]] = {}

    with _scoped_world_secret(HELDOUT_WORLD_SECRET):
        env_base = Env(tier, seed, text_provider=provider)
        pol.reset(env_base.tools_spec(), env_base.instruction())
        for _ in range(1000):
            if env_base.done:
                break
            hist = list(env_base.history)
            step_hits: dict[str, tuple[str, dict[str, float]]] = {}
            tool, args = pol.act(hist, open_rules=step_hits)
            for rid, (emp_acc, m_snap) in step_hits.items():
                if rid not in branch_stops:
                    branch_stops[rid] = (len(hist), emp_acc, m_snap)
            env_base.call(tool, args)
        base_ep = env_base.result(pol.name)
        full_calls = [(st.tool, st.args) for st in base_ep.steps]
        abstain_meta = dict(pol.last_stop_metrics)

        bundle_rows: list[dict[str, Any]] = []
        for rid in STOPPING_RULE_ORDER:
            if rid in branch_stops:
                t_idx, emp_acc, sm = branch_stops[rid]
                rule_calls = full_calls[:t_idx] + [("accuse", {"employee": emp_acc})]
            else:
                rule_calls = full_calls
                sm = abstain_meta
            rep_env = Env(tier, seed, text_provider=provider)
            for r_tool, r_args in rule_calls:
                rep_env.call(r_tool, r_args)
            ep = rep_env.result(f"{policy_id}:{rid}")
            if rid == "always_abstain" and (abs(float(ep.score) - float(base_ep.score)) > 1e-9 or ep.accused != base_ep.accused):
                raise AssertionError(f"always_abstain replay mismatch on {tier}:{seed}")
            top_p = float(sm.get("top_p", 0.0))
            be_p = float(sm.get("breakeven_p", 1.0))
            correct = bool(ep.correct and ep.accused is not None)
            wrong = bool((not ep.correct) and ep.accused is not None)
            outcome = "C" if correct else ("W" if wrong else "A")
            inv_calls = sum(1 for st in ep.steps if st.tool in INVESTIGATIVE_MCP_TOOLS)
            trace_sha = canonical_trace_sha256(ep.steps)
            bundle_rows.append(
                {
                    "policy_id": policy_id,
                    "rule_id": rid,
                    "tier": tier,
                    "seed": int(seed),
                    "score": round(float(ep.score), 4),
                    "outcome": outcome,
                    "accused": ep.accused is not None,
                    "final_day": int(ep.final_day),
                    "inv_calls": inv_calls,
                    "top_p_at_stop": round(top_p, 5),
                    "below_breakeven_accuse": bool(ep.accused is not None and top_p + 1e-9 < be_p),
                    "trace_sha10": trace_sha[:10],
                }
            )
    return bundle_rows


def _summarize_rule_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = max(1, len(rows))
    scores = [float(r["score"]) for r in rows]
    ci = mean_ci95(scores)
    c_cnt = sum(1 for r in rows if r["outcome"] == "C")
    w_cnt = sum(1 for r in rows if r["outcome"] == "W")
    a_cnt = sum(1 for r in rows if r["outcome"] == "A")
    acc_cnt = c_cnt + w_cnt
    acc_days = [int(r["final_day"]) for r in rows if r["accused"]]
    bb_cnt = sum(1 for r in rows if r["below_breakeven_accuse"])
    digest_tag = safe_segmented_sha15(
        "\n".join(f"{r['tier']}:{r['seed']}:{r['trace_sha10']}" for r in rows).encode("utf-8")
    )
    return {
        "n": len(rows),
        "mean_score": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "correct_count": c_cnt,
        "wrong_count": w_cnt,
        "abstain_count": a_cnt,
        "accuse_count": acc_cnt,
        "accuracy": round(c_cnt / n, 5),
        "accuse_rate": round(acc_cnt / n, 5),
        "wrong_accuse_rate": round(w_cnt / n, 5),
        "abstain_rate": round(a_cnt / n, 5),
        "mean_final_day": round(sum(int(r["final_day"]) for r in rows) / n, 4),
        "mean_accuse_day": round(sum(acc_days) / len(acc_days), 4) if acc_days else None,
        "mean_investigative_calls": round(sum(int(r["inv_calls"]) for r in rows) / n, 4),
        "mean_top_p_at_stop": round(sum(float(r["top_p_at_stop"]) for r in rows) / n, 5),
        "below_breakeven_accuse_count": bb_cnt,
        "below_breakeven_accuse_rate": round(bb_cnt / max(1, acc_cnt), 5) if acc_cnt else 0.0,
        "replay_verified_count": len(rows),
        "trace_set_digest": digest_tag,
    }


def run_audit(repo_root: Path = ROOT, max_workers: int = 8) -> dict[str, Any]:
    from canary import rules
    from canary.env import Env as _Env
    from canary.eval import run_episode as _run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as _rtp

    _ = (_Env, _run_episode, _rtp)
    t0 = time.perf_counter()
    repo_root = repo_root.resolve()
    heldout_seeds = list(range(HELDOUT_SEED_START, HELDOUT_SEED_STOP))
    for s in heldout_seeds:
        if s not in rules.HELDOUT_SEEDS or s in rules.JUDGE_SEEDS or s >= JUDGE_SEED_MIN:
            raise ValueError(f"seed {s} violates HELDOUT_SEEDS isolation")

    secret_tag = compute_secret_tag(HELDOUT_WORLD_SECRET)
    if secret_tag != EXPECTED_WORLD_SECRET_TAG:
        raise AssertionError(f"secret_tag {secret_tag} != {EXPECTED_WORLD_SECRET_TAG}")

    panel_e, cross_links = load_empirical_cross_links(repo_root)
    provider = TemplateProvider()
    factories: dict[str, Callable[..., StoppingCounterfactualPolicy]] = {}
    metas: dict[str, dict[str, Any]] = {}
    for pid in POLICY_ORDER:
        fac, meta = load_policy_factory(pid, repo_root=repo_root)
        factories[pid] = fac
        metas[pid] = meta

    tasks = [
        (pid, tier, seed)
        for tier in ("hard", "medium", "easy")
        for pid in ("compact_linear_dagger", "empirical_bayes")
        for seed in heldout_seeds
    ]

    with _fast_compact_dagger_features():
        import multiprocessing

        _WORKER_CTX["provider"] = provider
        _WORKER_CTX["factories"] = factories
        use_fork = (
            max_workers > 1
            and "pytest" not in sys.modules
            and "fork" in multiprocessing.get_all_start_methods()
        )
        if use_fork:
            from concurrent.futures import ProcessPoolExecutor

            ctx = multiprocessing.get_context("fork")
            with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
                bundles = list(pool.map(_run_world_bundle_task, tasks, chunksize=2))
        else:
            bundles = [_run_world_bundle_task(tk) for tk in tasks]
    raw_rows = [r for b in bundles for r in b]

    tier_rank = {t: idx for idx, t in enumerate(CANONICAL_TIERS)}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in raw_rows:
        grouped.setdefault((str(r["policy_id"]), str(r["rule_id"])), []).append(r)

    policies_out: dict[str, Any] = {}
    for pid in POLICY_ORDER:
        meta = metas[pid]
        cal_rows = sorted(
            grouped[(pid, "calibrated_ev_breakeven")],
            key=lambda x: (tier_rank[x["tier"]], int(x["seed"])),
        )
        cal_scores = [float(r["score"]) for r in cal_rows]
        cal_outcomes = [str(r["outcome"]) for r in cal_rows]
        rules_out: dict[str, Any] = {}
        for rid in STOPPING_RULE_ORDER:
            rspec = STOPPING_RULE_SPECS[rid]
            r_rows = sorted(
                grouped[(pid, rid)],
                key=lambda x: (tier_rank[x["tier"]], int(x["seed"])),
            )
            r_scores = [float(r["score"]) for r in r_rows]
            r_outcomes = [str(r["outcome"]) for r in r_rows]
            overall = _summarize_rule_rows(r_rows)
            regret = decompose_regret_from_vectors(cal_scores, cal_outcomes, r_scores, r_outcomes)
            by_tier: dict[str, Any] = {}
            for tier in CANONICAL_TIERS:
                t_rows = [r for r in r_rows if r["tier"] == tier]
                t_cal = [r for r in cal_rows if r["tier"] == tier]
                t_sum = _summarize_rule_rows(t_rows)
                t_reg = decompose_regret_from_vectors(
                    [float(x["score"]) for x in t_cal],
                    [str(x["outcome"]) for x in t_cal],
                    [float(x["score"]) for x in t_rows],
                    [str(x["outcome"]) for x in t_rows],
                )
                by_tier[tier] = {
                    "n": t_sum["n"],
                    "mean_score": t_sum["mean_score"],
                    "correct_count": t_sum["correct_count"],
                    "wrong_count": t_sum["wrong_count"],
                    "abstain_count": t_sum["abstain_count"],
                    "total_regret": t_reg["total_regret"],
                    "premature_wrong_accusation_regret": t_reg["premature_wrong_accusation_regret"],
                    "late_stopping_value_leakage_regret": t_reg["late_stopping_value_leakage_regret"],
                    "over_abstention_missed_catch_regret": t_reg["over_abstention_missed_catch_regret"],
                }
            rules_out[rid] = {
                "rule_id": rid,
                "threshold": rspec["threshold"],
                "formula": rspec["formula"],
                "regime_analog": rspec["regime_analog"],
                "overall": overall,
                "regret_vs_calibrated": regret,
                "by_tier": by_tier,
                "episode_scores_csv": ",".join(f"{round(s, 4):g}" for s in r_scores),
                "episode_outcomes_csv": ",".join(r_outcomes),
            }
        policies_out[pid] = {
            "policy_id": pid,
            "policy_class": meta["policy_class"],
            "run_id": meta["run_id"],
            "module_path": meta["module_path"],
            "summary_path": meta["summary_path"],
            "param_count": int(meta["param_count"]),
            "train_seed_range": meta["train_seed_range"],
            "is_open_weight_llm": False,
            "rules": rules_out,
        }

    target_script = repo_root / "scripts" / "tiebreak_stopping_counterfactual_audit.py"
    if not target_script.is_file():
        target_script = Path(__file__).resolve()
    ast_gate = audit_module_ast_isolation(target_script)
    elapsed_s = round(time.perf_counter() - t0, 3)

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "text_provider": "TemplateProvider",
        "world_secret_tag": secret_tag,
        "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seeds_per_tier": HELDOUT_SEEDS_PER_TIER,
        "episodes_per_rule": EPISODES_PER_RULE,
        "tiers": list(CANONICAL_TIERS),
        "stopping_rules": list(STOPPING_RULE_ORDER),
        "seed_isolation": {
            "train_seed_interval": "100000..199999",
            "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
            "judge_episodes_touched": 0,
            "dev_episodes_rolled_out": 0,
            "train_episodes_in_heldout_eval": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": panel_e,
        "ast_inference_isolation": ast_gate,
        "empirical_cross_links": cross_links,
        "totals": {
            "policies_audited": len(POLICY_ORDER),
            "rules_per_policy": len(STOPPING_RULE_ORDER),
            "total_live_episodes": len(raw_rows),
            "fresh_env_replays_verified": len(raw_rows),
            "elapsed_seconds": elapsed_s,
        },
        "policies": policies_out,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check or not args.generate:
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
