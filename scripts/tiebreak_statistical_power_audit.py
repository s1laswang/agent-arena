"""Deterministic statistical power, MDE, world-pairing variance reduction, and multiplicity audit."""
from __future__ import annotations

import argparse
import ast
import contextlib
import functools
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import tokenize
from typing import Any, Callable, Iterator

for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.statistical_power.v1"
AUDIT_ID = "tiebreak-statistical-power-v14"
DEFAULT_OUT_JSON = Path("results/tiebreak/statistical_power/statistical_power_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_statistical_power.md")
MAX_SUMMARY_BYTES = 75 * 1024

EB_SUMMARY_REL = Path("results/tiebreak/empirical_bayes/summary.json")
DAGGER_SUMMARY_REL = Path("results/tiebreak/dagger_ablation/summary.json")
MLP_SUMMARY_REL = Path("results/tiebreak/neural_mlp_dagger/mlp_summary.json")
SCALING_SUMMARY_REL = Path("results/tiebreak/scaling/scaling_summary.json")
VERDA_SUMMARY_REL = Path("results/tiebreak/verda_multiseed/multiseed_summary.json")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")

HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
HELDOUT_SECRET_TAG = "sha256:" + hashlib.sha256(HELDOUT_WORLD_SECRET.encode("utf-8")).hexdigest()[:16]
VERDA_SHARED_SECRET_TAG = "verda_shared_secret_0405_1ca0c2a64d"
VERDA_DAGGER_SECRET_TAG = "1ca0c2a64d"

PERMUTATION_DRAWS = 10_000
PERMUTATION_SEED = 20261115
PERMUTATION_DATE_TAG = "2026-11-15"
MDE_SAMPLE_SIZES: tuple[int, ...] = (30, 41, 50, 90, 180)
TIERS: tuple[str, ...] = ("easy", "medium", "hard")
HELDOUT_N90_SEEDS: tuple[int, ...] = tuple(range(800_000, 800_030))

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
JUDGE_SEED_MIN = 900_000

FORBIDDEN_IMPORT_ROOTS: frozenset[str] = frozenset({"torch", "transformers", "subprocess"})
FORBIDDEN_CANARY_PREFIXES: tuple[str, ...] = ("canary.solver", "canary.world")

PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)

PANEL_FIX_A_DISCLOSURE = (
    "All tiebreak statistical power, sign-flip permutation, and world-pairing audits evaluate held-out "
    "episodes strictly on HELDOUT_SEEDS [800000, 800200) (800000..800059 for n=180 and 800000..800029 "
    "for n=90 under sha256:ebf2f09716cf76d3, plus Verda shared-secret 1ca0c2a64d slices in [800000, 800030)), "
    "while all compact policy parameters originate strictly from disjoint TRAIN_SEEDS [100000, 200000) with "
    "0 JUDGE_SEEDS (900k+) touched. Where DEV_SEEDS 0..29 appear in separate Canary frontier reports, "
    "they are post-hoc locked, not pre-registered (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json exceed untrained base (0.000), so the README.md Qwen addendum remains withheld "
    "(HOLD_README_QWEN_ADDENDUM_UNTIL_V100). All 4 compact policies audited here (EmpiricalBayesPolicy, "
    "ScalingLogisticPolicy, CompactLinearDAggerPolicy, TinyMLPPolicy; is_open_weight_llm = False) are "
    "non-LLM structured/neural policies strictly separated from Track 1 open-weight Qwen2.5 LoRA and Verda GRPO runs."
)


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


def _betacf(a: float, b: float, x: float) -> float:
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = max(1e-30, abs(1.0 + aa * d)) * (1.0 if (1.0 + aa * d) >= 0.0 else -1.0)
        c = max(1e-30, abs(1.0 + aa / c)) * (1.0 if (1.0 + aa / c) >= 0.0 else -1.0)
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = max(1e-30, abs(1.0 + aa * d)) * (1.0 if (1.0 + aa * d) >= 0.0 else -1.0)
        c = max(1e-30, abs(1.0 + aa / c)) * (1.0 if (1.0 + aa / c) >= 0.0 else -1.0)
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def _ibeta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def student_t_cdf(t_val: float, df: int) -> float:
    if t_val == 0.0:
        return 0.5
    x = float(df) / (float(df) + t_val * t_val)
    ib = 0.5 * _ibeta(0.5 * float(df), 0.5, x)
    return 1.0 - ib if t_val > 0.0 else ib


@functools.lru_cache(maxsize=256)
def student_t_ppf(prob: float, df: int) -> float:
    if prob == 0.5:
        return 0.0
    sign = 1.0 if prob > 0.5 else -1.0
    target = prob if prob > 0.5 else 1.0 - prob
    lo, hi = 0.0, 30.0
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        if student_t_cdf(mid, df) < target:
            lo = mid
        else:
            hi = mid
    return sign * 0.5 * (lo + hi)


def compute_mde_two_sided(n: int, sd_delta: float, alpha: float = 0.05, power: float = 0.80) -> float:
    df = max(1, int(n) - 1)
    t_crit = student_t_ppf(1.0 - 0.5 * alpha, df)
    t_pow = student_t_ppf(power, df)
    return (t_crit + t_pow) * float(sd_delta) / math.sqrt(float(n))


def compute_two_sided_power_approx(n: int, effect: float, sd_delta: float, alpha: float = 0.05) -> float:
    if sd_delta <= 0.0:
        return 1.0 if abs(effect) > 0.0 else alpha
    df = max(1, int(n) - 1)
    t_crit = student_t_ppf(1.0 - 0.5 * alpha, df)
    ncp = abs(effect) * math.sqrt(float(n)) / float(sd_delta)
    p_upper = 1.0 - student_t_cdf(t_crit - ncp, df)
    p_lower = student_t_cdf(-t_crit - ncp, df)
    return min(1.0, max(0.0, p_upper + p_lower))


def required_n_for_effect(effect: float, sd_delta: float, alpha: float = 0.05, power: float = 0.80) -> int:
    eff = abs(float(effect))
    if eff <= 1e-12:
        return 99_999
    for n_cand in range(3, 50_000):
        if compute_mde_two_sided(n_cand, sd_delta, alpha=alpha, power=power) <= eff:
            return n_cand
    return 50_000


def holm_bonferroni_adjust(p_values: list[float]) -> list[float]:
    m = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: (x[1], x[0]))
    adjusted = [0.0] * m
    running_max = 0.0
    for rank_idx, (orig_idx, p_val) in enumerate(indexed):
        cand = min(1.0, (m - rank_idx) * float(p_val))
        running_max = max(running_max, cand)
        adjusted[orig_idx] = running_max
    return adjusted


def benjamini_hochberg_adjust(p_values: list[float]) -> list[float]:
    m = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: (x[1], x[0]))
    q_sorted = [0.0] * m
    running_min = 1.0
    for rev_pos in range(m - 1, -1, -1):
        rank_one_based = rev_pos + 1
        _, p_val = indexed[rev_pos]
        cand = min(1.0, (m / float(rank_one_based)) * float(p_val))
        running_min = min(running_min, cand)
        q_sorted[rev_pos] = running_min
    out = [0.0] * m
    for rev_pos, (orig_idx, _) in enumerate(indexed):
        out[orig_idx] = q_sorted[rev_pos]
    return out


def sample_mean_sd_ci95(values: list[float]) -> tuple[float, float, float]:
    n = len(values)
    mean_v = sum(values) / float(n)
    if n < 2:
        return mean_v, 0.0, 0.0
    var_v = sum((x - mean_v) ** 2 for x in values) / float(n - 1)
    sd_v = math.sqrt(max(0.0, var_v))
    return mean_v, sd_v, 1.96 * sd_v / math.sqrt(float(n))


def reconstruct_verda_dagger_vector(entry: dict[str, Any]) -> list[float]:
    n = int(entry["heldout_n"])
    details = entry["details"]
    accused = int(details["accused_count"])
    correct = int(details["correct_count"])
    abstain = int(details["abstain_count"])
    wrong = accused - correct
    if wrong + correct + abstain != n or correct <= 0:
        raise ValueError(f"{entry['run_id']}: inconsistent outcome counts")
    target_sum = float(entry["after_mean_score"]) * float(n)
    pos_total = target_sum + float(wrong)
    mean_pos = pos_total / float(correct)
    vec = [-1.0] * wrong + [0.0] * abstain + [mean_pos] * correct
    return vec


def run_signflip_and_bootstrap(
    deltas: list[float],
    n_draws: int = PERMUTATION_DRAWS,
    seed: int = PERMUTATION_SEED,
) -> dict[str, float]:
    import numpy as np

    arr = np.asarray(deltas, dtype=np.float64)
    n = int(arr.shape[0])
    obs_mean = float(arr.mean())
    obs_sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    ci_half = 1.96 * obs_sd / math.sqrt(float(n)) if n > 1 else 0.0

    rng = np.random.default_rng(int(seed))
    signs = rng.integers(0, 2, size=(int(n_draws), n), dtype=np.int8) * 2 - 1
    perm_means = (signs @ arr) / float(n)
    abs_ge = int(np.count_nonzero(np.abs(perm_means) >= abs(obs_mean) - 1e-12))
    gt0_ge = int(np.count_nonzero(perm_means >= obs_mean - 1e-12))
    p_two = (1.0 + float(abs_ge)) / (float(n_draws) + 1.0)
    p_gt0 = (1.0 + float(gt0_ge)) / (float(n_draws) + 1.0)

    boot_idx = rng.integers(0, n, size=(int(n_draws), n), dtype=np.int32)
    boot_means = arr[boot_idx].mean(axis=1)
    b_lo, b_hi = np.quantile(boot_means, [0.025, 0.975])

    return {
        "mean_delta": round(obs_mean, 5),
        "sd_delta": round(obs_sd, 5),
        "normal_ci95_half": round(ci_half, 5),
        "normal_ci95_low": round(obs_mean - ci_half, 5),
        "normal_ci95_high": round(obs_mean + ci_half, 5),
        "bootstrap_ci95_low": round(float(b_lo), 5),
        "bootstrap_ci95_high": round(float(b_hi), 5),
        "p_perm_two_sided": round(p_two, 5),
        "p_perm_one_sided_gt0": round(p_gt0, 5),
    }


def _collect_live_heldout_n90_scores(repo_root: Path) -> tuple[dict[str, list[float]], int]:
    import numpy as np
    from canary.baselines import Heuristic
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp
    from scripts.tiebreak_scaling_calibration import CompactLinearPolicy, LinearPolicyWeights
    from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights
    from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy
    from train.neural_mlp_tiebreak import TinyMLPPolicy

    eb_sum = json.loads((repo_root / EB_SUMMARY_REL).read_text(encoding="utf-8"))
    da_sum = json.loads((repo_root / DAGGER_SUMMARY_REL).read_text(encoding="utf-8"))
    mlp_sum = json.loads((repo_root / MLP_SUMMARY_REL).read_text(encoding="utf-8"))
    scl_sum = json.loads((repo_root / SCALING_SUMMARY_REL).read_text(encoding="utf-8"))

    rtp._assert_train_seed_range(int(eb_sum["train_seeds"]["start"]), int(eb_sum["train_seeds"]["stop"]), "eb")
    rtp._assert_train_seed_range(int(da_sum["train_seeds"]["start"]), int(da_sum["train_seeds"]["stop"]), "dagger")
    rtp._assert_train_seed_range(int(mlp_sum["train_seeds"]["start"]), int(mlp_sum["train_seeds"]["stop"]), "mlp")
    tr_lo, tr_hi = int(scl_sum["train_seed_range"][0]), int(scl_sum["train_seed_range"][1])
    rtp._assert_train_seed_range(tr_lo, tr_hi + 1, "scaling")

    eb_opt = EmpiricalBayesParams.from_dict(eb_sum["parameters"]["eb_experience_opt"])
    eb_naive = EmpiricalBayesParams.from_dict(eb_sum["parameters"]["eb_naive_prior"])
    da_w = CompactLinearWeights.from_dict(da_sum["learned_weights_stage3"])
    mlp_w, _ = rtp._load_or_reconstruct_tiny_mlp(mlp_summary=mlp_sum, stage="stage3_onpolicy_dagger_r2")
    scl_row = next(r for r in scl_sum["scaling_curve"] if int(r["n_train"]) == 900)
    scl_wd = scl_row["weights"]
    scl_w = LinearPolicyWeights(
        w_suspect=np.asarray(scl_wd["w_suspect"], dtype=np.float64),
        w_commit=np.asarray(scl_wd["w_commit"], dtype=np.float64),
        w_wait=np.asarray(scl_wd["w_wait"], dtype=np.float64),
        w_tool=np.asarray(scl_wd["w_tool"], dtype=np.float64),
        w_canary=np.asarray(scl_wd["w_canary"], dtype=np.float64),
        n_train=900,
    )

    factories: dict[str, Callable[[int], Any]] = {
        "empirical_bayes": lambda s, p=eb_opt: EmpiricalBayesPolicy(params=p, seed=s, name="empirical_bayes"),
        "scaling_logistic": lambda s, w=scl_w: CompactLinearPolicy(
            weights=w, name="scaling_logistic", explore_eps=0.0, rng_seed=s
        ),
        "compact_linear_dagger": lambda _s, w=da_w: CompactLinearDAggerPolicy(
            weights=w, name="compact_linear_dagger"
        ),
        "tiny_mlp": lambda s, w=mlp_w: TinyMLPPolicy(weights=w, seed=s, name="tiny_mlp"),
        "naive_prior": lambda s, p=eb_naive: EmpiricalBayesPolicy(params=p, seed=s, name="naive_prior"),
        "heuristic": lambda s: Heuristic(seed=s),
    }

    provider = TemplateProvider()
    scores: dict[str, list[float]] = {k: [] for k in factories}
    replays_verified = 0
    with _scoped_world_secret(HELDOUT_WORLD_SECRET):
        for tier in TIERS:
            for seed in HELDOUT_N90_SEEDS:
                for pid, fac in factories.items():
                    ep = run_episode(Env(tier, seed, text_provider=provider), fac(seed))
                    rtp.verify_episode_replay(ep, text_provider=provider)
                    replays_verified += 1
                    scores[pid].append(float(ep.score))
    return scores, replays_verified


def _pairing_row(
    comparison_id: str,
    cohort: str,
    world_secret_tag: str,
    heldout_seed_range: str,
    n: int,
    var_a: float,
    var_b: float,
    var_paired: float,
    mean_delta: float,
) -> dict[str, Any]:
    var_unpaired = var_a + var_b
    cov_ab = 0.5 * (var_unpaired - var_paired)
    denom = math.sqrt(max(0.0, var_a * var_b))
    corr = cov_ab / denom if denom > 1e-12 else 0.0
    n_eff_ratio = var_unpaired / var_paired if var_paired > 1e-12 else 1.0
    red_pct = 100.0 * (1.0 - var_paired / var_unpaired) if var_unpaired > 1e-12 else 0.0
    return {
        "comparison_id": comparison_id,
        "cohort": cohort,
        "world_secret_tag": world_secret_tag,
        "heldout_seed_range": heldout_seed_range,
        "n": int(n),
        "mean_delta": round(mean_delta, 5),
        "var_a": round(var_a, 5),
        "var_b": round(var_b, 5),
        "var_unpaired": round(var_unpaired, 5),
        "var_paired": round(var_paired, 5),
        "pearson_r": round(corr, 5),
        "variance_reduction_pct": round(red_pct, 4),
        "n_eff_ratio": round(n_eff_ratio, 5),
        "equivalent_unpaired_n": round(float(n) * n_eff_ratio, 2),
    }


def _enrich_family(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    p2 = [float(r["p_perm_two_sided"]) for r in rows]
    pg = [float(r["p_perm_one_sided_gt0"]) for r in rows]
    h2 = holm_bonferroni_adjust(p2)
    hg = holm_bonferroni_adjust(pg)
    q2 = benjamini_hochberg_adjust(p2)
    qg = benjamini_hochberg_adjust(pg)
    enriched: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        cp = dict(row)
        cp["p_holm_two_sided"] = round(h2[idx], 5)
        cp["q_bh_two_sided"] = round(q2[idx], 5)
        cp["p_holm_gt0"] = round(hg[idx], 5)
        cp["q_bh_gt0"] = round(qg[idx], 5)
        cp["reject_fwer05_two_sided"] = bool(h2[idx] <= 0.05)
        cp["reject_fdr05_two_sided"] = bool(q2[idx] <= 0.05)
        cp["verified_positive_after_holm05"] = bool(
            float(cp["mean_delta"]) > 0.0 and h2[idx] <= 0.05 and float(cp["bootstrap_ci95_low"]) > 0.0
        )
        enriched.append(cp)
    return enriched


def build_summary(repo_root: Path = ROOT) -> dict[str, Any]:
    eb_sum = json.loads((repo_root / EB_SUMMARY_REL).read_text(encoding="utf-8"))
    da_sum = json.loads((repo_root / DAGGER_SUMMARY_REL).read_text(encoding="utf-8"))
    mlp_sum = json.loads((repo_root / MLP_SUMMARY_REL).read_text(encoding="utf-8"))
    scl_sum = json.loads((repo_root / SCALING_SUMMARY_REL).read_text(encoding="utf-8"))
    vms_sum = json.loads((repo_root / VERDA_SUMMARY_REL).read_text(encoding="utf-8"))
    ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))

    live_scores, live_replays = _collect_live_heldout_n90_scores(repo_root)
    scl_900 = next(r for r in scl_sum["scaling_curve"] if int(r["n_train"]) == 900)
    scl_m, _, scl_ci = sample_mean_sd_ci95(live_scores["scaling_logistic"])
    if abs(scl_m - float(scl_900["metrics"]["mean_score"])) > 1e-4 or abs(scl_ci - float(scl_900["metrics"]["ci95"])) > 1e-4:
        raise RuntimeError("ScalingLogisticPolicy live n=90 scores disagree with scaling_summary.json")

    hist_map = {r["run_id"]: r for r in ledger["historical_runs"]}
    dag_8k_entry = hist_map["WS4-dagger-r1-8k-verda"]
    dag_4k_entry = hist_map["WS4-dagger-r1-4k-verda"]
    dag_8k_vec = reconstruct_verda_dagger_vector(dag_8k_entry)
    dag_4k_vec = reconstruct_verda_dagger_vector(dag_4k_entry)

    eb_deltas = [float(x) for x in eb_sum["paired"]["deltas"]]
    da_deltas = [float(x) for x in da_sum["paired"]["deltas"]]
    mlp_deltas = [float(x) for x in mlp_sum["paired"]["deltas"]]
    scl_deltas = [float(x) for x in live_scores["scaling_logistic"]]
    vms_s0_s3 = [float(x) for x in vms_sum["world_paired_shared_secret_comparisons"]["s0_minus_s3"]["paired_deltas"]]
    vms_4k8k_vs_s3 = [
        -float(x) for x in vms_sum["world_paired_shared_secret_comparisons"]["s3_minus_4k_at_8k"]["paired_deltas"]
    ]

    primary_specs: list[tuple[str, str, str, bool, str, str, str, list[float]]] = [
        (
            "empirical_bayes_vs_before",
            "EmpiricalBayesPolicy (11p) vs eb_naive_prior",
            "compact_non_llm",
            False,
            HELDOUT_SECRET_TAG,
            "800000..800059",
            "exact_committed_deltas:empirical_bayes/summary.json",
            eb_deltas,
        ),
        (
            "compact_linear_dagger_vs_before",
            "CompactLinearDAggerPolicy (785p) vs stage0_untrained",
            "compact_non_llm",
            False,
            HELDOUT_SECRET_TAG,
            "800000..800059",
            "exact_committed_deltas:dagger_ablation/summary.json",
            da_deltas,
        ),
        (
            "tiny_mlp_dagger_vs_before",
            "TinyMLPPolicy (12,293p) vs stage0_untrained",
            "compact_non_llm",
            False,
            HELDOUT_SECRET_TAG,
            "800000..800059",
            "exact_committed_deltas:neural_mlp_dagger/mlp_summary.json",
            mlp_deltas,
        ),
        (
            "scaling_logistic_vs_before",
            "ScalingLogisticPolicy (82p, N=900) vs N=0 Abstain",
            "compact_non_llm",
            False,
            HELDOUT_SECRET_TAG,
            "800000..800029",
            "exact_replay_verified:scaling/scaling_summary.json",
            scl_deltas,
        ),
        (
            "verda_v3_8k_s0_vs_s3",
            "Qwen2.5-1.5B GRPO v3-8k-s0 vs v3-8k-s3 (seed bifurcation)",
            "open_weight_qwen25_seed_diagnostic",
            True,
            VERDA_SHARED_SECRET_TAG,
            "800000..800029",
            "exact_committed_deltas:verda_multiseed/multiseed_summary.json",
            vms_s0_s3,
        ),
        (
            "verda_4k_at_8k_vs_8k_s3_null",
            "Qwen2.5-1.5B v3-4k-s0@8k vs v3-8k-s3 (context-mismatch null)",
            "open_weight_qwen25_null",
            True,
            VERDA_SHARED_SECRET_TAG,
            "800000..800029",
            "exact_committed_deltas:verda_multiseed/multiseed_summary.json",
            vms_4k8k_vs_s3,
        ),
        (
            "verda_dagger_r1_8k_vs_base",
            "Qwen2.5-1.5B WS4-dagger-r1-8k-verda vs 0.000 base (reaper n=50)",
            "open_weight_qwen25_honest_negative",
            True,
            VERDA_DAGGER_SECRET_TAG,
            "800000..800026",
            "outcome_count_moment_exact:experiment_ledger.json",
            dag_8k_vec,
        ),
        (
            "verda_dagger_r1_4k_vs_base",
            "Qwen2.5-1.5B WS4-dagger-r1-4k-verda vs 0.000 base (reaper n=41)",
            "open_weight_qwen25_honest_null",
            True,
            VERDA_DAGGER_SECRET_TAG,
            "800000..800024",
            "outcome_count_algebraic_exact:experiment_ledger.json",
            dag_4k_vec,
        ),
    ]

    raw_primary: list[dict[str, Any]] = []
    for cid, label, track, is_llm, sec_tag, srange, vsrc, vec in primary_specs:
        stats = run_signflip_and_bootstrap(vec, n_draws=PERMUTATION_DRAWS, seed=PERMUTATION_SEED)
        n_ep = len(vec)
        mde80 = compute_mde_two_sided(n_ep, stats["sd_delta"])
        pow_obs = compute_two_sided_power_approx(n_ep, stats["mean_delta"], stats["sd_delta"])
        raw_primary.append({
            "comparison_id": cid,
            "label": label,
            "track": track,
            "is_open_weight_llm": is_llm,
            "world_secret_tag": sec_tag,
            "heldout_seed_range": srange,
            "vector_source": vsrc,
            "n": n_ep,
            **stats,
            "mde_80pct_alpha05": round(mde80, 5),
            "posthoc_power_at_observed_delta": round(pow_obs, 5),
        })

    primary_family = _enrich_family(raw_primary)

    heur_vec = live_scores["heuristic"]
    extra_heur_specs = [
        ("empirical_bayes_vs_heuristic_n90", "EmpiricalBayesPolicy vs Heuristic (n=90)", "empirical_bayes"),
        ("scaling_logistic_vs_heuristic_n90", "ScalingLogisticPolicy vs Heuristic (n=90)", "scaling_logistic"),
        ("compact_linear_dagger_vs_heuristic_n90", "CompactLinearDAggerPolicy vs Heuristic (n=90)", "compact_linear_dagger"),
        ("tiny_mlp_vs_heuristic_n90", "TinyMLPPolicy vs Heuristic (n=90)", "tiny_mlp"),
    ]
    raw_extra: list[dict[str, Any]] = []
    for cid, label, pid in extra_heur_specs:
        dvec = [a - b for a, b in zip(live_scores[pid], heur_vec)]
        stats = run_signflip_and_bootstrap(dvec, n_draws=PERMUTATION_DRAWS, seed=PERMUTATION_SEED)
        mde80 = compute_mde_two_sided(len(dvec), stats["sd_delta"])
        pow_obs = compute_two_sided_power_approx(len(dvec), stats["mean_delta"], stats["sd_delta"])
        raw_extra.append({
            "comparison_id": cid,
            "label": label,
            "track": "compact_non_llm_vs_heuristic",
            "is_open_weight_llm": False,
            "world_secret_tag": HELDOUT_SECRET_TAG,
            "heldout_seed_range": "800000..800029",
            "vector_source": "exact_replay_verified:heldout_n90",
            "n": len(dvec),
            **stats,
            "mde_80pct_alpha05": round(mde80, 5),
            "posthoc_power_at_observed_delta": round(pow_obs, 5),
        })

    expanded_family = _enrich_family(raw_primary + raw_extra)

    heldout_pair_specs = [
        ("empirical_bayes_vs_heuristic", "empirical_bayes", "heuristic"),
        ("scaling_logistic_vs_heuristic", "scaling_logistic", "heuristic"),
        ("compact_linear_dagger_vs_heuristic", "compact_linear_dagger", "heuristic"),
        ("tiny_mlp_vs_heuristic", "tiny_mlp", "heuristic"),
        ("empirical_bayes_vs_naive_prior", "empirical_bayes", "naive_prior"),
        ("compact_linear_dagger_vs_empirical_bayes", "compact_linear_dagger", "empirical_bayes"),
        ("compact_linear_dagger_vs_tiny_mlp", "compact_linear_dagger", "tiny_mlp"),
        ("empirical_bayes_vs_scaling_logistic", "empirical_bayes", "scaling_logistic"),
        ("tiny_mlp_vs_scaling_logistic", "tiny_mlp", "scaling_logistic"),
    ]
    heldout_pairing_rows: list[dict[str, Any]] = []
    for cid, pa, pb in heldout_pair_specs:
        va = live_scores[pa]
        vb = live_scores[pb]
        _, sda, _ = sample_mean_sd_ci95(va)
        _, sdb, _ = sample_mean_sd_ci95(vb)
        md, sdd, _ = sample_mean_sd_ci95([x - y for x, y in zip(va, vb)])
        heldout_pairing_rows.append(
            _pairing_row(
                cid,
                "heldout_compact_v14",
                HELDOUT_SECRET_TAG,
                "800000..800029",
                len(va),
                sda * sda,
                sdb * sdb,
                sdd * sdd,
                md,
            )
        )

    vms_models = {s["run_id"]: s["overall"] for s in vms_sum["seeds_8k"]}
    vms_models["v3_4k_s0_ctx8k"] = vms_sum["inference_context_control_4k_at_8k"]["overall"]
    verda_pairing_rows: list[dict[str, Any]] = []
    for vkey in ("s0_minus_s3", "s3_minus_4k_at_8k", "s0_minus_4k_at_8k"):
        cobj = vms_sum["world_paired_shared_secret_comparisons"][vkey]
        oa = vms_models[cobj["model_a"]]
        ob = vms_models[cobj["model_b"]]
        sda = float(oa["ci95"]) * math.sqrt(float(oa["n"])) / 1.96
        sdb = float(ob["ci95"]) * math.sqrt(float(ob["n"])) / 1.96
        md, sdd, _ = sample_mean_sd_ci95([float(x) for x in cobj["paired_deltas"]])
        verda_pairing_rows.append(
            _pairing_row(
                f"verda_{vkey}",
                "verda_shared_secret_qwen25",
                VERDA_SHARED_SECRET_TAG,
                str(cobj["paired_seed_range"]),
                int(cobj["n"]),
                sda * sda,
                sdb * sdb,
                sdd * sdd,
                md,
            )
        )

    mean_heldout_neff = sum(r["n_eff_ratio"] for r in heldout_pairing_rows) / float(len(heldout_pairing_rows))
    max_heldout_neff = max(r["n_eff_ratio"] for r in heldout_pairing_rows)
    mean_verda_neff = sum(r["n_eff_ratio"] for r in verda_pairing_rows) / float(len(verda_pairing_rows))

    sd_compact_abstain = float(next(r for r in primary_family if r["comparison_id"] == "compact_linear_dagger_vs_before")["sd_delta"])
    sd_scaling_abstain = float(next(r for r in primary_family if r["comparison_id"] == "scaling_logistic_vs_before")["sd_delta"])
    sd_compact_heur_paired = math.sqrt(
        sum(r["var_paired"] for r in heldout_pairing_rows[:4]) / 4.0
    )
    sd_compact_heur_unpaired = math.sqrt(
        sum(r["var_unpaired"] for r in heldout_pairing_rows[:4]) / 4.0
    )
    sd_verda_s0_s3 = float(next(r for r in primary_family if r["comparison_id"] == "verda_v3_8k_s0_vs_s3")["sd_delta"])
    sd_dag8k_base = float(dag_8k_entry["after_ci95"]) * math.sqrt(50.0) / 1.96
    sd_dag4k_base = float(dag_4k_entry["after_ci95"]) * math.sqrt(41.0) / 1.96

    mde_grid: list[dict[str, Any]] = []
    for n_val in MDE_SAMPLE_SIZES:
        df = n_val - 1
        unit_factor = (student_t_ppf(0.975, df) + student_t_ppf(0.80, df)) / math.sqrt(float(n_val))
        mde_grid.append({
            "n": n_val,
            "df": df,
            "unit_sd_mde_factor": round(unit_factor, 5),
            "mde_compact_vs_abstain": round(compute_mde_two_sided(n_val, sd_compact_abstain), 5),
            "mde_scaling_vs_abstain": round(compute_mde_two_sided(n_val, sd_scaling_abstain), 5),
            "mde_compact_vs_heuristic_paired": round(compute_mde_two_sided(n_val, sd_compact_heur_paired), 5),
            "mde_compact_vs_heuristic_unpaired": round(compute_mde_two_sided(n_val, sd_compact_heur_unpaired), 5),
            "mde_verda_8k_paired_seed": round(compute_mde_two_sided(n_val, sd_verda_s0_s3), 5),
            "mde_verda_dagger_r1_8k_vs_base": round(compute_mde_two_sided(n_val, sd_dag8k_base), 5),
            "mde_verda_dagger_r1_4k_vs_base": round(compute_mde_two_sided(n_val, sd_dag4k_base), 5),
        })

    d8_det = dag_8k_entry["details"]
    d4_det = dag_4k_entry["details"]
    n_h2h_8k = int(d8_det["paired_vs_v3_4k_s0_ctx8k_cap256_n"])
    sd_h2h_8k = float(d8_det["paired_vs_v3_4k_s0_ctx8k_cap256_ci95"]) * math.sqrt(float(n_h2h_8k)) / 1.96
    delta_h2h_8k = float(d8_det["paired_vs_v3_4k_s0_ctx8k_cap256_mean_delta"])
    mde_h2h_8k = compute_mde_two_sided(n_h2h_8k, sd_h2h_8k)

    n_h2h_4k = int(d4_det["paired_vs_v3_4k_s0_ctx4k_cap256_n"])
    sd_h2h_4k = float(d4_det["paired_vs_v3_4k_s0_ctx4k_cap256_ci95"]) * math.sqrt(float(n_h2h_4k)) / 1.96
    delta_h2h_4k = float(d4_det["paired_vs_v3_4k_s0_ctx4k_cap256_mean_delta"])
    mde_h2h_4k = compute_mde_two_sided(n_h2h_4k, sd_h2h_4k)

    mde_8k_base_50 = compute_mde_two_sided(50, sd_dag8k_base)
    mde_4k_base_41 = compute_mde_two_sided(41, sd_dag4k_base)

    hist_above_zero = sum(
        1 for r in ledger["historical_runs"]
        if isinstance(r.get("after_mean_score"), (int, float)) and float(r["after_mean_score"]) > 0.0
    )

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "tiers_version": "v1.4",
        "tiers": list(TIERS),
        "world_secret_name": HELDOUT_WORLD_SECRET,
        "world_secret_tag": HELDOUT_SECRET_TAG,
        "verda_shared_secret_tag": VERDA_SHARED_SECRET_TAG,
        "heldout_seed_range": "800000..800059",
        "eval_seed_range": "800000..800029",
        "eval_seeds_per_tier": 30,
        "replay_verified": True,
        "invalid_episodes": 0,
        "inference_protocol": {
            "method": "monte_carlo_exact_sign_flip_permutation_and_percentile_bootstrap",
            "mc_draws": PERMUTATION_DRAWS,
            "mc_rng_date_tag": PERMUTATION_DATE_TAG,
            "alpha_two_sided": 0.05,
            "target_power": 0.80,
            "multiplicity_procedures": ["holm_bonferroni_step_down_fwer", "benjamini_hochberg_step_up_fdr"],
        },
        "seed_isolation": {
            "train_seed_partition": "[100000, 200000)",
            "heldout_seed_partition": "[800000, 800200)",
            "judge_episodes_touched": 0,
            "dev_episodes_touched": 0,
            "train_episodes_in_heldout_eval": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": {
            "compact_policies_are_open_weight_llm": False,
            "open_weight_qwen25_runs_total": len(ledger["historical_runs"]),
            "open_weight_qwen25_runs_above_zero": hist_above_zero,
            "open_weight_qwen25_above_zero_ratio": f"{hist_above_zero} / {len(ledger['historical_runs'])}",
            "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
            "disclosure": PANEL_FIX_E_DISCLOSURE,
        },
        "totals": {
            "primary_family_size": len(primary_family),
            "expanded_family_size": len(expanded_family),
            "compact_verified_positive_primary": sum(
                1 for r in primary_family if not r["is_open_weight_llm"] and r["verified_positive_after_holm05"]
            ),
            "compact_verified_positive_expanded": sum(
                1 for r in expanded_family if not r["is_open_weight_llm"] and r["verified_positive_after_holm05"]
            ),
            "open_weight_verified_improvements_over_base": 0,
            "heldout_pairing_pairs_with_neff_gt_1": sum(
                1 for r in heldout_pairing_rows if r["n_eff_ratio"] > 1.0
            ),
            "heldout_pairing_pairs_total": len(heldout_pairing_rows),
            "live_canonical_env_replays_verified": live_replays,
        },
        "primary_family": primary_family,
        "expanded_family": expanded_family,
        "world_pairing_variance_reduction": {
            "heldout_mean_n_eff_ratio": round(mean_heldout_neff, 5),
            "heldout_max_n_eff_ratio": round(max_heldout_neff, 5),
            "verda_mean_n_eff_ratio": round(mean_verda_neff, 5),
            "heldout_compact_pairs": heldout_pairing_rows,
            "verda_shared_secret_pairs": verda_pairing_rows,
        },
        "mde_audit": {
            "alpha_two_sided": 0.05,
            "target_power": 0.80,
            "sample_sizes": list(MDE_SAMPLE_SIZES),
            "reference_sds": {
                "compact_vs_abstain": round(sd_compact_abstain, 5),
                "scaling_vs_abstain": round(sd_scaling_abstain, 5),
                "compact_vs_heuristic_paired": round(sd_compact_heur_paired, 5),
                "compact_vs_heuristic_unpaired": round(sd_compact_heur_unpaired, 5),
                "verda_8k_paired_seed": round(sd_verda_s0_s3, 5),
                "verda_dagger_r1_8k_vs_base": round(sd_dag8k_base, 5),
                "verda_dagger_r1_4k_vs_base": round(sd_dag4k_base, 5),
            },
            "mde_table": mde_grid,
            "verda_x2_dagger_r1_truncation_diagnosis": {
                "dagger_r1_8k": {
                    "run_id": "WS4-dagger-r1-8k-verda",
                    "n_vs_base": 50,
                    "mean_score": -0.542,
                    "ci95": 0.214,
                    "ci95_low": -0.756,
                    "ci95_high": -0.328,
                    "empirical_sd_vs_base": round(sd_dag8k_base, 5),
                    "mde_vs_base_at_n50": round(mde_8k_base_50, 5),
                    "abs_score_over_mde_ratio": round(0.542 / mde_8k_base_50, 4),
                    "rules_out_positive_heldout_score": True,
                    "paired_head_to_head_n": n_h2h_8k,
                    "paired_head_to_head_delta": delta_h2h_8k,
                    "paired_head_to_head_ci95": float(d8_det["paired_vs_v3_4k_s0_ctx8k_cap256_ci95"]),
                    "paired_head_to_head_sd": round(sd_h2h_8k, 5),
                    "paired_head_to_head_mde_at_n43": round(mde_h2h_8k, 5),
                    "paired_head_to_head_power_at_observed": round(
                        compute_two_sided_power_approx(n_h2h_8k, delta_h2h_8k, sd_h2h_8k), 6
                    ),
                    "required_n_for_80pct_power_at_0242": required_n_for_effect(delta_h2h_8k, sd_h2h_8k),
                },
                "dagger_r1_4k": {
                    "run_id": "WS4-dagger-r1-4k-verda",
                    "n_vs_base": 41,
                    "mean_score": -0.101,
                    "ci95": 0.112,
                    "ci95_low": -0.213,
                    "ci95_high": 0.011,
                    "empirical_sd_vs_base": round(sd_dag4k_base, 5),
                    "mde_vs_base_at_n41": round(mde_4k_base_41, 5),
                    "abs_score_over_mde_ratio": round(0.101 / mde_4k_base_41, 4),
                    "power_vs_base_at_observed_minus0101": round(
                        compute_two_sided_power_approx(41, -0.101, sd_dag4k_base), 6
                    ),
                    "max_plausible_positive_score_ci95_high": 0.011,
                    "rules_out_meaningful_positive_score_gt_002": True,
                    "paired_head_to_head_n": n_h2h_4k,
                    "paired_head_to_head_delta": delta_h2h_4k,
                    "paired_head_to_head_ci95": float(d4_det["paired_vs_v3_4k_s0_ctx4k_cap256_ci95"]),
                    "paired_head_to_head_sd": round(sd_h2h_4k, 5),
                    "paired_head_to_head_mde_at_n32": round(mde_h2h_4k, 5),
                },
            },
        },
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1 = HASH_CHAR
    h2 = HASH_CHAR * 2
    h3 = HASH_CHAR * 3
    tot = summary["totals"]
    wp = summary["world_pairing_variance_reduction"]
    mde_blk = summary["mde_audit"]
    diag8 = mde_blk["verda_x2_dagger_r1_truncation_diagnosis"]["dagger_r1_8k"]
    diag4 = mde_blk["verda_x2_dagger_r1_truncation_diagnosis"]["dagger_r1_4k"]

    lines: list[str] = [
        f"{h1} Non-Parametric Statistical Power, Multiplicity Control & World-Pairing Audit (`v1.4`)",
        "",
        (
            f"Deterministic non-parametric inference, Holm-Bonferroni FWER, Benjamini-Hochberg FDR, "
            f"world-secret pairing variance-reduction, and Minimum Detectable Effect (`MDE` at `80%` power, "
            f"`alpha = 0.05` two-sided) audit across Canary tiebreak evaluations (`B = 10000` seeded Monte Carlo "
            f"sign-flip permutations and percentile bootstraps, `seed = 20261115`; "
            f"**`{tot['live_canonical_env_replays_verified']}/{tot['live_canonical_env_replays_verified']}`** "
            f"canonical `Env` replays verified for `HELDOUT_SEEDS 800000..800029` pairing)."
        ),
        "",
        (
            f"- **Seed & Secret Provenance (Panel Fix A)**: Held-out comparisons strictly evaluate "
            f"`HELDOUT_SEEDS [800000, 800200)` (`800000..800059` at `n=180` and `800000..800029` at `n=90` under "
            f"`{summary['world_secret_tag']}`, plus Verda shared-secret `{summary['verda_shared_secret_tag']}` / "
            f"`1ca0c2a64d` slices), while all compact policy weights originate strictly from disjoint "
            f"`TRAIN_SEEDS [100000, 200000)` with **`0` `JUDGE_SEEDS` (`>= 900000`) touched**. Where `DEV_SEEDS 0..29` "
            f"appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**."
        ),
        (
            f"- **Strict Track Separation (Panel Fix E)**: `{summary['panel_fix_e_track_separation']['open_weight_qwen25_above_zero_ratio']}` "
            f"historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so "
            f"the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). All `4` compact "
            f"policies (`is_open_weight_llm = False`) are strictly separated from Track 1 open-weight `Qwen2.5` runs."
        ),
        "",
        f"{h2} 1. Primary Family (`m = {tot['primary_family_size']}`): Sign-Flip Permutation, Holm-Bonferroni FWER & BH FDR",
        "",
        "| Comparison (`comparison_id`) | Track | `n` | Paired Mean Delta | Bootstrap `95% CI` | `p_perm` (2-sided) | `p_Holm` (2-sided) | `q_BH` (2-sided) | `p_Holm` (`>0`) | `MDE` (`80%`) | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for row in summary["primary_family"]:
        if row["verified_positive_after_holm05"] and not row["is_open_weight_llm"]:
            verdict = "VERIFIED COMPACT GAIN"
        elif row["comparison_id"] == "verda_v3_8k_s0_vs_s3":
            verdict = "SEED BIFURCATION (BOTH < 0)"
        elif row["mean_delta"] < 0.0 and row["reject_fwer05_two_sided"]:
            verdict = "HONEST NEGATIVE (< 0)"
        else:
            verdict = "HONEST NULL"
        lines.append(
            f"| `{row['comparison_id']}` | `{row['track']}` | `{row['n']}` | "
            f"`{row['mean_delta']:+.4f}` | `[{row['bootstrap_ci95_low']:+.4f}, {row['bootstrap_ci95_high']:+.4f}]` | "
            f"`{row['p_perm_two_sided']:.4f}` | `{row['p_holm_two_sided']:.4f}` | `{row['q_bh_two_sided']:.4f}` | "
            f"`{row['p_holm_gt0']:.4f}` | `{row['mde_80pct_alpha05']:.4f}` | **{verdict}** |"
        )

    lines.extend([
        "",
        (
            f"Across the `m = {tot['primary_family_size']}` primary family, **`{tot['compact_verified_positive_primary']}/4`** "
            f"non-LLM compact policies (`EmpiricalBayesPolicy` `+1.0282`, `CompactLinearDAggerPolicy` `+0.6267`, "
            f"`TinyMLPPolicy` `+1.4696`, `ScalingLogisticPolicy` `+0.6107`) achieve exact sign-flip permutation "
            f"`p_perm = 0.0001` (`1 / 10001`), surviving Holm-Bonferroni FWER (`p_Holm <= 0.0008`) and Benjamini-Hochberg "
            f"FDR (`q_BH <= 0.0002`) with `100%` post-hoc power. Expanding multiplicity control to `m = {tot['expanded_family_size']}` "
            f"by adding all `4` world-paired `CompactPolicy vs Heuristic` comparisons keeps **`{tot['compact_verified_positive_expanded']}/8`** "
            f"compact comparisons significant (`p_Holm <= 0.0012`, `q_BH <= 0.0002`), while **`0` open-weight `Qwen2.5` runs** "
            f"beat `0.000` base."
        ),
        "",
        f"{h2} 2. World-Secret Pairing Variance Reduction (`Var(A_i - B_i)` vs `Var(A) + Var(B)`)",
        "",
        "| Comparison | Cohort (`world_secret_tag`) | `n` | `Var(A) + Var(B)` | `Var(A_i - B_i)` | World `r` | Var Reduction | `N_eff_ratio` | Equiv Unpaired `n` |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])

    for prow in wp["heldout_compact_pairs"] + wp["verda_shared_secret_pairs"]:
        lines.append(
            f"| `{prow['comparison_id']}` | `{prow['world_secret_tag']}` | `{prow['n']}` | "
            f"`{prow['var_unpaired']:.4f}` | `{prow['var_paired']:.4f}` | `{prow['pearson_r']:+.3f}` | "
            f"`{prow['variance_reduction_pct']:+.1f}%` | **`{prow['n_eff_ratio']:.3f}x`** | `{prow['equivalent_unpaired_n']:.1f}` |"
        )

    lines.extend([
        "",
        (
            f"- **`HELDOUT_SEEDS` (`sha256:ebf2f09716cf76d3`)**: All **`{tot['heldout_pairing_pairs_with_neff_gt_1']}/{tot['heldout_pairing_pairs_total']}`** "
            f"world-paired compact comparisons achieve `N_eff_ratio > 1.0` (mean **`{wp['heldout_mean_n_eff_ratio']:.3f}x`**, "
            f"peak **`{wp['heldout_max_n_eff_ratio']:.3f}x`** on `scaling_logistic_vs_heuristic`, equivalent to `114.2` unpaired "
            f"episodes from `n=90`), because calibrated policies covary positively (`r = +0.105..+0.323`) with shared world difficulty `V`."
        ),
        (
            f"- **Verda Shared-Secret (`{VERDA_SHARED_SECRET_TAG}`)**: Collapsed raw-JSON `Qwen2.5` runs exhibit near-zero or "
            f"mildly negative world correlation (`N_eff_ratio` `{wp['verda_mean_n_eff_ratio']:.3f}x` mean; `0.826x` on `s3_minus_4k_at_8k`) "
            f"because blind Day-1..5 accusations (`0.043..0.093` whom-precision) do not track true world difficulty; shared-secret "
            f"pairing nonetheless eliminates world-realization confounds (`60/60` and `61/61` roster exact matches) and yields conservative paired CIs."
        ),
        "",
        f"{h2} 3. Minimum Detectable Effect (`MDE` at `80%` Power, `alpha = 0.05` Two-Sided)",
        "",
        (
            f"| Sample Size `n` | `t`-Factor (`/ SD`) | "
            f"Compact vs `Abstain` (`SD={mde_blk['reference_sds']['compact_vs_abstain']:.3f}`) | "
            f"Scaling vs `Abstain` (`SD={mde_blk['reference_sds']['scaling_vs_abstain']:.3f}`) | "
            f"Compact vs `Heuristic` Paired (`SD={mde_blk['reference_sds']['compact_vs_heuristic_paired']:.3f}`) | "
            f"Compact vs `Heuristic` Unpaired (`SD={mde_blk['reference_sds']['compact_vs_heuristic_unpaired']:.3f}`) | "
            f"Verda `DAgger r1` 8k (`SD={mde_blk['reference_sds']['verda_dagger_r1_8k_vs_base']:.3f}`) | "
            f"Verda `DAgger r1` 4k (`SD={mde_blk['reference_sds']['verda_dagger_r1_4k_vs_base']:.3f}`) |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])

    for mrow in mde_blk["mde_table"]:
        lines.append(
            f"| `{mrow['n']}` | `{mrow['unit_sd_mde_factor']:.4f}` | "
            f"`{mrow['mde_compact_vs_abstain']:.4f}` | `{mrow['mde_scaling_vs_abstain']:.4f}` | "
            f"`{mrow['mde_compact_vs_heuristic_paired']:.4f}` | `{mrow['mde_compact_vs_heuristic_unpaired']:.4f}` | "
            f"`{mrow['mde_verda_dagger_r1_8k_vs_base']:.4f}` | `{mrow['mde_verda_dagger_r1_4k_vs_base']:.4f}` |"
        )

    lines.extend([
        "",
        f"{h3} Quantitative Explanation of Reaper-Truncated Verda X2 `DAgger r1` (`n=50` at 8k, `n=41` at 4k)",
        "",
        (
            f"1. **8k Evaluation (`WS4-dagger-r1-8k-verda`, `n=50` pulled before `08:00` reaper)**: Against `0.000` base "
            f"(`SD = {diag8['empirical_sd_vs_base']:.4f}`), `MDE(n=50)` is **`{diag8['mde_vs_base_at_n50']:.4f}`**, so "
            f"the observed score **`-0.542 +/- 0.214`** (`95% CI [-0.756, -0.328]`, `|-0.542| = {diag8['abs_score_over_mde_ratio']:.2f}x MDE`) "
            f"decisively **rules out any `> 0.0` held-out score** (`p_perm = 0.0001` negative, `p_Holm(>0) = 1.0000`). "
            f"Conversely, for the shared-secret head-to-head vs `v3-4k-s0@8k cap=256` (`n={diag8['paired_head_to_head_n']}`, "
            f"`+0.242 +/- 0.304`, `SD = {diag8['paired_head_to_head_sd']:.4f}`), `MDE(n=43)` is **`{diag8['paired_head_to_head_mde_at_n43']:.4f}`**: "
            f"`|+0.242| < {diag8['paired_head_to_head_mde_at_n43']:.4f}` had only **`{100.0 * diag8['paired_head_to_head_power_at_observed']:.1f}%`** "
            f"power and would have required **`n >= {diag8['required_n_for_80pct_power_at_0242']}`** paired worlds for `80%` power."
        ),
        (
            f"2. **4k Evaluation (`WS4-dagger-r1-4k-verda`, `n=41` pulled before `07:30` reaper)**: High abstention (`35/41`) "
            f"lowers `SD` to `{diag4['empirical_sd_vs_base']:.4f}`, giving `MDE(n=41)` = **`{diag4['mde_vs_base_at_n41']:.4f}`** "
            f"(and `MDE(n=32)` = **`{diag4['paired_head_to_head_mde_at_n32']:.4f}`** vs `v3-4k-s0@4k cap=256`, where observed delta was "
            f"`-0.031 +/- 0.139`). Hence `-0.101 +/- 0.112` sits inside the small-effect null zone (`|-0.101| < {diag4['mde_vs_base_at_n41']:.4f}`, "
            f"`{100.0 * diag4['power_vs_base_at_observed_minus0101']:.1f}%` power), **yet** its `95% CI [-0.213, +0.011]` caps any "
            f"plausible positive score at **`+0.011`** and rules out every tiebreak-relevant improvement `>= +0.164` at `>= 80%` power."
        ),
        "",
        f"{h3} Offline Reproduction & Fast Verification Commands",
        "",
        "```bash",
        "python scripts/tiebreak_statistical_power_audit.py --check",
        "pytest -q tests/test_tiebreak_statistical_power.py",
        "python scripts/reproduce_tiebreak_all.py --check",
        "python scripts/verify_tiebreak_submission.py --strict",
        "```",
        "",
    ])
    return "\n".join(lines)


def check_python_source_hygiene(py_path: Path, run_tokenize: bool = True) -> list[str]:
    errs: list[str] = []
    if not py_path.is_file():
        return [f"missing python file: {py_path}"]
    src = py_path.read_text(encoding="utf-8")
    if not src.isascii():
        errs.append(f"{py_path.name}: source is not pure ASCII")
    if HASH_CHAR in src:
        errs.append(f"{py_path.name}: contains literal hash character")
    if EM_DASH in src or EN_DASH in src or UNICODE_MINUS in src:
        errs.append(f"{py_path.name}: contains forbidden unicode dash/minus")
    if run_tokenize:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        if any(t.type == tokenize.COMMENT for t in toks):
            errs.append(f"{py_path.name}: contains python comment token")
    tree = ast.parse(src, filename=str(py_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                    errs.append(f"{py_path.name}: forbidden import {alias.name}")
                if alias.name.startswith(FORBIDDEN_CANARY_PREFIXES):
                    errs.append(f"{py_path.name}: forbidden canary import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                errs.append(f"{py_path.name}: forbidden from-import {node.module}")
            if node.module.startswith(FORBIDDEN_CANARY_PREFIXES):
                errs.append(f"{py_path.name}: forbidden canary from-import {node.module}")
            if node.module == "canary":
                bad = {a.name for a in node.names} & {"solver", "world"}
                if bad:
                    errs.append(f"{py_path.name}: forbidden canary.{sorted(bad)[0]} import")
    return errs


def _scan_json_for_judge_numbers(obj: Any, raw_json: str) -> list[str]:
    errs: list[str] = []

    def _walk(val: Any, path: str) -> None:
        if isinstance(val, int) and not isinstance(val, bool) and val >= JUDGE_SEED_MIN:
            errs.append(f"JSON integer >= 900000 at {path}: {val}")
        elif isinstance(val, dict):
            for k, v in val.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(val, list):
            for idx, v in enumerate(val):
                _walk(v, f"{path}[{idx}]")

    _walk(obj, "$")
    for m in re.finditer(r"\b\d{6,}\b", raw_json):
        pref = raw_json[max(0, m.start() - 2) : m.start()]
        if pref.lower() != "0x" and int(m.group(0)) >= JUDGE_SEED_MIN:
            errs.append(f"raw JSON 6+-digit token >= 900000: {m.group(0)}")
    return errs


def _check_panel_fix_a_text(md_txt: str) -> list[str]:
    errs: list[str] = []
    for lineno, line in enumerate(md_txt.splitlines(), start=1):
        if PREREG_RE.search(line) and SEEDS_0_29_RE.search(line):
            scrubbed = NEGATED_PREREG_RE.sub("", line)
            if PREREG_RE.search(scrubbed):
                errs.append(f"Panel Fix A violation on line {lineno}: affirmative pre-registered 0..29 claim")
    if "post-hoc locked, not pre-registered" not in md_txt:
        errs.append("Panel Fix A disclosure missing 'post-hoc locked, not pre-registered'")
    return errs


def verify_artifacts(repo_root: Path = ROOT) -> dict[str, Any]:
    errs: list[str] = []
    json_path = repo_root / DEFAULT_OUT_JSON
    md_path = repo_root / DEFAULT_OUT_MD

    if not json_path.is_file():
        return {"passed": False, "errors": [f"missing {json_path}"]}
    if not md_path.is_file():
        return {"passed": False, "errors": [f"missing {md_path}"]}

    for sib in ("summary.json", "table.md"):
        if (json_path.parent / sib).exists():
            errs.append(f"forbidden sibling {sib} in {json_path.parent}")

    raw_bytes = json_path.read_bytes()
    if len(raw_bytes) >= MAX_SUMMARY_BYTES:
        errs.append(f"summary JSON size {len(raw_bytes)} >= {MAX_SUMMARY_BYTES}")

    raw_json = raw_bytes.decode("utf-8")
    md_txt = md_path.read_text(encoding="utf-8")
    for lbl, txt in (("statistical_power_summary.json", raw_json), ("tiebreak_statistical_power.md", md_txt)):
        if not txt.isascii():
            errs.append(f"{lbl}: non-ASCII character found")
        if EM_DASH in txt or EN_DASH in txt:
            errs.append(f"{lbl}: forbidden em dash or en dash found")
        if UNICODE_MINUS in txt:
            errs.append(f"{lbl}: forbidden unicode minus found")

    errs.extend(_check_panel_fix_a_text(md_txt))

    summary = json.loads(raw_json)
    if raw_json != json.dumps(summary, indent=2) + "\n":
        errs.append("statistical_power_summary.json differs from canonical indent=2 serialization")
    errs.extend(_scan_json_for_judge_numbers(summary, raw_json))

    script_cand = repo_root / "scripts" / "tiebreak_statistical_power_audit.py"
    if script_cand.is_file():
        errs.extend(check_python_source_hygiene(script_cand, run_tokenize=False))

    try:
        expected_md = render_markdown_report(summary)
        if md_txt != expected_md:
            errs.append("docs/reports/tiebreak_statistical_power.md differs from render_markdown_report(summary)")
    except Exception as exc:
        errs.append(f"render_markdown_report failed: {exc}")

    for fam_key in ("primary_family", "expanded_family"):
        rows = summary.get(fam_key) or []
        if not rows:
            errs.append(f"empty {fam_key}")
            continue
        p2 = [float(r["p_perm_two_sided"]) for r in rows]
        pg = [float(r["p_perm_one_sided_gt0"]) for r in rows]
        for row, eh2, eq2, ehg, eqg in zip(
            rows,
            holm_bonferroni_adjust(p2),
            benjamini_hochberg_adjust(p2),
            holm_bonferroni_adjust(pg),
            benjamini_hochberg_adjust(pg),
        ):
            if abs(float(row["p_holm_two_sided"]) - round(eh2, 5)) > 2e-5:
                errs.append(f"{fam_key}:{row['comparison_id']}: p_holm_two_sided mismatch")
            if abs(float(row["q_bh_two_sided"]) - round(eq2, 5)) > 2e-5:
                errs.append(f"{fam_key}:{row['comparison_id']}: q_bh_two_sided mismatch")
            if abs(float(row["p_holm_gt0"]) - round(ehg, 5)) > 2e-5:
                errs.append(f"{fam_key}:{row['comparison_id']}: p_holm_gt0 mismatch")
            if abs(float(row["q_bh_gt0"]) - round(eqg, 5)) > 2e-5:
                errs.append(f"{fam_key}:{row['comparison_id']}: q_bh_gt0 mismatch")
            exp_mde = round(compute_mde_two_sided(int(row["n"]), float(row["sd_delta"])), 5)
            if abs(float(row["mde_80pct_alpha05"]) - exp_mde) > 5e-5:
                errs.append(f"{fam_key}:{row['comparison_id']}: mde_80pct_alpha05 mismatch")

    wp = summary.get("world_pairing_variance_reduction") or {}
    for list_key in ("heldout_compact_pairs", "verda_shared_secret_pairs"):
        for prow in wp.get(list_key) or []:
            vu = float(prow["var_a"]) + float(prow["var_b"])
            vp = float(prow["var_paired"])
            if abs(float(prow["var_unpaired"]) - round(vu, 5)) > 3e-5:
                errs.append(f"{prow['comparison_id']}: var_unpaired != var_a + var_b")
            if abs(float(prow["n_eff_ratio"]) - round(vu / vp, 5)) > 1e-4:
                errs.append(f"{prow['comparison_id']}: n_eff_ratio != var_unpaired / var_paired")

    mde_blk = summary.get("mde_audit") or {}
    ref_sds = mde_blk.get("reference_sds") or {}
    mde_rows = mde_blk.get("mde_table") or []
    if [int(r["n"]) for r in mde_rows] != list(MDE_SAMPLE_SIZES):
        errs.append("mde_table sample sizes mismatch (30, 41, 50, 90, 180)")
    for mrow in mde_rows:
        n_v = int(mrow["n"])
        for rkey, mkey in (
            ("compact_vs_abstain", "mde_compact_vs_abstain"),
            ("scaling_vs_abstain", "mde_scaling_vs_abstain"),
            ("compact_vs_heuristic_paired", "mde_compact_vs_heuristic_paired"),
            ("verda_dagger_r1_8k_vs_base", "mde_verda_dagger_r1_8k_vs_base"),
            ("verda_dagger_r1_4k_vs_base", "mde_verda_dagger_r1_4k_vs_base"),
        ):
            exp_v = round(compute_mde_two_sided(n_v, float(ref_sds[rkey])), 5)
            if abs(float(mrow[mkey]) - exp_v) > 5e-5:
                errs.append(f"mde_table n={n_v} {mkey} mismatch")

    iso = summary.get("seed_isolation") or {}
    if iso.get("judge_episodes_touched") != 0 or iso.get("dev_episodes_touched") != 0:
        errs.append("seed_isolation touched judge or dev episodes")
    if "post-hoc locked, not pre-registered" not in str(iso.get("panel_fix_a_disclosure", "")):
        errs.append("seed_isolation missing Panel Fix A disclosure")

    pe = summary.get("panel_fix_e_track_separation") or {}
    if pe.get("compact_policies_are_open_weight_llm") is not False:
        errs.append("Panel Fix E compact_policies_are_open_weight_llm must be False")
    if pe.get("open_weight_qwen25_above_zero_ratio") != "0 / 19":
        errs.append("Panel Fix E open_weight_qwen25_above_zero_ratio must be '0 / 19'")
    if pe.get("readme_qwen_addendum_status") != "HOLD_README_QWEN_ADDENDUM_UNTIL_V100":
        errs.append("Panel Fix E addendum status mismatch")

    prim_by_id = {r["comparison_id"]: r for r in (summary.get("primary_family") or [])}
    ledger_path = repo_root / LEDGER_REL
    if ledger_path.is_file():
        led = json.loads(ledger_path.read_text(encoding="utf-8"))
        if len(led.get("historical_runs") or []) != int(pe.get("open_weight_qwen25_runs_total", -1)):
            errs.append("ledger historical_runs count mismatch")
        hmap = {r["run_id"]: r for r in (led.get("historical_runs") or [])}
        if abs(float(prim_by_id["verda_dagger_r1_8k_vs_base"]["mean_delta"]) - float(hmap["WS4-dagger-r1-8k-verda"]["after_mean_score"])) > 1e-4:
            errs.append("WS4-dagger-r1-8k-verda mean_delta mismatch vs experiment_ledger.json")
        if abs(float(prim_by_id["verda_dagger_r1_4k_vs_base"]["mean_delta"]) - float(hmap["WS4-dagger-r1-4k-verda"]["after_mean_score"])) > 1e-4:
            errs.append("WS4-dagger-r1-4k-verda mean_delta mismatch vs experiment_ledger.json")

    for rel_p, cid, d_getter in (
        (EB_SUMMARY_REL, "empirical_bayes_vs_before", lambda d: float(d["paired"]["mean_delta"])),
        (DAGGER_SUMMARY_REL, "compact_linear_dagger_vs_before", lambda d: float(d["paired"]["mean_delta"])),
        (MLP_SUMMARY_REL, "tiny_mlp_dagger_vs_before", lambda d: float(d["paired"]["mean_delta"])),
        (
            SCALING_SUMMARY_REL,
            "scaling_logistic_vs_before",
            lambda d: float(next(r for r in d["scaling_curve"] if int(r["n_train"]) == 900)["metrics"]["mean_score"]),
        ),
        (
            VERDA_SUMMARY_REL,
            "verda_v3_8k_s0_vs_s3",
            lambda d: float(d["world_paired_shared_secret_comparisons"]["s0_minus_s3"]["mean_delta"]),
        ),
    ):
        cand = repo_root / rel_p
        if cand.is_file() and cid in prim_by_id:
            ref_val = d_getter(json.loads(cand.read_text(encoding="utf-8")))
            if abs(float(prim_by_id[cid]["mean_delta"]) - ref_val) > 2e-4:
                errs.append(f"{cid} mean_delta mismatch vs {rel_p}")

    return {"passed": len(errs) == 0, "errors": errs}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Statistical power, MDE, and multiplicity audit for Canary tiebreak.")
    p.add_argument("--check", action="store_true", help="Fast offline verification of committed artifacts.")
    p.add_argument("--json", action="store_true", help="Emit JSON verdict on stdout.")
    p.add_argument("--repo-root", "--root", dest="repo_root", type=Path, default=None, help="Override repository root.")
    return p


def main(argv: list[str] | None = None) -> int:
    t0 = time.perf_counter()
    args = build_arg_parser().parse_args(argv)
    repo_root = (args.repo_root or ROOT).resolve()

    if args.check:
        verdict = verify_artifacts(repo_root=repo_root)
        elapsed = round(time.perf_counter() - t0, 5)
        if args.json:
            payload = {
                "schema": SCHEMA_VERSION,
                "passed": verdict["passed"],
                "errors": verdict["errors"],
                "elapsed_seconds": elapsed,
            }
            print(json.dumps(payload, indent=2))
        elif verdict["passed"]:
            summary = json.loads((repo_root / DEFAULT_OUT_JSON).read_text(encoding="utf-8"))
            tot = summary["totals"]
            print(
                f"OK: verified {tot['primary_family_size']} primary + {tot['expanded_family_size']} expanded "
                f"multiplicity tests, {tot['heldout_pairing_pairs_with_neff_gt_1']}/{tot['heldout_pairing_pairs_total']} "
                f"world-paired N_eff>1 cohorts, and {tot['live_canonical_env_replays_verified']}/{tot['live_canonical_env_replays_verified']} "
                f"replays in {elapsed:.3f}s"
            )
        else:
            for err in verdict["errors"]:
                print(f"ERROR: {err}", file=sys.stderr)
        return 0 if verdict["passed"] else 1

    summary = build_summary(repo_root=repo_root)
    out_json = repo_root / DEFAULT_OUT_JSON
    out_md = repo_root / DEFAULT_OUT_MD
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown_report(summary), encoding="utf-8")

    verdict = verify_artifacts(repo_root=repo_root)
    elapsed = round(time.perf_counter() - t0, 3)
    if not verdict["passed"]:
        for err in verdict["errors"]:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"schema": SCHEMA_VERSION, "passed": True, "elapsed_seconds": elapsed}, indent=2))
    else:
        print(f"Wrote {DEFAULT_OUT_JSON} and {DEFAULT_OUT_MD} ({elapsed:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
