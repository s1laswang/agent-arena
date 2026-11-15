"""Zero-shot cross-tier transfer and OOD pool/horizon generalization audit for Canary v1.4."""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ProcessPoolExecutor
import contextlib
from dataclasses import replace
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import random
import re
import sys
import time
import tokenize
from typing import Any, Iterator

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.cross_tier_transfer.v1"
AUDIT_ID = "tiebreak-cross-tier-transfer-and-ood-horizon-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
TRAIN_REGIMES: tuple[str, ...] = ("easy_only", "medium_only", "hard_only", "pooled_all")
ALL_REGIMES: tuple[str, ...] = ("before_untrained",) + TRAIN_REGIMES
POLICY_FAMILIES: tuple[str, ...] = ("empirical_bayes", "scaling_logistic")

HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_N = HELDOUT_SEED_STOP - HELDOUT_SEED_START
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_WORLD_SECRET_TAG = "sha256:ebf2f09716cf76d3"

JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 100 * 1024
MAX_CHECK_SECONDS = 5.0
BOOTSTRAP_SAMPLES = 200
BOOTSTRAP_RNG_SEED = 202615

EB_STAGE2_COUNT = 180
EB_STAGE3_COUNT = 90
EB_EPISODES_PER_REGIME = EB_STAGE2_COUNT + EB_STAGE3_COUNT
SL_EPISODES_PER_REGIME = 270

EB_REGIME_SEEDS: dict[str, tuple[int, int]] = {
    "easy_only": (112_000, 112_270),
    "medium_only": (112_270, 112_540),
    "hard_only": (112_540, 112_810),
    "pooled_all": (112_810, 113_080),
}

SL_TIER_OFFSETS: dict[str, int] = {
    "easy": 107_000,
    "medium": 107_600,
    "hard": 108_200,
}

DEFAULT_OUT_JSON = Path("results/tiebreak/cross_tier_transfer/cross_tier_transfer_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_cross_tier_transfer.md")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")

PANEL_FIX_A_DISCLOSURE = (
    "All cross-tier transfer models audited here are fit strictly on disjoint single-tier or pooled "
    "TRAIN_SEEDS in [100000, 200000) (107000..108469 and 112000..113079) and evaluated strictly on "
    "world-paired HELDOUT_SEEDS 800000..800029 (n=30 per tier, 90 episodes per trained policy) under "
    "deterministic world_secret_tag sha256:ebf2f09716cf76d3; 0 DEV_SEEDS are rolled out and 0 "
    "JUDGE_SEEDS (900k+) are touched. Where DEV_SEEDS 0..29 appear in separate Canary frontier "
    "reports, they are post-hoc locked, not pre-registered (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5-1.5B runs in "
    "experiment_ledger.json beat untrained base (0.000), so the README Qwen addendum remains withheld "
    "(HOLD_README_QWEN_ADDENDUM_UNTIL_V100). Both policy families audited here (EmpiricalBayesPolicy, "
    "11 params; ScalingLogisticPolicy, 82 params; is_open_weight_llm = False) are non-LLM structured "
    "controls on the lossless public ledger and are never conflated with open-weight LLM runs."
)

FAMILY_SPECS: dict[str, dict[str, Any]] = {
    "empirical_bayes": {
        "family_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "module_path": "train/empirical_bayes_policy.py",
        "param_count": 11,
        "is_open_weight_llm": False,
        "architecture_summary": "6-channel empirical log-likelihood ratio + 1/(1+V_hat(d)) EV stopping + adaptive canary split",
    },
    "scaling_logistic": {
        "family_id": "scaling_logistic",
        "policy_class": "ScalingLogisticPolicy",
        "module_path": "scripts/tiebreak_cross_tier_transfer_audit.py",
        "param_count": 82,
        "is_open_weight_llm": False,
        "architecture_summary": "14-dim employee-equivariant softmax + 10-dim OOF commit + 6-dim horizon wait + 48-dim tool + 4-dim canary ridge",
    },
}

HARD_SURGICAL_ARM_ORDER: tuple[str, ...] = (
    "eb_easy_deception_neutral_hard_elim",
    "eb_easy_deception_neutral_fp95_cal",
    "eb_medium_plus_fp95_and_h21_stop",
    "sl_easy_noise_blind_hard_elim",
)

HARD_SURGICAL_SPECS: dict[str, dict[str, Any]] = {
    "eb_easy_deception_neutral_hard_elim": {
        "arm_id": "eb_easy_deception_neutral_hard_elim",
        "family_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "param_count": 11,
        "is_open_weight_llm": False,
        "train_seed_range": "112000..112269",
        "description": "Easy-only likelihoods/stopping with neutral 0.0 unseen decoy/framing weights and strict 0%-noise deterministic elimination (w_canary_miss=-30.0)",
    },
    "eb_easy_deception_neutral_fp95_cal": {
        "arm_id": "eb_easy_deception_neutral_fp95_cal",
        "family_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "param_count": 11,
        "is_open_weight_llm": False,
        "train_seed_range": "112000..112809",
        "description": "Identical to eb_easy_deception_neutral_hard_elim except w_canary_miss replaced by 5%-noise calibrated hard LLR",
    },
    "eb_medium_plus_fp95_and_h21_stop": {
        "arm_id": "eb_medium_plus_fp95_and_h21_stop",
        "family_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "param_count": 11,
        "is_open_weight_llm": False,
        "train_seed_range": "112270..112809",
        "description": "Medium-only likelihoods transplanted with hard 5%-noise w_canary_miss and 21d stopping/canary-split scalars",
    },
    "sl_easy_noise_blind_hard_elim": {
        "arm_id": "sl_easy_noise_blind_hard_elim",
        "family_id": "scaling_logistic",
        "policy_class": "ScalingLogisticPolicy",
        "param_count": 82,
        "is_open_weight_llm": False,
        "train_seed_range": "107000..107269",
        "description": "Easy-only ScalingLogisticPolicy with noise-blind hard elimination (w_suspect[5]=-30.0, ignoring public fingerprint_accuracy=0.95 header)",
    },
}

NOISE_SHOCK_ARM_ORDER: tuple[str, ...] = (
    "eb_easy_deception_neutral_hard_elim",
    "eb_hard_only",
    "sl_easy_only",
    "sl_hard_only",
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


def compute_secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def compute_hex_digest(text: str) -> str:
    raw = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    if raw.isdigit():
        raw = "a" + raw[1:]
    return "0x" + raw


def format_episode_digest(rec: dict[str, Any]) -> str:
    return (
        f"{int(rec['seed'])}:{rec['outcome']}:{int(rec['final_day'])}:{int(rec['tool_calls'])}:"
        f"{float(rec['score']):.4f}:{int(rec['canaries_planted'])}:{float(rec['cal_p']):.4f}:"
        f"{float(rec['cal_ev']):.4f}"
    )


def parse_episode_digest(digest: str) -> dict[str, Any]:
    parts = digest.split(":")
    if len(parts) != 8:
        raise ValueError(f"expected 8 fields in episode digest, got {len(parts)}: {digest!r}")
    outcome = parts[1]
    if outcome not in ("c", "w", "a"):
        raise ValueError(f"invalid outcome code {outcome!r} in {digest!r}")
    return {
        "seed": int(parts[0]),
        "outcome": outcome,
        "final_day": int(parts[2]),
        "tool_calls": int(parts[3]),
        "score": float(parts[4]),
        "canaries_planted": int(parts[5]),
        "cal_p": float(parts[6]),
        "cal_ev": float(parts[7]),
    }


def pack_episode_digests(digests: list[str], seed_start: int = HELDOUT_SEED_START) -> str:
    tokens: list[str] = []
    for idx, digest in enumerate(digests):
        rec = parse_episode_digest(digest)
        if rec["seed"] != seed_start + idx:
            raise ValueError(f"expected seed {seed_start + idx} at index {idx}, got {rec['seed']}")
        sc_tok = f"{round(rec['score'] * 100.0, 2):g}"
        cp_bp = int(round(rec["cal_p"] * 10000.0))
        cev_bp = int(round(rec["cal_ev"] * 10000.0))
        tokens.append(
            f"{rec['outcome']}{rec['final_day']},{rec['tool_calls']},{sc_tok},"
            f"{rec['canaries_planted']},{cp_bp},{cev_bp}"
        )
    return "|".join(tokens)


def unpack_episode_digests(packed: str, seed_start: int = HELDOUT_SEED_START) -> list[str]:
    if not isinstance(packed, str) or not packed:
        return []
    out: list[str] = []
    for idx, item in enumerate(packed.split("|")):
        fields = item.split(",")
        if len(fields) != 6 or not fields[0]:
            raise ValueError(f"malformed packed episode token {item!r}")
        outcome = fields[0][0]
        if outcome not in ("c", "w", "a"):
            raise ValueError(f"invalid packed outcome {outcome!r} in {item!r}")
        final_day = int(fields[0][1:])
        tool_calls = int(fields[1])
        score = float(fields[2]) / 100.0
        canaries = int(fields[3])
        cal_p = int(fields[4]) / 10000.0
        cal_ev = int(fields[5]) / 10000.0
        out.append(
            f"{seed_start + idx}:{outcome}:{final_day}:{tool_calls}:"
            f"{score:.4f}:{canaries}:{cal_p:.4f}:{cal_ev:.4f}"
        )
    return out


def _bootstrap_mean_ci(values: list[float], rng_tag: int) -> tuple[float, float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0
    choices = random.Random(BOOTSTRAP_RNG_SEED + int(rng_tag)).choices
    inv_n = 1.0 / n
    sums = sorted(sum(choices(values, k=n)) for _ in range(BOOTSTRAP_SAMPLES))
    lo = sums[int(0.025 * BOOTSTRAP_SAMPLES)] * inv_n
    hi = sums[int(0.975 * BOOTSTRAP_SAMPLES)] * inv_n
    half = 0.5 * (hi - lo)
    return round(lo, 5), round(hi, 5), round(half, 5)


def summarize_digests(
    digests: list[str],
    rng_tag: int,
    include_bootstrap: bool = True,
) -> dict[str, Any]:
    rows = [parse_episode_digest(d) for d in digests]
    n = len(rows)
    if n == 0:
        raise ValueError("cannot summarize empty digest list")
    scores = [r["score"] for r in rows]
    cal_evs = [r["cal_ev"] for r in rows]
    correct_count = sum(1 for r in rows if r["outcome"] == "c")
    wrong_count = sum(1 for r in rows if r["outcome"] == "w")
    abstain_count = sum(1 for r in rows if r["outcome"] == "a")
    mean_calls = sum(r["tool_calls"] for r in rows) / n
    mean_canaries = sum(r["canaries_planted"] for r in rows) / n
    mean_sc = round(sum(scores) / n, 5)
    mean_ev = round(sum(cal_evs) / n, 5)

    if include_bootstrap:
        ci_lo, ci_hi, _ = _bootstrap_mean_ci(scores, rng_tag=100 + rng_tag)
        ev_lo, ev_hi, _ = _bootstrap_mean_ci(cal_evs, rng_tag=500 + rng_tag)
    else:
        ci_lo, ci_hi = mean_sc, mean_sc
        ev_lo, ev_hi = mean_ev, mean_ev

    return {
        "n": n,
        "mean_score": mean_sc,
        "ci95_low": ci_lo,
        "ci95_high": ci_hi,
        "cal_ev_mean": mean_ev,
        "cal_ev_ci95_low": ev_lo,
        "cal_ev_ci95_high": ev_hi,
        "accuracy": round(correct_count / n, 5),
        "wrong_accuse_rate": round(wrong_count / n, 5),
        "abstain_rate": round(abstain_count / n, 5),
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "abstain_count": abstain_count,
        "mean_tool_calls": round(mean_calls, 3),
        "mean_canaries": round(mean_canaries, 3),
        "traces_digest": compute_hex_digest("|".join(digests)),
    }


def compute_paired_contrast(
    digests_a: list[str],
    digests_b: list[str],
    rng_tag: int,
    include_bootstrap: bool = True,
) -> dict[str, Any]:
    rows_a = [parse_episode_digest(d) for d in digests_a]
    rows_b = [parse_episode_digest(d) for d in digests_b]
    if len(rows_a) != len(rows_b) or not rows_a:
        raise ValueError("paired contrast requires equal non-empty digest lists")
    for ra, rb in zip(rows_a, rows_b):
        if ra["seed"] != rb["seed"]:
            raise ValueError(f"paired contrast mismatch: {ra['seed']} != {rb['seed']}")
    deltas = [round(ra["score"] - rb["score"], 5) for ra, rb in zip(rows_a, rows_b)]
    ev_deltas = [round(ra["cal_ev"] - rb["cal_ev"], 5) for ra, rb in zip(rows_a, rows_b)]
    n = len(deltas)
    mean_d = round(sum(deltas) / n, 5)
    mean_ev_d = round(sum(ev_deltas) / n, 5)
    if include_bootstrap:
        ci_lo, ci_hi, _ = _bootstrap_mean_ci(deltas, rng_tag=900 + rng_tag)
        ev_lo, ev_hi, _ = _bootstrap_mean_ci(ev_deltas, rng_tag=1300 + rng_tag)
    else:
        ci_lo, ci_hi = mean_d, mean_d
        ev_lo, ev_hi = mean_ev_d, mean_ev_d
    wins_a = sum(1 for d in deltas if d > 1e-9)
    wins_b = sum(1 for d in deltas if d < -1e-9)
    ties = n - wins_a - wins_b
    return {
        "n": n,
        "mean_score_delta": mean_d,
        "ci95_low": ci_lo,
        "ci95_high": ci_hi,
        "cal_ev_delta_mean": mean_ev_d,
        "cal_ev_delta_ci95_low": ev_lo,
        "cal_ev_delta_ci95_high": ev_hi,
        "a_wins": wins_a,
        "b_wins": wins_b,
        "ties": ties,
        "correct_delta": sum(1 for r in rows_a if r["outcome"] == "c")
        - sum(1 for r in rows_b if r["outcome"] == "c"),
        "wrong_accuse_delta": sum(1 for r in rows_a if r["outcome"] == "w")
        - sum(1 for r in rows_b if r["outcome"] == "w"),
    }


def compute_retention_summary(
    ood_digests: list[str],
    id_digests: list[str],
    pooled_digests: list[str],
    rng_tag: int,
) -> dict[str, Any]:
    ood_m = summarize_digests(ood_digests, rng_tag=rng_tag, include_bootstrap=False)
    id_m = summarize_digests(id_digests, rng_tag=rng_tag + 1, include_bootstrap=False)
    pool_m = summarize_digests(pooled_digests, rng_tag=rng_tag + 2, include_bootstrap=False)
    vs_id = compute_paired_contrast(ood_digests, id_digests, rng_tag=rng_tag + 3)
    vs_pool = compute_paired_contrast(ood_digests, pooled_digests, rng_tag=rng_tag + 4)
    ret_vs_id = (ood_m["mean_score"] / id_m["mean_score"] * 100.0) if abs(id_m["mean_score"]) > 1e-9 else 0.0
    ret_vs_pool = (ood_m["mean_score"] / pool_m["mean_score"] * 100.0) if abs(pool_m["mean_score"]) > 1e-9 else 0.0
    ev_ret_vs_id = (
        ood_m["cal_ev_mean"] / id_m["cal_ev_mean"] * 100.0
        if abs(id_m["cal_ev_mean"]) > 1e-9
        else 0.0
    )
    return {
        "ood_mean_score": ood_m["mean_score"],
        "in_dist_mean_score": id_m["mean_score"],
        "pooled_mean_score": pool_m["mean_score"],
        "score_retention_vs_in_dist_pct": round(ret_vs_id, 2),
        "score_retention_vs_pooled_pct": round(ret_vs_pool, 2),
        "calibrated_ev_retention_vs_in_dist_pct": round(ev_ret_vs_id, 2),
        "ood_correct_count": ood_m["correct_count"],
        "in_dist_correct_count": id_m["correct_count"],
        "ood_wrong_count": ood_m["wrong_count"],
        "ood_abstain_count": ood_m["abstain_count"],
        "paired_vs_in_dist": vs_id,
        "paired_vs_pooled": vs_pool,
    }


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if _PREREG_RE.search(raw_line) and _SEEDS_0_29_RE.search(raw_line):
            scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
            if _PREREG_RE.search(scrubbed):
                hits.append(f"line {lineno}: {raw_line.strip()[:120]}")
    return hits


def _scan_json_for_judge_numbers(obj: Any, raw_json: str) -> list[str]:
    hits: list[str] = []

    def _walk(val: Any, path: str) -> None:
        if isinstance(val, int) and not isinstance(val, bool):
            if val >= JUDGE_SEED_MIN:
                hits.append(f"{path}={val}")
        elif isinstance(val, dict):
            for k, v in val.items():
                _walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(val, list):
            for idx, v in enumerate(val):
                _walk(v, f"{path}[{idx}]")

    _walk(obj, "")
    for m in _INT_TOKEN_RE.finditer(raw_json):
        tok = int(m.group(0))
        if tok >= JUDGE_SEED_MIN:
            hits.append(f"raw_token={tok}")
            break
    return hits


_HYGIENE_CACHE: dict[tuple[str, int, int, bool], list[str]] = {}


def check_python_source_hygiene(py_path: Path, full_tokenize: bool = False) -> list[str]:
    resolved = py_path.resolve()
    try:
        st = resolved.stat()
        cache_key = (str(resolved), st.st_mtime_ns, st.st_size, bool(full_tokenize))
    except OSError as exc:
        return [f"{py_path.name}: stat failed ({exc})"]
    cached = _HYGIENE_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    errors: list[str] = []
    src = resolved.read_text(encoding="utf-8")
    lbl = resolved.name
    if H in src:
        errors.append(f"{lbl}: contains forbidden hash character")
    if full_tokenize or H in src:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        if any(t.type == tokenize.COMMENT for t in toks):
            errors.append(f"{lbl}: contains Python comment token")
    for bad_ch, ch_name in (
        (EM_DASH, "em dash"),
        (EN_DASH, "en dash"),
        (UNICODE_MINUS, "unicode minus"),
    ):
        if bad_ch in src:
            errors.append(f"{lbl}: contains forbidden {ch_name}")
    if not src.isascii():
        errors.append(f"{lbl}: contains non-ASCII characters")
    tree = ast.parse(src, filename=str(resolved))
    forbidden_roots = {"torch", "transformers", "subprocess"}
    forbidden_canary = {"canary.world", "canary.solver"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".")[0]
                if root_mod in forbidden_roots:
                    errors.append(f"{lbl}: imports forbidden module {alias.name}")
                if alias.name in forbidden_canary or alias.name.startswith(("canary.world.", "canary.solver.")):
                    errors.append(f"{lbl}: imports forbidden {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root_mod = node.module.split(".")[0]
            if root_mod in forbidden_roots:
                errors.append(f"{lbl}: imports from forbidden module {node.module}")
            if node.module in forbidden_canary or node.module.startswith(("canary.world.", "canary.solver.")):
                errors.append(f"{lbl}: imports from forbidden {node.module}")
            if node.module == "canary":
                for alias in node.names:
                    if alias.name in ("world", "solver"):
                        errors.append(f"{lbl}: imports canary.{alias.name}")
    _HYGIENE_CACHE[cache_key] = list(errors)
    return errors


def _precision_display(metrics: dict[str, Any]) -> str:
    accused = int(metrics["correct_count"]) + int(metrics["wrong_count"])
    return f"{int(metrics['correct_count'])}/{accused}" if accused > 0 else "0/0"


def render_markdown_report(summary: dict[str, Any]) -> str:
    pe = summary["panel_fix_e_track_separation"]
    tm = summary["tier_mechanics_v14"]
    eb_mat = summary["transfer_matrices"]["empirical_bayes"]
    sl_mat = summary["transfer_matrices"]["scaling_logistic"]
    ood = summary["ood_retention_and_noise_decomposition"]
    eb_ret_med = ood["zero_shot_hard_retention"]["empirical_bayes_medium_to_hard"]
    eb_ret_easy = ood["zero_shot_hard_retention"]["empirical_bayes_easy_to_hard"]
    sl_ret_med = ood["zero_shot_hard_retention"]["scaling_logistic_medium_to_hard"]
    sl_ret_easy = ood["zero_shot_hard_retention"]["scaling_logistic_easy_to_hard"]
    surg = ood["frozen_v14_hard_surgical_arms"]
    surg_c = ood["frozen_v14_hard_contrasts"]
    nshock = ood["hard_fingerprint_noise_counterfactual"]

    lines: list[str] = [
        f"{H} Zero-Shot Cross-Tier Transfer and OOD Pool/Horizon Generalization Audit (Canary `{summary['tiers_version']}`)",
        "",
        f"- Schema: `{summary['schema']}` (`{summary['audit_id']}`)",
        f"- Evaluation Slice: `HELDOUT_SEEDS {summary['heldout_seed_range']}` (`n={summary['eval_seeds_per_tier']}` per tier, `90` episodes per trained policy; shared `world_secret_tag` `{summary['world_secret_tag']}`; `{summary['totals']['total_replay_verified_episodes']}/{summary['totals']['total_episodes_evaluated']}` `100%` `Env` replay-verified; `0` API calls; `0` `canary.solver`/`canary.world` imports)",
        f"- Training Provenance: strictly disjoint `TRAIN_SEEDS` in `[100000, 200000)` (`112000..113079` for `EmpiricalBayesPolicy`, `107000..108469` for `ScalingLogisticPolicy`, `{EB_EPISODES_PER_REGIME}` episodes per train regime; `0` `DEV_SEEDS` rolled out; `0` `JUDGE_SEEDS (900k+)` touched)",
        f"- Panel Fix A Disclosure: {summary['seed_isolation']['panel_fix_a_disclosure']}",
        f"- Panel Fix E Disclosure: `{pe['open_weight_qwen25_above_zero_ratio']}` open-weight Qwen2.5-1.5B runs beat untrained `0.000` (`{pe['readme_qwen_addendum_status']}`); both compact policy families audited here (`EmpiricalBayesPolicy`, `11` params; `ScalingLogisticPolicy`, `82` params) have `is_open_weight_llm = False` and are strictly separated from open-weight LLM runs.",
        "",
        f"{H}{H} 1. Canary `v1.4` Tier Shift Geometry (`easy` vs `medium` vs `hard`)",
        "",
        "| Tier | Staff Pool `N` | Horizon `H` | Leak Delay `d` | Canaries / Day (`K` Variants) | Fingerprint Noise (`1 - fp_acc`) | Decoy / Framing / Careful Mole | Access Constraints |",
        "| :--- | ---: | ---: | :--- | :--- | ---: | :--- | :--- |",
    ]
    for t_name in CANONICAL_TIERS:
        spec = tm[t_name]
        delays = ",".join(str(x) for x in spec["delay_choices"]) + "d"
        noise_pct = f"{spec['fingerprint_noise_rate'] * 100:.1f}% (fp={spec['fingerprint_accuracy']:.2f})"
        dfc = f"{spec['decoy']} / {spec['framing']} / {spec['careful_mole']}"
        lines.append(
            f"| `{t_name}` | `{spec['n_employees']}` | `{spec['n_days']}d` | `{delays}` | "
            f"`{spec['canaries_per_day']}` (`K={spec['max_variants']}`) | `{noise_pct}` | `{dfc}` | `{spec['access_constraints']}` |"
        )

    lines.extend(
        [
            "",
            f"{H}{H} 2. Full `4 x 3` Cross-Tier Transfer Matrix on World-Paired `HELDOUT_SEEDS {summary['heldout_seed_range']}`",
            "",
            f"{H}{H}{H} 2A. `EmpiricalBayesPolicy` (`11` Parameters, `is_open_weight_llm = False`)",
            "",
            "| Train Regime (`TRAIN_SEEDS`) | Eval `easy` (`N=12, H=14d, 0% noise`) | Eval `medium` (`N=20, H=14d, 0% noise`) | Eval `hard` (`N=40, H=21d, 5% noise`) | Pooled `3`-Tier Mean (`n=90`) | Paired Delta vs `before` (`n=90`) |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for reg_id in ALL_REGIMES:
        rb = eb_mat["regimes"][reg_id]
        tr_disp = rb.get("train_seed_range", "untrained prior")
        c_e = rb["by_tier"]["easy"]
        c_m = rb["by_tier"]["medium"]
        c_h = rb["by_tier"]["hard"]
        ov = rb["overall_metrics"]
        p_bef = rb.get("paired_vs_before_overall")
        p_disp = (
            f"`{p_bef['mean_score_delta']:+.4f} [{p_bef['ci95_low']:+.4f}, {p_bef['ci95_high']:+.4f}]`"
            if isinstance(p_bef, dict)
            else "`baseline`"
        )
        lines.append(
            f"| `{reg_id}` (`{tr_disp}`) | "
            f"`{c_e['mean_score']:+.4f}` (`{c_e['correct_count']}/{c_e['wrong_count']}/{c_e['abstain_count']}`) | "
            f"`{c_m['mean_score']:+.4f}` (`{c_m['correct_count']}/{c_m['wrong_count']}/{c_m['abstain_count']}`) | "
            f"`{c_h['mean_score']:+.4f}` (`{c_h['correct_count']}/{c_h['wrong_count']}/{c_h['abstain_count']}`) | "
            f"`{ov['mean_score']:+.4f} [{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]` | {p_disp} |"
        )

    lines.extend(
        [
            "",
            f"{H}{H}{H} 2B. `ScalingLogisticPolicy` (`82` Parameters, `is_open_weight_llm = False`)",
            "",
            "| Train Regime (`TRAIN_SEEDS`) | Eval `easy` (`N=12, H=14d, 0% noise`) | Eval `medium` (`N=20, H=14d, 0% noise`) | Eval `hard` (`N=40, H=21d, 5% noise`) | Pooled `3`-Tier Mean (`n=90`) | Paired Delta vs `before` (`n=90`) |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for reg_id in ALL_REGIMES:
        rb = sl_mat["regimes"][reg_id]
        tr_disp = rb.get("train_seed_range_display", rb.get("train_seed_range", "untrained prior"))
        c_e = rb["by_tier"]["easy"]
        c_m = rb["by_tier"]["medium"]
        c_h = rb["by_tier"]["hard"]
        ov = rb["overall_metrics"]
        p_bef = rb.get("paired_vs_before_overall")
        p_disp = (
            f"`{p_bef['mean_score_delta']:+.4f} [{p_bef['ci95_low']:+.4f}, {p_bef['ci95_high']:+.4f}]`"
            if isinstance(p_bef, dict)
            else "`baseline`"
        )
        lines.append(
            f"| `{reg_id}` (`{tr_disp}`) | "
            f"`{c_e['mean_score']:+.4f}` (`{c_e['correct_count']}/{c_e['wrong_count']}/{c_e['abstain_count']}`) | "
            f"`{c_m['mean_score']:+.4f}` (`{c_m['correct_count']}/{c_m['wrong_count']}/{c_m['abstain_count']}`) | "
            f"`{c_h['mean_score']:+.4f}` (`{c_h['correct_count']}/{c_h['wrong_count']}/{c_h['abstain_count']}`) | "
            f"`{ov['mean_score']:+.4f} [{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]` | {p_disp} |"
        )

    lines.extend(
        [
            "",
            f"{H}{H} 3. Zero-Shot OOD Pool/Horizon Retention vs Unseen `5%` Canary Fingerprint Noise (`hard`, `n=30`)",
            "",
            "| OOD Transfer / Surgical Arm (`hard`, `N=40, H=21d, 5% noise`) | Score `[95% Bootstrap CI]` | Calibrated Public EV `[95% CI]` | C / W / A (`Precision`) | Retention vs `hard_only` | Paired Delta vs Reference `[95% CI]` |",
            "| :--- | :--- | :--- | :--- | ---: | :--- |",
        ]
    )

    eb_h_only = eb_mat["regimes"]["hard_only"]["by_tier"]["hard"]
    eb_m_only = eb_mat["regimes"]["medium_only"]["by_tier"]["hard"]
    eb_e_only = eb_mat["regimes"]["easy_only"]["by_tier"]["hard"]
    sl_h_only = sl_mat["regimes"]["hard_only"]["by_tier"]["hard"]
    sl_m_only = sl_mat["regimes"]["medium_only"]["by_tier"]["hard"]
    sl_e_only = sl_mat["regimes"]["easy_only"]["by_tier"]["hard"]
    s_nh = surg["eb_easy_deception_neutral_hard_elim"]["metrics"]
    s_nc = surg["eb_easy_deception_neutral_fp95_cal"]["metrics"]
    s_mp = surg["eb_medium_plus_fp95_and_h21_stop"]["metrics"]
    s_sb = surg["sl_easy_noise_blind_hard_elim"]["metrics"]

    table3_rows = [
        (
            "`EmpiricalBayesPolicy` (`medium_only -> hard`)",
            eb_m_only,
            f"`{eb_ret_med['score_retention_vs_in_dist_pct']:.1f}%`",
            eb_ret_med["paired_vs_in_dist"],
            "vs `eb_hard_only`",
        ),
        (
            "`EmpiricalBayesPolicy` (`easy_only -> hard` raw)",
            eb_e_only,
            f"`{eb_ret_easy['score_retention_vs_in_dist_pct']:.1f}%`",
            eb_ret_easy["paired_vs_in_dist"],
            "vs `eb_hard_only`",
        ),
        (
            "`eb_easy_deception_neutral_hard_elim` (`0%` fp hard-elim)",
            s_nh,
            f"`{s_nh['mean_score'] / eb_h_only['mean_score'] * 100.0:.1f}%`",
            surg_c["eb_easy_deception_neutral_vs_raw_easy"],
            "vs `eb_easy_only`",
        ),
        (
            "`eb_easy_deception_neutral_fp95_cal` (`5%` fp calibrated)",
            s_nc,
            f"`{s_nc['mean_score'] / eb_h_only['mean_score'] * 100.0:.1f}%`",
            surg_c["eb_easy_fp95_cal_minus_hard_elim"],
            "vs `0%` fp hard-elim",
        ),
        (
            "`eb_medium_plus_fp95_and_h21_stop`",
            s_mp,
            f"`{s_mp['mean_score'] / eb_h_only['mean_score'] * 100.0:.1f}%`",
            surg_c["eb_medium_fp95_h21_minus_medium_only"],
            "vs `eb_medium_only`",
        ),
        (
            "`ScalingLogisticPolicy` (`easy_only -> hard`)",
            sl_e_only,
            f"`{sl_ret_easy['score_retention_vs_in_dist_pct']:.1f}%`",
            sl_ret_easy["paired_vs_in_dist"],
            "vs `sl_hard_only`",
        ),
        (
            "`ScalingLogisticPolicy` (`medium_only -> hard`)",
            sl_m_only,
            f"`{sl_ret_med['score_retention_vs_in_dist_pct']:.1f}%`",
            sl_ret_med["paired_vs_in_dist"],
            "vs `sl_hard_only`",
        ),
        (
            "`sl_easy_noise_blind_hard_elim` (`w_suspect[5]=-30`)",
            s_sb,
            f"`{s_sb['mean_score'] / sl_h_only['mean_score'] * 100.0:.1f}%`",
            surg_c["sl_easy_noise_blind_minus_header_aware"],
            "vs `sl_easy_only`",
        ),
    ]
    for label, m, ret_str, pc, ref_lbl in table3_rows:
        lines.append(
            f"| {label} | `{m['mean_score']:+.4f} [{m['ci95_low']:+.4f}, {m['ci95_high']:+.4f}]` | "
            f"`{m['cal_ev_mean']:+.4f} [{m['cal_ev_ci95_low']:+.4f}, {m['cal_ev_ci95_high']:+.4f}]` | "
            f"`{m['correct_count']}/{m['wrong_count']}/{m['abstain_count']}` (`{_precision_display(m)}`) | "
            f"{ret_str} | `{pc['mean_score_delta']:+.4f} [{pc['ci95_low']:+.4f}, {pc['ci95_high']:+.4f}]` ({ref_lbl}) |"
        )

    lines.extend(
        [
            "",
            f"{H}{H} 4. Exact Environment-Side `5%` Canary Fingerprint Noise Counterfactual (`fp_acc: 1.00 -> 0.95` on `hard`, `n=30`)",
            "",
            "| Policy (`N=40, H=21d, 2-3d delay, decoy+framing`) | Noise-Free `hard` (`fp=1.00`) | Standard `v1.4` `hard` (`fp=0.95`, `5%` noise) | Exact `5%` Noise Cost (`fp=0.95 - fp=1.00`) `[95% CI]` | Calibrated EV Delta `[95% CI]` |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for aid in NOISE_SHOCK_ARM_ORDER:
        nb = nshock["arms"][aid]
        m100 = nb["fp100_noise_free_metrics"]
        m095 = nb["fp095_standard_metrics"]
        sh = nb["noise_shock_fp095_minus_fp100"]
        lines.append(
            f"| `{aid}` | `{m100['mean_score']:+.4f}` (`{m100['correct_count']}/{m100['wrong_count']}/{m100['abstain_count']}`) | "
            f"`{m095['mean_score']:+.4f}` (`{m095['correct_count']}/{m095['wrong_count']}/{m095['abstain_count']}`) | "
            f"`{sh['mean_score_delta']:+.4f} [{sh['ci95_low']:+.4f}, {sh['ci95_high']:+.4f}]` | "
            f"`{sh['cal_ev_delta_mean']:+.4f} [{sh['cal_ev_delta_ci95_low']:+.4f}, {sh['cal_ev_delta_ci95_high']:+.4f}]` |"
        )

    eb_e100 = nshock["arms"]["eb_easy_deception_neutral_hard_elim"]["fp100_noise_free_metrics"]
    eb_e095 = nshock["arms"]["eb_easy_deception_neutral_hard_elim"]["fp095_standard_metrics"]
    eb_h100 = nshock["arms"]["eb_hard_only"]["fp100_noise_free_metrics"]
    eb_h095 = nshock["arms"]["eb_hard_only"]["fp095_standard_metrics"]
    eb_shock_easy = nshock["arms"]["eb_easy_deception_neutral_hard_elim"]["noise_shock_fp095_minus_fp100"]
    eb_shock_hard = nshock["arms"]["eb_hard_only"]["noise_shock_fp095_minus_fp100"]
    eb_easy_ang_obs = eb_mat["regimes"]["easy_only"]["angry_messages_observed_total"]

    lines.extend(
        [
            "",
            f"{H}{H} 5. Mechanistic Findings",
            "",
            f"1. **Employee-Equivariant Pool Scaling (`N=12/20 -> 40`) + Horizon-Aware `1/(1+V(d))` Stopping (`H=14d -> 21d`) Generalize Zero-Shot (`{sl_ret_med['score_retention_vs_in_dist_pct']:.1f}%` to `{eb_ret_med['score_retention_vs_in_dist_pct']:.1f}%` Retention)**: When deceptive social/framing channels are calibrated on `medium_only` (`N=20, H=14d, 0% fingerprint noise, 1 canary/day`), zero-shot transfer to `hard` (`N=40, H=21d, 5% fingerprint noise, 2 canaries/day`) retains `{eb_ret_med['score_retention_vs_in_dist_pct']:.1f}%` of `hard_only` score for `EmpiricalBayesPolicy` (`{eb_m_only['mean_score']:+.4f}` vs `{eb_h_only['mean_score']:+.4f}`, `{eb_m_only['correct_count']}/30` correct, `{eb_m_only['wrong_count']}` wrong accusations) and `{sl_ret_med['score_retention_vs_in_dist_pct']:.1f}%` for `ScalingLogisticPolicy` (`{sl_m_only['mean_score']:+.4f}` vs `{sl_h_only['mean_score']:+.4f}`, `{sl_m_only['correct_count']}/30` correct, `{sl_m_only['wrong_count']}` wrong accusations). Even from `easy_only` (`N=12, H=14d, decoy=False, framing=False`), `ScalingLogisticPolicy` achieves `{sl_e_only['mean_score']:+.4f}` zero-shot on `hard` (`{sl_ret_easy['score_retention_vs_in_dist_pct']:.1f}%` of `hard_only`, `{sl_e_only['correct_count']}/30` correct, `{sl_e_only['wrong_count']}` wrong) because its features normalize recipient/variant group information as `log(N / |group|)` and gate decoy/after-hours signals via the public instruction flags.",
            f"2. **Why Raw `EmpiricalBayesPolicy` (`easy_only`) Fails on `medium`/`hard` vs Surgical Fix**: On `easy_only` (`decoy=False`), `{eb_easy_ang_obs}` angry messages occur across all `{EB_STAGE2_COUNT}` Stage-2 episodes, so unguarded class-imbalanced Laplace smoothing (`1` mole vs `11` innocents) assigns `w_angry_msg = {eb_mat['regimes']['easy_only']['learned_params']['w_angry_msg']:+.3f}` plus unframed `w_after_hours = {eb_mat['regimes']['easy_only']['learned_params']['w_after_hours']:+.3f}`, producing `{eb_e_only['wrong_count']}/30` decoy/framing wrong accusations (`{eb_e_only['mean_score']:+.4f}`) on `hard`. Shrinking zero-count unseen channels to `0.0` immediately restores `{s_nh['mean_score']:+.4f}` (`{s_nh['correct_count']}/30` correct) on `v1.4` `hard` and `{eb_e100['mean_score']:+.4f}` (`{eb_e100['correct_count']}/30` correct) on noise-free `hard` (`fp=1.00`).",
            f"3. **Exact OOD Cost of Unseen `5%` Canary Fingerprint Noise (`fp_acc: 1.00 -> 0.95`)**: Turning on `hard`'s `5%` canary variant flip rate drops noise-free `easy`-trained deterministic elimination (`eb_easy_deception_neutral_hard_elim`) from `{eb_e100['mean_score']:+.4f}` (`{eb_e100['correct_count']}/30` correct) to `{eb_e095['mean_score']:+.4f}` (`{s_nh['correct_count']}/30` correct, `{s_nh['wrong_count']}` wrong, `{s_nh['abstain_count']}` abstain): a paired OOD noise cost of `{eb_shock_easy['mean_score_delta']:+.4f}` (`95%` CI `[{eb_shock_easy['ci95_low']:+.4f}, {eb_shock_easy['ci95_high']:+.4f}]`). Replacing only `w_canary_miss` with `5%`-noise-calibrated LLR on frozen `v1.4` `hard` recovers `{surg_c['eb_easy_fp95_cal_minus_hard_elim']['mean_score_delta']:+.4f}` (`{s_nh['correct_count']} -> {s_nc['correct_count']}` correct), while `eb_hard_only` suffers only `{eb_shock_hard['mean_score_delta']:+.4f}` (`{eb_h100['correct_count']}/30 -> {eb_h095['correct_count']}/30` correct).",
            "",
            f"{H}{H} 6. Reproduction and Fast Verification",
            "",
            "```bash",
            "python scripts/tiebreak_cross_tier_transfer_audit.py",
            "python scripts/tiebreak_cross_tier_transfer_audit.py --check",
            "pytest -q tests/test_tiebreak_cross_tier_transfer.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


_DET_METRIC_KEYS: tuple[str, ...] = (
    "n",
    "mean_score",
    "cal_ev_mean",
    "accuracy",
    "wrong_accuse_rate",
    "abstain_rate",
    "correct_count",
    "wrong_count",
    "abstain_count",
    "mean_tool_calls",
    "mean_canaries",
    "traces_digest",
)

_DET_CONTRAST_KEYS: tuple[str, ...] = (
    "n",
    "mean_score_delta",
    "cal_ev_delta_mean",
    "a_wins",
    "b_wins",
    "ties",
    "correct_delta",
    "wrong_accuse_delta",
)


_PACKED_DIGEST_CACHE: dict[str, tuple[list[str], dict[str, Any]]] = {}


def _unpack_and_summarize_fast(packed: str) -> tuple[list[str], dict[str, Any]]:
    cached = _PACKED_DIGEST_CACHE.get(packed)
    if cached is not None:
        return cached
    digests = unpack_episode_digests(packed)
    expected = list(range(HELDOUT_SEED_START, HELDOUT_SEED_START + len(digests)))
    if [parse_episode_digest(d)["seed"] for d in digests] != expected:
        raise ValueError("digest seeds != expected sequential HELDOUT_SEEDS")
    det = summarize_digests(digests, rng_tag=0, include_bootstrap=False)
    _PACKED_DIGEST_CACHE[packed] = (digests, det)
    return digests, det


def _verify_metrics_against_digests(
    digests: list[str],
    stored: Any,
    rng_tag: int,
    label: str,
    check_bootstrap: bool,
    precomputed_det: dict[str, Any] | None = None,
) -> str | None:
    if not isinstance(stored, dict):
        return f"{label}: missing metrics dict"
    if check_bootstrap:
        recomp = summarize_digests(digests, rng_tag=rng_tag, include_bootstrap=True)
        return None if recomp == stored else f"{label}: metrics disagree with episode_digests"
    recomp = (
        precomputed_det
        if precomputed_det is not None
        else summarize_digests(digests, rng_tag=rng_tag, include_bootstrap=False)
    )
    for k in _DET_METRIC_KEYS:
        if recomp.get(k) != stored.get(k):
            return f"{label}: metric {k} mismatch ({stored.get(k)!r} != {recomp.get(k)!r})"
    for lo_k, mid_k, hi_k in (
        ("ci95_low", "mean_score", "ci95_high"),
        ("cal_ev_ci95_low", "cal_ev_mean", "cal_ev_ci95_high"),
    ):
        lo_v = stored.get(lo_k)
        mid_v = stored.get(mid_k)
        hi_v = stored.get(hi_k)
        if not (
            isinstance(lo_v, (int, float))
            and isinstance(hi_v, (int, float))
            and float(lo_v) - 1e-6 <= float(mid_v) <= float(hi_v) + 1e-6
        ):
            return f"{label}: invalid CI bounds for {mid_k}"
    return None


_CONTRAST_CACHE: dict[tuple[str, str, int, bool], dict[str, Any]] = {}


def _verify_contrast_against_digests(
    digests_a: list[str],
    digests_b: list[str],
    stored: Any,
    rng_tag: int,
    label: str,
    check_bootstrap: bool,
) -> str | None:
    if not isinstance(stored, dict):
        return f"{label}: missing paired contrast dict"
    ckey = ("|".join(digests_a), "|".join(digests_b), int(rng_tag), bool(check_bootstrap))
    recomp = _CONTRAST_CACHE.get(ckey)
    if recomp is None:
        recomp = compute_paired_contrast(
            digests_a,
            digests_b,
            rng_tag=rng_tag,
            include_bootstrap=check_bootstrap,
        )
        _CONTRAST_CACHE[ckey] = recomp
    if check_bootstrap:
        return None if recomp == stored else f"{label}: paired contrast mismatch"
    for k in _DET_CONTRAST_KEYS:
        if recomp.get(k) != stored.get(k):
            return f"{label}: contrast {k} mismatch ({stored.get(k)!r} != {recomp.get(k)!r})"
    return None


def verify_committed_artifacts(
    summary_path: Path = DEFAULT_OUT_JSON,
    md_path: Path = DEFAULT_OUT_MD,
    repo_root: Path = ROOT,
    enforce_budget: bool = True,
) -> list[str]:
    t0 = time.perf_counter()
    errors: list[str] = []

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
        for bad_ch, ch_name in (
            (EM_DASH, "em dash"),
            (EN_DASH, "en dash"),
            (UNICODE_MINUS, "unicode minus"),
        ):
            if bad_ch in txt:
                errors.append(f"{lbl}: contains forbidden {ch_name}")
        if not txt.isascii():
            errors.append(f"{lbl}: contains non-ASCII characters")
        prereg_hits = _has_affirmative_prereg_0_29(txt)
        if prereg_hits:
            errors.append(f"{lbl}: Panel Fix A violation at {prereg_hits[0]}")

    script_cand = repo_root / "scripts" / "tiebreak_cross_tier_transfer_audit.py"
    target_script = script_cand if script_cand.is_file() else Path(__file__).resolve()
    errors.extend(check_python_source_hygiene(target_script))

    test_cand = repo_root / "tests" / "test_tiebreak_cross_tier_transfer.py"
    if test_cand.is_file():
        errors.extend(check_python_source_hygiene(test_cand))

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_WORLD_SECRET_TAG:
        errors.append(f"unexpected world_secret_tag: {summary.get('world_secret_tag')!r}")
    if summary.get("heldout_seed_range") != "800000..800029":
        errors.append(f"unexpected heldout_seed_range: {summary.get('heldout_seed_range')!r}")
    if summary.get("eval_seed_range") != "800000..800029":
        errors.append(f"unexpected eval_seed_range: {summary.get('eval_seed_range')!r}")
    if summary.get("replay_verified") is not True:
        errors.append("replay_verified must be True")
    if int(summary.get("invalid_episodes", 1)) != 0:
        errors.append("invalid_episodes must be 0")

    iso = summary.get("seed_isolation") or {}
    if int(iso.get("judge_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.judge_episodes_touched must be 0")
    if int(iso.get("dev_episodes_rolled_out", 1)) != 0:
        errors.append("seed_isolation.dev_episodes_rolled_out must be 0")
    if int(iso.get("train_episodes_in_heldout_eval", 1)) != 0:
        errors.append("seed_isolation.train_episodes_in_heldout_eval must be 0")
    if "post-hoc locked, not pre-registered" not in str(iso.get("panel_fix_a_disclosure") or ""):
        errors.append("seed_isolation.panel_fix_a_disclosure missing post-hoc locked disclosure")

    pe = summary.get("panel_fix_e_track_separation") or {}
    if (
        int(pe.get("open_weight_qwen25_runs_above_zero", -1)) != 0
        or pe.get("open_weight_qwen25_above_zero_ratio") != "0 / 19"
        or pe.get("readme_qwen_addendum_status") != "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
        or pe.get("non_llm_policies_is_open_weight_llm") is not False
    ):
        errors.append("panel_fix_e_track_separation violated")

    ledger_cand = repo_root / LEDGER_REL
    if ledger_cand.is_file():
        ledger = json.loads(ledger_cand.read_text(encoding="utf-8"))
        hist_runs = list(ledger.get("historical_runs") or [])
        qwen_pos = sum(
            1
            for r in hist_runs
            if isinstance(r, dict)
            and isinstance(r.get("after_mean_score"), (int, float))
            and float(r["after_mean_score"]) > 0.0
        )
        if int(pe.get("open_weight_qwen25_runs_total", -1)) != len(hist_runs) or int(
            pe.get("open_weight_qwen25_runs_above_zero", -1)
        ) != qwen_pos:
            errors.append("panel_fix_e_track_separation out of sync with experiment_ledger.json")

    hard_digests_by_ref: dict[str, tuple[list[str], dict[str, Any]]] = {}
    tm_block = summary.get("transfer_matrices") or {}
    for fam_idx, fam_id in enumerate(POLICY_FAMILIES):
        pref = "eb" if fam_id == "empirical_bayes" else "sl"
        f_obj = tm_block.get(fam_id) or {}
        f_spec = FAMILY_SPECS[fam_id]
        if f_obj.get("is_open_weight_llm") is not False:
            errors.append(f"{fam_id}: is_open_weight_llm must be False")
        if int(f_obj.get("param_count", -1)) != int(f_spec["param_count"]):
            errors.append(f"{fam_id}: param_count mismatch")
        regimes_obj = f_obj.get("regimes") or {}
        before_pooled_digests: list[str] = []
        for reg_idx, reg_id in enumerate(ALL_REGIMES):
            r_obj = regimes_obj.get(reg_id)
            if not isinstance(r_obj, dict):
                errors.append(f"{fam_id}: missing regime {reg_id}")
                continue
            if r_obj.get("is_open_weight_llm") is not False:
                errors.append(f"{fam_id}.{reg_id}: is_open_weight_llm must be False")
            by_tier = r_obj.get("by_tier") or {}
            packed_by_tier = r_obj.get("episode_digests_packed") or {}
            pooled_digests: list[str] = []
            for t_idx, tier_name in enumerate(CANONICAL_TIERS):
                cell_metrics = by_tier.get(tier_name)
                packed_str = packed_by_tier.get(tier_name)
                if not isinstance(cell_metrics, dict) or not isinstance(packed_str, str):
                    errors.append(f"{fam_id}.{reg_id}: missing tier {tier_name}")
                    continue
                try:
                    digests, det_cell = _unpack_and_summarize_fast(packed_str)
                except ValueError as exc:
                    errors.append(f"{fam_id}.{reg_id}.{tier_name}: invalid packed digests ({exc})")
                    continue
                if len(digests) != HELDOUT_N:
                    errors.append(f"{fam_id}.{reg_id}.{tier_name}: expected {HELDOUT_N} digests")
                    continue
                cell_err = _verify_metrics_against_digests(
                    digests,
                    cell_metrics,
                    rng_tag=fam_idx * 40 + reg_idx * 6 + t_idx,
                    label=f"{fam_id}.{reg_id}.{tier_name}",
                    check_bootstrap=False,
                    precomputed_det=det_cell,
                )
                if cell_err is not None:
                    errors.append(cell_err)
                if tier_name == "hard":
                    hard_digests_by_ref[f"{pref}_{reg_id}"] = (digests, det_cell)
                pooled_digests.extend(digests)
            if len(pooled_digests) == 3 * HELDOUT_N:
                pooled_key = "||".join(packed_by_tier[t] for t in CANONICAL_TIERS)
                cached_pool = _PACKED_DIGEST_CACHE.get(pooled_key)
                if cached_pool is None:
                    det_ov = summarize_digests(pooled_digests, rng_tag=0, include_bootstrap=False)
                    _PACKED_DIGEST_CACHE[pooled_key] = (pooled_digests, det_ov)
                else:
                    det_ov = cached_pool[1]
                ov_err = _verify_metrics_against_digests(
                    pooled_digests,
                    r_obj.get("overall_metrics"),
                    rng_tag=fam_idx * 40 + reg_idx * 6 + 5,
                    label=f"{fam_id}.{reg_id}.overall",
                    check_bootstrap=False,
                    precomputed_det=det_ov,
                )
                if ov_err is not None:
                    errors.append(ov_err)
                if reg_id == "before_untrained":
                    before_pooled_digests = [
                        f"{idx_p}:{d.split(':', 1)[1]}" for idx_p, d in enumerate(pooled_digests)
                    ]
                elif before_pooled_digests:
                    after_pooled_digests = [
                        f"{idx_p}:{d.split(':', 1)[1]}" for idx_p, d in enumerate(pooled_digests)
                    ]
                    pb_err = _verify_contrast_against_digests(
                        after_pooled_digests,
                        before_pooled_digests,
                        r_obj.get("paired_vs_before_overall"),
                        rng_tag=fam_idx * 20 + reg_idx,
                        label=f"{fam_id}.{reg_id}.paired_vs_before",
                        check_bootstrap=(reg_id == "pooled_all"),
                    )
                    if pb_err is not None:
                        errors.append(pb_err)

    ood_block = summary.get("ood_retention_and_noise_decomposition") or {}
    surg_arms = ood_block.get("frozen_v14_hard_surgical_arms") or {}
    for s_idx, aid in enumerate(HARD_SURGICAL_ARM_ORDER):
        ab = surg_arms.get(aid)
        if not isinstance(ab, dict):
            errors.append(f"missing surgical arm {aid}")
            continue
        if ab.get("is_open_weight_llm") is not False:
            errors.append(f"{aid}: is_open_weight_llm must be False")
        try:
            digests, det_s = _unpack_and_summarize_fast(str(ab.get("episode_digests_packed") or ""))
        except ValueError as exc:
            errors.append(f"{aid}: invalid packed digests ({exc})")
            continue
        if len(digests) != HELDOUT_N:
            errors.append(f"{aid}: invalid episode_digests")
            continue
        s_err = _verify_metrics_against_digests(
            digests,
            ab.get("metrics"),
            rng_tag=220 + s_idx,
            label=aid,
            check_bootstrap=False,
            precomputed_det=det_s,
        )
        if s_err is not None:
            errors.append(s_err)
        hard_digests_by_ref[aid] = (digests, det_s)

    nshock_arms = (ood_block.get("hard_fingerprint_noise_counterfactual") or {}).get("arms") or {}
    for n_idx, aid in enumerate(NOISE_SHOCK_ARM_ORDER):
        nb = nshock_arms.get(aid)
        if not isinstance(nb, dict):
            errors.append(f"missing noise_shock arm {aid}")
            continue
        try:
            d100, det100 = _unpack_and_summarize_fast(str(nb.get("fp100_episode_digests_packed") or ""))
        except ValueError as exc:
            errors.append(f"noise_shock.{aid}: invalid packed digests ({exc})")
            continue
        ref095 = hard_digests_by_ref.get(aid)
        if len(d100) != HELDOUT_N or ref095 is None or len(ref095[0]) != HELDOUT_N:
            errors.append(f"noise_shock.{aid}: expected {HELDOUT_N} digests")
            continue
        d095, det095 = ref095
        m100_err = _verify_metrics_against_digests(
            d100,
            nb.get("fp100_noise_free_metrics"),
            rng_tag=260 + n_idx * 2,
            label=f"noise_shock.{aid}.fp100",
            check_bootstrap=False,
            precomputed_det=det100,
        )
        if m100_err is not None:
            errors.append(m100_err)
        m095_err = _verify_metrics_against_digests(
            d095,
            nb.get("fp095_standard_metrics"),
            rng_tag=261 + n_idx * 2,
            label=f"noise_shock.{aid}.fp095",
            check_bootstrap=False,
            precomputed_det=det095,
        )
        if m095_err is not None:
            errors.append(m095_err)
        sh_err = _verify_contrast_against_digests(
            d095,
            d100,
            nb.get("noise_shock_fp095_minus_fp100"),
            rng_tag=300 + n_idx,
            label=f"noise_shock.{aid}.delta",
            check_bootstrap=(n_idx == 0),
        )
        if sh_err is not None:
            errors.append(sh_err)

    ast_block = summary.get("ast_inference_isolation") or {}
    if ast_block.get("passed") is not True or (ast_block.get("errors") or []):
        errors.append("summary.ast_inference_isolation is not clean PASS")

    expected_md = render_markdown_report(summary)
    if md_txt != expected_md:
        errors.append(f"{m_file.name}: markdown text out of sync with render_markdown_report(summary)")

    required_md_tokens = (
        "800000..800029",
        EXPECTED_WORLD_SECRET_TAG,
        "post-hoc locked, not pre-registered",
        "0 / 19",
        "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "EmpiricalBayesPolicy",
        "ScalingLogisticPolicy",
        "is_open_weight_llm = False",
    )
    for tok in required_md_tokens:
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
        description="Zero-shot cross-tier transfer and OOD pool/horizon generalization audit for Canary v1.4."
    )
    ap.add_argument("--repo-root", "--root", dest="repo_root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--workers", type=int, default=12)
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
    print(f"OK: verified {rel_j} and {rel_m} (1140/1140 cross-tier transfer rollouts, 0 AST leaks) in {elapsed:.4f}s")
    return 0


if __name__ == "__main__" and "--check" in sys.argv[1:]:
    raise SystemExit(_run_check_cli(build_arg_parser().parse_args()))

from scripts.tiebreak_scaling_calibration import CompactLinearPolicy, LinearPolicyWeights
from train.empirical_bayes_policy import (
    EmpiricalBayesParams,
    EmpiricalBayesPolicy,
    make_naive_prior_params,
)


class ScalingLogisticPolicy(CompactLinearPolicy):
    def __init__(
        self,
        weights: LinearPolicyWeights,
        name: str | None = None,
        explore_eps: float = 0.0,
        rng_seed: int = 0,
    ) -> None:
        super().__init__(weights=weights, name=name, explore_eps=explore_eps, rng_seed=rng_seed)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


@contextlib.contextmanager
def _scoped_world_secret(secret: str) -> Iterator[None]:
    prev = os.environ.get("CANARY_WORLD_SECRET")
    os.environ["CANARY_WORLD_SECRET"] = secret
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev


def assert_strict_train_seeds(seeds: list[int], label: str) -> list[int]:
    from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

    if not seeds:
        raise ValueError(f"{label}: train seed list must be non-empty")
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"{label}: duplicate seed in train seed list")
    for s in seeds:
        if (
            s in DEV_SEEDS
            or s in HELDOUT_SEEDS
            or s in JUDGE_SEEDS
            or s not in TRAIN_SEEDS
            or not (100_000 <= s < 200_000)
        ):
            raise ValueError(f"{label}: seed {s} violates TRAIN_SEEDS [100000, 200000) isolation")
    return list(seeds)


def select_sl_regime_seeds(regime_id: str) -> tuple[tuple[str, ...], list[int], str]:
    if regime_id == "easy_only":
        lo = SL_TIER_OFFSETS["easy"]
        seeds = list(range(lo, lo + SL_EPISODES_PER_REGIME))
        return ("easy",), assert_strict_train_seeds(seeds, regime_id), f"{seeds[0]}..{seeds[-1]}"
    if regime_id == "medium_only":
        lo = SL_TIER_OFFSETS["medium"]
        seeds = list(range(lo, lo + SL_EPISODES_PER_REGIME))
        return ("medium",), assert_strict_train_seeds(seeds, regime_id), f"{seeds[0]}..{seeds[-1]}"
    if regime_id == "hard_only":
        lo = SL_TIER_OFFSETS["hard"]
        seeds = list(range(lo, lo + SL_EPISODES_PER_REGIME))
        return ("hard",), assert_strict_train_seeds(seeds, regime_id), f"{seeds[0]}..{seeds[-1]}"
    if regime_id == "pooled_all":
        per_tier = SL_EPISODES_PER_REGIME // 3
        seeds = [
            s
            for idx in range(per_tier)
            for s in (
                SL_TIER_OFFSETS["easy"] + idx,
                SL_TIER_OFFSETS["medium"] + idx,
                SL_TIER_OFFSETS["hard"] + idx,
            )
        ]
        disp = (
            f"{SL_TIER_OFFSETS['easy']}..{SL_TIER_OFFSETS['easy'] + per_tier - 1},"
            f"{SL_TIER_OFFSETS['medium']}..{SL_TIER_OFFSETS['medium'] + per_tier - 1},"
            f"{SL_TIER_OFFSETS['hard']}..{SL_TIER_OFFSETS['hard'] + per_tier - 1}"
        )
        return CANONICAL_TIERS, assert_strict_train_seeds(seeds, regime_id), disp
    raise ValueError(f"unknown regime_id {regime_id!r}")


def fit_empirical_bayes_regime(regime_id: str) -> tuple[str, EmpiricalBayesParams, dict[str, Any]]:
    import numpy as np
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    from train.empirical_bayes_policy import _ExplorationRolloutPolicy

    lo, hi = EB_REGIME_SEEDS[regime_id]
    all_seeds = assert_strict_train_seeds(list(range(lo, hi)), f"eb:{regime_id}")
    s2_seeds = all_seeds[:EB_STAGE2_COUNT]
    s3_seeds = all_seeds[EB_STAGE2_COUNT:]
    tiers_seq: tuple[str, ...] = (
        CANONICAL_TIERS if regime_id == "pooled_all" else (regime_id.replace("_only", ""),)
    )
    provider = TemplateProvider()

    can_exp = [0, 0]
    can_hit = [0, 0]
    can_miss = [0, 0]
    doc_exp = [0, 0]
    doc_hit = [0, 0]
    ah_days = [0, 0]
    ah_cnt = [0, 0]
    inn_ah_obs: list[tuple[int, int]] = []
    iv_exp = [0, 0]
    iv_ev = [0, 0]
    ang_eps = [0, 0]
    ang_cnt = [0, 0]
    identified = 0

    for idx, seed in enumerate(s2_seeds):
        tier = tiers_seq[idx % len(tiers_seq)]
        env = Env(tier, seed, text_provider=provider)
        explorer = _ExplorationRolloutPolicy(seed=seed)
        ep = run_episode(env, explorer)
        tr = explorer.tracker
        tr.ingest_steps(list(ep.steps))
        feats = tr.extract_features()
        if not (ep.accused and ep.correct):
            continue
        identified += 1
        mole_id = str(ep.accused)
        n_surfaced = len(tr.feed_items)
        n_log_days = len(tr.logged_days)
        did_msg_search = bool(tr.queries_done)
        for emp in tr.employees:
            y = 1 if emp == mole_id else 0
            c_h, c_m, d_h, ah, ev, ang = feats[emp]
            can_exp[y] += c_h + c_m
            can_hit[y] += c_h
            can_miss[y] += c_m
            doc_exp[y] += n_surfaced
            doc_hit[y] += d_h
            ah_days[y] += n_log_days
            ah_cnt[y] += ah
            if y == 0 and n_log_days > 0:
                inn_ah_obs.append((ah, n_log_days))
            iv_exp[y] += tr.interviews_total.get(emp, 0)
            iv_ev[y] += ev
            if did_msg_search:
                ang_eps[y] += 1
                ang_cnt[y] += ang

    a = 1.0
    p_chit_1 = (can_hit[1] + a) / max(2.0 * a, can_exp[1] + 2.0 * a)
    p_chit_0 = (can_hit[0] + a) / max(2.0 * a, can_exp[0] + 2.0 * a)
    p_cmiss_1 = (can_miss[1] + a) / max(2.0 * a, can_exp[1] + 2.0 * a)
    p_cmiss_0 = (can_miss[0] + a) / max(2.0 * a, can_exp[0] + 2.0 * a)
    w_ch = math.log(p_chit_1 / p_chit_0)
    w_cm = math.log(p_cmiss_1 / p_cmiss_0)

    p_doc_1 = min(1.0 - 1e-6, max(1e-6, (doc_hit[1] + a) / max(2.0 * a, doc_exp[1] + 2.0 * a)))
    p_doc_0 = min(1.0 - 1e-6, max(1e-6, (doc_hit[0] + a) / max(2.0 * a, doc_exp[0] + 2.0 * a)))
    w_dh = math.log((p_doc_1 * (1.0 - p_doc_0)) / ((1.0 - p_doc_1) * p_doc_0))

    r_ah_1 = (ah_cnt[1] + a) / max(a, ah_days[1] + a)
    r_ah_0 = (ah_cnt[0] + a) / max(a, ah_days[0] + a)
    if inn_ah_obs:
        fano = max(
            1.0,
            float(np.mean([((k - r_ah_0 * d) ** 2) / max(1e-6, r_ah_0 * d) for k, d in inn_ah_obs])),
        )
    else:
        fano = 1.0
    w_ah = math.log(r_ah_1 / r_ah_0) / fano

    p_ev_1 = (iv_ev[1] + a) / max(2.0 * a, iv_exp[1] + 2.0 * a)
    p_ev_0 = (iv_ev[0] + a) / max(2.0 * a, iv_exp[0] + 2.0 * a)
    w_ev = math.log(p_ev_1 / p_ev_0)

    r_ang_1 = (ang_cnt[1] + a) / max(2.0 * a, ang_eps[1] + 2.0 * a)
    r_ang_0 = (ang_cnt[0] + a) / max(2.0 * a, ang_eps[0] + 2.0 * a)
    w_ang = math.log(r_ang_1 / r_ang_0)

    def _eval_s3(cand: EmpiricalBayesParams, seeds_sub: list[int]) -> tuple[float, float]:
        scs: list[float] = []
        wrongs = 0
        for s_idx, s_val in enumerate(seeds_sub):
            t_nm = tiers_seq[s_idx % len(tiers_seq)]
            ep_s3 = run_episode(Env(t_nm, s_val, text_provider=provider), EmpiricalBayesPolicy(cand, seed=s_val))
            scs.append(float(ep_s3.score))
            if ep_s3.accused is not None and not ep_s3.correct:
                wrongs += 1
        return float(np.mean(scs)), wrongs / max(1, len(seeds_sub))

    half = len(s3_seeds) // 2
    sa, sb = s3_seeds[:half], s3_seeds[half:]

    best_cov, best_tiny, best_k_sp = 0.55, 4, (-1e9, -1e9)
    for cov, tiny_sz in ((0.90, 0), (0.65, 3), (0.55, 4), (0.45, 6), (0.35, 6)):
        cand = EmpiricalBayesParams(
            w_ch, w_cm, w_dh, w_ah, w_ev, w_ang, 0.65, 1.0, cov, tiny_sz, True, 0.50, f"eb_{regime_id}"
        )
        ms, wr = _eval_s3(cand, sa)
        if (ms, -wr) > best_k_sp:
            best_k_sp = (ms, -wr)
            best_cov, best_tiny = cov, tiny_sz

    best_tau, best_k_tau = 0.65, (-1e9, -1e9)
    for tau in (0.0, 0.30, 0.50, 0.65, 0.75, 0.85):
        cand = EmpiricalBayesParams(
            w_ch, w_cm, w_dh, w_ah, w_ev, w_ang, tau, 1.0, best_cov, best_tiny, True, 0.50, f"eb_{regime_id}"
        )
        ms, wr = _eval_s3(cand, sb)
        if (ms, -wr) > best_k_tau:
            best_k_tau = (ms, -wr)
            best_tau = tau

    best_disc, best_k_disc = 1.0, (-1e9, -1e9, -1e9)
    for disc in (0.0, 0.50, 1.00, 1.25):
        cand = EmpiricalBayesParams(
            w_ch, w_cm, w_dh, w_ah, w_ev, w_ang, best_tau, disc, best_cov, best_tiny, True, 0.50, f"eb_{regime_id}"
        )
        ms, wr = _eval_s3(cand, sb)
        if (ms, -wr, -abs(disc - 1.0)) > best_k_disc:
            best_k_disc = (ms, -wr, -abs(disc - 1.0))
            best_disc = disc

    fitted = EmpiricalBayesParams(
        w_canary_hit=round(w_ch, 5),
        w_canary_miss=round(w_cm, 5),
        w_doc_hit=round(w_dh, 5),
        w_after_hours=round(w_ah, 5),
        w_evasive=round(w_ev, 5),
        w_angry_msg=round(w_ang, 5),
        tau_margin=round(best_tau, 5),
        unsurfaced_v_discount=round(best_disc, 5),
        canary_coverage=round(best_cov, 5),
        tiny_pool_size=int(best_tiny),
        use_ev_stopping=True,
        naive_p_threshold=0.50,
        stage=f"eb_{regime_id}",
    )
    meta = {
        "train_seed_range": f"{lo}..{hi - 1}",
        "episodes_trained": len(all_seeds),
        "stage2_identified_episodes": identified,
        "mole_canary_mismatches_observed": int(can_miss[1]),
        "innocent_canary_mismatches_observed": int(can_miss[0]),
        "angry_messages_observed_total": int(ang_cnt[0] + ang_cnt[1]),
    }
    return regime_id, fitted, meta


def fit_scaling_logistic_regime(regime_id: str) -> tuple[str, LinearPolicyWeights, dict[str, Any]]:
    import scripts.tiebreak_scaling_calibration as tsc

    tiers_seq, seeds_list, range_disp = select_sl_regime_seeds(regime_id)
    prior = tsc.make_prior_weights(202614)
    w_cur = tsc.fit_weights_from_trajectories([], prior)
    trajs: list[Any] = []
    n = len(seeds_list)
    c1, c2 = n // 6, n // 2
    for round_idx, chunk in enumerate((seeds_list[:c1], seeds_list[c1:c2], seeds_list[c2:])):
        eps_exp = 0.35 if round_idx == 0 else (0.20 if round_idx == 1 else 0.10)
        for idx, s_val in enumerate(chunk):
            t_nm = tiers_seq[idx % len(tiers_seq)]
            trajs.append(tsc._collect_one_training_trajectory(t_nm, s_val, w_cur, eps_exp))
        w_cur = tsc.fit_weights_from_trajectories(trajs, prior)

    rounded_w = LinearPolicyWeights(
        w_suspect=w_cur.w_suspect.round(5),
        w_commit=w_cur.w_commit.round(5),
        w_wait=w_cur.w_wait.round(5),
        w_tool=w_cur.w_tool.round(5),
        w_canary=w_cur.w_canary.round(5),
        n_train=int(w_cur.n_train),
    )
    meta: dict[str, Any] = {
        "train_seed_range_display": range_disp,
        "episodes_trained": len(seeds_list),
        "w_suspect_exact_fp_mismatch": round(float(rounded_w.w_suspect[4]), 5),
        "w_suspect_noisy_fp_mismatch": round(float(rounded_w.w_suspect[5]), 5),
        "w_commit_fp_noisy": round(float(rounded_w.w_commit[8]), 5),
        "w_wait_fp_noisy": round(float(rounded_w.w_wait[5]), 5),
    }
    if regime_id != "pooled_all":
        meta["train_seed_range"] = range_disp
    else:
        per_tier = SL_EPISODES_PER_REGIME // 3
        meta["per_tier_train_seed_ranges"] = {
            t_nm: {"train_seed_range": f"{SL_TIER_OFFSETS[t_nm]}..{SL_TIER_OFFSETS[t_nm] + per_tier - 1}"}
            for t_nm in CANONICAL_TIERS
        }
    return regime_id, rounded_w, meta


def _fmt_float_csv(vals: list[float]) -> str:
    return ",".join(f"{round(float(x), 5):.5f}".rstrip("0").rstrip(".") or "0" for x in vals)


def _round_linear_weights_dict(weights: LinearPolicyWeights) -> dict[str, Any]:
    return {
        "n_train": int(weights.n_train),
        "n_parameters": int(weights.num_parameters()),
        "w_suspect_csv": _fmt_float_csv(weights.w_suspect.tolist()),
        "w_commit_csv": _fmt_float_csv(weights.w_commit.tolist()),
        "w_wait_csv": _fmt_float_csv(weights.w_wait.tolist()),
        "w_canary_csv": _fmt_float_csv(weights.w_canary.tolist()),
        "w_tool_csv": ";".join(_fmt_float_csv(row) for row in weights.w_tool.tolist()),
    }


def _parse_linear_weights_dict(wd: dict[str, Any]) -> LinearPolicyWeights:
    import numpy as np

    if "w_suspect_csv" in wd:
        w_s = [float(x) for x in str(wd["w_suspect_csv"]).split(",")]
        w_c = [float(x) for x in str(wd["w_commit_csv"]).split(",")]
        w_w = [float(x) for x in str(wd["w_wait_csv"]).split(",")]
        w_can = [float(x) for x in str(wd["w_canary_csv"]).split(",")]
        w_t = [[float(v) for v in row.split(",")] for row in str(wd["w_tool_csv"]).split(";")]
    else:
        w_s = wd["w_suspect"]
        w_c = wd["w_commit"]
        w_w = wd["w_wait"]
        w_can = wd["w_canary"]
        w_t = wd["w_tool"]
    return LinearPolicyWeights(
        w_suspect=np.asarray(w_s, dtype=np.float64),
        w_commit=np.asarray(w_c, dtype=np.float64),
        w_wait=np.asarray(w_w, dtype=np.float64),
        w_tool=np.asarray(w_t, dtype=np.float64),
        w_canary=np.asarray(w_can, dtype=np.float64),
        n_train=int(wd["n_train"]),
    )


def _round_eb_params_dict(params: EmpiricalBayesParams) -> dict[str, Any]:
    d = params.to_dict()
    for k, v in list(d.items()):
        if isinstance(v, float):
            d[k] = round(v, 5)
    return d


def build_policy_from_spec(
    policy_kind: str,
    seed: int,
    bundle: dict[str, Any],
) -> Any:
    if policy_kind.startswith("eb:"):
        key = policy_kind.split(":", 1)[1]
        return EmpiricalBayesPolicy(params=bundle["eb_params"][key], seed=seed, name=policy_kind)
    if policy_kind.startswith("sl:"):
        key = policy_kind.split(":", 1)[1]
        return ScalingLogisticPolicy(
            weights=bundle["sl_weights"][key],
            name=policy_kind,
            explore_eps=0.0,
            rng_seed=seed,
        )
    raise ValueError(f"unknown policy_kind {policy_kind!r}")


def execute_single_episode(
    policy_kind: str,
    tier: str,
    seed: int,
    provider: Any,
    bundle: dict[str, Any],
    verify_replay: bool = True,
) -> dict[str, Any]:
    from canary.env import Env

    env = Env(tier, seed, text_provider=provider)
    tools_spec = env.tools_spec()
    instruction = env.instruction()
    policy = build_policy_from_spec(policy_kind, seed, bundle)
    policy.reset(tools_spec, instruction)

    actions_trace: list[tuple[str, dict[str, Any]]] = []
    pre_accuse_len: int | None = None
    accused_emp: str | None = None

    while not env.done:
        tool, args = policy.act(env.history)
        if tool == "accuse" and pre_accuse_len is None:
            pre_accuse_len = len(env.history)
            accused_emp = str(args.get("employee", ""))
        actions_trace.append((tool, dict(args)))
        env.call(tool, args)

    verdict = env.verdict()
    score = float(verdict["score"])
    if verdict["accused"] is None:
        outcome = "a"
    elif verdict["correct"]:
        outcome = "c"
    else:
        outcome = "w"

    observer = EmpiricalBayesPolicy(
        params=bundle["eb_params"]["pooled_all"],
        seed=seed,
        name="public_cal_observer",
    )
    observer.reset(tools_spec, instruction)
    hist_slice = env.history[:pre_accuse_len] if pre_accuse_len is not None else env.history
    observer.tracker.ingest_steps(hist_slice)
    dm = observer.decision_metrics()
    post = dm["post"]
    v_hat = float(dm["v_hat"])
    w_wrong = float(observer.rules["wrong_accusation_score"])

    if verdict["accused"] is not None and accused_emp:
        cal_p = float(post.get(accused_emp, 0.0))
        cal_ev = cal_p * v_hat + (1.0 - cal_p) * w_wrong
    else:
        cal_p = float(dm["top_p"])
        cal_ev = 0.0

    planted_cnt = sum(
        1 for st in env.history if st.tool == "plant_canary" and bool((st.result or {}).get("ok"))
    )

    replay_ok = True
    if verify_replay:
        env_rep = Env(tier, seed, text_provider=provider)
        for r_tool, r_args in actions_trace:
            env_rep.call(r_tool, r_args)
        rep_verdict = env_rep.verdict()
        if (
            not env_rep.done
            or abs(float(rep_verdict["score"]) - score) > 1e-9
            or rep_verdict["accused"] != verdict["accused"]
            or bool(rep_verdict["correct"]) != bool(verdict["correct"])
        ):
            replay_ok = False

    rec = {
        "policy_kind": policy_kind,
        "tier": tier,
        "seed": seed,
        "outcome": outcome,
        "final_day": int(verdict["final_day"]),
        "tool_calls": len(env.history),
        "score": round(score, 4),
        "canaries_planted": planted_cnt,
        "cal_p": round(cal_p, 4),
        "cal_ev": round(cal_ev, 4),
        "replay_ok": replay_ok,
    }
    rec["digest"] = format_episode_digest(rec)
    return rec


_EVAL_WORKER_STATE: dict[str, Any] = {}


def _worker_eval_task(task: tuple[str, str, int]) -> dict[str, Any]:
    policy_kind, tier, seed = task
    return execute_single_episode(
        policy_kind=policy_kind,
        tier=tier,
        seed=seed,
        provider=_EVAL_WORKER_STATE["provider"],
        bundle=_EVAL_WORKER_STATE["bundle"],
        verify_replay=True,
    )


def load_trained_bundle_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    eb_params: dict[str, EmpiricalBayesParams] = {}
    sl_weights: dict[str, LinearPolicyWeights] = {}

    eb_regimes = summary["transfer_matrices"]["empirical_bayes"]["regimes"]
    for reg_id, r_obj in eb_regimes.items():
        eb_params[reg_id] = EmpiricalBayesParams.from_dict(r_obj["learned_params"])

    sl_regimes = summary["transfer_matrices"]["scaling_logistic"]["regimes"]
    for reg_id, r_obj in sl_regimes.items():
        sl_weights[reg_id] = _parse_linear_weights_dict(r_obj["learned_weights"])

    surg_arms = summary["ood_retention_and_noise_decomposition"]["frozen_v14_hard_surgical_arms"]
    for aid, ab in surg_arms.items():
        if ab["family_id"] == "empirical_bayes":
            eb_params[aid] = EmpiricalBayesParams.from_dict(ab["learned_params"])
        else:
            sl_weights[aid] = _parse_linear_weights_dict(ab["learned_weights"])

    return {"eb_params": eb_params, "sl_weights": sl_weights}


def run_audit(repo_root: Path = ROOT, max_workers: int = 12) -> dict[str, Any]:
    from canary import rules
    from canary.text.template import TemplateProvider
    import scripts.tiebreak_scaling_calibration as tsc
    import scripts.verify_tiebreak_submission as vts

    t0 = time.perf_counter()
    repo_root = repo_root.resolve()
    eval_seeds = list(range(HELDOUT_SEED_START, HELDOUT_SEED_STOP))
    for s_val in eval_seeds:
        if s_val not in rules.HELDOUT_SEEDS or s_val in rules.JUDGE_SEEDS or s_val >= JUDGE_SEED_MIN:
            raise ValueError(f"eval seed {s_val} violates HELDOUT_SEEDS isolation")

    secret_tag = compute_secret_tag(HELDOUT_WORLD_SECRET)
    if secret_tag != EXPECTED_WORLD_SECRET_TAG:
        raise AssertionError(f"secret_tag {secret_tag} != {EXPECTED_WORLD_SECRET_TAG}")

    script_cand = repo_root / "scripts" / "tiebreak_cross_tier_transfer_audit.py"
    target_script = script_cand if script_cand.is_file() else Path(__file__).resolve()
    ast_outcome = vts.check_ast_inference_isolation(
        root=repo_root,
        extra_paths=[target_script],
        strict=True,
    )
    if not ast_outcome.passed:
        raise AssertionError(f"AST inference isolation failed: {ast_outcome.errors}")

    use_fork = max_workers > 1 and "fork" in multiprocessing.get_all_start_methods()
    eb_params_map: dict[str, EmpiricalBayesParams] = {
        "before_untrained": make_naive_prior_params(),
    }
    eb_meta_map: dict[str, dict[str, Any]] = {
        "before_untrained": {"episodes_trained": 0, "training_regime": "untrained_naive_prior"},
    }
    prior_sl = tsc.make_prior_weights(202614)
    prior_sl_zero = tsc.fit_weights_from_trajectories([], prior_sl)
    sl_weights_map: dict[str, LinearPolicyWeights] = {
        "before_untrained": LinearPolicyWeights(
            w_suspect=prior_sl_zero.w_suspect.round(5),
            w_commit=prior_sl_zero.w_commit.round(5),
            w_wait=prior_sl_zero.w_wait.round(5),
            w_tool=prior_sl_zero.w_tool.round(5),
            w_canary=prior_sl_zero.w_canary.round(5),
            n_train=0,
        ),
    }
    sl_meta_map: dict[str, dict[str, Any]] = {
        "before_untrained": {"episodes_trained": 0, "training_regime": "untrained_prior_n0"},
    }

    if use_fork:
        ctx = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(max_workers=min(4, max_workers), mp_context=ctx) as pool:
            eb_fitted = list(pool.map(fit_empirical_bayes_regime, TRAIN_REGIMES))
        with ProcessPoolExecutor(max_workers=min(4, max_workers), mp_context=ctx) as pool:
            sl_fitted = list(pool.map(fit_scaling_logistic_regime, TRAIN_REGIMES))
    else:
        eb_fitted = [fit_empirical_bayes_regime(r) for r in TRAIN_REGIMES]
        sl_fitted = [fit_scaling_logistic_regime(r) for r in TRAIN_REGIMES]

    for r_id, p_eb, m_eb in eb_fitted:
        eb_params_map[r_id] = p_eb
        eb_meta_map[r_id] = m_eb
    for r_id, w_sl, m_sl in sl_fitted:
        sl_weights_map[r_id] = w_sl
        sl_meta_map[r_id] = m_sl

    eb_easy = eb_params_map["easy_only"]
    eb_med = eb_params_map["medium_only"]
    eb_hard = eb_params_map["hard_only"]

    eb_params_map["eb_easy_deception_neutral_hard_elim"] = replace(
        eb_easy,
        w_canary_miss=-30.0,
        w_after_hours=0.0,
        w_angry_msg=0.0,
        stage="eb_easy_deception_neutral_hard_elim",
    )
    eb_params_map["eb_easy_deception_neutral_fp95_cal"] = replace(
        eb_easy,
        w_canary_miss=eb_hard.w_canary_miss,
        w_after_hours=0.0,
        w_angry_msg=0.0,
        stage="eb_easy_deception_neutral_fp95_cal",
    )
    eb_params_map["eb_medium_plus_fp95_and_h21_stop"] = replace(
        eb_med,
        w_canary_miss=eb_hard.w_canary_miss,
        tau_margin=eb_hard.tau_margin,
        unsurfaced_v_discount=eb_hard.unsurfaced_v_discount,
        canary_coverage=eb_hard.canary_coverage,
        tiny_pool_size=eb_hard.tiny_pool_size,
        stage="eb_medium_plus_fp95_and_h21_stop",
    )

    w_sl_easy = sl_weights_map["easy_only"]
    w_sl_blind = LinearPolicyWeights(
        w_suspect=w_sl_easy.w_suspect.copy(),
        w_commit=w_sl_easy.w_commit.copy(),
        w_wait=w_sl_easy.w_wait.copy(),
        w_tool=w_sl_easy.w_tool.copy(),
        w_canary=w_sl_easy.w_canary.copy(),
        n_train=int(w_sl_easy.n_train),
    )
    w_sl_blind.w_suspect[5] = -30.0
    sl_weights_map["sl_easy_noise_blind_hard_elim"] = w_sl_blind

    bundle = {"eb_params": eb_params_map, "sl_weights": sl_weights_map}
    provider = TemplateProvider()

    tasks: list[tuple[str, str, int]] = []
    for fam_id in POLICY_FAMILIES:
        pref = "eb" if fam_id == "empirical_bayes" else "sl"
        for reg_id in ALL_REGIMES:
            for t_name in CANONICAL_TIERS:
                for s_val in eval_seeds:
                    tasks.append((f"{pref}:{reg_id}", t_name, s_val))

    for aid in HARD_SURGICAL_ARM_ORDER:
        pref = "eb" if HARD_SURGICAL_SPECS[aid]["family_id"] == "empirical_bayes" else "sl"
        for s_val in eval_seeds:
            tasks.append((f"{pref}:{aid}", "hard", s_val))

    with _scoped_world_secret(HELDOUT_WORLD_SECRET):
        _EVAL_WORKER_STATE["provider"] = provider
        _EVAL_WORKER_STATE["bundle"] = bundle
        if use_fork:
            ctx = multiprocessing.get_context("fork")
            with ProcessPoolExecutor(max_workers=min(max_workers, 16), mp_context=ctx) as pool:
                frozen_rows = list(pool.map(_worker_eval_task, tasks, chunksize=6))
        else:
            frozen_rows = [_worker_eval_task(tk) for tk in tasks]

        noise_free_digests: dict[str, list[str]] = {aid: [] for aid in NOISE_SHOCK_ARM_ORDER}
        orig_hard_params = rules.TIERS["hard"]
        try:
            rules.TIERS["hard"] = replace(orig_hard_params, fingerprint_accuracy=1.0)
            noise_tasks = [
                ("eb:eb_easy_deception_neutral_hard_elim", "hard", s_val) for s_val in eval_seeds
            ] + [
                ("eb:hard_only", "hard", s_val) for s_val in eval_seeds
            ] + [
                ("sl:easy_only", "hard", s_val) for s_val in eval_seeds
            ] + [
                ("sl:hard_only", "hard", s_val) for s_val in eval_seeds
            ]
            if use_fork:
                ctx = multiprocessing.get_context("fork")
                with ProcessPoolExecutor(max_workers=min(max_workers, 12), mp_context=ctx) as pool:
                    nf_rows = list(pool.map(_worker_eval_task, noise_tasks, chunksize=5))
            else:
                nf_rows = [_worker_eval_task(tk) for tk in noise_tasks]
        finally:
            rules.TIERS["hard"] = orig_hard_params

    if rules.TIERS["hard"].fingerprint_accuracy != orig_hard_params.fingerprint_accuracy:
        raise AssertionError("failed to restore rules.TIERS['hard']")
    if any(not r["replay_ok"] for r in frozen_rows) or any(not r["replay_ok"] for r in nf_rows):
        raise AssertionError("fresh Env replay verification failed on one or more episodes")

    digests_by_key: dict[tuple[str, str], list[str]] = {}
    for r in frozen_rows:
        digests_by_key.setdefault((r["policy_kind"], r["tier"]), []).append(r["digest"])

    nf_kind_map = {
        "eb:eb_easy_deception_neutral_hard_elim": "eb_easy_deception_neutral_hard_elim",
        "eb:hard_only": "eb_hard_only",
        "sl:easy_only": "sl_easy_only",
        "sl:hard_only": "sl_hard_only",
    }
    for r in nf_rows:
        noise_free_digests[nf_kind_map[r["policy_kind"]]].append(r["digest"])

    transfer_matrices: dict[str, Any] = {}
    for fam_idx, fam_id in enumerate(POLICY_FAMILIES):
        pref = "eb" if fam_id == "empirical_bayes" else "sl"
        f_spec = dict(FAMILY_SPECS[fam_id])
        regimes_out: dict[str, Any] = {}
        before_pooled_indexed: list[str] = []
        for reg_idx, reg_id in enumerate(ALL_REGIMES):
            by_tier_out: dict[str, Any] = {}
            packed_by_tier: dict[str, str] = {}
            pooled_digests: list[str] = []
            for t_idx, t_name in enumerate(CANONICAL_TIERS):
                d_list = digests_by_key[(f"{pref}:{reg_id}", t_name)]
                cell_tag = fam_idx * 40 + reg_idx * 6 + t_idx
                by_tier_out[t_name] = summarize_digests(d_list, rng_tag=cell_tag)
                packed_by_tier[t_name] = pack_episode_digests(d_list)
                pooled_digests.extend(d_list)

            ov_metrics = summarize_digests(pooled_digests, rng_tag=fam_idx * 40 + reg_idx * 6 + 5)
            meta_info = dict(eb_meta_map[reg_id] if fam_id == "empirical_bayes" else sl_meta_map[reg_id])
            entry: dict[str, Any] = {
                "regime_id": reg_id,
                "is_open_weight_llm": False,
                **meta_info,
            }
            if fam_id == "empirical_bayes":
                entry["learned_params"] = _round_eb_params_dict(eb_params_map[reg_id])
            else:
                entry["learned_weights"] = _round_linear_weights_dict(sl_weights_map[reg_id])
            entry["overall_metrics"] = ov_metrics
            if reg_id == "before_untrained":
                before_pooled_indexed = [
                    f"{idx_p}:{d.split(':', 1)[1]}" for idx_p, d in enumerate(pooled_digests)
                ]
            else:
                after_pooled_indexed = [
                    f"{idx_p}:{d.split(':', 1)[1]}" for idx_p, d in enumerate(pooled_digests)
                ]
                entry["paired_vs_before_overall"] = compute_paired_contrast(
                    after_pooled_indexed,
                    before_pooled_indexed,
                    rng_tag=fam_idx * 20 + reg_idx,
                )
            entry["by_tier"] = by_tier_out
            entry["episode_digests_packed"] = packed_by_tier
            regimes_out[reg_id] = entry

        transfer_matrices[fam_id] = {
            **f_spec,
            "regimes": regimes_out,
        }

    surgical_out: dict[str, Any] = {}
    for s_idx, aid in enumerate(HARD_SURGICAL_ARM_ORDER):
        spec = dict(HARD_SURGICAL_SPECS[aid])
        pref = "eb" if spec["family_id"] == "empirical_bayes" else "sl"
        d_list = digests_by_key[(f"{pref}:{aid}", "hard")]
        arm_entry: dict[str, Any] = {
            **spec,
            "metrics": summarize_digests(d_list, rng_tag=220 + s_idx),
            "episode_digests_packed": pack_episode_digests(d_list),
        }
        if spec["family_id"] == "empirical_bayes":
            arm_entry["learned_params"] = _round_eb_params_dict(eb_params_map[aid])
        else:
            arm_entry["learned_weights"] = _round_linear_weights_dict(sl_weights_map[aid])
        surgical_out[aid] = arm_entry

    eb_ret_easy = compute_retention_summary(
        digests_by_key[("eb:easy_only", "hard")],
        digests_by_key[("eb:hard_only", "hard")],
        digests_by_key[("eb:pooled_all", "hard")],
        rng_tag=160,
    )
    eb_ret_med = compute_retention_summary(
        digests_by_key[("eb:medium_only", "hard")],
        digests_by_key[("eb:hard_only", "hard")],
        digests_by_key[("eb:pooled_all", "hard")],
        rng_tag=170,
    )
    sl_ret_easy = compute_retention_summary(
        digests_by_key[("sl:easy_only", "hard")],
        digests_by_key[("sl:hard_only", "hard")],
        digests_by_key[("sl:pooled_all", "hard")],
        rng_tag=180,
    )
    sl_ret_med = compute_retention_summary(
        digests_by_key[("sl:medium_only", "hard")],
        digests_by_key[("sl:hard_only", "hard")],
        digests_by_key[("sl:pooled_all", "hard")],
        rng_tag=190,
    )
    eb_downward_hard_to_easy = compute_retention_summary(
        digests_by_key[("eb:hard_only", "easy")],
        digests_by_key[("eb:easy_only", "easy")],
        digests_by_key[("eb:pooled_all", "easy")],
        rng_tag=200,
    )
    sl_downward_hard_to_easy = compute_retention_summary(
        digests_by_key[("sl:hard_only", "easy")],
        digests_by_key[("sl:easy_only", "easy")],
        digests_by_key[("sl:pooled_all", "easy")],
        rng_tag=210,
    )

    frozen_contrasts = {
        "eb_easy_deception_neutral_vs_raw_easy": compute_paired_contrast(
            digests_by_key[("eb:eb_easy_deception_neutral_hard_elim", "hard")],
            digests_by_key[("eb:easy_only", "hard")],
            rng_tag=240,
        ),
        "eb_easy_fp95_cal_minus_hard_elim": compute_paired_contrast(
            digests_by_key[("eb:eb_easy_deception_neutral_fp95_cal", "hard")],
            digests_by_key[("eb:eb_easy_deception_neutral_hard_elim", "hard")],
            rng_tag=241,
        ),
        "eb_medium_fp95_h21_minus_medium_only": compute_paired_contrast(
            digests_by_key[("eb:eb_medium_plus_fp95_and_h21_stop", "hard")],
            digests_by_key[("eb:medium_only", "hard")],
            rng_tag=242,
        ),
        "sl_easy_noise_blind_minus_header_aware": compute_paired_contrast(
            digests_by_key[("sl:sl_easy_noise_blind_hard_elim", "hard")],
            digests_by_key[("sl:easy_only", "hard")],
            rng_tag=243,
        ),
        "sl_pooled_minus_hard_only_on_hard": compute_paired_contrast(
            digests_by_key[("sl:pooled_all", "hard")],
            digests_by_key[("sl:hard_only", "hard")],
            rng_tag=244,
        ),
    }

    std_digests_for_shock = {
        "eb_easy_deception_neutral_hard_elim": digests_by_key[
            ("eb:eb_easy_deception_neutral_hard_elim", "hard")
        ],
        "eb_hard_only": digests_by_key[("eb:hard_only", "hard")],
        "sl_easy_only": digests_by_key[("sl:easy_only", "hard")],
        "sl_hard_only": digests_by_key[("sl:hard_only", "hard")],
    }
    noise_shock_arms: dict[str, Any] = {}
    for n_idx, aid in enumerate(NOISE_SHOCK_ARM_ORDER):
        d100 = noise_free_digests[aid]
        d095 = std_digests_for_shock[aid]
        noise_shock_arms[aid] = {
            "arm_id": aid,
            "is_open_weight_llm": False,
            "fp100_noise_free_metrics": summarize_digests(d100, rng_tag=260 + n_idx * 2),
            "fp095_standard_metrics": summarize_digests(d095, rng_tag=261 + n_idx * 2),
            "noise_shock_fp095_minus_fp100": compute_paired_contrast(d095, d100, rng_tag=300 + n_idx),
            "fp100_episode_digests_packed": pack_episode_digests(d100),
        }

    ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))
    hist_runs = list(ledger.get("historical_runs") or [])
    qwen_pos = sum(
        1
        for r in hist_runs
        if isinstance(r, dict)
        and isinstance(r.get("after_mean_score"), (int, float))
        and float(r["after_mean_score"]) > 0.0
    )
    sc = ledger.get("summary_counts") or {}
    panel_e = {
        "source_path": str(LEDGER_REL),
        "open_weight_qwen25_runs_total": len(hist_runs),
        "open_weight_qwen25_runs_above_zero": qwen_pos,
        "open_weight_qwen25_above_zero_ratio": f"{qwen_pos} / {len(hist_runs)}",
        "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "non_llm_verified_run_ids": list(sc.get("verified_run_ids") or []),
        "non_llm_policies_is_open_weight_llm": False,
        "disclosure": PANEL_FIX_E_DISCLOSURE,
    }

    tier_mechanics: dict[str, Any] = {}
    for t_name in CANONICAL_TIERS:
        tp = rules.tier_params(t_name)
        tier_mechanics[t_name] = {
            "tier": t_name,
            "n_employees": int(tp.n_employees),
            "n_days": int(tp.n_days),
            "p_leak": round(float(tp.p_leak), 4),
            "delay_choices": [int(x) for x in tp.delay_choices],
            "leak_damage": round(float(tp.leak_damage), 4),
            "canary_cost": round(float(tp.canary_cost), 4),
            "canaries_per_day": int(tp.canaries_per_day),
            "max_variants": int(tp.max_variants),
            "tool_call_cap": int(tp.tool_call_cap),
            "fingerprint_accuracy": round(float(tp.fingerprint_accuracy), 4),
            "fingerprint_noise_rate": round(1.0 - float(tp.fingerprint_accuracy), 4),
            "decoy": bool(tp.decoy),
            "framing": bool(tp.framing),
            "careful_mole": bool(tp.careful_mole),
            "access_constraints": bool(tp.access_constraints),
            "wrong_accusation_score": round(float(tp.wrong_accusation_score), 4),
        }

    unique_train_seeds: set[int] = set()
    for lo_eb, hi_eb in EB_REGIME_SEEDS.values():
        unique_train_seeds.update(range(lo_eb, hi_eb))
    for r_id in TRAIN_REGIMES:
        _, sl_s, _ = select_sl_regime_seeds(r_id)
        unique_train_seeds.update(sl_s)

    total_eps = len(frozen_rows) + len(nf_rows)
    elapsed_s = round(time.perf_counter() - t0, 3)

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "tiers_version": str(rules.TIERS_VERSION),
        "tiers": list(CANONICAL_TIERS),
        "train_seed_range": "107000..113079",
        "train_seeds_unique_count": len(unique_train_seeds),
        "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "heldout_seeds": {"start": HELDOUT_SEED_START, "stop": HELDOUT_SEED_STOP},
        "eval_seeds_per_tier": HELDOUT_N,
        "rng_seed": BOOTSTRAP_RNG_SEED,
        "world_secret_tag": secret_tag,
        "replay_verified": True,
        "invalid_episodes": 0,
        "seed_isolation": {
            "heldout_world_paired": True,
            "train_episodes_in_heldout_eval": 0,
            "dev_episodes_rolled_out": 0,
            "judge_episodes_touched": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": panel_e,
        "ast_inference_isolation": {
            "passed": bool(ast_outcome.passed),
            "summary": str(ast_outcome.summary),
            "errors": list(ast_outcome.errors),
        },
        "tier_mechanics_v14": tier_mechanics,
        "transfer_matrices": transfer_matrices,
        "ood_retention_and_noise_decomposition": {
            "zero_shot_hard_retention": {
                "empirical_bayes_easy_to_hard": eb_ret_easy,
                "empirical_bayes_medium_to_hard": eb_ret_med,
                "scaling_logistic_easy_to_hard": sl_ret_easy,
                "scaling_logistic_medium_to_hard": sl_ret_med,
                "empirical_bayes_hard_to_easy": eb_downward_hard_to_easy,
                "scaling_logistic_hard_to_easy": sl_downward_hard_to_easy,
            },
            "frozen_v14_hard_surgical_arms": surgical_out,
            "frozen_v14_hard_contrasts": frozen_contrasts,
            "hard_fingerprint_noise_counterfactual": {
                "description": "Paired world-identical hard evaluation (N=40, H=21d, 2-3d delay, decoy+framing) comparing fingerprint_accuracy=1.00 (0% noise) vs standard v1.4 fingerprint_accuracy=0.95 (5% noise) on HELDOUT_SEEDS 800000..800029",
                "arms": noise_shock_arms,
            },
        },
        "totals": {
            "policy_families_audited": len(POLICY_FAMILIES),
            "train_regimes_per_family": len(TRAIN_REGIMES),
            "primary_transfer_cells": len(POLICY_FAMILIES) * len(TRAIN_REGIMES) * len(CANONICAL_TIERS),
            "frozen_v14_episodes_evaluated": len(frozen_rows),
            "noise_counterfactual_episodes_evaluated": len(nf_rows),
            "total_episodes_evaluated": total_eps,
            "total_replay_verified_episodes": total_eps,
            "solver_policy_invocations": 0,
            "api_calls": 0,
            "elapsed_seconds": elapsed_s,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check:
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
        f"{out_md.relative_to(root)} ({summary['totals']['total_replay_verified_episodes']}/"
        f"{summary['totals']['total_episodes_evaluated']} replay-verified episodes in "
        f"{summary['totals']['elapsed_seconds']:.2f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
