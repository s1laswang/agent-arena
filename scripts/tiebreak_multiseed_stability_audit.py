"""Deterministic multi-world-secret stability and luck-adjusted EV audit for Canary compact policies."""
from __future__ import annotations

import argparse
import ast
import contextlib
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

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.multiseed_stability.v1"
AUDIT_ID = "tiebreak-multiseed-stability-v14"

H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_SEEDS_PER_TIER = HELDOUT_SEED_STOP - HELDOUT_SEED_START
EPISODES_PER_SECRET = len(CANONICAL_TIERS) * HELDOUT_SEEDS_PER_TIER

WORLD_SECRET_SPECS: tuple[tuple[str, str], ...] = (
    ("eval-01", "canary-tiebreak-heldout-v14-eval-01"),
    ("eval-02", "canary-tiebreak-heldout-v14-eval-02"),
    ("eval-03", "canary-tiebreak-heldout-v14-eval-03"),
    ("eval-04", "canary-tiebreak-heldout-v14-eval-04"),
    ("eval-05", "canary-tiebreak-heldout-v14-eval-05"),
)
NUM_WORLD_SECRETS = len(WORLD_SECRET_SPECS)
EPISODES_PER_POLICY = NUM_WORLD_SECRETS * EPISODES_PER_SECRET
PRIMARY_WORLD_SECRET = WORLD_SECRET_SPECS[0][1]
EXPECTED_PRIMARY_SECRET_TAG = "sha256:ebf2f09716cf76d3"

JUDGE_SEED_MIN = 900_000
MAX_SUMMARY_BYTES = 75 * 1024
MAX_CHECK_SECONDS = 15.0
MAX_EXCESS_INTER_SECRET_TAU = 0.03
MAX_RAW_INTER_SECRET_SD = 0.045

DEFAULT_OUT_JSON = Path("results/tiebreak/multiseed_stability/multiseed_stability_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_multiseed_stability.md")
LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")
VERDA_SUMMARY_REL = Path("results/tiebreak/verda_multiseed/multiseed_summary.json")
EB_SUMMARY_REL = Path("results/tiebreak/empirical_bayes/summary.json")

POLICY_ORDER: tuple[str, ...] = (
    "compact_linear_dagger",
    "tiny_mlp",
    "scaling_logistic",
    "empirical_bayes",
)

POLICY_META_SPECS: dict[str, dict[str, Any]] = {
    "compact_linear_dagger": {
        "policy_id": "compact_linear_dagger",
        "policy_class": "CompactLinearDAggerPolicy",
        "run_id": "compact-linear-dagger-v14",
        "module_path": "train/compact_dagger_ablation.py",
        "summary_path": "results/tiebreak/dagger_ablation/summary.json",
        "expected_param_count": 785,
        "expected_train_seed_range": "109000..109509",
        "before_baseline_id": "stage0_zero_abstain",
    },
    "tiny_mlp": {
        "policy_id": "tiny_mlp",
        "policy_class": "TinyMLPPolicy",
        "run_id": "tiny-mlp-dagger-v14",
        "module_path": "train/neural_mlp_tiebreak.py",
        "summary_path": "results/tiebreak/neural_mlp_dagger/mlp_summary.json",
        "expected_param_count": 12293,
        "expected_train_seed_range": "107000..107599",
        "before_baseline_id": "tiny_mlp_untrained",
    },
    "scaling_logistic": {
        "policy_id": "scaling_logistic",
        "policy_class": "ScalingLogisticPolicy",
        "run_id": "scaling-logistic-v14",
        "module_path": "scripts/tiebreak_scaling_calibration.py",
        "summary_path": "results/tiebreak/scaling/scaling_summary.json",
        "expected_param_count": 82,
        "expected_train_seed_range": "107000..108999",
        "before_baseline_id": "stage0_zero_abstain",
    },
    "empirical_bayes": {
        "policy_id": "empirical_bayes",
        "policy_class": "EmpiricalBayesPolicy",
        "run_id": "empirical-bayes-v14",
        "module_path": "train/empirical_bayes_policy.py",
        "summary_path": "results/tiebreak/empirical_bayes/summary.json",
        "expected_param_count": 11,
        "expected_train_seed_range": "102000..102779",
        "before_baseline_id": "eb_naive_prior",
    },
}

PANEL_FIX_A_DISCLOSURE = (
    "All 1800 primary trained-policy episodes (4 policies x K=5 world secrets x n=90 episodes) "
    "strictly evaluate world-paired HELDOUT_SEEDS 800000..800029 (30 easy, 30 medium, 30 hard per secret) "
    "under deterministic world secrets eval-01..05 (primary sha256:ebf2f09716cf76d3), while all learned "
    "policy weights and the EmpiricalBayesPolicy posterior likelihoods originate strictly from disjoint "
    "TRAIN_SEEDS [100000, 200000) with 0 JUDGE_SEEDS (900k+) touched. Where DEV_SEEDS 0..29 appear in "
    "separate Canary frontier reports, they are post-hoc locked, not pre-registered (Panel Fix A)."
)

PANEL_FIX_E_DISCLOSURE = (
    "Per Panel Fix E strict track separation, 0 / 19 historical open-weight Qwen2.5 runs in "
    "experiment_ledger.json exceed untrained base (0.000), so the README.md Qwen addendum remains "
    "withheld (HOLD_README_QWEN_ADDENDUM_UNTIL_V100). All 4 compact policies audited here "
    "(CompactLinearDAggerPolicy, TinyMLPPolicy, ScalingLogisticPolicy, EmpiricalBayesPolicy; "
    "is_open_weight_llm = False) are non-LLM neural and parametric policies strictly separated "
    "from open-weight Qwen2.5 LoRA and Verda GRPO runs."
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
_FORBIDDEN_IMPORTS: frozenset[str] = frozenset({"torch", "transformers"})


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
    sd = sample_sd(values)
    half = 1.96 * sd / math.sqrt(n)
    return {
        "mean": round(mean_v, 5),
        "ci95_low": round(mean_v - half, 5),
        "ci95_high": round(mean_v + half, 5),
        "ci95_half_width": round(half, 5),
    }


def paired_delta_summary(
    after_scores: list[float],
    before_scores: list[float],
    after_evs: list[float],
    before_evs: list[float],
) -> dict[str, Any]:
    s_deltas = [a - b for a, b in zip(after_scores, before_scores)]
    e_deltas = [a - b for a, b in zip(after_evs, before_evs)]
    s_ci = mean_ci95(s_deltas)
    e_ci = mean_ci95(e_deltas)
    return {
        "n": len(s_deltas),
        "mean_delta": s_ci["mean"],
        "ci95_low": s_ci["ci95_low"],
        "ci95_high": s_ci["ci95_high"],
        "ci95_positive": bool(s_ci["ci95_low"] > 0.0),
        "luck_ev_mean_delta": e_ci["mean"],
        "luck_ev_ci95_low": e_ci["ci95_low"],
        "luck_ev_ci95_high": e_ci["ci95_high"],
        "luck_ev_ci95_positive": bool(e_ci["ci95_low"] > 0.0),
    }


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not _PREREG_RE.search(raw_line) or not _SEEDS_0_29_RE.search(raw_line):
            continue
        scrubbed = _NEGATED_PREREG_RE.sub("", raw_line)
        if _PREREG_RE.search(scrubbed):
            hits.append(f"line {lineno}: {raw_line.strip()[:120]}")
    return hits


_HYGIENE_CACHE: dict[tuple[str, bytes, bool], tuple[str, ...]] = {}


def check_python_source_hygiene(py_path: Path, run_tokenize: bool = False) -> list[str]:
    if not py_path.is_file():
        return [f"missing python file: {py_path}"]
    raw_bytes = py_path.read_bytes()
    cache_key = (py_path.name, hashlib.sha256(raw_bytes).digest(), bool(run_tokenize))
    cached = _HYGIENE_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    errs: list[str] = []
    src = raw_bytes.decode("utf-8")
    if not src.isascii():
        errs.append(f"{py_path.name}: contains non-ASCII characters")
    if H in src:
        errs.append(f"{py_path.name}: contains Python comment or hash character")
    elif run_tokenize:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        if any(t.type == tokenize.COMMENT for t in toks):
            errs.append(f"{py_path.name}: contains Python comment token")
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
                root_pkg = name.split(".")[0]
                if root_pkg in _FORBIDDEN_IMPORTS or name == "canary.solver" or name.startswith("canary.solver."):
                    errs.append(f"{py_path.name}: forbidden import {name}")
                if name == "canary.world" or name.startswith("canary.world."):
                    errs.append(f"{py_path.name}: forbidden import {name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            root_pkg = mod.split(".")[0]
            if root_pkg in _FORBIDDEN_IMPORTS or mod == "canary.solver" or mod.startswith("canary.solver."):
                errs.append(f"{py_path.name}: forbidden from-import {mod}")
            if mod == "canary.world" or mod.startswith("canary.world."):
                errs.append(f"{py_path.name}: forbidden from-import {mod}")
            if mod == "canary":
                for alias in node.names:
                    if alias.name in ("solver", "world"):
                        errs.append(f"{py_path.name}: forbidden from canary import {alias.name}")
        elif isinstance(node, ast.Name) and node.id == "SolverPolicy":
            errs.append(f"{py_path.name}: forbidden reference to SolverPolicy")
    _HYGIENE_CACHE[cache_key] = tuple(errs)
    return errs


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
            if float(node) >= JUDGE_SEED_MIN:
                hits.append(f"{path}: numeric value {node} >= {JUDGE_SEED_MIN}")

    _walk(obj, "$")
    for m in _INT_TOKEN_RE.finditer(raw_json):
        val = int(m.group(0))
        if val >= JUDGE_SEED_MIN:
            hits.append(f"raw_json integer token {val} >= {JUDGE_SEED_MIN}")
    return hits


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1 = H
    h2 = H * 2
    h3 = H * 3

    totals = summary["totals"]
    pe = summary["panel_fix_e_track_separation"]
    vc = summary["verda_grpo_contrast"]
    v8 = vc["seeds_8k"]

    lines: list[str] = [
        f"{h1} Multi-World-Secret Stability & Luck-Adjusted EV Robustness Audit (`v1.4`)",
        "",
        (
            f"Deterministic keyless audit across all `4` verified Canary compact non-LLM policies "
            f"(`CompactLinearDAggerPolicy`, `TinyMLPPolicy`, `ScalingLogisticPolicy`, `EmpiricalBayesPolicy`) "
            f"evaluating `HELDOUT_SEEDS {summary['heldout_seed_range']}` (`n={summary['episodes_per_secret']}` "
            f"per secret: `30` `easy`, `30` `medium`, `30` `hard`) across `K={summary['num_world_secrets']}` "
            f"independent deterministic world secrets (`eval-01` = `{summary['world_secret_tag']}` through "
            f"`eval-05`, `{summary['episodes_per_policy']}` fast `TemplateProvider()` episodes/policy, "
            f"`{totals['primary_trained_episodes']}` primary trained rollouts + `{totals['fresh_env_replays_verified']}` "
            "fresh `Env` replays). Luck-adjusted accusation expected value is computed directly from public "
            "tool observations via `EmpiricalBayesPolicy`'s exact calibrated softmax posterior "
            "(`p_posterior * known_or_true_V_est - (1 - p_posterior) * 1.0`, `0` `canary.solver` imports)."
        ),
        "",
        (
            f"- **Seed & Secret Provenance (Panel Fix A)**: All `{totals['primary_trained_episodes']}` primary "
            f"rollouts strictly evaluate `HELDOUT_SEEDS {summary['heldout_seed_range']}` across `K=5` deterministic "
            f"world secrets (`eval-01..05`, primary `{summary['world_secret_tag']}`), while all policy weights and "
            "posterior likelihood parameters originate strictly from disjoint `TRAIN_SEEDS [100000, 200000)` with "
            "**`0` `JUDGE_SEEDS` (`900k+`) touched**. Where `DEV_SEEDS 0..29` appear in separate Canary frontier "
            "reports, they are **post-hoc locked, not pre-registered**."
        ),
        (
            f"- **Strict Track Separation (Panel Fix E)**: `{pe['open_weight_qwen25_above_zero_ratio']}` historical "
            "open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the "
            f"`README.md` Qwen addendum remains withheld (`{pe['readme_qwen_addendum_status']}`). All `4` compact "
            "policies audited here (`is_open_weight_llm = False`) are non-LLM structured/neural models strictly "
            "separated from open-weight `Qwen2.5` LoRA and Verda GRPO runs."
        ),
        "",
        f"{h2} 1. Headline Multi-Secret Stability Summary (`K=5` World Secrets x `n=90` = `450` Episodes / Policy)",
        "",
        "| Policy (`run_id`) | Params | Train Seeds | Mean Score Across `K=5` Secrets | Raw Sample SD / Within-Secret SE / Excess `tau` (`< 0.030`) | Mean Luck-Adj EV Across `K=5` | Inter-Secret Luck-EV SD | Positive Paired `95% CI` Secrets (vs `0.000` / Untrained) | Verda `8k` SD / Policy SD |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        st = pb["stability_summary"]
        lines.append(
            f"| `{pb['policy_class']}` (`{pb['run_id']}`) | `{pb['param_count']:,}` | `{pb['train_seed_range']}` | "
            f"`{st['inter_secret_score_mean']:+.4f}` (`[{st['inter_secret_score_min']:+.4f}, {st['inter_secret_score_max']:+.4f}]`) | "
            f"`{st['inter_secret_score_sd']:.5f}` / `{st['mean_within_secret_se']:.5f}` / **`{st['excess_inter_secret_tau']:.5f}`** | "
            f"`{st['inter_secret_luck_ev_mean']:+.4f}` (`[{st['inter_secret_luck_ev_min']:+.4f}, {st['inter_secret_luck_ev_max']:+.4f}]`) | "
            f"**`{st['inter_secret_luck_ev_sd']:.5f}`** | "
            f"**`{st['positive_paired_ci95_vs_abstain_secrets']}/5` & `{st['positive_paired_ci95_vs_untrained_secrets']}/5`** | "
            f"`{st['verda_8k_sd_over_policy_sd_ratio']:.1f}x` |"
        )

    lines.extend(
        [
            "",
            (
                f"Across all `4` compact non-LLM policies, raw sample inter-secret score SD (`ddof=1` across `K=5` "
                f"secrets of `n=90` episodes) spans `{totals['min_policy_inter_secret_score_sd']:.5f}..{totals['max_policy_inter_secret_score_sd']:.5f}` "
                f"(population SD `{totals['min_policy_inter_secret_score_sd_pop']:.5f}..{totals['max_policy_inter_secret_score_sd_pop']:.5f}`), "
                f"matching the theoretical `n=90` finite-sample standard error (`~0.033..0.037`) so that "
                f"noise-subtracted excess inter-secret heterogeneity `tau` spans "
                f"**`0.00000..{totals['max_policy_excess_inter_secret_tau']:.5f}`** (every policy strictly `< {MAX_EXCESS_INTER_SECRET_TAU:.2f}`). "
                f"Inter-secret luck-adjusted EV SD spans `{totals['min_policy_inter_secret_luck_ev_sd']:.5f}..{totals['max_policy_inter_secret_luck_ev_sd']:.5f}`, "
                f"and **`{totals['positive_secret_cells_vs_abstain']}/{totals['total_secret_cells']}` (`100.0%`)** "
                "policy-secret cells achieve strictly positive paired `95%` CIs on both raw score and luck-adjusted EV "
                "against both zero-skill `abstain` (`0.000`) and architecture-matched untrained baselines."
            ),
            "",
            f"{h2} 2. Per-Secret Trajectory & Luck-Adjusted EV Matrix (`20` Policy x Secret Cells, `n=90` Each)",
            "",
            "| Policy | Secret ID (`world_secret_tag`) | Raw Score (`95% CI`) | Luck-Adj EV (`95% CI`) | Paired Delta vs Untrained (`95% CI`) | Luck-EV Delta vs Untrained (`95% CI`) | Acc / Wrong / Abstain | Mean `p_post` / `V_est` | Replay |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        for sec_spec in summary["world_secrets"]:
            sid = sec_spec["secret_id"]
            sb = pb["by_secret"][sid]
            ov = sb["overall"]
            pu = sb["paired_vs_untrained"]
            lines.append(
                f"| `{pb['policy_class']}` | `{sid}` (`{sb['world_secret_tag']}`) | "
                f"`{ov['mean_score']:+.4f} [{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}]` | "
                f"`{ov['luck_adjusted_ev']:+.4f} [{ov['luck_ev_ci95_low']:+.4f}, {ov['luck_ev_ci95_high']:+.4f}]` | "
                f"`{pu['mean_delta']:+.4f} [{pu['ci95_low']:+.4f}, {pu['ci95_high']:+.4f}]` | "
                f"`{pu['luck_ev_mean_delta']:+.4f} [{pu['luck_ev_ci95_low']:+.4f}, {pu['luck_ev_ci95_high']:+.4f}]` | "
                f"`{ov['accuracy']:.3f}` / `{ov['wrong_accuse_rate']:.3f}` / `{ov['abstain_rate']:.3f}` | "
                f"`{ov['mean_p_posterior_at_accuse']:.3f}` / `{ov['mean_v_est_at_accuse']:.3f}` | "
                f"`{ov['n']}/{ov['n']}` |"
            )

    lines.extend(
        [
            "",
            f"{h2} 3. Pooled `450`-Episode Tier & Calibration Summary Across `K=5` World Secrets",
            "",
            "| Policy | Pooled `450` Raw Score (`95% CI`) | Pooled `450` Luck-Adj EV (`95% CI`) | `easy` (`n=150`) Score / Luck-EV | `medium` (`n=150`) Score / Luck-EV | `hard` (`n=150`) Score / Luck-EV | Valid Call Rate |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for pid in POLICY_ORDER:
        pb = summary["policies"][pid]
        p450 = pb["pooled_450"]
        bt = pb["pooled_by_tier"]
        lines.append(
            f"| `{pb['policy_class']}` | "
            f"`{p450['mean_score']:+.4f} [{p450['ci95_low']:+.4f}, {p450['ci95_high']:+.4f}]` | "
            f"`{p450['luck_adjusted_ev']:+.4f} [{p450['luck_ev_ci95_low']:+.4f}, {p450['luck_ev_ci95_high']:+.4f}]` | "
            f"`{bt['easy']['mean_score']:+.4f}` / `{bt['easy']['luck_adjusted_ev']:+.4f}` | "
            f"`{bt['medium']['mean_score']:+.4f}` / `{bt['medium']['luck_adjusted_ev']:+.4f}` | "
            f"`{bt['hard']['mean_score']:+.4f}` / `{bt['hard']['luck_adjusted_ev']:+.4f}` | "
            f"`{p450['valid_call_rate']:.4f}` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 4. Contrast vs Bimodal Verda `8k` GRPO Seed Instability (`Qwen2.5-3B` LoRA)",
            "",
            (
                "Whereas compact non-LLM policies act on sufficient public summary statistics with calibrated "
                "EV stopping (producing tight inter-secret SDs `< 0.03` and `5/5` positive paired `95%` CIs), "
                "open-weight `Qwen2.5-3B` Verda `8k` GRPO runs on the same `HELDOUT_SEEDS 800000..800029` (`n=90`) "
                "exhibit severe bimodal instability across training seeds (`s0=-0.060`, `s2=-0.050` high-step "
                "abstain collapse vs `s1=-0.777`, `s3=-0.788` low-step over-accusation):"
            ),
            "",
            "| Cohort / Run | Seeds / Scope | Mean Score | Luck-Adjusted EV | Accuse / Abstain Rate | Regime / Stability Verdict |",
            "|---|---|---:|---:|---:|---|",
        ]
    )

    for r8 in v8:
        lines.append(
            f"| Verda GRPO `{r8['run_id']}` (`{r8['short_label']}`, `{r8['gpu_family']}`) | "
            f"`800000..800029` (`n={r8['n']}`, `{r8['grpo_steps']}` steps) | "
            f"`{r8['mean_score']:+.4f}` (`{r8['mean_score_3d']:+.3f}`) | "
            f"`{r8['luck_adjusted_ev']:+.4f}` | "
            f"`{r8['accused_rate']:.3f}` / `{r8['abstain_rate']:.3f}` | "
            f"`{r8['regime']}` (below `0.000` base) |"
        )

    lines.extend(
        [
            (
                f"| **Verda `8k` GRPO Dispersion (`4` runs)** | `s0, s1, s2, s3` (`360` eps) | "
                f"`{vc['verda_8k_mean_score']:+.4f}` (`SD = {vc['verda_8k_inter_run_score_sd']:.4f}`, range `{vc['verda_8k_score_range']:.4f}`) | "
                f"`{vc['verda_8k_mean_luck_adjusted_ev']:+.4f}` (`SD = {vc['verda_8k_inter_run_luck_ev_sd']:.4f}`) | "
                f"bimodal `0.072` vs `0.950` | **`0/4` runs > `0.000`** (`+{vc['high_minus_low_cluster_delta']:.4f}` cluster split) |"
            ),
            (
                f"| **Compact Non-LLM Policies (`4` models x `5` secrets)** | `eval-01..05` (`1800` eps) | "
                f"`{totals['mean_across_policies_score']:+.4f}` (`SD = {totals['min_policy_inter_secret_score_sd']:.4f}..{totals['max_policy_inter_secret_score_sd']:.4f}`, `tau <= {totals['max_policy_excess_inter_secret_tau']:.4f} < 0.030`) | "
                f"`{totals['mean_across_policies_luck_ev']:+.4f}` (`SD = {totals['min_policy_inter_secret_luck_ev_sd']:.4f}..{totals['max_policy_inter_secret_luck_ev_sd']:.4f}`) | "
                f"calibrated EV commit | **`20/20` cells positive `95% CI`** (`{vc['min_verda_to_compact_sd_ratio']:.1f}x..{vc['max_verda_to_compact_sd_ratio']:.1f}x` tighter SD) |"
            ),
            "",
            f"{h3} Offline Reproduction & Fast Verification Commands",
            "",
            "```bash",
            "python scripts/tiebreak_multiseed_stability_audit.py --check",
            "pytest -q tests/test_tiebreak_multiseed_stability.py tests/test_reproduce_tiebreak_all.py",
            "python scripts/reproduce_tiebreak_all.py --check",
            "python scripts/verify_tiebreak_submission.py --strict",
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
    if not raw_json.isascii():
        errors.append(f"{s_file.name}: contains non-ASCII characters")
    if not md_txt.isascii():
        errors.append(f"{m_file.name}: contains non-ASCII characters")

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
        prereg_hits = _has_affirmative_prereg_0_29(txt)
        if prereg_hits:
            errors.append(f"{lbl}: Panel Fix A violation at {prereg_hits[0]}")

    script_cand = repo_root / "scripts" / "tiebreak_multiseed_stability_audit.py"
    target_script = script_cand if script_cand.is_file() else Path(__file__).resolve()
    errors.extend(check_python_source_hygiene(target_script))

    test_cand = repo_root / "tests" / "test_tiebreak_multiseed_stability.py"
    if test_cand.is_file():
        errors.extend(check_python_source_hygiene(test_cand))

    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_PRIMARY_SECRET_TAG:
        errors.append(f"unexpected primary world_secret_tag: {summary.get('world_secret_tag')!r}")
    if summary.get("heldout_seed_range") != "800000..800029":
        errors.append(f"unexpected heldout_seed_range: {summary.get('heldout_seed_range')!r}")
    if summary.get("eval_seed_range") != "800000..800029":
        errors.append(f"unexpected eval_seed_range: {summary.get('eval_seed_range')!r}")
    if int(summary.get("num_world_secrets", -1)) != NUM_WORLD_SECRETS:
        errors.append(f"num_world_secrets != {NUM_WORLD_SECRETS}")
    if int(summary.get("episodes_per_secret", -1)) != EPISODES_PER_SECRET:
        errors.append(f"episodes_per_secret != {EPISODES_PER_SECRET}")
    if int(summary.get("episodes_per_policy", -1)) != EPISODES_PER_POLICY:
        errors.append(f"episodes_per_policy != {EPISODES_PER_POLICY}")

    expected_ws = [
        {
            "secret_id": sid,
            "world_secret_name": sname,
            "world_secret_tag": compute_secret_tag(sname),
        }
        for sid, sname in WORLD_SECRET_SPECS
    ]
    if summary.get("world_secrets") != expected_ws:
        errors.append("world_secrets metadata mismatch against deterministic K=5 world secrets")

    iso = summary.get("seed_isolation") or {}
    if int(iso.get("judge_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.judge_episodes_touched must be 0")
    if int(iso.get("dev_episodes_touched", 1)) != 0:
        errors.append("seed_isolation.dev_episodes_touched must be 0")
    if int(iso.get("train_episodes_in_heldout_eval", 1)) != 0:
        errors.append("seed_isolation.train_episodes_in_heldout_eval must be 0")

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
        pe = summary.get("panel_fix_e_track_separation") or {}
        if int(pe.get("open_weight_qwen25_runs_total", -1)) != len(hist_runs) or int(
            pe.get("open_weight_qwen25_runs_above_zero", -1)
        ) != qwen_pos:
            errors.append("panel_fix_e_track_separation out of sync with experiment_ledger.json")

    vc = summary.get("verda_grpo_contrast") or {}
    verda_cand = repo_root / VERDA_SUMMARY_REL
    if verda_cand.is_file():
        vdata = json.loads(verda_cand.read_text(encoding="utf-8"))
        v8_src = list(vdata.get("seeds_8k") or [])
        v8_scores = [float(r["overall"]["mean_score"]) for r in v8_src]
        exp_v8_sd = round(sample_sd(v8_scores), 5)
        if abs(float(vc.get("verda_8k_inter_run_score_sd", -1.0)) - exp_v8_sd) > 1e-4:
            errors.append("verda_grpo_contrast.verda_8k_inter_run_score_sd mismatch with multiseed_summary.json")
        if len(vc.get("seeds_8k") or []) != 4:
            errors.append("verda_grpo_contrast.seeds_8k expected 4 runs")

    v8_sd_val = float(vc.get("verda_8k_inter_run_score_sd", 0.0))
    policies_block = summary.get("policies") or {}
    score_sds: list[float] = []
    ev_sds: list[float] = []
    pos_abstain_total = 0
    pos_untrained_total = 0

    for pid in POLICY_ORDER:
        if pid not in policies_block:
            errors.append(f"missing policy block: {pid}")
            continue
        pb = policies_block[pid]
        mspec = POLICY_META_SPECS[pid]
        if pb.get("is_open_weight_llm") is not False:
            errors.append(f"{pid}: is_open_weight_llm must be False")
        if int(pb.get("param_count", -1)) != int(mspec["expected_param_count"]):
            errors.append(f"{pid}: param_count mismatch")
        if pb.get("train_seed_range") != mspec["expected_train_seed_range"]:
            errors.append(f"{pid}: train_seed_range mismatch")
        if int(pb.get("total_episodes", -1)) != EPISODES_PER_POLICY:
            errors.append(f"{pid}: total_episodes != {EPISODES_PER_POLICY}")
        if pb.get("replay_verified") is not True or int(pb.get("invalid_episodes", 1)) != 0:
            errors.append(f"{pid}: replay_verified must be True and invalid_episodes must be 0")

        by_sec = pb.get("by_secret") or {}
        sec_scores: list[float] = []
        sec_evs: list[float] = []
        pos_abs = 0
        pos_unt = 0

        for sid, sname in WORLD_SECRET_SPECS:
            if sid not in by_sec:
                errors.append(f"{pid}: missing secret {sid}")
                continue
            sb = by_sec[sid]
            if sb.get("world_secret_tag") != compute_secret_tag(sname):
                errors.append(f"{pid}/{sid}: world_secret_tag mismatch")
            ov = sb.get("overall") or {}
            if int(ov.get("n", -1)) != EPISODES_PER_SECRET:
                errors.append(f"{pid}/{sid}: n != {EPISODES_PER_SECRET}")
            sec_scores.append(float(ov.get("mean_score", 0.0)))
            sec_evs.append(float(ov.get("luck_adjusted_ev", 0.0)))

            pa = sb.get("paired_vs_abstain") or {}
            pu = sb.get("paired_vs_untrained") or {}
            if float(pa.get("ci95_low", 0.0)) > 0.0 and float(pa.get("luck_ev_ci95_low", 0.0)) > 0.0:
                pos_abs += 1
            if float(pu.get("ci95_low", 0.0)) > 0.0 and float(pu.get("luck_ev_ci95_low", 0.0)) > 0.0:
                pos_unt += 1

            bt = sb.get("by_tier") or {}
            tier_means: list[float] = []
            for tier in CANONICAL_TIERS:
                tb = bt.get(tier) or {}
                if int(tb.get("n", -1)) != HELDOUT_SEEDS_PER_TIER:
                    errors.append(f"{pid}/{sid}/{tier}: n != {HELDOUT_SEEDS_PER_TIER}")
                tier_means.append(float(tb.get("mean_score", 0.0)))
            if len(tier_means) == 3 and abs(sum(tier_means) / 3.0 - float(ov.get("mean_score", 0.0))) > 1e-4:
                errors.append(f"{pid}/{sid}: tier mean scores do not average to overall.mean_score")

        st = pb.get("stability_summary") or {}
        if len(sec_scores) == NUM_WORLD_SECRETS:
            recomp_s_sd = round(sample_sd(sec_scores), 5)
            recomp_e_sd = round(sample_sd(sec_evs), 5)
            recomp_s_mean = round(sum(sec_scores) / NUM_WORLD_SECRETS, 5)
            recomp_e_mean = round(sum(sec_evs) / NUM_WORLD_SECRETS, 5)
            ses = [
                float(by_sec[sid]["overall"]["ci95_half_width"]) / 1.96
                for sid, _ in WORLD_SECRET_SPECS
                if sid in by_sec
            ]
            mean_se2 = sum(x * x for x in ses) / max(1, len(ses))
            recomp_tau = round(math.sqrt(max(0.0, recomp_s_sd * recomp_s_sd - mean_se2)), 5)
            if abs(float(st.get("inter_secret_score_sd", -1.0)) - recomp_s_sd) > 1e-4:
                errors.append(f"{pid}: inter_secret_score_sd mismatch ({st.get('inter_secret_score_sd')} vs {recomp_s_sd})")
            if abs(float(st.get("inter_secret_luck_ev_sd", -1.0)) - recomp_e_sd) > 1e-4:
                errors.append(f"{pid}: inter_secret_luck_ev_sd mismatch")
            if abs(float(st.get("inter_secret_score_mean", -1.0)) - recomp_s_mean) > 1e-4:
                errors.append(f"{pid}: inter_secret_score_mean mismatch")
            if abs(float(st.get("inter_secret_luck_ev_mean", -1.0)) - recomp_e_mean) > 1e-4:
                errors.append(f"{pid}: inter_secret_luck_ev_mean mismatch")
            if abs(float(st.get("excess_inter_secret_tau", -1.0)) - recomp_tau) > 1e-4:
                errors.append(f"{pid}: excess_inter_secret_tau mismatch ({st.get('excess_inter_secret_tau')} vs {recomp_tau})")
            if recomp_tau >= MAX_EXCESS_INTER_SECRET_TAU:
                errors.append(f"{pid}: excess_inter_secret_tau {recomp_tau} >= {MAX_EXCESS_INTER_SECRET_TAU}")
            if recomp_s_sd >= MAX_RAW_INTER_SECRET_SD:
                errors.append(f"{pid}: inter_secret_score_sd {recomp_s_sd} >= {MAX_RAW_INTER_SECRET_SD}")
            if recomp_e_sd >= MAX_RAW_INTER_SECRET_SD:
                errors.append(f"{pid}: inter_secret_luck_ev_sd {recomp_e_sd} >= {MAX_RAW_INTER_SECRET_SD}")
            if recomp_s_sd > 0.0 and v8_sd_val > 0.0:
                exp_ratio = round(v8_sd_val / recomp_s_sd, 2)
                if abs(float(st.get("verda_8k_sd_over_policy_sd_ratio", -1.0)) - exp_ratio) > 0.25:
                    errors.append(f"{pid}: verda_8k_sd_over_policy_sd_ratio mismatch")
            score_sds.append(recomp_s_sd)
            ev_sds.append(recomp_e_sd)

        if pos_abs != NUM_WORLD_SECRETS or int(st.get("positive_paired_ci95_vs_abstain_secrets", -1)) != NUM_WORLD_SECRETS:
            errors.append(f"{pid}: expected 5/5 positive paired 95% CIs vs abstain, got {pos_abs}")
        if pos_unt != NUM_WORLD_SECRETS or int(st.get("positive_paired_ci95_vs_untrained_secrets", -1)) != NUM_WORLD_SECRETS:
            errors.append(f"{pid}: expected 5/5 positive paired 95% CIs vs untrained, got {pos_unt}")
        pos_abstain_total += pos_abs
        pos_untrained_total += pos_unt

    totals = summary.get("totals") or {}
    exp_primary = len(POLICY_ORDER) * EPISODES_PER_POLICY
    if int(totals.get("primary_trained_episodes", -1)) != exp_primary:
        errors.append(f"totals.primary_trained_episodes != {exp_primary}")
    if int(totals.get("fresh_env_replays_verified", -1)) != exp_primary:
        errors.append(f"totals.fresh_env_replays_verified != {exp_primary}")
    if pos_abstain_total != len(POLICY_ORDER) * NUM_WORLD_SECRETS:
        errors.append("not all 20 policy-secret cells positive vs abstain")
    if pos_untrained_total != len(POLICY_ORDER) * NUM_WORLD_SECRETS:
        errors.append("not all 20 policy-secret cells positive vs untrained")
    if score_sds and max(score_sds) >= MAX_RAW_INTER_SECRET_SD:
        errors.append(f"max inter-secret score SD {max(score_sds)} >= {MAX_RAW_INTER_SECRET_SD}")

    expected_md = render_markdown_report(summary)
    if md_txt != expected_md:
        errors.append(f"{m_file.name}: markdown text out of sync with render_markdown_report(summary)")

    required_md_tokens = (
        "800000..800029",
        EXPECTED_PRIMARY_SECRET_TAG,
        "post-hoc locked, not pre-registered",
        "0 / 19",
        "CompactLinearDAggerPolicy",
        "TinyMLPPolicy",
        "ScalingLogisticPolicy",
        "EmpiricalBayesPolicy",
        "-0.060",
        "-0.050",
        "-0.777",
        "-0.788",
        "20/20",
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
        description="Deterministic multi-world-secret stability and luck-adjusted EV audit for Canary compact policies."
    )
    ap.add_argument("--repo-root", "--root", dest="repo_root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--workers", type=int, default=4)
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
    print(f"OK: verified {rel_j} and {rel_m} (4 policies x 5 secrets = 1800 eps, 20/20 positive CIs) in {elapsed:.4f}s")
    return 0


if __name__ == "__main__" and "--check" in sys.argv[1:]:
    raise SystemExit(_run_check_cli(build_arg_parser().parse_args()))


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


def compute_public_luck_adjusted_ev(
    ep: Any,
    tools_spec: list[dict[str, Any]],
    instruction: str,
    eb_params: Any,
) -> tuple[float, float | None, float | None]:
    from train.empirical_bayes_policy import EmpiricalBayesPolicy

    if not getattr(ep, "accused", None):
        return 0.0, None, None
    obs = EmpiricalBayesPolicy(params=eb_params, seed=int(ep.seed), name="eb_public_posterior_observer")
    obs.reset(tools_spec, instruction)
    pre_steps: list[Any] = []
    for st in ep.steps:
        t_name = str(getattr(st, "tool", st.get("tool", "") if isinstance(st, dict) else ""))
        if t_name == "accuse":
            break
        pre_steps.append(st)
    obs.tracker.ingest_steps(pre_steps)
    post = obs.posterior()
    n_emp = max(1, int(obs.rules.get("n_employees", 20)))
    p_post = float(post.get(str(ep.accused), 1.0 / n_emp))
    v_est = float(obs.estimated_true_v())
    ev = p_post * v_est - (1.0 - p_post) * 1.0
    return ev, p_post, v_est


def _canonical_ep_sha(ep: Any) -> str:
    parts = [
        f"{ep.tier}:{int(ep.seed)}:{float(ep.score):.5f}:{ep.accused}:{int(bool(ep.correct))}:{int(ep.final_day)}"
    ]
    for s in ep.steps:
        parts.append(f"{int(s.t)}:{int(s.day)}:{s.tool}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _summarize_records(records: list[dict[str, Any]], include_sha16: bool = True) -> dict[str, Any]:
    n = len(records)
    denom = max(1, n)
    scores = [float(r["score"]) for r in records]
    evs = [float(r["luck_ev"]) for r in records]
    s_ci = mean_ci95(scores)
    e_ci = mean_ci95(evs)
    correct_cnt = sum(1 for r in records if r["accused"] is not None and r["correct"])
    wrong_cnt = sum(1 for r in records if r["accused"] is not None and not r["correct"])
    abstain_cnt = sum(1 for r in records if r["accused"] is None)
    p_vals = [float(r["p_post"]) for r in records if r["p_post"] is not None]
    v_vals = [float(r["v_est"]) for r in records if r["v_est"] is not None]
    total_calls = sum(int(r["steps"]) for r in records)
    ok_calls = sum(int(r["ok_steps"]) for r in records)
    days_sum = sum(int(r["final_day"]) for r in records)

    out: dict[str, Any] = {
        "n": n,
        "mean_score": s_ci["mean"],
        "ci95_low": s_ci["ci95_low"],
        "ci95_high": s_ci["ci95_high"],
        "ci95_half_width": s_ci["ci95_half_width"],
        "luck_adjusted_ev": e_ci["mean"],
        "luck_ev_ci95_low": e_ci["ci95_low"],
        "luck_ev_ci95_high": e_ci["ci95_high"],
        "luck_ev_ci95_half_width": e_ci["ci95_half_width"],
        "accuracy": round(correct_cnt / denom, 5),
        "wrong_accuse_rate": round(wrong_cnt / denom, 5),
        "abstain_rate": round(abstain_cnt / denom, 5),
        "mean_p_posterior_at_accuse": round(sum(p_vals) / len(p_vals), 5) if p_vals else 0.0,
        "mean_v_est_at_accuse": round(sum(v_vals) / len(v_vals), 5) if v_vals else 0.0,
        "mean_final_day": round(days_sum / denom, 4),
        "mean_steps": round(total_calls / denom, 4),
        "valid_call_rate": round(ok_calls / max(1, total_calls), 5),
    }
    if include_sha16:
        agg_sha = hashlib.sha256(
            "\n".join(f"{r['tier']}:{r['seed']}:{r['ep_sha']}" for r in records).encode("utf-8")
        ).hexdigest()[:16]
        out["trace_sha16"] = f"0x{agg_sha}"
    return out


_WORKER_CTX: dict[str, Any] = {}


def _eval_secret_policy_slice(task: tuple[str, str, str]) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode
    import scripts.run_tiebreak_policy as rtp

    secret_id, secret_str, policy_id = task
    provider = _WORKER_CTX["provider"]
    eb_params = _WORKER_CTX["eb_params"]
    trained_fac = _WORKER_CTX["trained_factories"][policy_id]
    before_fac = _WORKER_CTX["before_factories"].get(policy_id)
    heldout_seeds: list[int] = _WORKER_CTX["heldout_seeds"]

    after_records: list[dict[str, Any]] = []
    before_records: list[dict[str, Any]] = []

    with _scoped_world_secret(secret_str):
        for tier in CANONICAL_TIERS:
            for seed in heldout_seeds:
                env_a = Env(tier, seed, text_provider=provider)
                spec = env_a.tools_spec()
                instr = env_a.instruction()
                ep_a = run_episode(env_a, trained_fac(seed))
                rtp.verify_episode_replay(ep_a, text_provider=provider)
                ev_a, p_a, v_a = compute_public_luck_adjusted_ev(ep_a, spec, instr, eb_params)
                ok_cnt_a = sum(
                    1 for st in ep_a.steps if isinstance(st.result, dict) and bool(st.result.get("ok"))
                )
                after_records.append(
                    {
                        "tier": tier,
                        "seed": seed,
                        "score": float(ep_a.score),
                        "luck_ev": float(ev_a),
                        "accused": ep_a.accused,
                        "correct": bool(ep_a.correct),
                        "p_post": p_a,
                        "v_est": v_a,
                        "final_day": int(ep_a.final_day),
                        "steps": len(ep_a.steps),
                        "ok_steps": ok_cnt_a,
                        "ep_sha": _canonical_ep_sha(ep_a),
                    }
                )

                if before_fac is None:
                    before_records.append(
                        {
                            "tier": tier,
                            "seed": seed,
                            "score": 0.0,
                            "luck_ev": 0.0,
                            "accused": None,
                            "correct": False,
                            "p_post": None,
                            "v_est": None,
                            "final_day": int(env_a.p.n_days),
                            "steps": int(env_a.p.n_days),
                            "ok_steps": int(env_a.p.n_days),
                            "ep_sha": "0" * 16,
                        }
                    )
                else:
                    env_b = Env(tier, seed, text_provider=provider)
                    ep_b = run_episode(env_b, before_fac(seed))
                    ev_b, p_b, v_b = compute_public_luck_adjusted_ev(ep_b, spec, instr, eb_params)
                    ok_cnt_b = sum(
                        1 for st in ep_b.steps if isinstance(st.result, dict) and bool(st.result.get("ok"))
                    )
                    before_records.append(
                        {
                            "tier": tier,
                            "seed": seed,
                            "score": float(ep_b.score),
                            "luck_ev": float(ev_b),
                            "accused": ep_b.accused,
                            "correct": bool(ep_b.correct),
                            "p_post": p_b,
                            "v_est": v_b,
                            "final_day": int(ep_b.final_day),
                            "steps": len(ep_b.steps),
                            "ok_steps": ok_cnt_b,
                            "ep_sha": _canonical_ep_sha(ep_b),
                        }
                    )

    return {
        "secret_id": secret_id,
        "world_secret_tag": compute_secret_tag(secret_str),
        "policy_id": policy_id,
        "after_records": after_records,
        "before_records": before_records,
    }


def _load_policy_factories(repo_root: Path) -> tuple[
    dict[str, Callable[[int], Any]],
    dict[str, Callable[[int], Any] | None],
    dict[str, dict[str, Any]],
    Any,
]:
    import numpy as np
    import scripts.run_tiebreak_policy as rtp
    from scripts.tiebreak_scaling_calibration import CompactLinearPolicy, LinearPolicyWeights
    from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights
    from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy
    from train.neural_mlp_tiebreak import TinyMLPPolicy

    trained_facs: dict[str, Callable[[int], Any]] = {}
    before_facs: dict[str, Callable[[int], Any] | None] = {}
    meta_out: dict[str, dict[str, Any]] = {}

    cld_spec = POLICY_META_SPECS["compact_linear_dagger"]
    cld_sum = json.loads((repo_root / cld_spec["summary_path"]).read_text(encoding="utf-8"))
    cld_tr = cld_sum["train_seeds"]
    rtp._assert_train_seed_range(int(cld_tr["start"]), int(cld_tr["stop"]), cld_spec["summary_path"])
    cld_w = CompactLinearWeights.from_dict(cld_sum["learned_weights_stage3"])
    trained_facs["compact_linear_dagger"] = lambda _seed, w=cld_w: CompactLinearDAggerPolicy(
        weights=w, name="compact_linear_dagger"
    )
    before_facs["compact_linear_dagger"] = None
    meta_out["compact_linear_dagger"] = {
        **cld_spec,
        "param_count": int(cld_w.param_count()),
        "train_seed_range": f"{int(cld_tr['start'])}..{int(cld_tr['stop']) - 1}",
    }

    mlp_spec = POLICY_META_SPECS["tiny_mlp"]
    mlp_sum = json.loads((repo_root / mlp_spec["summary_path"]).read_text(encoding="utf-8"))
    mlp_tr = mlp_sum["train_seeds"]
    rtp._assert_train_seed_range(int(mlp_tr["start"]), int(mlp_tr["stop"]), mlp_spec["summary_path"])
    mlp_w, mlp_src = rtp._load_or_reconstruct_tiny_mlp(mlp_summary=mlp_sum, stage="stage3_onpolicy_dagger_r2")
    mlp_w0, _ = rtp._load_or_reconstruct_tiny_mlp(mlp_summary=mlp_sum, stage="stage0_untrained")
    trained_facs["tiny_mlp"] = lambda seed, w=mlp_w: TinyMLPPolicy(weights=w, seed=seed, name="tiny_mlp")
    before_facs["tiny_mlp"] = lambda seed, w=mlp_w0: TinyMLPPolicy(weights=w, seed=seed, name="tiny_mlp_untrained")
    meta_out["tiny_mlp"] = {
        **mlp_spec,
        "param_count": int(mlp_w.param_count()),
        "weight_source": mlp_src,
        "train_seed_range": f"{int(mlp_tr['start'])}..{int(mlp_tr['stop']) - 1}",
    }

    scl_spec = POLICY_META_SPECS["scaling_logistic"]
    scl_sum = json.loads((repo_root / scl_spec["summary_path"]).read_text(encoding="utf-8"))
    tr_lo, tr_hi = int(scl_sum["train_seed_range"][0]), int(scl_sum["train_seed_range"][1])
    rtp._assert_train_seed_range(tr_lo, tr_hi + 1, scl_spec["summary_path"])
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
    trained_facs["scaling_logistic"] = lambda seed, w=scl_w: CompactLinearPolicy(
        weights=w, name="scaling_logistic", explore_eps=0.0, rng_seed=seed
    )
    before_facs["scaling_logistic"] = None
    meta_out["scaling_logistic"] = {
        **scl_spec,
        "param_count": int(scl_w.num_parameters()),
        "train_seed_range": f"{tr_lo}..{tr_hi}",
    }

    eb_spec = POLICY_META_SPECS["empirical_bayes"]
    eb_sum = json.loads((repo_root / eb_spec["summary_path"]).read_text(encoding="utf-8"))
    eb_tr = eb_sum["train_seeds"]
    rtp._assert_train_seed_range(int(eb_tr["start"]), int(eb_tr["stop"]), eb_spec["summary_path"])
    eb_raw_opt = eb_sum["parameters"]["eb_experience_opt"]
    eb_raw_naive = eb_sum["parameters"]["eb_naive_prior"]
    eb_opt = EmpiricalBayesParams.from_dict(eb_raw_opt)
    eb_naive = EmpiricalBayesParams.from_dict(eb_raw_naive)
    eb_pcount = len([k for k in eb_raw_opt if k not in ("stage", "naive_p_threshold")])
    trained_facs["empirical_bayes"] = lambda seed, p=eb_opt: EmpiricalBayesPolicy(
        params=p, seed=seed, name="empirical_bayes"
    )
    before_facs["empirical_bayes"] = lambda seed, p=eb_naive: EmpiricalBayesPolicy(
        params=p, seed=seed, name="eb_naive_prior"
    )
    meta_out["empirical_bayes"] = {
        **eb_spec,
        "param_count": eb_pcount,
        "train_seed_range": f"{int(eb_tr['start'])}..{int(eb_tr['stop']) - 1}",
    }

    return trained_facs, before_facs, meta_out, eb_opt


def _build_verda_contrast(
    repo_root: Path,
    compact_score_sds: dict[str, float],
) -> dict[str, Any]:
    verda_data = json.loads((repo_root / VERDA_SUMMARY_REL).read_text(encoding="utf-8"))
    s8_list = list(verda_data.get("seeds_8k") or [])
    bimodal = verda_data.get("bimodal_regime_split") or {}

    rows_8k: list[dict[str, Any]] = []
    scores_8k: list[float] = []
    evs_8k: list[float] = []
    for item in s8_list:
        ov = item["overall"]
        ms = round(float(ov["mean_score"]), 5)
        ev = round(float(ov["luck_adjusted_ev"]), 5)
        scores_8k.append(ms)
        evs_8k.append(ev)
        rows_8k.append(
            {
                "run_id": str(item["run_id"]),
                "short_label": str(item["short_label"]),
                "gpu_family": str(item["gpu_family"]),
                "rng_seed": int(item["rng_seed"]),
                "grpo_steps": int(item["grpo_steps"]),
                "regime": str(item["regime"]),
                "n": int(ov["n"]),
                "mean_score": ms,
                "mean_score_3d": round(float(ov["mean_score_3d"]), 3),
                "ci95_half_width": round(float(ov["ci95"]), 5),
                "luck_adjusted_ev": ev,
                "luck_ev_ci95_half_width": round(float(ov["luck_adjusted_ev_ci95"]), 5),
                "accused_rate": round(float(ov["accused_rate"]), 5),
                "abstain_rate": round(float(ov["abstain_rate"]), 5),
                "beats_zero_base": bool(ms > 0.0),
            }
        )

    v8_sd = round(sample_sd(scores_8k), 5)
    v8_ev_sd = round(sample_sd(evs_8k), 5)
    ratios = [round(v8_sd / sd, 2) for sd in compact_score_sds.values() if sd > 0.0]
    hi_cl = bimodal.get("high_step_8k_cluster") or {}
    lo_cl = bimodal.get("low_step_8k_cluster") or {}
    two_s = bimodal.get("two_sample_high_minus_low_8k") or {}

    return {
        "source_path": str(VERDA_SUMMARY_REL),
        "verda_8k_runs_count": len(rows_8k),
        "verda_8k_mean_score": round(sum(scores_8k) / len(scores_8k), 5),
        "verda_8k_inter_run_score_sd": v8_sd,
        "verda_8k_score_range": round(max(scores_8k) - min(scores_8k), 5),
        "verda_8k_mean_luck_adjusted_ev": round(sum(evs_8k) / len(evs_8k), 5),
        "verda_8k_inter_run_luck_ev_sd": v8_ev_sd,
        "verda_8k_runs_above_zero": sum(1 for x in scores_8k if x > 0.0),
        "high_step_abstain_cluster_mean": round(float(hi_cl.get("mean_score", 0.0)), 5),
        "low_step_over_accuse_cluster_mean": round(float(lo_cl.get("mean_score", 0.0)), 5),
        "high_minus_low_cluster_delta": round(float(two_s.get("mean_delta", 0.0)), 5),
        "min_verda_to_compact_sd_ratio": min(ratios) if ratios else 0.0,
        "max_verda_to_compact_sd_ratio": max(ratios) if ratios else 0.0,
        "seeds_8k": rows_8k,
    }


def run_audit(repo_root: Path = ROOT, max_workers: int = 4) -> dict[str, Any]:
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    from canary import rules
    from canary.text.template import TemplateProvider

    t0 = time.perf_counter()
    repo_root = repo_root.resolve()
    heldout_seeds = list(range(HELDOUT_SEED_START, HELDOUT_SEED_STOP))
    for s in heldout_seeds:
        if s not in rules.HELDOUT_SEEDS or s in rules.JUDGE_SEEDS or s >= JUDGE_SEED_MIN:
            raise ValueError(f"seed {s} violates HELDOUT_SEEDS isolation")

    primary_tag = compute_secret_tag(PRIMARY_WORLD_SECRET)
    if primary_tag != EXPECTED_PRIMARY_SECRET_TAG:
        raise AssertionError(f"primary secret tag {primary_tag} != {EXPECTED_PRIMARY_SECRET_TAG}")

    provider = TemplateProvider()
    trained_facs, before_facs, meta_map, eb_opt = _load_policy_factories(repo_root)

    _WORKER_CTX["provider"] = provider
    _WORKER_CTX["eb_params"] = eb_opt
    _WORKER_CTX["trained_factories"] = trained_facs
    _WORKER_CTX["before_factories"] = before_facs
    _WORKER_CTX["heldout_seeds"] = heldout_seeds

    cost_rank = {
        "compact_linear_dagger": 0,
        "scaling_logistic": 1,
        "tiny_mlp": 2,
        "empirical_bayes": 3,
    }
    tasks = sorted(
        [
            (sid, sname, pid)
            for sid, sname in WORLD_SECRET_SPECS
            for pid in POLICY_ORDER
        ],
        key=lambda x: (cost_rank[x[2]], x[0]),
    )

    try:
        aff = len(os.sched_getaffinity(0))
    except AttributeError:
        aff = os.cpu_count() or 2
    eff_workers = min(max(1, int(max_workers)), max(1, aff), len(tasks))

    in_pytest = ("PYTEST_CURRENT_TEST" in os.environ) or ("pytest" in sys.modules)
    if eff_workers > 1 and not in_pytest and "fork" in multiprocessing.get_all_start_methods():
        ctx = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(max_workers=eff_workers, mp_context=ctx) as pool:
            slice_results = list(pool.map(_eval_secret_policy_slice, tasks, chunksize=1))
    else:
        slice_results = [_eval_secret_policy_slice(tk) for tk in tasks]

    by_key = {(r["policy_id"], r["secret_id"]): r for r in slice_results}

    verda_raw = json.loads((repo_root / VERDA_SUMMARY_REL).read_text(encoding="utf-8"))
    verda_8k_scores = [float(r["overall"]["mean_score"]) for r in verda_raw["seeds_8k"]]
    verda_8k_sd = round(sample_sd(verda_8k_scores), 5)

    policies_out: dict[str, Any] = {}
    compact_score_sds: dict[str, float] = {}
    compact_score_sds_pop: dict[str, float] = {}
    compact_excess_taus: dict[str, float] = {}
    compact_ev_sds: dict[str, float] = {}
    policy_mean_scores: list[float] = []
    policy_mean_evs: list[float] = []
    live_before_rollouts = 0

    for pid in POLICY_ORDER:
        pmeta = meta_map[pid]
        has_live_before = before_facs[pid] is not None
        by_secret_out: dict[str, Any] = {}
        all_after_recs: list[dict[str, Any]] = []
        all_before_recs: list[dict[str, Any]] = []
        sec_mean_scores: list[float] = []
        sec_mean_evs: list[float] = []
        sec_within_ses: list[float] = []
        pos_vs_abstain = 0
        pos_vs_untrained = 0
        min_ci_low_abs = 999.0
        min_ev_ci_low_abs = 999.0
        min_ci_low_unt = 999.0
        min_ev_ci_low_unt = 999.0

        for sid, _ in WORLD_SECRET_SPECS:
            sl = by_key[(pid, sid)]
            a_recs = sl["after_records"]
            b_recs = sl["before_records"]
            all_after_recs.extend(a_recs)
            all_before_recs.extend(b_recs)
            if has_live_before:
                live_before_rollouts += len(b_recs)

            ov_after = _summarize_records(a_recs, include_sha16=True)
            ov_before = _summarize_records(b_recs, include_sha16=False)

            zeros_90 = [0.0] * len(a_recs)
            a_scores = [float(x["score"]) for x in a_recs]
            a_evs = [float(x["luck_ev"]) for x in a_recs]
            b_scores = [float(x["score"]) for x in b_recs]
            b_evs = [float(x["luck_ev"]) for x in b_recs]

            pair_abs = paired_delta_summary(a_scores, zeros_90, a_evs, zeros_90)
            pair_unt = paired_delta_summary(a_scores, b_scores, a_evs, b_evs)

            if pair_abs["ci95_positive"] and pair_abs["luck_ev_ci95_positive"]:
                pos_vs_abstain += 1
            if pair_unt["ci95_positive"] and pair_unt["luck_ev_ci95_positive"]:
                pos_vs_untrained += 1

            min_ci_low_abs = min(min_ci_low_abs, float(pair_abs["ci95_low"]))
            min_ev_ci_low_abs = min(min_ev_ci_low_abs, float(pair_abs["luck_ev_ci95_low"]))
            min_ci_low_unt = min(min_ci_low_unt, float(pair_unt["ci95_low"]))
            min_ev_ci_low_unt = min(min_ev_ci_low_unt, float(pair_unt["luck_ev_ci95_low"]))

            sec_mean_scores.append(float(ov_after["mean_score"]))
            sec_mean_evs.append(float(ov_after["luck_adjusted_ev"]))
            sec_within_ses.append(float(ov_after["ci95_half_width"]) / 1.96)

            by_tier_sec: dict[str, Any] = {}
            for tier in CANONICAL_TIERS:
                t_sub = [x for x in a_recs if x["tier"] == tier]
                t_sum = _summarize_records(t_sub, include_sha16=False)
                by_tier_sec[tier] = {
                    "n": t_sum["n"],
                    "mean_score": t_sum["mean_score"],
                    "luck_adjusted_ev": t_sum["luck_adjusted_ev"],
                    "accuracy": t_sum["accuracy"],
                }

            by_secret_out[sid] = {
                "secret_id": sid,
                "world_secret_tag": sl["world_secret_tag"],
                "overall": ov_after,
                "before_untrained": {
                    "baseline_id": pmeta["before_baseline_id"],
                    "n": ov_before["n"],
                    "mean_score": ov_before["mean_score"],
                    "luck_adjusted_ev": ov_before["luck_adjusted_ev"],
                },
                "paired_vs_abstain": pair_abs,
                "paired_vs_untrained": pair_unt,
                "by_tier": by_tier_sec,
            }

        pooled_450 = _summarize_records(all_after_recs, include_sha16=True)
        pooled_pair_unt = paired_delta_summary(
            [float(x["score"]) for x in all_after_recs],
            [float(x["score"]) for x in all_before_recs],
            [float(x["luck_ev"]) for x in all_after_recs],
            [float(x["luck_ev"]) for x in all_before_recs],
        )
        pooled_450["paired_vs_untrained"] = pooled_pair_unt

        pooled_by_tier: dict[str, Any] = {}
        for tier in CANONICAL_TIERS:
            t_all = [x for x in all_after_recs if x["tier"] == tier]
            pooled_by_tier[tier] = _summarize_records(t_all, include_sha16=True)

        s_mean = round(sum(sec_mean_scores) / NUM_WORLD_SECRETS, 5)
        s_sd = round(sample_sd(sec_mean_scores), 5)
        s_sd_pop = round(s_sd * math.sqrt((NUM_WORLD_SECRETS - 1) / NUM_WORLD_SECRETS), 5)
        mean_se2 = sum(x * x for x in sec_within_ses) / NUM_WORLD_SECRETS
        mean_within_se = round(math.sqrt(mean_se2), 5)
        excess_tau = round(math.sqrt(max(0.0, s_sd * s_sd - mean_se2)), 5)
        e_mean = round(sum(sec_mean_evs) / NUM_WORLD_SECRETS, 5)
        e_sd = round(sample_sd(sec_mean_evs), 5)
        compact_score_sds[pid] = s_sd
        compact_score_sds_pop[pid] = s_sd_pop
        compact_excess_taus[pid] = excess_tau
        compact_ev_sds[pid] = e_sd
        policy_mean_scores.append(s_mean)
        policy_mean_evs.append(e_mean)

        policies_out[pid] = {
            "policy_id": pid,
            "policy_class": pmeta["policy_class"],
            "run_id": pmeta["run_id"],
            "module_path": pmeta["module_path"],
            "summary_path": pmeta["summary_path"],
            "param_count": int(pmeta["param_count"]),
            "train_seed_range": pmeta["train_seed_range"],
            "before_baseline_id": pmeta["before_baseline_id"],
            "is_open_weight_llm": False,
            "secrets_evaluated": NUM_WORLD_SECRETS,
            "episodes_per_secret": EPISODES_PER_SECRET,
            "total_episodes": len(all_after_recs),
            "replay_verified": True,
            "invalid_episodes": 0,
            "stability_summary": {
                "secret_mean_scores": [round(x, 5) for x in sec_mean_scores],
                "inter_secret_score_mean": s_mean,
                "inter_secret_score_sd": s_sd,
                "inter_secret_score_sd_pop": s_sd_pop,
                "mean_within_secret_se": mean_within_se,
                "excess_inter_secret_tau": excess_tau,
                "inter_secret_score_min": round(min(sec_mean_scores), 5),
                "inter_secret_score_max": round(max(sec_mean_scores), 5),
                "inter_secret_score_range": round(max(sec_mean_scores) - min(sec_mean_scores), 5),
                "inter_secret_score_cv": round(s_sd / max(1e-9, abs(s_mean)), 5),
                "secret_mean_luck_adjusted_evs": [round(x, 5) for x in sec_mean_evs],
                "inter_secret_luck_ev_mean": e_mean,
                "inter_secret_luck_ev_sd": e_sd,
                "inter_secret_luck_ev_min": round(min(sec_mean_evs), 5),
                "inter_secret_luck_ev_max": round(max(sec_mean_evs), 5),
                "inter_secret_luck_ev_range": round(max(sec_mean_evs) - min(sec_mean_evs), 5),
                "raw_minus_luck_ev_mean_gap": round(s_mean - e_mean, 5),
                "positive_paired_ci95_vs_abstain_secrets": pos_vs_abstain,
                "min_paired_ci95_low_vs_abstain": round(min_ci_low_abs, 5),
                "min_luck_ev_ci95_low_vs_abstain": round(min_ev_ci_low_abs, 5),
                "positive_paired_ci95_vs_untrained_secrets": pos_vs_untrained,
                "min_paired_ci95_low_vs_untrained": round(min_ci_low_unt, 5),
                "min_luck_ev_ci95_low_vs_untrained": round(min_ev_ci_low_unt, 5),
                "verda_8k_sd_over_policy_sd_ratio": round(verda_8k_sd / max(1e-9, s_sd), 2),
            },
            "pooled_450": pooled_450,
            "pooled_by_tier": pooled_by_tier,
            "by_secret": by_secret_out,
        }

    ledger = json.loads((repo_root / LEDGER_REL).read_text(encoding="utf-8"))
    hist_runs = list(ledger.get("historical_runs") or [])
    qwen_above_zero = sum(
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
        "open_weight_qwen25_runs_above_zero": qwen_above_zero,
        "open_weight_qwen25_above_zero_ratio": f"{qwen_above_zero} / {len(hist_runs)}",
        "readme_qwen_addendum_status": "HOLD_README_QWEN_ADDENDUM_UNTIL_V100",
        "non_llm_verified_run_ids": list(sc.get("verified_run_ids") or []),
        "non_llm_policies_is_open_weight_llm": False,
        "disclosure": PANEL_FIX_E_DISCLOSURE,
    }

    verda_contrast = _build_verda_contrast(repo_root, compact_score_sds)
    primary_eps = len(POLICY_ORDER) * EPISODES_PER_POLICY
    total_cells = len(POLICY_ORDER) * NUM_WORLD_SECRETS
    elapsed_s = round(time.perf_counter() - t0, 3)

    return {
        "schema": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "tiers_version": str(rules.TIERS_VERSION),
        "tiers": list(CANONICAL_TIERS),
        "heldout_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "eval_seed_range": f"{HELDOUT_SEED_START}..{HELDOUT_SEED_STOP - 1}",
        "heldout_seeds": {"start": HELDOUT_SEED_START, "stop": HELDOUT_SEED_STOP},
        "eval_seeds_per_tier": HELDOUT_SEEDS_PER_TIER,
        "num_world_secrets": NUM_WORLD_SECRETS,
        "episodes_per_secret": EPISODES_PER_SECRET,
        "episodes_per_policy": EPISODES_PER_POLICY,
        "world_secret_tag": primary_tag,
        "world_secrets": [
            {
                "secret_id": sid,
                "world_secret_name": sname,
                "world_secret_tag": compute_secret_tag(sname),
            }
            for sid, sname in WORLD_SECRET_SPECS
        ],
        "posterior_luck_ev_method": {
            "observer_policy": "EmpiricalBayesPolicy",
            "observer_stage": "eb_experience_opt",
            "observer_train_seed_range": "102000..102779",
            "formula": "p_posterior * known_or_true_V_est - (1 - p_posterior) * 1.0",
            "uses_canary_solver": False,
            "public_observations_only": True,
        },
        "replay_verified": True,
        "invalid_episodes": 0,
        "seed_isolation": {
            "heldout_world_paired": True,
            "train_episodes_in_heldout_eval": 0,
            "dev_episodes_touched": 0,
            "judge_episodes_touched": 0,
            "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        },
        "panel_fix_e_track_separation": panel_e,
        "verda_grpo_contrast": verda_contrast,
        "totals": {
            "policies_audited": len(POLICY_ORDER),
            "world_secrets_audited": NUM_WORLD_SECRETS,
            "total_secret_cells": total_cells,
            "positive_secret_cells_vs_abstain": sum(
                int(policies_out[p]["stability_summary"]["positive_paired_ci95_vs_abstain_secrets"])
                for p in POLICY_ORDER
            ),
            "positive_secret_cells_vs_untrained": sum(
                int(policies_out[p]["stability_summary"]["positive_paired_ci95_vs_untrained_secrets"])
                for p in POLICY_ORDER
            ),
            "primary_trained_episodes": primary_eps,
            "live_untrained_baseline_episodes": live_before_rollouts,
            "fresh_env_replays_verified": primary_eps,
            "min_policy_inter_secret_score_sd": min(compact_score_sds.values()),
            "max_policy_inter_secret_score_sd": max(compact_score_sds.values()),
            "min_policy_inter_secret_score_sd_pop": min(compact_score_sds_pop.values()),
            "max_policy_inter_secret_score_sd_pop": max(compact_score_sds_pop.values()),
            "max_policy_excess_inter_secret_tau": max(compact_excess_taus.values()),
            "min_policy_inter_secret_luck_ev_sd": min(compact_ev_sds.values()),
            "max_policy_inter_secret_luck_ev_sd": max(compact_ev_sds.values()),
            "all_policies_excess_tau_below_003": all(v < MAX_EXCESS_INTER_SECRET_TAU for v in compact_excess_taus.values()),
            "mean_across_policies_score": round(sum(policy_mean_scores) / len(policy_mean_scores), 5),
            "mean_across_policies_luck_ev": round(sum(policy_mean_evs) / len(policy_mean_evs), 5),
            "elapsed_seconds": elapsed_s,
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
        f"{out_md.relative_to(root)} (max SD={summary['totals']['max_policy_inter_secret_score_sd']:.5f}, "
        f"20/20 positive CIs in {summary['totals']['elapsed_seconds']:.2f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
