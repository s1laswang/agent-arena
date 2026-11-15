"""Standalone keyless evaluation CLI for Canary compact tiebreak policies."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator

for _blas_key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_key, "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_ID = "canary.tiebreak.policy_eval.v1"
CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
CHECK_SEEDS: tuple[int, ...] = (800_000, 800_001, 800_002)
DEFAULT_SEEDS_SPEC = "800000-800029"
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"

TRAINED_POLICIES: tuple[str, ...] = (
    "empirical_bayes",
    "compact_linear_dagger",
    "tiny_mlp",
    "scaling_logistic",
)
BASELINE_POLICIES: tuple[str, ...] = (
    "naive_prior",
    "abstain",
)
SUPPORTED_POLICIES: tuple[str, ...] = TRAINED_POLICIES + BASELINE_POLICIES
PAIRED_BEFORE_CHOICES: tuple[str, ...] = (
    "auto",
    "naive_prior",
    "abstain",
    "untrained",
)

EB_SUMMARY_REL = Path("results/tiebreak/empirical_bayes/summary.json")
DAGGER_SUMMARY_REL = Path("results/tiebreak/dagger_ablation/summary.json")
MLP_SUMMARY_REL = Path("results/tiebreak/neural_mlp_dagger/mlp_summary.json")
SCALING_SUMMARY_REL = Path("results/tiebreak/scaling/scaling_summary.json")

SEED_RANGE_RE = re.compile(r"^\s*(-?\d+)\s*(?:\.\.|-)\s*(-?\d+)\s*$")
MAX_SLICE_SEEDS = 10_000

FORBIDDEN_SECRET_PLACEHOLDERS: frozenset[str] = frozenset({
    "",
    "none",
    "null",
    "unset",
    "unpaired",
    "unknown",
    "missing",
    "todo",
    "na",
    "n/a",
    "public",
    "random",
    "urandom",
    "os.urandom",
    "per_process",
    "per-process",
    "proc_secret",
    "ephemeral",
})
FORBIDDEN_SECRET_PREFIXES: tuple[str, ...] = (
    "unset",
    "unpaired",
    "proc:",
    "proc_",
    "per_process",
    "per-process",
    "random:",
    "random_",
    "urandom",
    "ephemeral",
)

_MLP_WEIGHT_MEMO: dict[tuple[str, str], Any] = {}


class AbstainPolicy:
    name = "abstain"

    def __init__(self, seed: int = 0, name: str = "abstain") -> None:
        self.seed = int(seed)
        self.name = str(name)
        self.ready = False

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        _ = (tools_spec, instruction)
        self.ready = True

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        _ = history
        return ("advance_day", {})


def _validate_secret_string(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    low = cleaned.lower()
    if len(cleaned) < 6 or low in FORBIDDEN_SECRET_PLACEHOLDERS:
        return None
    if low.startswith(FORBIDDEN_SECRET_PREFIXES):
        return None
    return cleaned


def compute_secret_tag(secret: str) -> str:
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _assert_train_seed_range(start: int, stop: int, label: str) -> None:
    from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

    if not isinstance(start, int) or not isinstance(stop, int) or isinstance(start, bool) or isinstance(stop, bool):
        raise ValueError(f"{label}: train seed bounds must be integers")
    if start >= stop:
        raise ValueError(f"{label}: empty train seed range [{start}, {stop})")
    for seed in range(start, stop):
        if (
            seed in DEV_SEEDS
            or seed in HELDOUT_SEEDS
            or seed in JUDGE_SEEDS
            or seed not in TRAIN_SEEDS
            or not (100_000 <= seed < 200_000)
        ):
            raise ValueError(f"{label}: train seed {seed} violates TRAIN_SEEDS [100000, 200000) isolation")


def parse_tiers(spec: str) -> list[str]:
    from canary.rules import TIERS, TRACKS

    cleaned = (spec or "").strip().lower()
    if not cleaned:
        raise ValueError("--tier must be non-empty")
    if cleaned == "all":
        return list(CANONICAL_TIERS)
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if not parts:
        raise ValueError(f"invalid --tier specification {spec!r}")
    expanded: list[str] = []
    for part in parts:
        if part == "all":
            for t_name in CANONICAL_TIERS:
                if t_name not in expanded:
                    expanded.append(t_name)
        elif part in TIERS or part in TRACKS:
            if part not in expanded:
                expanded.append(part)
        else:
            raise ValueError(f"unknown tier {part!r}; expected easy, medium, hard, or all")
    return expanded


def parse_seed_slice(spec: str) -> list[int]:
    from canary.rules import JUDGE_SEEDS

    cleaned = str(spec or "").strip()
    if not cleaned:
        raise ValueError("--seeds must be non-empty")

    presets: dict[str, list[int]] = {
        "heldout3": [800_000, 800_001, 800_002],
        "heldout10": list(range(800_000, 800_010)),
        "heldout30": list(range(800_000, 800_030)),
        "heldout60": list(range(800_000, 800_060)),
        "heldout": list(range(800_000, 800_200)),
        "heldout200": list(range(800_000, 800_200)),
        "dev20": list(range(0, 20)),
        "dev30": list(range(0, 30)),
        "judge": list(JUDGE_SEEDS),
    }
    if cleaned in presets:
        return presets[cleaned]

    for prefix, base in (("heldout:", 800_000), ("dev:", 0), ("n:", 0)):
        if cleaned.startswith(prefix):
            raw_n = cleaned[len(prefix) :].strip()
            try:
                count = int(raw_n)
            except ValueError as exc:
                raise ValueError(f"invalid seed count in {spec!r}") from exc
            if count <= 0 or count > MAX_SLICE_SEEDS:
                raise ValueError(f"seed count {count} in {spec!r} must be in 1..{MAX_SLICE_SEEDS}")
            return list(range(base, base + count))

    seeds: list[int] = []
    for part in cleaned.split(","):
        tok = part.strip()
        if not tok:
            raise ValueError(f"empty token in --seeds {spec!r}")
        m_rng = SEED_RANGE_RE.match(tok)
        if m_rng:
            lo = int(m_rng.group(1))
            hi = int(m_rng.group(2))
            if hi < lo:
                raise ValueError(f"descending seed range {tok!r} in --seeds")
            if len(seeds) + (hi - lo + 1) > MAX_SLICE_SEEDS:
                raise ValueError(f"--seeds {spec!r} exceeds maximum slice size {MAX_SLICE_SEEDS}")
            seeds.extend(range(lo, hi + 1))
        else:
            try:
                val = int(tok)
            except ValueError as exc:
                raise ValueError(f"unrecognized seed token {tok!r} in --seeds {spec!r}") from exc
            if len(seeds) + 1 > MAX_SLICE_SEEDS:
                raise ValueError(f"--seeds {spec!r} exceeds maximum slice size {MAX_SLICE_SEEDS}")
            seeds.append(val)

    if not seeds:
        raise ValueError(f"--seeds {spec!r} produced no seeds")
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"--seeds {spec!r} contains duplicate seeds")
    return seeds


def validate_and_resolve_seeds(
    seeds: list[int],
    allow_judge_smoke: bool = False,
    explicit_world_secret: str | None = None,
    ambient_world_secret: str | None = None,
) -> tuple[str, str | None, str, str]:
    from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

    if not seeds:
        raise ValueError("seeds list must be non-empty")
    if len(set(seeds)) != len(seeds):
        raise ValueError("seeds list must not contain duplicates")

    splits: set[str] = set()
    for raw_seed in seeds:
        if not isinstance(raw_seed, int) or isinstance(raw_seed, bool):
            raise ValueError(f"seed must be integer, got {raw_seed!r}")
        if raw_seed < 0:
            raise ValueError(f"negative seed {raw_seed} is not permitted")
        if raw_seed >= 900_000 or raw_seed in JUDGE_SEEDS:
            if not allow_judge_smoke:
                raise ValueError(
                    f"seed {raw_seed} is in JUDGE_SEEDS (>= 900000); blocked unless "
                    "--allow-judge-smoke with explicit CANARY_WORLD_SECRET is passed"
                )
            if raw_seed not in JUDGE_SEEDS:
                raise ValueError(
                    f"seed {raw_seed} >= 900000 lies outside canonical JUDGE_SEEDS [900000, 900040)"
                )
            splits.add("judge_smoke")
        elif raw_seed in TRAIN_SEEDS or (100_000 <= raw_seed < 200_000):
            raise ValueError(
                f"seed {raw_seed} is in TRAIN_SEEDS [100000, 200000); "
                "evaluation CLI strictly forbids evaluating on training seeds"
            )
        elif raw_seed in HELDOUT_SEEDS and (800_000 <= raw_seed < 800_200):
            splits.add("heldout")
        elif raw_seed in DEV_SEEDS and (0 <= raw_seed < 10_000):
            splits.add("dev")
        else:
            raise ValueError(
                f"seed {raw_seed} is outside allowed HELDOUT_SEEDS [800000, 800199] and DEV_SEEDS [0, 9999]"
            )

    if len(splits) > 1:
        raise ValueError(f"cannot mix seed splits {sorted(splits)} in a single evaluation run")

    split_name = next(iter(splits))
    explicit_clean = _validate_secret_string(explicit_world_secret)
    if explicit_world_secret is not None and explicit_clean is None:
        raise ValueError("invalid --world-secret; must be >= 6 non-placeholder characters")
    ambient_clean = _validate_secret_string(ambient_world_secret)

    if split_name == "judge_smoke":
        chosen_secret = explicit_clean or ambient_clean
        if chosen_secret is None:
            raise ValueError(
                "JUDGE_SEEDS smoke run requires an explicit valid CANARY_WORLD_SECRET "
                "(via environment variable or --world-secret)"
            )
        note = (
            "Explicit judge smoke slice authorized with caller-supplied CANARY_WORLD_SECRET; "
            "compact policies evaluated here are non-LLM structured models strictly separated from open-weight LLMs."
        )
        return split_name, chosen_secret, compute_secret_tag(chosen_secret), note

    if split_name == "dev":
        note = (
            "DEV_SEEDS [0, 9999] use public worlds; where DEV_SEEDS 0..29 appear in Canary frontier reports "
            "they are post-hoc locked, not pre-registered (Panel Fix A). Compact policies evaluated here are "
            "non-LLM structured models strictly separated from open-weight Qwen2.5 LoRA runs (Panel Fix E)."
        )
        return split_name, None, "public", note

    chosen_secret = explicit_clean or ambient_clean or HELDOUT_WORLD_SECRET
    note = (
        "Disjoint HELDOUT_SEEDS [800000, 800199] evaluated under deterministic CANARY_WORLD_SECRET; "
        "0 TRAIN_SEEDS and 0 JUDGE_SEEDS touched. Compact policies evaluated here are non-LLM structured "
        "models strictly separated from open-weight Qwen2.5 LoRA runs (Panel Fix E)."
    )
    return split_name, chosen_secret, compute_secret_tag(chosen_secret), note


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


def _default_mlp_cache_dir() -> Path:
    preferred = Path("/tmp/opencode")
    if preferred.is_dir() and os.access(preferred, os.W_OK):
        return preferred / "canary_tiebreak_policy_cache"
    return Path(tempfile.gettempdir()) / "canary_tiebreak_policy_cache"


def _load_or_reconstruct_tiny_mlp(
    mlp_summary: dict[str, Any],
    stage: str,
    mlp_ckpt_path: Path | None = None,
) -> tuple[Any, str]:
    import train.neural_mlp_tiebreak as mlp_mod

    tr_obj = mlp_summary["train_seeds"]
    tr_start = int(tr_obj["start"])
    tr_stop = int(tr_obj["stop"])
    _assert_train_seed_range(tr_start, tr_stop, "mlp_summary.json")

    if stage == "stage0_untrained":
        return mlp_mod.init_untrained_weights(rng_seed=tr_start), "deterministic_he_init"

    expected_params = int(mlp_summary["param_count"])
    expected_thr = float(mlp_summary["selected_commit_threshold"])
    memo_key = (f"{tr_start}:{tr_stop}:{expected_params}:{expected_thr:.4f}", stage)
    if mlp_ckpt_path is None and memo_key in _MLP_WEIGHT_MEMO:
        return _MLP_WEIGHT_MEMO[memo_key]

    candidates: list[tuple[Path, str]] = []
    if mlp_ckpt_path is not None:
        if not mlp_ckpt_path.is_file():
            raise FileNotFoundError(f"TinyMLP checkpoint not found: {mlp_ckpt_path}")
        candidates.append((mlp_ckpt_path, "explicit_ckpt_npz"))
    else:
        shared_default = Path(mlp_mod.DEFAULT_CKPT_PATH)
        if (
            shared_default.is_file()
            and tr_start == mlp_mod.TRAIN_SEED_START
            and tr_stop == mlp_mod.TRAIN_SEED_STOP
        ):
            candidates.append((shared_default, "shared_ckpt_npz"))
        cache_tag = hashlib.sha256(memo_key[0].encode("utf-8")).hexdigest()[:12]
        cache_npz = _default_mlp_cache_dir() / f"tiny_mlp_{cache_tag}.npz"
        if cache_npz.is_file():
            candidates.append((cache_npz, "cached_reconstructed_npz"))

    for cand_path, source_label in candidates:
        wt = mlp_mod.load_checkpoint_npz(cand_path, stage=stage)
        if wt.param_count() == expected_params and abs(float(wt.commit_threshold) - expected_thr) <= 1e-4:
            if mlp_ckpt_path is None:
                _MLP_WEIGHT_MEMO[memo_key] = (wt, source_label)
            return wt, source_label
        if mlp_ckpt_path is not None:
            raise ValueError(
                f"checkpoint {cand_path} metadata mismatch against mlp_summary.json "
                f"(params={wt.param_count()} vs {expected_params}, thr={wt.commit_threshold} vs {expected_thr})"
            )

    all_train = list(range(tr_start, tr_stop))
    n_tr = len(all_train)
    stride = 2 if n_tr >= 240 else 1
    c2 = max(3, n_tr // 4)
    c3 = max(5, (3 * n_tr) // 5)
    c4 = max(7, (19 * n_tr) // 20)
    bc_seeds = all_train[:c2]
    d1_seeds = all_train[c2:c3:stride]
    d2_seeds = all_train[c3 : min(c4, n_tr) : stride]
    val_seeds = all_train[c4:] if c4 < n_tr else all_train[-max(2, n_tr // 6) :]

    wt0 = mlp_mod.init_untrained_weights(rng_seed=tr_start)
    _, d_s2 = mlp_mod._collect_solver_trajectories(bc_seeds)
    wt2 = mlp_mod._train_mlp_adam(
        d_s2, wt0, epochs=50, lr=4.5e-3, mode="bc", stage_name="stage2_calibrated_bc", rng_seed=tr_start + 2
    )
    d_r1 = mlp_mod._collect_dagger_rollouts(wt2, d1_seeds, override_premature=True)
    wt_r1 = mlp_mod._train_mlp_adam(
        d_s2 + d_r1, wt2, epochs=45, lr=2.5e-3, mode="dagger", stage_name="dagger_r1", rng_seed=tr_start + 3
    )
    d_r2 = mlp_mod._collect_dagger_rollouts(wt_r1, d2_seeds, override_premature=False)
    wt3_raw = mlp_mod._train_mlp_adam(
        d_s2 + d_r1 + d_r2,
        wt_r1,
        epochs=45,
        lr=1.8e-3,
        mode="dagger",
        stage_name="stage3_onpolicy_dagger_r2",
        rng_seed=tr_start + 4,
    )
    wt3 = mlp_mod._calibrate_threshold([wt3_raw, wt_r1], val_seeds)
    if wt3.param_count() != expected_params:
        raise ValueError(f"reconstructed TinyMLP param_count {wt3.param_count()} != {expected_params}")

    cache_tag = hashlib.sha256(memo_key[0].encode("utf-8")).hexdigest()[:12]
    cache_npz = _default_mlp_cache_dir() / f"tiny_mlp_{cache_tag}.npz"
    try:
        mlp_mod.save_checkpoint_npz(
            cache_npz,
            {
                "stage0_untrained": wt0,
                "stage2_calibrated_bc": wt2,
                "stage3_onpolicy_dagger_r2": wt3,
            },
        )
    except OSError:
        pass

    res = (wt3, "deterministic_retrain_from_summary")
    _MLP_WEIGHT_MEMO[memo_key] = res
    return res


def load_policy_bundle(
    policy_name: str,
    root: Path = ROOT,
    mlp_ckpt_path: Path | None = None,
    scaling_n_train: int = 900,
) -> tuple[Callable[[int], Any], dict[str, Any]]:
    root = root.resolve()

    if policy_name == "abstain":
        return (
            lambda seed: AbstainPolicy(seed=seed, name="abstain"),
            {
                "policy": "abstain",
                "run_id": "baseline-abstain",
                "summary_path": None,
                "stage": "abstain",
                "param_count": 0,
                "train_seed_range": "none",
                "is_open_weight_llm": False,
            },
        )

    if policy_name in ("empirical_bayes", "naive_prior"):
        from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy

        summary_file = root / EB_SUMMARY_REL
        if not summary_file.is_file():
            raise FileNotFoundError(f"missing committed summary: {summary_file}")
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        tr = summary["train_seeds"]
        _assert_train_seed_range(int(tr["start"]), int(tr["stop"]), str(EB_SUMMARY_REL))
        stage_key = "eb_experience_opt" if policy_name == "empirical_bayes" else "eb_naive_prior"
        raw_params = (summary.get("parameters") or {}).get(stage_key)
        if not isinstance(raw_params, dict):
            raise ValueError(f"{EB_SUMMARY_REL}: missing parameters[{stage_key!r}]")
        params = EmpiricalBayesParams.from_dict(raw_params)
        train_rng = f"{int(tr['start'])}..{int(tr['stop']) - 1}" if policy_name == "empirical_bayes" else "none"
        return (
            lambda seed, p=params, nm=policy_name: EmpiricalBayesPolicy(params=p, seed=seed, name=nm),
            {
                "policy": policy_name,
                "run_id": str(summary.get("run_id", "empirical-bayes-v14")),
                "summary_path": str(EB_SUMMARY_REL),
                "stage": str(params.stage),
                "param_count": 10 if policy_name == "empirical_bayes" else 0,
                "train_seed_range": train_rng,
                "is_open_weight_llm": False,
            },
        )

    if policy_name in ("compact_linear_dagger", "compact_linear_untrained"):
        from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights

        summary_file = root / DAGGER_SUMMARY_REL
        if not summary_file.is_file():
            raise FileNotFoundError(f"missing committed summary: {summary_file}")
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        tr = summary["train_seeds"]
        _assert_train_seed_range(int(tr["start"]), int(tr["stop"]), str(DAGGER_SUMMARY_REL))
        if policy_name == "compact_linear_untrained":
            weights = CompactLinearWeights.zeros("stage0_untrained")
            train_rng = "none"
        else:
            w_dict = summary.get("learned_weights_stage3")
            if not isinstance(w_dict, dict):
                raise ValueError(f"{DAGGER_SUMMARY_REL}: missing learned_weights_stage3")
            weights = CompactLinearWeights.from_dict(w_dict)
            train_rng = f"{int(tr['start'])}..{int(tr['stop']) - 1}"
        return (
            lambda _seed, w=weights, nm=policy_name: CompactLinearDAggerPolicy(weights=w, name=nm),
            {
                "policy": policy_name,
                "run_id": str(summary.get("run_id", "compact-linear-dagger-v14")),
                "summary_path": str(DAGGER_SUMMARY_REL),
                "stage": str(weights.stage),
                "param_count": int(weights.param_count()),
                "train_seed_range": train_rng,
                "is_open_weight_llm": False,
            },
        )

    if policy_name in ("tiny_mlp", "tiny_mlp_untrained"):
        from train.neural_mlp_tiebreak import TinyMLPPolicy

        summary_file = root / MLP_SUMMARY_REL
        if not summary_file.is_file():
            raise FileNotFoundError(f"missing committed summary: {summary_file}")
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        tr = summary["train_seeds"]
        _assert_train_seed_range(int(tr["start"]), int(tr["stop"]), str(MLP_SUMMARY_REL))
        stage = "stage0_untrained" if policy_name == "tiny_mlp_untrained" else "stage3_onpolicy_dagger_r2"
        weights, weight_source = _load_or_reconstruct_tiny_mlp(
            mlp_summary=summary,
            stage=stage,
            mlp_ckpt_path=mlp_ckpt_path,
        )
        train_rng = "none" if policy_name == "tiny_mlp_untrained" else f"{int(tr['start'])}..{int(tr['stop']) - 1}"
        return (
            lambda seed, w=weights, nm=policy_name: TinyMLPPolicy(weights=w, seed=seed, name=nm),
            {
                "policy": policy_name,
                "run_id": str(summary.get("run_id", "tiny-mlp-dagger-v14")),
                "summary_path": str(MLP_SUMMARY_REL),
                "stage": stage,
                "weight_source": weight_source,
                "param_count": int(weights.param_count()),
                "commit_threshold": round(float(weights.commit_threshold), 4),
                "train_seed_range": train_rng,
                "is_open_weight_llm": False,
            },
        )

    if policy_name in ("scaling_logistic", "scaling_logistic_untrained"):
        import numpy as np
        from scripts.tiebreak_scaling_calibration import CompactLinearPolicy, LinearPolicyWeights

        summary_file = root / SCALING_SUMMARY_REL
        if not summary_file.is_file():
            raise FileNotFoundError(f"missing committed summary: {summary_file}")
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        tr_raw = summary.get("train_seed_range", [107_000, 108_999])
        if isinstance(tr_raw, (list, tuple)) and len(tr_raw) == 2:
            tr_lo, tr_hi = int(tr_raw[0]), int(tr_raw[1])
            tr_range_str = f"{tr_lo}..{tr_hi}"
        elif isinstance(tr_raw, dict) and "start" in tr_raw and "stop" in tr_raw:
            tr_lo, tr_hi = int(tr_raw["start"]), int(tr_raw["stop"]) - 1
            tr_range_str = f"{tr_lo}..{tr_hi}"
        elif isinstance(tr_raw, str) and (m_tr := SEED_RANGE_RE.match(tr_raw)):
            tr_lo, tr_hi = int(m_tr.group(1)), int(m_tr.group(2))
            tr_range_str = f"{tr_lo}..{tr_hi}"
        else:
            raise ValueError(f"{SCALING_SUMMARY_REL}: invalid train_seed_range {tr_raw!r}")
        _assert_train_seed_range(tr_lo, tr_hi + 1, str(SCALING_SUMMARY_REL))

        target_budget = 0 if policy_name == "scaling_logistic_untrained" else int(scaling_n_train)
        curve = summary.get("scaling_curve") or []
        matched = next((row for row in curve if int(row.get("n_train", -1)) == target_budget), None)
        if not isinstance(matched, dict) or not isinstance(matched.get("weights"), dict):
            avail = [int(r.get("n_train", -1)) for r in curve if isinstance(r, dict)]
            raise ValueError(
                f"{SCALING_SUMMARY_REL}: n_train={target_budget} not found in scaling_curve (available: {avail})"
            )
        wd = matched["weights"]
        weights = LinearPolicyWeights(
            w_suspect=np.asarray(wd["w_suspect"], dtype=np.float64),
            w_commit=np.asarray(wd["w_commit"], dtype=np.float64),
            w_wait=np.asarray(wd["w_wait"], dtype=np.float64),
            w_tool=np.asarray(wd["w_tool"], dtype=np.float64),
            w_canary=np.asarray(wd["w_canary"], dtype=np.float64),
            n_train=target_budget,
        )
        train_rng = "none" if target_budget == 0 else tr_range_str
        return (
            lambda seed, w=weights, nm=policy_name: CompactLinearPolicy(
                weights=w, name=nm, explore_eps=0.0, rng_seed=seed
            ),
            {
                "policy": policy_name,
                "run_id": f"scaling-logistic-n{target_budget}-v14",
                "summary_path": str(SCALING_SUMMARY_REL),
                "stage": f"n_train_{target_budget}",
                "n_train": target_budget,
                "param_count": int(weights.num_parameters()),
                "train_seed_range": train_rng,
                "is_open_weight_llm": False,
            },
        )

    raise ValueError(f"unsupported policy {policy_name!r}; expected one of {SUPPORTED_POLICIES}")


def resolve_before_policy_name(policy_name: str, paired_before: str) -> str:
    if paired_before == "naive_prior":
        return "naive_prior"
    if paired_before == "abstain":
        return "abstain"
    if paired_before in ("auto", "untrained"):
        if policy_name == "empirical_bayes":
            return "naive_prior"
        if policy_name == "compact_linear_dagger":
            return "compact_linear_untrained"
        if policy_name == "tiny_mlp":
            return "tiny_mlp_untrained"
        if policy_name == "scaling_logistic":
            return "scaling_logistic_untrained"
        return "abstain"
    raise ValueError(f"unsupported --paired-before mode {paired_before!r}; expected one of {PAIRED_BEFORE_CHOICES}")


def _step_fields(step: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if hasattr(step, "tool"):
        return str(step.tool), dict(step.args or {}), dict(step.result or {})
    return str(step.get("tool", "")), dict(step.get("args") or {}), dict(step.get("result") or {})


def verify_episode_replay(ep: Any, text_provider: Any = None) -> bool:
    from canary.env import Env

    ep_meta = getattr(ep, "meta", None) or {}
    if getattr(ep, "end_reason", None) in ("error", "invalid") or ep_meta.get("valid") is False:
        raise AssertionError(f"episode invalid before replay on {ep.tier}:{ep.seed} ({ep.agent})")

    env = Env(str(ep.tier), int(ep.seed), text_provider=text_provider)
    steps = list(getattr(ep, "steps", ()) or ())
    for step_idx, st in enumerate(steps):
        if env.done:
            raise AssertionError(
                f"replay terminated early at step {step_idx}/{len(steps)} on {ep.tier}:{ep.seed} ({ep.agent})"
            )
        tool, args, recorded = _step_fields(st)
        live = env.call(tool, args)
        if "ok" in recorded and bool(live.ok) != bool(recorded["ok"]):
            raise AssertionError(f"replay ok mismatch at step {step_idx} on {ep.tier}:{ep.seed} ({ep.agent})")
        if "data" in recorded and live.data != recorded["data"]:
            raise AssertionError(f"replay data mismatch at step {step_idx} on {ep.tier}:{ep.seed} ({ep.agent})")
        if "error" in recorded and live.error != recorded["error"]:
            raise AssertionError(f"replay error mismatch at step {step_idx} on {ep.tier}:{ep.seed} ({ep.agent})")

    rep = env.result("replay")
    if (
        not env.done
        or len(rep.steps) != len(steps)
        or abs(float(rep.score) - float(ep.score)) > 1e-9
        or rep.accused != ep.accused
        or bool(rep.correct) != bool(ep.correct)
        or int(rep.final_day) != int(ep.final_day)
        or str(rep.end_reason) != str(ep.end_reason)
    ):
        raise AssertionError(f"replay terminal mismatch on {ep.tier}:{ep.seed} ({ep.agent})")
    return True


def mean_ci95(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    mean_v = sum(values) / n
    if n < 2:
        r_m = round(mean_v, 6)
        return {"mean": r_m, "ci95_low": r_m, "ci95_high": r_m, "ci95_half_width": 0.0}
    var = sum((x - mean_v) ** 2 for x in values) / (n - 1)
    half = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return {
        "mean": round(mean_v, 6),
        "ci95_low": round(mean_v - half, 6),
        "ci95_high": round(mean_v + half, 6),
        "ci95_half_width": round(half, 6),
    }


def _summarize_episodes(eps: list[Any], world_secret_tag: str) -> dict[str, Any]:
    n = len(eps)
    denom = max(1, n)
    scores = [float(e.score) for e in eps]
    ci = mean_ci95(scores)
    ok_calls = 0
    total_calls = 0
    canaries_planted = 0
    invalid_count = 0
    final_days_sum = 0

    for ep in eps:
        ep_meta = getattr(ep, "meta", None) or {}
        if getattr(ep, "end_reason", None) in ("error", "invalid") or ep_meta.get("valid") is False:
            invalid_count += 1
        final_days_sum += int(getattr(ep, "final_day", 1))
        for st in ep.steps:
            total_calls += 1
            t_name, _, res = _step_fields(st)
            if res.get("ok"):
                ok_calls += 1
                if t_name == "plant_canary":
                    canaries_planted += 1

    correct_cnt = sum(1 for e in eps if e.accused is not None and bool(e.correct))
    wrong_cnt = sum(1 for e in eps if e.accused is not None and not bool(e.correct))
    abstain_cnt = sum(1 for e in eps if e.accused is None)

    return {
        "n": n,
        "mean_score": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "ci95_half_width": ci["ci95_half_width"],
        "accuracy": round(correct_cnt / denom, 6),
        "wrong_accuse_rate": round(wrong_cnt / denom, 6),
        "abstain_rate": round(abstain_cnt / denom, 6),
        "mean_canaries_planted": round(canaries_planted / denom, 4),
        "mean_final_day": round(final_days_sum / denom, 4),
        "mean_steps": round(total_calls / denom, 4),
        "valid_call_rate": round(ok_calls / max(1, total_calls), 6) if total_calls > 0 else 1.0,
        "invalid_episodes": invalid_count,
        "replay_verified": invalid_count == 0,
        "world_secret_tag": world_secret_tag,
    }


def _summarize_paired(after_eps: list[Any], before_eps: list[Any]) -> dict[str, Any]:
    if len(after_eps) != len(before_eps):
        raise ValueError("paired episode lists must have equal length")
    deltas: list[float] = []
    for a_ep, b_ep in zip(after_eps, before_eps):
        if (a_ep.tier, int(a_ep.seed)) != (b_ep.tier, int(b_ep.seed)):
            raise ValueError(f"unpaired episode order: {a_ep.tier}:{a_ep.seed} vs {b_ep.tier}:{b_ep.seed}")
        deltas.append(round(float(a_ep.score) - float(b_ep.score), 6))
    ci = mean_ci95(deltas)
    return {
        "n": len(deltas),
        "mean_delta": ci["mean"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "ci95_half_width": ci["ci95_half_width"],
        "positive_count": sum(1 for d in deltas if d > 1e-9),
        "negative_count": sum(1 for d in deltas if d < -1e-9),
        "tie_count": sum(1 for d in deltas if abs(d) <= 1e-9),
        "deltas": deltas,
    }


def evaluate_policy(
    policy_name: str = "empirical_bayes",
    tiers: list[str] | tuple[str, ...] = CANONICAL_TIERS,
    seeds: list[int] | tuple[int, ...] = CHECK_SEEDS,
    paired_before: str | None = None,
    allow_judge_smoke: bool = False,
    world_secret: str | None = None,
    root: Path = ROOT,
    mlp_ckpt_path: Path | None = None,
    scaling_n_train: int = 900,
    mode: str = "eval",
    stripe_seeds_across_tiers: bool = False,
) -> dict[str, Any]:
    from canary import rules
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider

    t0 = time.perf_counter()
    if policy_name not in SUPPORTED_POLICIES:
        raise ValueError(f"unsupported policy {policy_name!r}; expected one of {SUPPORTED_POLICIES}")

    tiers_list = list(tiers)
    if not tiers_list:
        raise ValueError("tiers must be non-empty")
    for t_name in tiers_list:
        if t_name not in rules.TIERS and t_name not in rules.TRACKS:
            raise ValueError(f"unknown tier {t_name!r}")

    seeds_list = [int(s) for s in seeds]
    ambient_secret = os.environ.get("CANARY_WORLD_SECRET")
    seed_split, resolved_secret, secret_tag, protocol_note = validate_and_resolve_seeds(
        seeds=seeds_list,
        allow_judge_smoke=allow_judge_smoke,
        explicit_world_secret=world_secret,
        ambient_world_secret=ambient_secret,
    )

    if mode == "check" and seed_split != "heldout":
        raise ValueError("--check requires HELDOUT_SEEDS [800000, 800199]")

    after_factory, after_prov = load_policy_bundle(
        policy_name=policy_name,
        root=root,
        mlp_ckpt_path=mlp_ckpt_path,
        scaling_n_train=scaling_n_train,
    )

    before_resolved_name: str | None = None
    before_factory: Callable[[int], Any] | None = None
    before_prov: dict[str, Any] | None = None
    if paired_before is not None:
        before_resolved_name = resolve_before_policy_name(policy_name, paired_before)
        before_factory, before_prov = load_policy_bundle(
            policy_name=before_resolved_name,
            root=root,
            mlp_ckpt_path=mlp_ckpt_path,
            scaling_n_train=scaling_n_train,
        )

    provider = TemplateProvider()
    after_by_tier: dict[str, list[Any]] = {t: [] for t in tiers_list}
    before_by_tier: dict[str, list[Any]] = {t: [] for t in tiers_list}
    replayed_count = 0

    if stripe_seeds_across_tiers:
        schedule = [(tiers_list[idx % len(tiers_list)], seed) for idx, seed in enumerate(seeds_list)]
    else:
        schedule = [(tier, seed) for tier in tiers_list for seed in seeds_list]

    with _scoped_world_secret(resolved_secret):
        for tier, seed in schedule:
            if before_factory is not None:
                b_ep = run_episode(Env(tier, seed, text_provider=provider), before_factory(seed))
                verify_episode_replay(b_ep, text_provider=provider)
                replayed_count += 1
                before_by_tier[tier].append(b_ep)

            a_ep = run_episode(Env(tier, seed, text_provider=provider), after_factory(seed))
            verify_episode_replay(a_ep, text_provider=provider)
            replayed_count += 1
            after_by_tier[tier].append(a_ep)

    after_pooled = [ep for t in tiers_list for ep in after_by_tier[t]]
    after_overall = _summarize_episodes(after_pooled, secret_tag)
    after_tiers_summary = {t: _summarize_episodes(after_by_tier[t], secret_tag) for t in tiers_list}

    n_primary = len(after_pooled)
    expected_replays = n_primary * (2 if before_factory is not None else 1)
    total_invalid = int(after_overall["invalid_episodes"])

    report: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "mode": mode,
        "tiers_version": str(rules.TIERS_VERSION),
        "policy": policy_name,
        "provenance": after_prov,
        "seed_split": seed_split,
        "tiers": tiers_list,
        "seeds": seeds_list,
        "n": n_primary,
        "world_secret_tag": secret_tag,
        "protocol_note": protocol_note,
        "replay_verified": replayed_count == expected_replays and total_invalid == 0,
        "episodes_replayed": replayed_count,
        "episodes_expected": expected_replays,
        "invalid_episodes": total_invalid,
        "metrics": {
            "overall": after_overall,
            "by_tier": after_tiers_summary,
        },
    }

    if before_factory is not None and before_resolved_name is not None and before_prov is not None:
        before_pooled = [ep for t in tiers_list for ep in before_by_tier[t]]
        before_overall = _summarize_episodes(before_pooled, secret_tag)
        before_tiers_summary = {t: _summarize_episodes(before_by_tier[t], secret_tag) for t in tiers_list}
        paired_overall = _summarize_paired(after_pooled, before_pooled)
        paired_by_tier = {
            t: {k: v for k, v in _summarize_paired(after_by_tier[t], before_by_tier[t]).items() if k != "deltas"}
            for t in tiers_list
        }
        total_invalid += int(before_overall["invalid_episodes"])
        report["invalid_episodes"] = total_invalid
        report["replay_verified"] = replayed_count == expected_replays and total_invalid == 0
        report["paired_before_policy"] = before_resolved_name
        report["before_provenance"] = before_prov
        report["before"] = {
            **before_overall,
            "by_tier": before_tiers_summary,
        }
        report["after"] = {
            **after_overall,
            "by_tier": after_tiers_summary,
        }
        report["paired"] = {
            **paired_overall,
            "by_tier": paired_by_tier,
        }

    elapsed = round(time.perf_counter() - t0, 4)
    report["elapsed_seconds"] = elapsed

    passed = bool(report["replay_verified"]) and int(report["invalid_episodes"]) == 0
    errors: list[str] = []
    if not report["replay_verified"]:
        errors.append("fresh Env step-by-step replay verification failed")
    if mode == "check":
        paired_block = report.get("paired") or {}
        if float(paired_block.get("mean_delta", 0.0)) <= 0.0:
            passed = False
            errors.append(f"check mode requires positive paired mean_delta, got {paired_block.get('mean_delta')}")
    report["passed"] = passed
    report["errors"] = errors
    return report


def format_human_summary(report: dict[str, Any]) -> str:
    verdict = "PASS" if report["passed"] else "FAIL"
    mode_lbl = str(report["mode"]).upper()
    ov = report["metrics"]["overall"]
    lines = [
        f"TIEBREAK POLICY EVAL [{mode_lbl}]: {verdict} "
        f"(policy={report['policy']}, split={report['seed_split']}, n={report['n']}, "
        f"replayed={report['episodes_replayed']}/{report['episodes_expected']}, "
        f"secret={report['world_secret_tag']}, {report['elapsed_seconds']:.3f}s)",
        f"  after ({report['policy']}): mean_score={ov['mean_score']:+.4f} "
        f"[{ov['ci95_low']:+.4f}, {ov['ci95_high']:+.4f}] "
        f"acc={ov['accuracy']:.3f} wrong={ov['wrong_accuse_rate']:.3f} "
        f"abstain={ov['abstain_rate']:.3f} valid_calls={ov['valid_call_rate']:.3f}",
    ]
    if "paired" in report and "before" in report:
        bef = report["before"]
        pair = report["paired"]
        lines.append(
            f"  before ({report['paired_before_policy']}): mean_score={bef['mean_score']:+.4f} "
            f"[{bef['ci95_low']:+.4f}, {bef['ci95_high']:+.4f}] "
            f"acc={bef['accuracy']:.3f} wrong={bef['wrong_accuse_rate']:.3f} "
            f"abstain={bef['abstain_rate']:.3f}"
        )
        lines.append(
            f"  paired delta (after - before): {pair['mean_delta']:+.4f} "
            f"[{pair['ci95_low']:+.4f}, {pair['ci95_high']:+.4f}] "
            f"(+{pair['positive_count']} / -{pair['negative_count']} / ={pair['tie_count']})"
        )
    for tier in report["tiers"]:
        tm = report["metrics"]["by_tier"][tier]
        if "paired" in report:
            td = report["paired"]["by_tier"][tier]["mean_delta"]
            lines.append(
                f"    tier={tier:6s} n={tm['n']:3d} score={tm['mean_score']:+.4f} "
                f"acc={tm['accuracy']:.3f} paired_delta={td:+.4f}"
            )
        else:
            lines.append(
                f"    tier={tier:6s} n={tm['n']:3d} score={tm['mean_score']:+.4f} "
                f"acc={tm['accuracy']:.3f} abstain={tm['abstain_rate']:.3f}"
            )
    for err in report.get("errors") or []:
        lines.append(f"  ERROR: {err}")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Keyless standalone evaluation CLI for Canary compact tiebreak policies."
    )
    ap.add_argument(
        "--policy",
        default="empirical_bayes",
        choices=SUPPORTED_POLICIES,
        help="Trained compact tiebreak policy or before-baseline to evaluate.",
    )
    ap.add_argument(
        "--tier",
        default=None,
        help="Tier name (easy, medium, hard, all, or comma-separated list; default: all).",
    )
    ap.add_argument(
        "--seeds",
        default=None,
        help="HELDOUT_SEEDS (800000..800199) or DEV_SEEDS (0..9999) slice (default: 800000-800029).",
    )
    ap.add_argument(
        "--paired-before",
        nargs="?",
        const="auto",
        default=None,
        choices=PAIRED_BEFORE_CHOICES,
        help="Run world-paired before/after comparison (auto, naive_prior, abstain, untrained).",
    )
    ap.add_argument(
        "--allow-judge-smoke",
        action="store_true",
        help="Allow JUDGE_SEEDS (900000..900039) smoke evaluation when explicit CANARY_WORLD_SECRET is set.",
    )
    ap.add_argument(
        "--world-secret",
        default=None,
        help="Explicit CANARY_WORLD_SECRET override for held-out or authorized judge-smoke worlds.",
    )
    ap.add_argument(
        "--mlp-ckpt",
        type=Path,
        default=None,
        help="Optional explicit .npz checkpoint path for tiny_mlp.",
    )
    ap.add_argument(
        "--scaling-n-train",
        type=int,
        default=900,
        help="Training budget checkpoint from scaling_summary.json for scaling_logistic (default: 900).",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root containing results/tiebreak summaries.",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Fast <0.5s smoke test on 3 held-out seeds across easy/medium/hard verifying positive paired delta and 100%% replay.",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        if args.check:
            tiers = parse_tiers(args.tier) if args.tier is not None else list(CANONICAL_TIERS)
            seeds = parse_seed_slice(args.seeds) if args.seeds is not None else list(CHECK_SEEDS)
            paired_mode = args.paired_before if args.paired_before is not None else "auto"
            if args.policy in BASELINE_POLICIES:
                raise ValueError("--check requires a trained policy so before/after paired delta is positive")
            mode = "check"
            stripe = len(seeds) >= len(tiers)
        else:
            tiers = parse_tiers(args.tier if args.tier is not None else "all")
            seeds = parse_seed_slice(args.seeds if args.seeds is not None else DEFAULT_SEEDS_SPEC)
            paired_mode = args.paired_before
            mode = "eval"
            stripe = False

        report = evaluate_policy(
            policy_name=args.policy,
            tiers=tiers,
            seeds=seeds,
            paired_before=paired_mode,
            allow_judge_smoke=bool(args.allow_judge_smoke),
            world_secret=args.world_secret,
            root=args.root.resolve(),
            mlp_ckpt_path=args.mlp_ckpt.resolve() if args.mlp_ckpt is not None else None,
            scaling_n_train=int(args.scaling_n_train),
            mode=mode,
            stripe_seeds_across_tiers=stripe,
        )
    except (ValueError, FileNotFoundError) as exc:
        if args.json:
            print(json.dumps({"schema": SCHEMA_ID, "passed": False, "error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_human_summary(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
