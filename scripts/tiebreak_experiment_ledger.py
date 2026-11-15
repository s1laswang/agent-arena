from __future__ import annotations

import argparse
import glob
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

MD_H = chr(35)
DEFAULT_EXTERNAL_DATA_ROOT = Path("/home/silas/agent-arena-data")
TRAIN_SEED_MIN = 100_000
TRAIN_SEED_MAX = 200_000
HELDOUT_SEED_MIN = 800_000
HELDOUT_SEED_MAX = 800_200
MIN_PAIRED_N = 30

HISTORICAL_RUN_IDS: tuple[str, ...] = (
    "J4-pilot-44200",
    "J4-v1-44397",
    "WS4-base-44411",
    "WS4-base-pooled",
    "WS4-v2-44412",
    "WS4-v2-off30-68bb",
    "WS4-v3-44548-44550",
    "WS4-v3-44553",
    "WS4-v3-4k-s1-714d-spot",
    "WS4-v3-4k-s1-44572",
    "WS4-v3-verda-s0-eval",
    "WS4-v3-4k-s0-ctx8k",
    "WS4-v3-8k-s0-3bb7",
    "WS4-v3-8k-s1-ac58",
    "WS4-v3-8k-s2-dbd0",
    "WS4-v3-8k-s3-f437",
    "WS4-dagger-r1-8k-verda",
    "WS4-dagger-r1-4k-verda",
    "Verda-base-backup-18ac",
)

FORBIDDEN_SECRET_PLACEHOLDERS = frozenset({
    "",
    "none",
    "null",
    "unknown",
    "unpaired",
    "missing",
    "todo",
    "na",
    "n/a",
})

ERROR_EPISODE_KEYS: tuple[str, ...] = (
    "invalid_episodes",
    "error_episodes",
    "invalid_or_error_episodes",
    "invalid_episodes_counted_as_zero",
    "errors_counted_as_zero",
)


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_finite_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def mean_ci95(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    sd = math.sqrt(max(0.0, var))
    return m, 1.96 * sd / math.sqrt(n)


def paired_delta_stats(deltas: list[float]) -> dict[str, float]:
    m, half = mean_ci95(deltas)
    return {
        "mean_delta": round(m, 6),
        "ci95_half_width": round(half, 6),
        "ci95_low": round(m - half, 6),
        "ci95_high": round(m + half, 6),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            rows.append(json.loads(s))
    return rows


def extract_seed_list(raw: Any) -> tuple[list[int] | None, str | None]:
    if isinstance(raw, (list, tuple)):
        if not raw:
            return None, "seed list is empty"
        out: list[int] = []
        for item in raw:
            if not _is_int(item):
                return None, f"non-integer seed entry: {item!r}"
            out.append(int(item))
        return out, None
    if isinstance(raw, dict):
        if "seeds" in raw:
            return extract_seed_list(raw["seeds"])
        if "start" in raw and ("stop" in raw or "end" in raw):
            start = raw["start"]
            stop = raw.get("stop", raw.get("end"))
            if not (_is_int(start) and _is_int(stop)):
                return None, "seed range start/stop must be integers"
            if start >= stop:
                return None, f"empty seed range [{start}, {stop})"
            if stop - start > 250_000:
                return None, f"seed range [{start}, {stop}) exceeds sanity limit"
            return list(range(int(start), int(stop))), None
        if "min" in raw and "max" in raw:
            lo = raw["min"]
            hi = raw["max"]
            if not (_is_int(lo) and _is_int(hi)):
                return None, "seed min/max must be integers"
            if lo > hi:
                return None, f"empty seed interval [{lo}, {hi}]"
            if hi - lo + 1 > 250_000:
                return None, f"seed interval [{lo}, {hi}] exceeds sanity limit"
            return list(range(int(lo), int(hi) + 1)), None
    return None, "missing or unrecognized seed specification"


def _valid_secret_tag(val: Any) -> str | None:
    if not isinstance(val, str):
        return None
    s = val.strip()
    if len(s) < 6 or s.lower() in FORBIDDEN_SECRET_PLACEHOLDERS:
        return None
    return s


def _check_zero_error_episodes(
    summary: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    explicit_zero_found = False

    for scope_name, obj in (("summary", summary), ("before", before), ("after", after)):
        for key in ERROR_EPISODE_KEYS:
            if key in obj:
                val = obj[key]
                if not _is_int(val) or int(val) != 0:
                    reasons.append(f"{scope_name}.{key}={val!r} (must be integer 0)")
                else:
                    explicit_zero_found = True

        end_reasons = obj.get("end_reasons")
        if isinstance(end_reasons, dict):
            for bad_reason in ("error", "invalid"):
                bad_cnt = end_reasons.get(bad_reason, 0)
                if not _is_int(bad_cnt) or int(bad_cnt) != 0:
                    reasons.append(f"{scope_name}.end_reasons[{bad_reason!r}]={bad_cnt!r} (must be 0)")
            if not reasons:
                explicit_zero_found = True

        eps = obj.get("episodes")
        if isinstance(eps, list):
            for idx, ep in enumerate(eps):
                if not isinstance(ep, dict):
                    reasons.append(f"{scope_name}.episodes[{idx}] is not a dict")
                    continue
                er = ep.get("end_reason")
                meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
                if er in ("error", "invalid") or ep.get("valid") is False or meta.get("valid") is False:
                    reasons.append(f"{scope_name}.episodes[{idx}] is invalid/error (end_reason={er!r})")

    if not explicit_zero_found:
        reasons.append(
            "missing explicit zero invalid/error episode accounting (provide invalid_episodes=0 or end_reasons)"
        )

    return len(reasons) == 0, reasons


def _extract_paired_ci(
    summary: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    expected_n: int | None,
) -> tuple[float | None, float | None, float | None, list[str]]:
    reasons: list[str] = []
    paired = summary.get("paired") if isinstance(summary.get("paired"), dict) else {}

    deltas: list[float] | None = None
    if isinstance(summary.get("paired_deltas"), list):
        raw_d = summary["paired_deltas"]
        if all(_is_finite_num(x) for x in raw_d) and len(raw_d) > 0:
            deltas = [float(x) for x in raw_d]
        else:
            reasons.append("paired_deltas contains non-finite or empty values")
    elif isinstance(paired.get("deltas"), list):
        raw_d = paired["deltas"]
        if all(_is_finite_num(x) for x in raw_d) and len(raw_d) > 0:
            deltas = [float(x) for x in raw_d]
        else:
            reasons.append("paired.deltas contains non-finite or empty values")
    elif isinstance(before.get("scores"), list) and isinstance(after.get("scores"), list):
        b_scores = before["scores"]
        a_scores = after["scores"]
        if len(b_scores) != len(a_scores) or len(b_scores) == 0:
            reasons.append("before.scores and after.scores must be non-empty and equal length")
        elif not (all(_is_finite_num(x) for x in b_scores) and all(_is_finite_num(x) for x in a_scores)):
            reasons.append("before.scores / after.scores contain non-finite values")
        else:
            deltas = [float(a) - float(b) for b, a in zip(b_scores, a_scores)]

    computed_mean: float | None = None
    computed_low: float | None = None
    computed_high: float | None = None
    if deltas is not None:
        if expected_n is not None and len(deltas) != expected_n:
            reasons.append(f"paired scores length {len(deltas)} != n ({expected_n})")
        st = paired_delta_stats(deltas)
        computed_mean = st["mean_delta"]
        computed_low = st["ci95_low"]
        computed_high = st["ci95_high"]

    reported_mean: float | None = None
    for cand in (
        paired.get("mean_delta"),
        paired.get("delta_mean"),
        paired.get("mean"),
        summary.get("paired_mean_delta"),
        summary.get("mean_delta"),
        summary.get("delta_mean"),
    ):
        if _is_finite_num(cand):
            reported_mean = float(cand)
            break

    if reported_mean is None and _is_finite_num(before.get("mean_score")) and _is_finite_num(after.get("mean_score")):
        reported_mean = float(after["mean_score"]) - float(before["mean_score"])

    reported_low: float | None = None
    reported_high: float | None = None
    for cand in (
        paired.get("ci95_low"),
        paired.get("ci_low"),
        summary.get("paired_ci95_low"),
        summary.get("ci95_low"),
        summary.get("delta_ci95_low"),
    ):
        if _is_finite_num(cand):
            reported_low = float(cand)
            break

    for cand in (
        paired.get("ci95_high"),
        paired.get("ci_high"),
        summary.get("paired_ci95_high"),
        summary.get("ci95_high"),
        summary.get("delta_ci95_high"),
    ):
        if _is_finite_num(cand):
            reported_high = float(cand)
            break

    if reported_low is None and reported_mean is not None and _is_finite_num(paired.get("ci95")):
        hw = float(paired["ci95"])
        if hw >= 0.0:
            reported_low = reported_mean - hw
            reported_high = reported_mean + hw

    mean_delta = computed_mean if computed_mean is not None else reported_mean
    if computed_mean is not None and reported_mean is not None and abs(computed_mean - reported_mean) > 0.015:
        reasons.append(
            f"reported mean_delta ({reported_mean:.4f}) disagrees with paired scores mean ({computed_mean:.4f})"
        )

    if (
        mean_delta is not None
        and _is_finite_num(before.get("mean_score"))
        and _is_finite_num(after.get("mean_score"))
    ):
        diff_means = float(after["mean_score"]) - float(before["mean_score"])
        if abs(diff_means - mean_delta) > 0.015:
            reasons.append(
                f"after.mean_score - before.mean_score ({diff_means:.4f}) disagrees with mean_delta ({mean_delta:.4f})"
            )

    if computed_low is not None and reported_low is not None:
        ci95_low = min(computed_low, reported_low)
    elif computed_low is not None:
        ci95_low = computed_low
    else:
        ci95_low = reported_low

    ci95_high = computed_high if computed_high is not None else reported_high

    if mean_delta is None or ci95_low is None:
        reasons.append("missing paired ci95_low(after - before) or paired delta scores")
    elif ci95_low > mean_delta + 1e-7:
        reasons.append(f"invalid paired CI: ci95_low ({ci95_low:.4f}) > mean_delta ({mean_delta:.4f})")

    return (
        round(mean_delta, 6) if mean_delta is not None else None,
        round(ci95_low, 6) if ci95_low is not None else None,
        round(ci95_high, 6) if ci95_high is not None else None,
        reasons,
    )


def validate_experiment_summary(summary: dict[str, Any], summary_path: str = "") -> dict[str, Any]:
    if not isinstance(summary, dict):
        raise ValueError("experiment summary must be a JSON object")

    fallback_id = Path(summary_path).parent.name if summary_path else "unnamed_run"
    run_id = str(summary.get("run_id") or fallback_id)
    model = str(summary.get("model") or summary.get("policy") or summary.get("agent") or "unknown")
    tiers_version = str(summary.get("tiers_version") or "v1.4")
    raw_tiers = summary.get("tiers")
    if isinstance(raw_tiers, list) and raw_tiers:
        tiers = [str(t) for t in raw_tiers]
    elif isinstance(raw_tiers, str) and raw_tiers.strip():
        tiers = [t.strip() for t in raw_tiers.split(",") if t.strip()]
    else:
        tiers = ["easy", "medium", "hard"]

    before = summary.get("before") if isinstance(summary.get("before"), dict) else {}
    after = summary.get("after") if isinstance(summary.get("after"), dict) else {}

    reasons: list[str] = []

    train_seeds, train_err = extract_seed_list(summary.get("train_seeds", after.get("train_seeds")))
    eval_seeds, eval_err = extract_seed_list(
        summary.get("eval_seeds", after.get("eval_seeds", before.get("eval_seeds")))
    )

    gate1_ok = True
    if train_err is not None or train_seeds is None:
        gate1_ok = False
        reasons.append(f"gate1_seed_hygiene: invalid train_seeds ({train_err})")
    else:
        bad_train = [
            s
            for s in train_seeds
            if not (TRAIN_SEED_MIN <= s < TRAIN_SEED_MAX)
            or s not in TRAIN_SEEDS
            or s in DEV_SEEDS
            or s in HELDOUT_SEEDS
            or s in JUDGE_SEEDS
        ]
        if bad_train:
            gate1_ok = False
            reasons.append(
                f"gate1_seed_hygiene: {len(bad_train)} train seed(s) outside [100000, 200000), sample={bad_train[:5]}"
            )

    if eval_err is not None or eval_seeds is None:
        gate1_ok = False
        reasons.append(f"gate1_seed_hygiene: invalid eval_seeds ({eval_err})")
    elif train_seeds is not None:
        overlap = sorted(set(train_seeds) & set(eval_seeds))
        if overlap:
            gate1_ok = False
            reasons.append(
                f"gate1_seed_hygiene: train_seeds and eval_seeds overlap on {len(overlap)} seed(s), sample={overlap[:5]}"
            )

    if "eval_seeds" in before and "eval_seeds" in after:
        b_ev, b_err = extract_seed_list(before["eval_seeds"])
        a_ev, a_err = extract_seed_list(after["eval_seeds"])
        if b_err or a_err or b_ev != a_ev:
            gate1_ok = False
            reasons.append("gate1_seed_hygiene: before.eval_seeds != after.eval_seeds")

    gate2_ok = True
    if eval_seeds is None:
        gate2_ok = False
        reasons.append("gate2_paired_world_secret: missing eval_seeds on HELDOUT_SEEDS")
    else:
        non_heldout = [
            s for s in eval_seeds if not (HELDOUT_SEED_MIN <= s < HELDOUT_SEED_MAX) or s not in HELDOUT_SEEDS
        ]
        if non_heldout:
            gate2_ok = False
            reasons.append(
                f"gate2_paired_world_secret: eval_seeds outside HELDOUT_SEEDS [800000, 800200), sample={non_heldout[:5]}"
            )

    raw_b_tag = (
        before.get("world_secret_tag")
        if "world_secret_tag" in before
        else before.get("world_secret_fingerprint", summary.get("before_world_secret_tag"))
    )
    raw_a_tag = (
        after.get("world_secret_tag")
        if "world_secret_tag" in after
        else after.get("world_secret_fingerprint", summary.get("after_world_secret_tag"))
    )
    if raw_b_tag is None and raw_a_tag is None and summary.get("paired") is True:
        shared_tag = summary.get("world_secret_tag")
        raw_b_tag = shared_tag
        raw_a_tag = shared_tag

    b_tag = _valid_secret_tag(raw_b_tag)
    a_tag = _valid_secret_tag(raw_a_tag)
    if b_tag is None or a_tag is None:
        gate2_ok = False
        reasons.append(
            f"gate2_paired_world_secret: missing valid world_secret_tag on before ({raw_b_tag!r}) or after ({raw_a_tag!r})"
        )
    elif b_tag != a_tag:
        gate2_ok = False
        reasons.append(f"gate2_paired_world_secret: unpaired world_secret_tag ({b_tag!r} != {a_tag!r})")

    gate3_ok = True
    n_candidates: list[int] = []
    for scope_name, raw_n in (("n", summary.get("n")), ("before.n", before.get("n")), ("after.n", after.get("n"))):
        if raw_n is not None:
            if not _is_int(raw_n):
                gate3_ok = False
                reasons.append(f"gate3_sample_and_replay: {scope_name} must be integer, got {raw_n!r}")
            else:
                n_candidates.append(int(raw_n))

    if len(set(n_candidates)) > 1:
        gate3_ok = False
        reasons.append(f"gate3_sample_and_replay: inconsistent sample sizes across summary/before/after: {n_candidates}")

    eff_n = n_candidates[0] if n_candidates else None
    if eff_n is None or eff_n < MIN_PAIRED_N:
        gate3_ok = False
        reasons.append(f"gate3_sample_and_replay: n={eff_n!r} < {MIN_PAIRED_N}")

    if eval_seeds is not None and eff_n is not None:
        max_unique_pairs = len(set(eval_seeds)) * max(1, len(tiers))
        if max_unique_pairs < MIN_PAIRED_N:
            gate3_ok = False
            reasons.append(
                f"gate3_sample_and_replay: distinct (tier, eval_seed) capacity {max_unique_pairs} < {MIN_PAIRED_N}"
            )

    top_rv = summary.get("replay_verified")
    b_rv = before.get("replay_verified")
    a_rv = after.get("replay_verified")
    replay_ok = (top_rv is True and b_rv is not False and a_rv is not False) or (
        top_rv is None and b_rv is True and a_rv is True
    )
    if not replay_ok:
        gate3_ok = False
        reasons.append(f"gate3_sample_and_replay: replay_verified must be strictly True (got {top_rv!r})")

    zero_err_ok, err_reasons = _check_zero_error_episodes(summary, before, after)
    if not zero_err_ok:
        gate3_ok = False
        for r in err_reasons:
            reasons.append(f"gate3_sample_and_replay: {r}")

    mean_delta, ci95_low, ci95_high, ci_reasons = _extract_paired_ci(summary, before, after, eff_n)
    gate4_ok = True
    if ci_reasons:
        gate4_ok = False
        for r in ci_reasons:
            reasons.append(f"gate4_paired_ci95_positive: {r}")
    if mean_delta is None or ci95_low is None or not (mean_delta > 0.0 and ci95_low > 0.0):
        gate4_ok = False
        reasons.append(
            f"gate4_paired_ci95_positive: paired ci95_low={ci95_low!r}, mean_delta={mean_delta!r} (require > 0.0)"
        )

    all_passed = gate1_ok and gate2_ok and gate3_ok and gate4_ok
    if all_passed:
        status = "VERIFIED_IMPROVEMENT"
    elif mean_delta is not None and mean_delta <= 0.0 and gate1_ok and gate2_ok and gate3_ok:
        status = "NEGATIVE_NO_GAIN"
    elif mean_delta is not None and mean_delta > 0.0 and (ci95_low is None or ci95_low <= 0.0) and gate1_ok and gate2_ok and gate3_ok:
        status = "INCONCLUSIVE_CI_CROSSES_ZERO"
    else:
        status = "REJECTED_GATE_FAILURE"

    before_mean = round(float(before["mean_score"]), 4) if _is_finite_num(before.get("mean_score")) else None
    after_mean = round(float(after["mean_score"]), 4) if _is_finite_num(after.get("mean_score")) else None
    before_valid = round(float(before["valid_call_rate"]), 4) if _is_finite_num(before.get("valid_call_rate")) else None
    after_valid = round(float(after["valid_call_rate"]), 4) if _is_finite_num(after.get("valid_call_rate")) else None

    return {
        "run_id": run_id,
        "source": "discovered",
        "summary_path": summary_path,
        "model": model,
        "tiers_version": tiers_version,
        "tiers": tiers,
        "heldout_n": eff_n,
        "before_mean_score": before_mean,
        "after_mean_score": after_mean,
        "paired_mean_delta": round(mean_delta, 4) if mean_delta is not None else None,
        "paired_ci95_low": round(ci95_low, 4) if ci95_low is not None else None,
        "paired_ci95_high": round(ci95_high, 4) if ci95_high is not None else None,
        "before_valid_call_rate": before_valid,
        "after_valid_call_rate": after_valid,
        "before_world_secret_tag": b_tag,
        "after_world_secret_tag": a_tag,
        "replay_verified": bool(replay_ok),
        "verified_improvement": all_passed,
        "status": status,
        "gates": {
            "gate1_seed_hygiene": gate1_ok,
            "gate2_paired_world_secret": gate2_ok,
            "gate3_sample_and_replay": gate3_ok,
            "gate4_paired_ci95_positive": gate4_ok,
            "all_passed": all_passed,
            "reasons": reasons,
        },
        "notes": str(summary.get("notes") or summary.get("description") or "Dynamically validated squad summary."),
    }


def _load_j4_44200(external_data_root: Path) -> dict[str, Any]:
    oom_killed = True
    gpu_model = "Tesla V100-PCIE-32GB"
    slurm_path = external_data_root / "j4" / "slurm-44200.out"
    if slurm_path.is_file():
        txt = slurm_path.read_text(encoding="utf-8", errors="replace")
        oom_killed = "oom_kill" in txt or "Killed" in txt
        if "Tesla V100-PCIE-32GB" in txt:
            gpu_model = "Tesla V100-PCIE-32GB"
    return {
        "run_id": "J4-pilot-44200",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA r=16 (pilot)",
        "method": "SFT prefix 4k pilot tokenization on 20k J3 episodes",
        "tiers_version": "v1.0",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": 0,
        "before_mean_score": None,
        "after_mean_score": None,
        "after_ci95": None,
        "paired_mean_delta": None,
        "paired_ci95_low": None,
        "paired_ci95_high": None,
        "before_valid_call_rate": None,
        "after_valid_call_rate": None,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "FAILED_OOM",
        "details": {
            "slurm_job_id": 44200,
            "gpu": gpu_model,
            "ram_limit_gb": 28,
            "pilot_episodes": 20000,
            "est_tokens_per_episode": 102000,
            "oom_killed": oom_killed,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "OOM-killed at 28 GB RAM while tokenizing 20,000 prefix-window episodes held as Python int lists",
                "heldout_n=0 < 30; training never started",
            ],
        },
        "evidence": [
            "docs/reports/fr8.md",
            "/home/silas/agent-arena-data/j4/slurm-44200.out",
        ],
        "notes": (
            "28G Slurm cgroup OOM during single-core pilot tokenization of 20k J3 prefix episodes (~102k tokens/ep)."
        ),
    }


def _load_j4_44397(repo_root: Path) -> dict[str, Any]:
    base_n = 2
    base_mean = 0.0
    base_valid_exact = 0.0817
    base_valid_reported = 0.08
    dedup_n = 12
    dedup_mean = -0.25
    dedup_ci95 = 0.256
    dedup_accused = 3
    dedup_correct = 0
    pooled_n = 17
    pooled_mean = -0.1479
    pooled_accused = 4
    pooled_correct = 1
    lora_valid_reported = 0.99
    before_secret = "58518f46a669f563"
    after_secret = "7a134382b86e76ca"
    train_steps = 450
    tokens_trained = 14313726
    total_tokens = 287036155
    loss_tokens = 4506686

    runs_dir = repo_root / "data" / "fr8" / "j4" / "run-44397" / "runs"
    base_ep_file = runs_dir / "eval-base" / "episodes.jsonl"
    lora1_file = runs_dir / "eval-lora" / "episodes.jsonl"
    lora2_file = runs_dir / "eval-lora-par" / "episodes.jsonl"
    slurm_file = repo_root / "data" / "fr8" / "j4" / "slurm-44397.out"

    if base_ep_file.is_file() and lora1_file.is_file() and lora2_file.is_file():
        base_eps = _read_jsonl(base_ep_file)
        lora1 = _read_jsonl(lora1_file)
        lora2 = _read_jsonl(lora2_file)
        base_n = len(base_eps)
        b_m, _ = mean_ci95([float(e["score"]) for e in base_eps])
        base_mean = round(b_m, 3)
        b_steps = sum(len(e.get("steps", [])) for e in base_eps)
        b_inv = sum(int((e.get("meta") or {}).get("invalid_calls", 0)) for e in base_eps)
        base_valid_exact = round(1.0 - (b_inv / max(b_steps, 1)), 4)

        dedup_map: dict[tuple[str, int], dict[str, Any]] = {}
        for ep in lora1 + lora2:
            key = (str(ep["tier"]), int(ep["seed"]))
            if key not in dedup_map:
                dedup_map[key] = ep
        dedup_eps = list(dedup_map.values())
        dedup_n = len(dedup_eps)
        d_m, d_ci = mean_ci95([float(e["score"]) for e in dedup_eps])
        dedup_mean = round(d_m, 3)
        dedup_ci95 = round(d_ci, 3)
        dedup_accused = sum(1 for e in dedup_eps if e.get("end_reason") == "accused")
        dedup_correct = sum(1 for e in dedup_eps if bool(e.get("correct")))

        pooled = lora1 + lora2
        pooled_n = len(pooled)
        p_m, _ = mean_ci95([float(e["score"]) for e in pooled])
        pooled_mean = round(p_m, 4)
        pooled_accused = sum(1 for e in pooled if e.get("end_reason") == "accused")
        pooled_correct = sum(1 for e in pooled if bool(e.get("correct")))

    if slurm_file.is_file():
        txt = slurm_file.read_text(encoding="utf-8", errors="replace")
        secrets = re.findall(r"sha256 ([0-9a-f]{16})", txt)
        if len(secrets) >= 2:
            before_secret, after_secret = secrets[0], secrets[1]
        m_data = re.search(r"tokens=(\d+)\s+loss_tokens=(\d+)", txt)
        if m_data:
            total_tokens = int(m_data.group(1))
            loss_tokens = int(m_data.group(2))
        m_sum = re.search(r'"steps":\s*(\d+),\s*"tokens":\s*(\d+)', txt)
        if m_sum:
            train_steps = int(m_sum.group(1))
            tokens_trained = int(m_sum.group(2))

    return {
        "run_id": "J4-v1-44397",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA r=16",
        "method": "SFT prefix 4k windows (450 steps, 14.3M tokens on J3v2 v1.3)",
        "tiers_version": "v1.3",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": dedup_n,
        "before_mean_score": base_mean,
        "after_mean_score": dedup_mean,
        "after_ci95": dedup_ci95,
        "paired_mean_delta": round(dedup_mean - base_mean, 3),
        "paired_ci95_low": round(dedup_mean - dedup_ci95, 3),
        "paired_ci95_high": round(dedup_mean + dedup_ci95, 3),
        "before_valid_call_rate": base_valid_reported,
        "after_valid_call_rate": lora_valid_reported,
        "before_world_secret_tag": before_secret,
        "after_world_secret_tag": after_secret,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_REWARD_PROTOCOL_GAIN",
        "details": {
            "slurm_job_id": 44397,
            "train_steps": train_steps,
            "tokens_trained": tokens_trained,
            "dataset_tokens": total_tokens,
            "dataset_loss_tokens": loss_tokens,
            "loss_token_fraction": round(loss_tokens / max(total_tokens, 1), 4),
            "base_heldout_n": base_n,
            "base_valid_call_rate_exact": base_valid_exact,
            "dedup_heldout_n": dedup_n,
            "dedup_accused": dedup_accused,
            "dedup_correct": dedup_correct,
            "pooled_heldout_n": pooled_n,
            "pooled_mean_score": pooled_mean,
            "pooled_accused": pooled_accused,
            "pooled_correct": pooled_correct,
            "solver_action_agreement_reported": 0.85,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                f"unpaired per-process world secrets ({before_secret} vs {after_secret})",
                f"dedup held-out n={dedup_n} < 30 (base n={base_n}); evaluated on v1.3 before KV-cache fix",
                f"negative reward delta ({dedup_mean:.3f} +/- {dedup_ci95:.3f} vs base {base_mean:.3f})",
            ],
        },
        "evidence": [
            "docs/reports/fr8.md",
            "data/fr8/j4/slurm-44397.out",
            "data/fr8/j4/run-44397/runs/eval-base/episodes.jsonl",
            "data/fr8/j4/run-44397/runs/eval-lora/episodes.jsonl",
            "data/fr8/j4/run-44397/runs/eval-lora-par/episodes.jsonl",
        ],
        "notes": (
            "Protocol syntax jumped from 0.08 to 0.99 valid calls (~0.85 solver action-type agreement), "
            "but prefix 4k SFT (1.57% loss tokens) rarely committed and missed when accusing: "
            "dedup held-out n=12 scored -0.250 +/- 0.256 vs base 0.000."
        ),
    }


def _load_ws4_base_44411(external_data_root: Path) -> dict[str, Any]:
    secret_tag = "f272803cdb679dbe"
    paired_counterpart_secret = "c86b9c8a54f8b269"
    heldout_n = 16
    mean_score = 0.0
    ci95 = 0.0
    invalid_rate = 0.9703
    valid_rate = 0.0297
    valid_rate_short = 0.03
    eval_cap_rate = 1.0

    log_file = external_data_root / "j4" / "eval-44411.out"
    sum_file = external_data_root / "j4" / "runs" / "ws4-base-v14" / "summary.json"
    if log_file.is_file():
        m = re.search(r"sha256 ([0-9a-f]{16})", log_file.read_text(encoding="utf-8", errors="replace"))
        if m:
            secret_tag = m.group(1)
    if sum_file.is_file():
        s_all = json.loads(sum_file.read_text(encoding="utf-8"))["by_tier"]["all"]
        heldout_n = int(s_all["n"])
        mean_score = round(float(s_all["mean_score"]), 4)
        ci95 = round(float(s_all["ci95"]), 4)
        invalid_rate = round(float(s_all["invalid_call_rate"]), 4)
        valid_rate = round(1.0 - invalid_rate, 4)
        valid_rate_short = round(valid_rate, 2)
        eval_cap_rate = round(float(s_all["eval_cap_rate"]), 4)

    return {
        "run_id": "WS4-base-44411",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct (base)",
        "method": "Zero-shot base evaluation at 4k context (max_calls=120)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": heldout_n,
        "before_mean_score": mean_score,
        "after_mean_score": None,
        "after_ci95": ci95,
        "paired_mean_delta": None,
        "paired_ci95_low": None,
        "paired_ci95_high": None,
        "before_valid_call_rate": valid_rate_short,
        "after_valid_call_rate": None,
        "before_world_secret_tag": secret_tag,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "BASELINE_CAVEATED",
        "details": {
            "slurm_job_id": 44411,
            "world_secret_tag": secret_tag,
            "counterpart_44412_secret_tag": paired_counterpart_secret,
            "unpaired_urandom_secret_caveat": True,
            "invalid_call_rate": invalid_rate,
            "valid_call_rate_exact": valid_rate,
            "eval_cap_rate": eval_cap_rate,
            "mean_final_day": 1.0,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                f"baseline-only run; fresh os.urandom(32) secret ({secret_tag}) unpaired with 44412 ({paired_counterpart_secret})",
                f"heldout_n={heldout_n} < 30; 16/16 episodes hit eval_cap=120 on Day 1",
            ],
        },
        "evidence": [
            "docs/reports/CEO.md",
            "/home/silas/agent-arena-data/j4/eval-44411.out",
            "/home/silas/agent-arena-data/j4/runs/ws4-base-v14/summary.json",
        ],
        "notes": (
            "Qwen2.5-1.5B base v1.4 held-out n=16 scored 0.000 (valid call rate 0.03, never leaves Day 1); "
            "ran without CANARY_WORLD_SECRET so os.urandom(32) world key f272803cdb679dbe is unpaired vs 44412."
        ),
    }


def _load_ws4_base_pooled(repo_root: Path, external_data_root: Path) -> dict[str, Any]:
    sec_44411 = "f272803cdb679dbe"
    sec_44584 = "404f83e6a15c3f1c"
    sec_44583_aborted = "b8cf262cf76208ae"
    n_44411 = 16
    n_44584 = 20
    inv_44411 = 0.9703
    inv_44584 = 0.9721

    log_44411 = external_data_root / "j4" / "eval-44411.out"
    sum_44411 = external_data_root / "j4" / "runs" / "ws4-base-v14" / "summary.json"
    log_44584 = external_data_root / "j4" / "eval-44584.out"
    sum_44584_ext = external_data_root / "j4" / "runs" / "ws4-base-v14-off6" / "summary.json"
    sum_44584_repo = repo_root / "data" / "fr8" / "ws4" / "ws4-base-v14-off6" / "summary.json"

    if log_44411.is_file():
        m1 = re.search(r"sha256 ([0-9a-f]{16})", log_44411.read_text(encoding="utf-8", errors="replace"))
        if m1:
            sec_44411 = m1.group(1)
    if sum_44411.is_file():
        s1_all = json.loads(sum_44411.read_text(encoding="utf-8"))["by_tier"]["all"]
        n_44411 = int(s1_all["n"])
        inv_44411 = round(float(s1_all["invalid_call_rate"]), 4)

    if log_44584.is_file():
        m2 = re.search(r"sha256 ([0-9a-f]{16})", log_44584.read_text(encoding="utf-8", errors="replace"))
        if m2:
            sec_44584 = m2.group(1)
    sum_44584 = sum_44584_repo if sum_44584_repo.is_file() else sum_44584_ext
    if sum_44584.is_file():
        s2_all = json.loads(sum_44584.read_text(encoding="utf-8"))["by_tier"]["all"]
        n_44584 = int(s2_all["n"])
        inv_44584 = round(float(s2_all["invalid_call_rate"]), 4)

    heldout_n = n_44411 + n_44584
    pooled_invalid = round((n_44411 * inv_44411 + n_44584 * inv_44584) / max(heldout_n, 1), 4)
    pooled_valid_exact = round(1.0 - pooled_invalid, 4)
    pooled_valid_short = round(pooled_valid_exact, 2)

    return {
        "run_id": "WS4-base-pooled",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct (base, pooled)",
        "method": "Zero-shot base evaluation at 4k context (44411 n=16 + 44584 off6 n=20, max_calls=120)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": None,
        "after_ci95": 0.0,
        "paired_mean_delta": None,
        "paired_ci95_low": None,
        "paired_ci95_high": None,
        "before_valid_call_rate": pooled_valid_short,
        "after_valid_call_rate": None,
        "before_world_secret_tag": sec_44411,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "BASELINE_CAVEATED",
        "details": {
            "slurm_job_ids": [44411, 44584],
            "aborted_duplicate_job_id": 44583,
            "aborted_44583_secret_tag": sec_44583_aborted,
            "n_44411": n_44411,
            "n_44584": n_44584,
            "heldout_seed_range": "800000..800012",
            "by_tier_n": {"easy": 13, "medium": 12, "hard": 11},
            "world_secret_tags": [sec_44411, sec_44584],
            "unpaired_urandom_secret_caveat": True,
            "invalid_call_rate": pooled_invalid,
            "valid_call_rate_exact": pooled_valid_exact,
            "eval_cap_rate": 1.0,
            "mean_final_day": 1.0,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                f"baseline-only pooled reference (n={heldout_n}: 44411 n={n_44411} + 44584 n={n_44584}) across unpaired os.urandom(32) world secrets ({sec_44411} and {sec_44584})",
                f"{heldout_n}/{heldout_n} episodes hit eval_cap=120 on Day 1 without accusing (0.000 score, valid call rate {pooled_valid_short:.2f})",
            ],
        },
        "evidence": [
            "README.md",
            "docs/reports/fr8.md",
            "origin/justSilas-fr8@8f920b2f:data/fr8/ws4/ws4-base-v14-off6/summary.json",
            "origin/justSilas-fr8@8f920b2f:fr8/analysis/out/ws4_table_v3.md",
        ],
        "notes": (
            "Published pooled untrained Qwen2.5-1.5B base reference (n=36: job 44411 n=16 on 800000..800005 + "
            "job 44584 n=20 on 800006..800012) scored 0.000 +/- 0.000 because valid tool calls were 0.03 and "
            "all 36 episodes hit eval_cap=120 on Day 1."
        ),
    }


def _load_ws4_v2_44412(external_data_root: Path) -> dict[str, Any]:
    base_secret = "f272803cdb679dbe"
    v2_secret = "c86b9c8a54f8b269"
    header_tokens = 2842
    body_budget_tokens = 1254
    train_steps = 887
    train_episodes = 800
    windows = 14176
    oversample_endings = 3
    heldout_n = 82
    mean_score = -0.395
    ci95 = 0.128
    ci95_exact = 0.1283
    accused_count = 42
    accused_rate = 0.51
    accused_rate_exact = 0.5122
    accuracy_short = 0.06
    accuracy_exact = 0.061
    valid_rate = 0.9222
    eval_cap_count = 40

    train_log = external_data_root / "j4" / "slurm-44410.out"
    eval_log = external_data_root / "j4" / "eval-44412.out"
    sum_file = external_data_root / "j4" / "runs" / "ws4-v2-44410" / "summary.json"

    if train_log.is_file():
        txt = train_log.read_text(encoding="utf-8", errors="replace")
        mh = re.search(r"header\(system\+tools\+kickoff\)=(\d+)\s+tokens,\s+body budget=(\d+)", txt)
        if mh:
            header_tokens = int(mh.group(1))
            body_budget_tokens = int(mh.group(2))
        ms = re.search(r'"steps":\s*(\d+).*?"windows":\s*(\d+)', txt)
        if ms:
            train_steps = int(ms.group(1))
            windows = int(ms.group(2))

    if eval_log.is_file():
        m = re.search(r"sha256 ([0-9a-f]{16})", eval_log.read_text(encoding="utf-8", errors="replace"))
        if m:
            v2_secret = m.group(1)

    if sum_file.is_file():
        s_all = json.loads(sum_file.read_text(encoding="utf-8"))["by_tier"]["all"]
        heldout_n = int(s_all["n"])
        mean_score = round(float(s_all["mean_score"]), 3)
        ci95_exact = round(float(s_all["ci95"]), 4)
        ci95 = round(ci95_exact, 3)
        accuracy_exact = round(float(s_all["accuracy"]), 4)
        accuracy_short = round(accuracy_exact, 2)
        end_r = s_all.get("end_reasons", {})
        accused_count = int(end_r.get("accused", 42))
        eval_cap_count = int(end_r.get("eval_cap", 40))
        accused_rate_exact = round(accused_count / max(heldout_n, 1), 4)
        accused_rate = round(accused_rate_exact, 2)
        valid_rate = round(1.0 - float(s_all["invalid_call_rate"]), 4)

    return {
        "run_id": "WS4-v2-44412",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA r=16 (dense v2)",
        "method": "SFT dense 4k windows + oversample-endings 3 (887 steps on J3v14)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": mean_score,
        "after_ci95": ci95,
        "paired_mean_delta": mean_score,
        "paired_ci95_low": round(mean_score - ci95, 3),
        "paired_ci95_high": round(mean_score + ci95, 3),
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": round(valid_rate, 2),
        "before_world_secret_tag": base_secret,
        "after_world_secret_tag": v2_secret,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_BLIND_ACCUSE",
        "details": {
            "train_slurm_job_id": 44410,
            "eval_slurm_job_id": 44412,
            "train_episodes": train_episodes,
            "windows": windows,
            "train_steps": train_steps,
            "oversample_endings": oversample_endings,
            "header_tokens": header_tokens,
            "body_budget_tokens": body_budget_tokens,
            "ci95_exact": ci95_exact,
            "accused_count": accused_count,
            "accused_rate": accused_rate,
            "accused_rate_exact": accused_rate_exact,
            "eval_cap_count": eval_cap_count,
            "accuracy": accuracy_short,
            "accuracy_exact": accuracy_exact,
            "hard_accuracy": 0.0,
            "valid_call_rate_exact": valid_rate,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                f"unpaired os.urandom(32) world secret vs base 44411 ({base_secret} != {v2_secret})",
                f"40/82 episodes hit eval_cap=120; not paired replay-verified",
                f"severe score regression ({mean_score:.3f} +/- {ci95:.3f}) from blind accusations under 4k truncation",
            ],
        },
        "evidence": [
            "docs/reports/CEO.md",
            "/home/silas/agent-arena-data/j4/slurm-44410.out",
            "/home/silas/agent-arena-data/j4/eval-44412.out",
            "/home/silas/agent-arena-data/j4/runs/ws4-v2-44410/summary.json",
        ],
        "notes": (
            "Dense 4k + oversample-endings 3 on 100% accuse-only SFT caused blind accusations: "
            "held-out n=82 scored -0.395 +/- 0.128 (accused 0.51, correct 0.06; 0/27 correct on hard) "
            "because the 2,842-token header left only 1,254 body tokens and evicted employee/canary mappings."
        ),
    }


def _load_ws4_v3_oom(external_data_root: Path) -> dict[str, Any]:
    alloc_44548 = 5.49
    alloc_44550 = 5.52
    gpu_total_gib = 31.73
    n_states = 2000

    p48 = external_data_root / "v3" / "slurm-44548.out"
    p50 = external_data_root / "v3" / "slurm-44550.out"
    if p48.is_file():
        m = re.search(
            r"Tried to allocate ([0-9.]+) GiB\.\s*GPU 0 has a total capacity of ([0-9.]+) GiB",
            p48.read_text(encoding="utf-8", errors="replace"),
        )
        if m:
            alloc_44548 = float(m.group(1))
            gpu_total_gib = float(m.group(2))
    if p50.is_file():
        m = re.search(r"Tried to allocate ([0-9.]+) GiB", p50.read_text(encoding="utf-8", errors="replace"))
        if m:
            alloc_44550 = float(m.group(1))

    return {
        "run_id": "WS4-v3-44548-44550",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3 GRPO init from 44410)",
        "method": "Decision-point GRPO on 2,000 TRAIN states (150000+/151000+)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium"],
        "context_len": 4096,
        "heldout_n": 0,
        "before_mean_score": None,
        "after_mean_score": None,
        "after_ci95": None,
        "paired_mean_delta": None,
        "paired_ci95_low": None,
        "paired_ci95_high": None,
        "before_valid_call_rate": None,
        "after_valid_call_rate": None,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "FAILED_CUDA_OOM",
        "details": {
            "slurm_job_ids": [44548, 44550],
            "n_states": n_states,
            "gpu_total_gib": gpu_total_gib,
            "failed_alloc_gib_44548": alloc_44548,
            "failed_alloc_gib_44550": alloc_44550,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "CUDA OOM on V100-32GB during batched group generation / full-logit sampling at step 0",
                "heldout_n=0 < 30",
            ],
        },
        "evidence": [
            "/home/silas/agent-arena-data/v3/slurm-44548.out",
            "/home/silas/agent-arena-data/v3/slurm-44550.out",
        ],
        "notes": (
            "Decision-point GRPO OOMed V100-32GB (tried to allocate 5.49-5.52 GiB above ~26.5 GiB reserved) "
            "during unchunked group prefill and full-logit sampling."
        ),
    }


def _load_ws4_v3_44553(external_data_root: Path) -> dict[str, Any]:
    steps_logged = 6
    zero_var_10 = 8
    total_groups_window = 10
    zero_var_12 = 10

    curve_file = external_data_root / "v3" / "run-44553" / "curve.jsonl"
    if curve_file.is_file():
        rows = _read_jsonl(curve_file)
        if len(rows) >= 5:
            steps_logged = len(rows)
            zero_var_10 = sum(int(r["zero_var_groups"]) for r in rows[:5])
            zero_var_12 = sum(int(r["zero_var_groups"]) for r in rows[:6])

    return {
        "run_id": "WS4-v3-44553",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3 GRPO unguided)",
        "method": "Decision-point GRPO with gradient checkpointing, unguided sampling",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium"],
        "context_len": 4096,
        "heldout_n": 0,
        "before_mean_score": None,
        "after_mean_score": None,
        "after_ci95": None,
        "paired_mean_delta": None,
        "paired_ci95_low": None,
        "paired_ci95_high": None,
        "before_valid_call_rate": None,
        "after_valid_call_rate": None,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "FAILED_ZERO_VARIANCE",
        "details": {
            "slurm_job_id": 44553,
            "steps_logged": steps_logged,
            "zero_variance_groups_first_10": zero_var_10,
            "groups_first_window": total_groups_window,
            "zero_variance_groups_all_12": zero_var_12,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                f"{zero_var_10}/{total_groups_window} GRPO groups had zero reward variance (continue_frac=1.0, accuse_frac=0.0)",
                "terminated at step 5 to add guided forced-accuse exploration; heldout_n=0",
            ],
        },
        "evidence": [
            "docs/reports/CEO.md",
            "/home/silas/agent-arena-data/v3/slurm-44553.out",
            "/home/silas/agent-arena-data/v3/run-44553/curve.jsonl",
        ],
        "notes": (
            "Unguided GRPO collapsed to continue_frac=1.0 (8/10 groups zero variance in first 5 steps; "
            "10/12 across 6 steps) before guided forced-accuse exploration was introduced."
        ),
    }


def _load_ws4_v2_off30(repo_root: Path) -> dict[str, Any]:
    heldout_n = 90
    mean_score_exact = -0.5142
    ci95_exact = 0.1152
    accused_count = 52
    eval_cap_count = 38
    accuracy_exact = 0.0333
    invalid_call_rate = 0.0825

    sum_file = repo_root / "data" / "fr8" / "verda" / "evalbox-68bb" / "v2-off30" / "summary.json"
    if sum_file.is_file():
        s_all = json.loads(sum_file.read_text(encoding="utf-8"))["by_tier"]["all"]
        heldout_n = int(s_all["n"])
        mean_score_exact = round(float(s_all["mean_score"]), 4)
        ci95_exact = round(float(s_all["ci95"]), 4)
        accuracy_exact = round(float(s_all["accuracy"]), 4)
        end_r = s_all.get("end_reasons", {})
        accused_count = int(end_r.get("accused", 52))
        eval_cap_count = int(end_r.get("eval_cap", 38))
        invalid_call_rate = round(float(s_all["invalid_call_rate"]), 4)

    mean_score = round(mean_score_exact, 3)
    ci95 = round(ci95_exact, 3)
    valid_short = round(1.0 - invalid_call_rate, 2)

    return {
        "run_id": "WS4-v2-off30-68bb",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA r=16 (dense v2, off30)",
        "method": "SFT dense 4k + oversample-endings 3 evaluated on held-out seeds 800030..800059 (Verda A100 68bbe201)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": mean_score,
        "after_ci95": ci95,
        "paired_mean_delta": mean_score,
        "paired_ci95_low": round(mean_score - ci95, 3),
        "paired_ci95_high": round(mean_score + ci95, 3),
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": valid_short,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_BLIND_ACCUSE",
        "details": {
            "verda_instance": "68bbe201",
            "heldout_seed_range": "800030..800059",
            "mean_score_exact": mean_score_exact,
            "ci95_exact": ci95_exact,
            "accused_count": accused_count,
            "eval_cap_count": eval_cap_count,
            "accuracy_exact": accuracy_exact,
            "hard_accuracy": 0.0,
            "invalid_call_rate": invalid_call_rate,
            "pooled_v2_n": 172,
            "pooled_v2_mean_score": -0.457,
            "pooled_v2_ci95": 0.086,
            "pooled_v2_accused_count": 94,
            "pooled_v2_correct_count": 8,
            "pooled_v2_accused_rate": 0.55,
            "pooled_v2_precision": 0.09,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "unpaired per-process world secret on Verda evalbox 68bbe201",
                f"{eval_cap_count}/{heldout_n} episodes hit eval_cap=120",
                f"negative held-out score ({mean_score:.3f} +/- {ci95:.3f} on off30 n={heldout_n}; pooled v2 n=172 is -0.457 +/- 0.086)",
            ],
        },
        "evidence": [
            "README.md",
            "docs/reports/fr8.md",
            "data/fr8/verda/evalbox-68bb/v2-off30/summary.json",
            "origin/justSilas-fr8@8f920b2f:fr8/analysis/out/ws4_table_v3.md",
        ],
        "notes": (
            "Verda A100 extra held-out n=90 (800030..800059) confirmed v2 blind-accusation collapse: "
            "-0.514 +/- 0.115 (52/90 accused, 3/90 correct, 0/30 on hard); pooled v2 n=172 is -0.457 +/- 0.086 "
            "(accused 94/172 = 0.55, precision 8/94 = 0.09)."
        ),
    }


def _load_ws4_v3_4k_s1_714d_spot(repo_root: Path) -> dict[str, Any]:
    spot_preempted = True
    inst_capture = repo_root / "data" / "fr8" / "verda" / "instances-0308.txt"
    if inst_capture.is_file():
        txt = inst_capture.read_text(encoding="utf-8", errors="replace")
        spot_preempted = "714d8144" not in txt

    return {
        "run_id": "WS4-v3-4k-s1-714d-spot",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3-4k s1 spot replicate)",
        "method": "Guided decision-point GRPO at 4k context on Verda A100-80GB spot 714d8144",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": 0,
        "before_mean_score": None,
        "after_mean_score": None,
        "after_ci95": None,
        "paired_mean_delta": None,
        "paired_ci95_low": None,
        "paired_ci95_high": None,
        "before_valid_call_rate": None,
        "after_valid_call_rate": None,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "FAILED_SPOT_PREEMPTED",
        "details": {
            "verda_instance": "714d8144",
            "verda_instance_full": "714d8144-c036-4814-999d-a38ed192a48f",
            "gpu": "A100-80GB spot (1A100.22V)",
            "region": "FIN-01",
            "grpo_replicate": 1,
            "approx_train_minutes": 29,
            "spot_preempted": spot_preempted,
            "eval_episodes": 0,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "Verda A100-80GB spot instance 714d8144 preempted ~30 min into 4k GRPO training (started 02:39, gone by 03:08)",
                "heldout_n=0 < 30; 0 evaluation episodes completed",
            ],
        },
        "evidence": [
            "fr8/verda/README.md",
            "data/fr8/verda/instances-0308.txt",
        ],
        "notes": (
            "Verda A100-80GB spot instance 714d8144 (4k GRPO s1 replicate) was preempted ~30m into training "
            "(launched 02:39, absent from 03:08 SDK capture); 0 eval episodes completed."
        ),
    }


def _load_ws4_v3_4k_s1_44572(repo_root: Path, external_data_root: Path) -> dict[str, Any]:
    grpo_steps = 192
    n_states = 2000
    train_seed_start = 150000
    before_secret = "f272803cdb679dbe"
    after_secret = "09f8bc6443018b18"
    heldout_n = 82
    mean_score_exact = -0.2088
    ci95_exact = 0.0938
    accused_count = 19
    eval_cap_count = 63
    accuracy_exact = 0.0122
    invalid_call_rate = 0.0312
    easy_n = 28
    medium_n = 27
    hard_n = 27
    easy_score = -0.576
    medium_score = 0.0
    hard_score = -0.037

    ts_repo = repo_root / "data" / "fr8" / "ws4" / "v3-s1-44572-train" / "train_summary.json"
    ts_ext = external_data_root / "v3" / "run-44572" / "lora" / "train_summary.json"
    ts_file = ts_repo if ts_repo.is_file() else ts_ext
    if ts_file.is_file():
        ts = json.loads(ts_file.read_text(encoding="utf-8"))
        grpo_steps = int(ts.get("steps", 192))
        t_args = ts.get("args") or {}
        n_states = int(t_args.get("n_states", 2000))
        train_seed_start = int(t_args.get("seed_base", 150000))

    eval_log = external_data_root / "j4" / "eval-44573.out"
    if eval_log.is_file():
        m = re.search(r"sha256 ([0-9a-f]{16})", eval_log.read_text(encoding="utf-8", errors="replace"))
        if m:
            after_secret = m.group(1)

    sum_repo = repo_root / "data" / "fr8" / "ws4" / "v3-s1-44572" / "summary.json"
    sum_ext = external_data_root / "v3" / "runs" / "v3-s1-44572" / "summary.json"
    sum_file = sum_repo if sum_repo.is_file() else sum_ext
    if sum_file.is_file():
        by_tier = json.loads(sum_file.read_text(encoding="utf-8"))["by_tier"]
        s_all = by_tier["all"]
        heldout_n = int(s_all["n"])
        mean_score_exact = round(float(s_all["mean_score"]), 4)
        ci95_exact = round(float(s_all["ci95"]), 4)
        accuracy_exact = round(float(s_all["accuracy"]), 4)
        end_r = s_all.get("end_reasons") or {}
        accused_count = int(end_r.get("accused", 19))
        eval_cap_count = int(end_r.get("eval_cap", 63))
        invalid_call_rate = round(float(s_all["invalid_call_rate"]), 4)
        easy_n = int(by_tier["easy"]["n"])
        medium_n = int(by_tier["medium"]["n"])
        hard_n = int(by_tier["hard"]["n"])
        easy_score = round(float(by_tier["easy"]["mean_score"]), 3)
        medium_score = round(float(by_tier["medium"]["mean_score"]), 3)
        hard_score = round(float(by_tier["hard"]["mean_score"]), 3)

    mean_score = round(mean_score_exact, 3)
    ci95 = round(ci95_exact, 3)
    valid_short = round(1.0 - invalid_call_rate, 2)
    accused_rate = round(accused_count / max(heldout_n, 1), 2)
    abstain_rate = round(eval_cap_count / max(heldout_n, 1), 2)
    accuracy_short = round(accuracy_exact, 2)
    correct_count = round(accuracy_exact * heldout_n)

    return {
        "run_id": "WS4-v3-4k-s1-44572",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3-4k s1, 192 GRPO steps, FR8 V100 n=82)",
        "method": "Guided decision-point GRPO on FR8 V100 job 44572 (4.0h, ~191-192 steps, max_ctx=4096; finalized eval 44573 n=82)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": mean_score,
        "after_ci95": ci95,
        "paired_mean_delta": mean_score,
        "paired_ci95_low": round(mean_score - ci95, 3),
        "paired_ci95_high": round(mean_score + ci95, 3),
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": valid_short,
        "before_world_secret_tag": before_secret,
        "after_world_secret_tag": after_secret,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_FLAT_V100_REPLICATE",
        "details": {
            "train_slurm_job_id": 44572,
            "eval_slurm_job_id": 44573,
            "precursor_slurm_job_id": 44555,
            "gpu": "Tesla V100-PCIE-32GB",
            "grpo_steps": grpo_steps,
            "train_hours": 4.0,
            "n_states": n_states,
            "train_seed_start": train_seed_start,
            "grpo_replicate": 1,
            "forced_accuse_whom_first_w96": 0.224,
            "forced_accuse_whom_last_w96": 0.267,
            "heldout_seed_range": "800000..800027",
            "by_tier_n": {"easy": easy_n, "medium": medium_n, "hard": hard_n},
            "mean_score_exact": mean_score_exact,
            "ci95_exact": ci95_exact,
            "accused_count": accused_count,
            "eval_cap_count": eval_cap_count,
            "abstain_count": eval_cap_count,
            "accused_rate": accused_rate,
            "correct_count": correct_count,
            "accuracy": accuracy_short,
            "accuracy_exact": accuracy_exact,
            "precision_when_accused": round(correct_count / max(accused_count, 1), 2),
            "abstain_rate": abstain_rate,
            "invalid_call_rate": invalid_call_rate,
            "easy_score": easy_score,
            "medium_score": medium_score,
            "hard_score": hard_score,
            "two_sample_delta_vs_base_mean": -0.209,
            "two_sample_delta_vs_base_ci95": 0.094,
            "two_sample_delta_vs_v2_mean": 0.249,
            "two_sample_delta_vs_v2_ci95": 0.127,
            "two_sample_delta_vs_v3_4k_s0_mean": -0.061,
            "two_sample_delta_vs_v3_4k_s0_ci95": 0.113,
            "partial_n25_mean_score": -0.24,
            "partial_n25_ci95": 0.171,
            "partial_n25_accused_rate": 0.24,
            "partial_n25_accuracy": 0.0,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                f"unpaired per-process world secret ({before_secret} vs {after_secret})",
                f"{eval_cap_count}/{heldout_n} episodes hit eval_cap=120 (28 easy, 27 medium, 27 hard)",
                f"flat training dynamics (whom-acc 0.22 -> 0.27 over ~191-192 V100 steps) and negative held-out score ({mean_score:.3f} +/- {ci95:.3f}, 1/19 correct; earlier partial n=25 was -0.240 +/- 0.171)",
            ],
        },
        "evidence": [
            "docs/reports/fr8.md",
            "origin/justSilas-fr8@94d33248:fr8/analysis/out/ws4_table_final.md",
            "origin/justSilas-fr8@94d33248:data/fr8/ws4/v3-s1-44572/summary.json",
            "/home/silas/agent-arena-data/v3/run-44572/lora/train_summary.json",
        ],
        "notes": (
            "Finalized FR8 V100 ~191-192-step 4k GRPO s1 replicate (job 44572/44573) scored -0.209 +/- 0.094 "
            "on held-out n=82 (valid 0.97, accused 0.23 = 19/82, correct 0.01 = 1/82, abstain 0.77 = 63/82; "
            "two-sample +0.249 +/- 0.127 vs v2; earlier partial n=25 was -0.240 +/- 0.171) after flat training "
            "whom-accuracy (0.224 -> 0.267)."
        ),
    }


def _load_ws4_v3_verda_s0_eval(repo_root: Path) -> dict[str, Any]:
    grpo_steps = 609
    s0_n = 90
    s0_mean = -0.103
    s0_ci95 = 0.081
    s0_accused = 15
    s0_eval_cap = 75
    off30_n = 90
    off30_mean_exact = -0.1919
    off30_ci95_exact = 0.0959
    off30_accused = 23
    off30_eval_cap = 67

    ts_file = repo_root / "data" / "fr8" / "verda" / "h100-3bb7" / "run-verda-s0" / "lora" / "train_summary.json"
    s0_sum = repo_root / "data" / "fr8" / "verda" / "h100-3bb7" / "runs" / "v3-verda-s0" / "summary.json"
    off30_sum = repo_root / "data" / "fr8" / "verda" / "evalbox-68bb" / "v3-4k-s0-off30" / "summary.json"

    if ts_file.is_file():
        grpo_steps = int(json.loads(ts_file.read_text(encoding="utf-8")).get("steps", 609))
    if s0_sum.is_file():
        s0_all = json.loads(s0_sum.read_text(encoding="utf-8"))["by_tier"]["all"]
        s0_n = int(s0_all["n"])
        s0_mean = round(float(s0_all["mean_score"]), 3)
        s0_ci95 = round(float(s0_all["ci95"]), 3)
        s0_accused = int((s0_all.get("end_reasons") or {}).get("accused", 15))
        s0_eval_cap = int((s0_all.get("end_reasons") or {}).get("eval_cap", 75))
    if off30_sum.is_file():
        off_all = json.loads(off30_sum.read_text(encoding="utf-8"))["by_tier"]["all"]
        off30_n = int(off_all["n"])
        off30_mean_exact = round(float(off_all["mean_score"]), 4)
        off30_ci95_exact = round(float(off_all["ci95"]), 4)
        off30_accused = int((off_all.get("end_reasons") or {}).get("accused", 23))
        off30_eval_cap = int((off_all.get("end_reasons") or {}).get("eval_cap", 67))

    heldout_n = s0_n + off30_n
    pooled_mean = round((s0_n * s0_mean + off30_n * off30_mean_exact) / max(heldout_n, 1), 3)
    pooled_ci95 = 0.063
    accused_count = s0_accused + off30_accused
    eval_cap_count = s0_eval_cap + off30_eval_cap
    correct_count = 6
    accused_rate = round(accused_count / max(heldout_n, 1), 2)
    precision_when_accused = round(correct_count / max(accused_count, 1), 2)

    return {
        "run_id": "WS4-v3-verda-s0-eval",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3-4k s0, 609 GRPO steps, pooled n=180)",
        "method": "Guided decision-point GRPO on Verda H100 3bb74f5a (2.0h, 609 steps, max_ctx=4096; s0 + off30 pooled)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": pooled_mean,
        "after_ci95": pooled_ci95,
        "paired_mean_delta": pooled_mean,
        "paired_ci95_low": round(pooled_mean - pooled_ci95, 3),
        "paired_ci95_high": round(pooled_mean + pooled_ci95, 3),
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": 1.00,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_4K_TRUNCATION_PERSISTS",
        "details": {
            "verda_instance": "3bb74f5a",
            "verda_off30_instance": "68bbe201",
            "adapter_sha256_12": "3d0cd43b8037",
            "grpo_steps": grpo_steps,
            "train_hours": 2.0,
            "step_140_valid_only_gain_vs_solver": 0.091,
            "forced_accuse_whom_first_w100": 0.19,
            "forced_accuse_whom_last_w100": 0.892,
            "forced_accuse_whom_last_reported": 0.89,
            "train_state_draws": 1218,
            "train_state_pool": 2000,
            "heldout_seed_range": "800000..800059",
            "s0_n": s0_n,
            "s0_mean_score": s0_mean,
            "s0_ci95": s0_ci95,
            "off30_n": off30_n,
            "off30_mean_score": round(off30_mean_exact, 3),
            "off30_mean_score_exact": off30_mean_exact,
            "off30_ci95": round(off30_ci95_exact, 3),
            "off30_ci95_exact": off30_ci95_exact,
            "accused_count": accused_count,
            "eval_cap_count": eval_cap_count,
            "accused_rate": accused_rate,
            "abstain_rate": round(eval_cap_count / max(heldout_n, 1), 2),
            "correct_count": correct_count,
            "accuracy": 0.03,
            "accuracy_exact": 0.0333,
            "precision_when_accused": precision_when_accused,
            "easy_score": -0.409,
            "medium_score": 0.0,
            "hard_score": -0.033,
            "medium_accuracy": 0.0,
            "hard_accuracy": 0.0,
            "delta_vs_v2_mean": 0.31,
            "delta_vs_v2_ci95": 0.107,
            "delta_vs_base_mean": -0.147,
            "delta_vs_base_ci95": 0.063,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "unpaired per-process world secrets across Verda H100 s0 (800000..800029), A100 off30 (800030..800059), and FR8 base",
                f"{eval_cap_count}/{heldout_n} episodes hit eval_cap=120",
                "pooled held-out score remained negative (-0.147 +/- 0.063, n=180; 6/38 = 0.16 precision) despite +0.310 +/- 0.107 two-sample gain over v2",
            ],
        },
        "evidence": [
            "README.md",
            "docs/reports/fr8.md",
            "data/fr8/verda/h100-3bb7/runs/v3-verda-s0/summary.json",
            "data/fr8/verda/evalbox-68bb/v3-4k-s0-off30/summary.json",
            "origin/justSilas-fr8@8f920b2f:fr8/analysis/out/ws4_table_v3.md",
        ],
        "notes": (
            "Pooled v3-4k-s0 across held-out 800000..800059 (n=180: s0 n=90 -0.103 +/- 0.081 + off30 n=90 "
            "-0.192 +/- 0.096) scored -0.147 +/- 0.063 (valid 1.00, accused 38/180 = 0.21, correct 6/38 = 0.16; "
            "two-sample +0.310 +/- 0.107 vs v2), learning solver-state culprit reading (0.19 -> 0.89) but not "
            "autonomous evidence gathering."
        ),
    }


def _load_ws4_v3_4k_s0_ctx8k() -> dict[str, Any]:
    return {
        "run_id": "WS4-v3-4k-s0-ctx8k",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3-4k s0 evaluated at max_ctx=8192)",
        "method": "Same 609-step 4k GRPO adapter (3d0cd43b8037) evaluated at 8k context on Verda A100 68bbe201 (shared secret 1ca0c2a64d)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 8192,
        "heldout_n": 90,
        "before_mean_score": 0.0,
        "after_mean_score": -0.716,
        "after_ci95": 0.105,
        "paired_mean_delta": -0.716,
        "paired_ci95_low": -0.821,
        "paired_ci95_high": -0.611,
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": 0.99,
        "before_world_secret_tag": None,
        "after_world_secret_tag": "1ca0c2a64d",
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_INFERENCE_CTX_CONFOUND",
        "details": {
            "verda_eval_instance": "68bbe201",
            "adapter_sha256_12": "3d0cd43b8037",
            "grpo_steps": 609,
            "train_context_len": 4096,
            "eval_context_len": 8192,
            "shared_world_secret_tag": "1ca0c2a64d",
            "heldout_seed_range": "800000..800029",
            "accused_count": 70,
            "accused_rate": 0.78,
            "correct_count": 3,
            "accuracy": 0.03,
            "precision_when_accused": 0.0429,
            "abstain_rate": 0.22,
            "easy_score": -0.447,
            "easy_accused_rate": 0.63,
            "medium_score": -0.800,
            "medium_accused_rate": 0.80,
            "hard_score": -0.900,
            "hard_accused_rate": 0.90,
            "two_sample_delta_vs_4k_mean": -0.568,
            "two_sample_delta_vs_4k_ci95": 0.123,
            "two_sample_delta_vs_v2_mean": -0.258,
            "two_sample_delta_vs_v2_ci95": 0.136,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "shared secret 1ca0c2a64d is paired with WS4-v3-8k-s0-3bb7, WS4-v3-8k-s3-f437, WS4-dagger-r1-8k-verda, and WS4-dagger-r1-4k-verda, but untrained base never ran under 1ca0c2a64d",
                "inference-length confound: raising eval max_ctx from 4096 to 8192 flipped medium/hard accusations from 0.00/0.03 to 0.80/0.90 (0 correct)",
                "severe held-out regression (-0.716 +/- 0.105, n=90; two-sample -0.568 +/- 0.123 vs 4k inference)",
            ],
        },
        "evidence": [
            "origin/justSilas-fr8@8f920b2f:docs/reports/fr8.md",
            "origin/justSilas-fr8@8f920b2f:fr8/analysis/out/ws4_table_v3.md",
            "origin/justSilas-fr8@8f920b2f:fr8/verda/README.md",
        ],
        "notes": (
            "Evaluating the exact same 609-step 4k adapter (3d0cd43b8037) at max_ctx=8192 under shared secret "
            "1ca0c2a64d dropped held-out n=90 from -0.147 to -0.716 +/- 0.105 (two-sample -0.568 +/- 0.123 vs 4k; "
            "accused 0.78, 3/70 correct), proving longer inference context alone triggers reckless accusations."
        ),
    }


def _load_ws4_v3_8k_s0_3bb7(repo_root: Path) -> dict[str, Any]:
    grpo_steps = 637
    heldout_n = 90
    mean_score_exact = -0.0604
    ci95_exact = 0.0536
    accused_count = 7
    eval_cap_count = 68
    horizon_count = 15
    accuracy_exact = 0.0111
    invalid_call_rate = 0.0216

    ts_file = repo_root / "data" / "fr8" / "verda" / "h100-3bb7" / "run-verda-8k-s0" / "lora" / "train_summary.json"
    sum_file = repo_root / "data" / "fr8" / "verda" / "h100-3bb7" / "runs" / "v3-verda-8k-s0" / "summary.json"

    if ts_file.is_file():
        grpo_steps = int(json.loads(ts_file.read_text(encoding="utf-8")).get("steps", 637))
    if sum_file.is_file():
        s_all = json.loads(sum_file.read_text(encoding="utf-8"))["by_tier"]["all"]
        heldout_n = int(s_all["n"])
        mean_score_exact = round(float(s_all["mean_score"]), 4)
        ci95_exact = round(float(s_all["ci95"]), 4)
        accuracy_exact = round(float(s_all["accuracy"]), 4)
        end_r = s_all.get("end_reasons") or {}
        accused_count = int(end_r.get("accused", 7))
        eval_cap_count = int(end_r.get("eval_cap", 68))
        horizon_count = int(end_r.get("horizon", 15))
        invalid_call_rate = round(float(s_all["invalid_call_rate"]), 4)

    mean_score = round(mean_score_exact, 3)
    ci95 = round(ci95_exact, 3)
    valid_short = round(1.0 - invalid_call_rate, 2)
    abstain_count = eval_cap_count + horizon_count
    accused_rate = round(accused_count / max(heldout_n, 1), 2)
    abstain_rate = round(abstain_count / max(heldout_n, 1), 2)
    accuracy_short = round(accuracy_exact, 2)

    return {
        "run_id": "WS4-v3-8k-s0-3bb7",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3-8k s0, 637 GRPO steps, shared secret)",
        "method": "Guided decision-point GRPO at 8k context on Verda H100 3bb74f5a (3.0h, 637 steps; eval under shared secret 1ca0c2a64d)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 8192,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": mean_score,
        "after_ci95": ci95,
        "paired_mean_delta": mean_score,
        "paired_ci95_low": round(mean_score - ci95, 3),
        "paired_ci95_high": round(mean_score + ci95, 3),
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": valid_short,
        "before_world_secret_tag": None,
        "after_world_secret_tag": "1ca0c2a64d",
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_ABSTAIN_COLLAPSE",
        "details": {
            "verda_instance": "3bb74f5a",
            "gpu": "H100-80GB on-demand",
            "grpo_steps": grpo_steps,
            "train_hours": 3.0,
            "grpo_replicate": 0,
            "shared_world_secret_tag": "1ca0c2a64d",
            "heldout_seed_range": "800000..800029",
            "mean_score_exact": mean_score_exact,
            "ci95_exact": ci95_exact,
            "accused_count": accused_count,
            "eval_cap_count": eval_cap_count,
            "horizon_count": horizon_count,
            "abstain_count": abstain_count,
            "accused_rate": accused_rate,
            "correct_count": 1,
            "accuracy": accuracy_short,
            "accuracy_exact": accuracy_exact,
            "precision_when_accused": 0.14,
            "abstain_rate": abstain_rate,
            "invalid_call_rate": invalid_call_rate,
            "easy_score": -0.033,
            "medium_score": -0.067,
            "hard_score": -0.081,
            "two_sample_delta_vs_v2_mean": 0.397,
            "two_sample_delta_vs_v2_ci95": 0.101,
            "two_sample_delta_vs_v3_4k_s0_mean": 0.087,
            "two_sample_delta_vs_v3_4k_s0_ci95": 0.083,
            "paired_counterpart_run_id": "WS4-v3-8k-s3-f437",
            "paired_vs_8k_s3_mean_delta": 0.728,
            "paired_vs_8k_s3_ci95": 0.134,
            "paired_vs_8k_s3_n": 90,
            "paired_vs_4k_ctx8k_mean_delta": 0.655,
            "paired_vs_4k_ctx8k_ci95": 0.116,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "unpaired vs untrained FR8 base; truly paired under shared secret 1ca0c2a64d against WS4-v3-8k-s3-f437 (+0.728 +/- 0.134, n=90)",
                f"{eval_cap_count}/{heldout_n} episodes hit eval_cap=120 and {horizon_count}/{heldout_n} hit horizon (83/90 abstained)",
                f"collapsed to 92% abstention ({mean_score:.3f} +/- {ci95:.3f}, accused {accused_rate:.2f} = 7/90, correct {accuracy_short:.2f} = 1/90)",
            ],
        },
        "evidence": [
            "VERDA.md",
            "origin/justSilas-fr8@94d33248:fr8/analysis/out/ws4_table_final.md",
            "origin/justSilas-fr8@94d33248:fr8/analysis/out/ws4_table_8k_shared_secret_paired.md",
            "origin/justSilas-fr8@94d33248:data/fr8/verda/h100-3bb7/runs/v3-verda-8k-s0/summary.json",
            "origin/justSilas-fr8@94d33248:data/fr8/verda/h100-3bb7/run-verda-8k-s0/lora/train_summary.json",
        ],
        "notes": (
            "Verda H100 637-step 8k GRPO s0 under shared secret 1ca0c2a64d collapsed to conservative abstention "
            "on held-out n=90 (800000..800029): -0.060 +/- 0.054 (-0.0604 +/- 0.0536, valid 0.98, accused 0.08 = "
            "7/90, correct 0.01 = 1/90, abstain 0.92 = 83/90; two-sample +0.397 +/- 0.101 vs v2; truly paired "
            "+0.728 +/- 0.134 vs WS4-v3-8k-s3-f437 on n=90 identical worlds)."
        ),
    }


def _load_ws4_v3_8k_s1_ac58(repo_root: Path) -> dict[str, Any]:
    grpo_steps = 371
    heldout_n = 90
    mean_score_exact = -0.7767
    ci95_exact = 0.118
    accused_count = 85
    eval_cap_count = 4
    horizon_count = 1
    accuracy_exact = 0.0889
    invalid_call_rate = 0.0775

    ts_file = repo_root / "data" / "fr8" / "verda" / "a100-ac58" / "run-verda-8k-s1" / "lora" / "train_summary.json"
    sum_file = repo_root / "data" / "fr8" / "verda" / "a100-ac58" / "runs" / "v3-verda-8k-s1" / "summary.json"

    if ts_file.is_file():
        grpo_steps = int(json.loads(ts_file.read_text(encoding="utf-8")).get("steps", 371))
    if sum_file.is_file():
        s_all = json.loads(sum_file.read_text(encoding="utf-8"))["by_tier"]["all"]
        heldout_n = int(s_all["n"])
        mean_score_exact = round(float(s_all["mean_score"]), 4)
        ci95_exact = round(float(s_all["ci95"]), 4)
        accuracy_exact = round(float(s_all["accuracy"]), 4)
        end_r = s_all.get("end_reasons") or {}
        accused_count = int(end_r.get("accused", 85))
        eval_cap_count = int(end_r.get("eval_cap", 4))
        horizon_count = int(end_r.get("horizon", 1))
        invalid_call_rate = round(float(s_all["invalid_call_rate"]), 4)

    mean_score = round(mean_score_exact, 3)
    ci95 = round(ci95_exact, 3)
    valid_short = round(1.0 - invalid_call_rate, 2)
    accused_rate = round(accused_count / max(heldout_n, 1), 2)
    accuracy_short = round(accuracy_exact, 2)

    return {
        "run_id": "WS4-v3-8k-s1-ac58",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3-8k s1, 371 GRPO steps)",
        "method": "Guided decision-point GRPO at 8k context on Verda A100-80GB spot ac58df04 (3.0h, 371 steps)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 8192,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": mean_score,
        "after_ci95": ci95,
        "paired_mean_delta": mean_score,
        "paired_ci95_low": round(mean_score - ci95, 3),
        "paired_ci95_high": round(mean_score + ci95, 3),
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": valid_short,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_OFFPOLICY_OVERACCUSE",
        "details": {
            "verda_instance": "ac58df04",
            "gpu": "A100-80GB spot",
            "grpo_steps": grpo_steps,
            "train_hours": 3.01,
            "grpo_replicate": 1,
            "heldout_seed_range": "800000..800029",
            "mean_score_exact": mean_score_exact,
            "ci95_exact": ci95_exact,
            "accused_count": accused_count,
            "eval_cap_count": eval_cap_count,
            "horizon_count": horizon_count,
            "accused_rate": accused_rate,
            "correct_count": 8,
            "accuracy": accuracy_short,
            "accuracy_exact": accuracy_exact,
            "precision_when_accused": 0.09,
            "abstain_rate": round((eval_cap_count + horizon_count) / max(heldout_n, 1), 2),
            "invalid_call_rate": invalid_call_rate,
            "forced_accuse_whom_first_w100": 0.35,
            "forced_accuse_whom_last_w100": 0.412,
            "easy_score": -0.580,
            "medium_score": -0.938,
            "hard_score": -0.813,
            "two_sample_delta_vs_v3_4k_s0_mean": -0.629,
            "two_sample_delta_vs_v3_4k_s0_ci95": 0.134,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "unpaired per-process world secret on Verda A100-80GB spot ac58df04",
                f"{eval_cap_count}/{heldout_n} episodes hit eval_cap=120",
                f"off-policy + 8k context over-accusation ({mean_score:.3f} +/- {ci95:.3f}, accused {accused_rate:.2f}, correct {accuracy_short:.2f})",
            ],
        },
        "evidence": [
            "docs/reports/fr8.md",
            "data/fr8/verda/a100-ac58/runs/v3-verda-8k-s1/summary.json",
            "data/fr8/verda/a100-ac58/run-verda-8k-s1/lora/train_summary.json",
            "origin/justSilas-fr8@8f920b2f:fr8/analysis/out/ws4_table_v3.md",
        ],
        "notes": (
            "Verda A100-80GB spot 371-step 8k GRPO s1 scored -0.777 +/- 0.118 on held-out n=90 (valid 0.92, "
            "accused 0.94, correct 0.09 = 8/85 precision); 8k gave a step 0..99 whom head start (0.35 vs 0.19) "
            "but did not learn faster at steps 271..370 (0.41 vs 0.37) and over-accused early on own states."
        ),
    }


def _load_ws4_v3_8k_s2_dbd0(repo_root: Path) -> dict[str, Any]:
    grpo_steps = 693
    heldout_n = 90
    mean_score_exact = -0.0498
    ci95_exact = 0.0492
    accused_count = 6
    eval_cap_count = 59
    horizon_count = 25
    accuracy_exact = 0.0111
    invalid_call_rate = 0.037

    ts_file = repo_root / "data" / "fr8" / "verda" / "h100spot-dbd0" / "run-verda-8k-s2" / "lora" / "train_summary.json"
    sum_file = repo_root / "data" / "fr8" / "verda" / "h100spot-dbd0" / "runs" / "v3-verda-8k-s2" / "summary.json"

    if ts_file.is_file():
        grpo_steps = int(json.loads(ts_file.read_text(encoding="utf-8")).get("steps", 693))
    if sum_file.is_file():
        s_all = json.loads(sum_file.read_text(encoding="utf-8"))["by_tier"]["all"]
        heldout_n = int(s_all["n"])
        mean_score_exact = round(float(s_all["mean_score"]), 4)
        ci95_exact = round(float(s_all["ci95"]), 4)
        accuracy_exact = round(float(s_all["accuracy"]), 4)
        end_r = s_all.get("end_reasons") or {}
        accused_count = int(end_r.get("accused", 6))
        eval_cap_count = int(end_r.get("eval_cap", 59))
        horizon_count = int(end_r.get("horizon", 25))
        invalid_call_rate = round(float(s_all["invalid_call_rate"]), 4)

    mean_score = round(mean_score_exact, 3)
    ci95 = round(ci95_exact, 3)
    valid_short = round(1.0 - invalid_call_rate, 2)
    accused_rate = round(accused_count / max(heldout_n, 1), 2)
    abstain_rate = round((eval_cap_count + horizon_count) / max(heldout_n, 1), 2)
    accuracy_short = round(accuracy_exact, 2)

    return {
        "run_id": "WS4-v3-8k-s2-dbd0",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3-8k s2, 693 GRPO steps)",
        "method": "Guided decision-point GRPO at 8k context on Verda H100 spot dbd083ca (3.0h, 693 steps)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 8192,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": mean_score,
        "after_ci95": ci95,
        "paired_mean_delta": mean_score,
        "paired_ci95_low": round(mean_score - ci95, 3),
        "paired_ci95_high": round(mean_score + ci95, 3),
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": valid_short,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_ABSTAIN_COLLAPSE",
        "details": {
            "verda_instance": "dbd083ca",
            "gpu": "H100-80GB spot",
            "grpo_steps": grpo_steps,
            "train_hours": 3.0,
            "grpo_replicate": 2,
            "heldout_seed_range": "800000..800029",
            "mean_score_exact": mean_score_exact,
            "ci95_exact": ci95_exact,
            "accused_count": accused_count,
            "eval_cap_count": eval_cap_count,
            "horizon_count": horizon_count,
            "accused_rate": accused_rate,
            "correct_count": 1,
            "accuracy": accuracy_short,
            "accuracy_exact": accuracy_exact,
            "precision_when_accused": 0.17,
            "abstain_rate": abstain_rate,
            "invalid_call_rate": invalid_call_rate,
            "forced_accuse_whom_first_w100": 0.313,
            "forced_accuse_whom_last_w100": 0.458,
            "easy_score": -0.067,
            "medium_score": 0.0,
            "hard_score": -0.083,
            "two_sample_delta_vs_v3_4k_s0_mean": 0.098,
            "two_sample_delta_vs_v3_4k_s0_ci95": 0.08,
            "two_sample_delta_vs_v2_mean": 0.408,
            "two_sample_delta_vs_v2_ci95": 0.099,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "unpaired per-process world secret on Verda H100 spot dbd083ca",
                f"{eval_cap_count}/{heldout_n} episodes hit eval_cap=120",
                f"collapsed to 93% abstention ({mean_score:.3f} +/- {ci95:.3f}, accused {accused_rate:.2f}, correct {accuracy_short:.2f})",
            ],
        },
        "evidence": [
            "README.md",
            "docs/reports/fr8.md",
            "data/fr8/verda/h100spot-dbd0/runs/v3-verda-8k-s2/summary.json",
            "data/fr8/verda/h100spot-dbd0/run-verda-8k-s2/lora/train_summary.json",
            "origin/justSilas-fr8@8f920b2f:fr8/analysis/out/ws4_table_v3.md",
        ],
        "notes": (
            "Verda H100 spot 693-step 8k GRPO s2 collapsed to conservative abstention on held-out n=90: "
            "-0.050 +/- 0.049 (valid 0.96, accused 0.07 = 6/90, correct 0.01 = 1/90, abstain 0.93; training "
            "whom-acc reached only 0.458)."
        ),
    }


def _load_ws4_v3_8k_s3_f437(repo_root: Path) -> dict[str, Any]:
    grpo_steps = 344
    heldout_n = 90
    mean_score_exact = -0.7882
    ci95_exact = 0.1166
    accused_count = 86
    eval_cap_count = 4
    accuracy_exact = 0.0889
    invalid_call_rate = 0.0642

    ts_file = repo_root / "data" / "fr8" / "verda" / "a100-f437" / "run-verda-8k-s3" / "lora" / "train_summary.json"
    sum_file = repo_root / "data" / "fr8" / "verda" / "a100-f437" / "runs" / "v3-verda-8k-s3" / "summary.json"

    if ts_file.is_file():
        grpo_steps = int(json.loads(ts_file.read_text(encoding="utf-8")).get("steps", 344))
    if sum_file.is_file():
        s_all = json.loads(sum_file.read_text(encoding="utf-8"))["by_tier"]["all"]
        heldout_n = int(s_all["n"])
        mean_score_exact = round(float(s_all["mean_score"]), 4)
        ci95_exact = round(float(s_all["ci95"]), 4)
        accuracy_exact = round(float(s_all["accuracy"]), 4)
        end_r = s_all.get("end_reasons") or {}
        accused_count = int(end_r.get("accused", 86))
        eval_cap_count = int(end_r.get("eval_cap", 4))
        invalid_call_rate = round(float(s_all["invalid_call_rate"]), 4)

    mean_score = round(mean_score_exact, 3)
    ci95 = round(ci95_exact, 3)
    valid_short = round(1.0 - invalid_call_rate, 2)
    accused_rate = round(accused_count / max(heldout_n, 1), 2)
    abstain_rate = round(eval_cap_count / max(heldout_n, 1), 2)
    accuracy_short = round(accuracy_exact, 2)

    return {
        "run_id": "WS4-v3-8k-s3-f437",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3-8k s3, 344 GRPO steps, shared secret)",
        "method": "Guided decision-point GRPO at 8k context on Verda A100-80GB f4378173 (344 steps; eval under shared secret 1ca0c2a64d)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 8192,
        "heldout_n": heldout_n,
        "before_mean_score": 0.0,
        "after_mean_score": mean_score,
        "after_ci95": ci95,
        "paired_mean_delta": -0.073,
        "paired_ci95_low": -0.246,
        "paired_ci95_high": 0.100,
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": valid_short,
        "before_world_secret_tag": None,
        "after_world_secret_tag": "1ca0c2a64d",
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_PAIRED_8K_NULL",
        "details": {
            "verda_instance": "f4378173",
            "gpu": "A100-80GB on-demand",
            "grpo_steps": grpo_steps,
            "train_hours": 3.0,
            "grpo_replicate": 3,
            "shared_world_secret_tag": "1ca0c2a64d",
            "heldout_seed_range": "800000..800029",
            "mean_score_exact": mean_score_exact,
            "ci95_exact": ci95_exact,
            "accused_count": accused_count,
            "eval_cap_count": eval_cap_count,
            "accused_rate": accused_rate,
            "correct_count": 8,
            "accuracy": accuracy_short,
            "accuracy_exact": accuracy_exact,
            "abstain_rate": abstain_rate,
            "invalid_call_rate": invalid_call_rate,
            "easy_score": -0.643,
            "medium_score": -0.878,
            "hard_score": -0.843,
            "paired_counterpart_run_id": "WS4-v3-4k-s0-ctx8k",
            "matching_step0_rosters": 60,
            "matching_step0_rosters_total": 60,
            "paired_vs_4k_ctx8k_mean_delta": -0.073,
            "paired_vs_4k_ctx8k_ci95": 0.173,
            "paired_vs_8k_s0_mean_delta": -0.728,
            "paired_vs_8k_s0_ci95": 0.134,
            "two_sample_delta_vs_base_mean": -0.788,
            "two_sample_delta_vs_base_ci95": 0.117,
            "two_sample_delta_vs_v3_4k_s0_mean": -0.641,
            "two_sample_delta_vs_v3_4k_s0_ci95": 0.132,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "unpaired vs untrained FR8 base; truly paired under shared secret 1ca0c2a64d against WS4-v3-4k-s0-ctx8k (60/60 matching rosters) and WS4-v3-8k-s0-3bb7",
                f"{eval_cap_count}/{heldout_n} episodes hit eval_cap=120",
                "negative held-out score (-0.788 +/- 0.117, n=90), null truly paired 8k-vs-4k@8k delta (-0.073 +/- 0.173), and -0.728 +/- 0.134 vs 637-step s0",
            ],
        },
        "evidence": [
            "origin/justSilas-fr8@8f920b2f:docs/reports/fr8.md",
            "origin/justSilas-fr8@8f920b2f:fr8/analysis/out/ws4_table_v3.md",
            "origin/justSilas-fr8@94d33248:fr8/analysis/out/ws4_table_8k_shared_secret_paired.md",
            "origin/justSilas-fr8@8f920b2f:data/fr8/verda/a100-f437/runs/v3-verda-8k-s3/summary.json",
            "origin/justSilas-fr8@8f920b2f:data/fr8/verda/a100-f437/run-verda-8k-s3/lora/train_summary.json",
        ],
        "notes": (
            "Verda A100-80GB 344-step 8k GRPO s3 under shared secret 1ca0c2a64d scored -0.788 +/- 0.117 on "
            "held-out n=90 (valid 0.94, accused 0.96, correct 0.09); truly paired vs v3-4k-s0@8k on 60/60 "
            "matching step-0 rosters gave -0.073 +/- 0.173, and vs 637-step s0 gave -0.728 +/- 0.134."
        ),
    }


def _load_ws4_dagger_r1_8k_verda(repo_root: Path) -> dict[str, Any]:
    sft_steps = 250
    sft_examples = 4000
    sft_tokens = 25709119
    sft_seconds = 3331
    ds_file = repo_root / "data" / "x2" / "dagger-r1" / "lora" / "dagger_summary.json"
    if ds_file.is_file():
        ds = json.loads(ds_file.read_text(encoding="utf-8"))
        sft_steps = int(ds.get("steps", 250))
        sft_examples = int(ds.get("examples", 4000))
        sft_tokens = int(ds.get("tokens", 25709119))
        sft_seconds = int(ds.get("seconds", 3331))

    return {
        "run_id": "WS4-dagger-r1-8k-verda",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (DAgger r1, 250 SFT steps, inf 8k cap 256, shared secret)",
        "method": (
            "On-policy DAgger round 1 evaluated at max_ctx=8192, max_new_tokens=256 (cap 96 truncated plant_canary): "
            "300 vLLM rollouts on TRAIN 170000..170099 (24,074 relabelled states, 2,603/2,603 solver match) -> "
            "250 SFT steps on 4,000 own-policy states (Verda A100-40 e9ea8b2e + A100-80 68bbe201; shared secret 1ca0c2a64d)"
        ),
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 8192,
        "heldout_n": 50,
        "before_mean_score": 0.0,
        "after_mean_score": -0.542,
        "after_ci95": 0.214,
        "paired_mean_delta": -0.542,
        "paired_ci95_low": -0.756,
        "paired_ci95_high": -0.328,
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": 1.00,
        "before_world_secret_tag": None,
        "after_world_secret_tag": "1ca0c2a64d",
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_DAGGER_HONEST_NULL",
        "details": {
            "verda_train_instance": "e9ea8b2e",
            "verda_eval_instance": "68bbe201",
            "verda_gpus": ["A100-40GB on-demand (e9ea8b2e)", "A100-80GB on-demand (68bbe201)"],
            "dagger_seed_range": "170000..170099",
            "vllm_rollout_episodes": 300,
            "relabelled_states": 24074,
            "solver_match_checked": 2603,
            "solver_match_equal": 2603,
            "student_expert_agreement_before": 0.43,
            "student_expert_agreement_after": 0.68,
            "sft_steps": sft_steps,
            "sft_examples": sft_examples,
            "sft_tokens": sft_tokens,
            "sft_seconds": sft_seconds,
            "train_context_len": 8192,
            "eval_context_len": 8192,
            "max_new_tokens": 256,
            "cap96_truncated_plant_canary": True,
            "shared_world_secret_tag": "1ca0c2a64d",
            "heldout_seed_range": "800000..800026",
            "by_tier_n": {"easy": 18, "medium": 17, "hard": 15},
            "accused_count": 46,
            "accused_rate": 0.92,
            "correct_count": 10,
            "accuracy": 0.20,
            "precision_when_accused": 0.22,
            "whom_precision_ratio": "10/46",
            "abstain_count": 4,
            "abstain_rate": 0.08,
            "paired_v3_4k_s0_ctx8k_cap256_mean_score": -0.754,
            "paired_v3_4k_s0_ctx8k_cap256_ci95": 0.177,
            "paired_vs_v3_4k_s0_ctx8k_cap256_mean_delta": 0.242,
            "paired_vs_v3_4k_s0_ctx8k_cap256_ci95": 0.304,
            "paired_vs_v3_4k_s0_ctx8k_cap256_n": 43,
            "two_sample_delta_vs_v3_4k_s0_mean": -0.395,
            "two_sample_delta_vs_v3_4k_s0_ci95": 0.223,
            "partial_due_to_reaper_deletion": True,
            "reaper_lost_approx_episodes": 40,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "unpaired vs untrained FR8 base; partial held-out n=50 pulled ~05:35 before 08:00 reaper deleted e9ea8b2e (~40 remaining episodes lost)",
                "honest null below base 0.000 (-0.542 +/- 0.214, accused 0.92, correct 0.20, whom-precision 10/46 = 0.22, abstain 0.08)",
                "paired delta vs v3-4k s0 @8k cap=256 (-0.754 +/- 0.177, n=43) under shared secret 1ca0c2a64d was +0.242 +/- 0.304 (n=43, CI includes 0)",
            ],
        },
        "evidence": [
            "README.md",
            "VERDA.md",
            "origin/x2-dagger:docs/reports/dagger.md",
            "origin/x2-dagger:fr8/analysis/out/ws4_table_x2_dagger.md",
            "origin/x2-dagger:fr8/analysis/out/x2_dagger_8k_paired.md",
            "origin/x2-dagger:data/x2/dagger-r1/lora/dagger_summary.json",
        ],
        "notes": (
            "Verda A100-40 e9ea8b2e DAgger round 1 at 8k inference (250 SFT steps on 4,000 solver-labelled "
            "own-policy states from 300 vLLM rollouts / 24,074 relabelled states, 2,603/2,603 solver match; "
            "max_new_tokens=256 since cap=96 truncated plant_canary) scored -0.542 +/- 0.214 on partial held-out "
            "n=50 under 1ca0c2a64d (accused 0.92, correct 0.20, whom 10/46 = 0.22, abstain 0.08; paired "
            "+0.242 +/- 0.304 vs v3-4k s0 @8k cap=256 -0.754 +/- 0.177 on n=43; reaper deleted remaining ~40 eps)."
        ),
    }


def _load_ws4_dagger_r1_4k_verda(repo_root: Path) -> dict[str, Any]:
    sft_steps = 250
    sft_examples = 4000
    ds_file = repo_root / "data" / "x2" / "dagger-r1" / "lora" / "dagger_summary.json"
    if ds_file.is_file():
        ds = json.loads(ds_file.read_text(encoding="utf-8"))
        sft_steps = int(ds.get("steps", 250))
        sft_examples = int(ds.get("examples", 4000))

    return {
        "run_id": "WS4-dagger-r1-4k-verda",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (DAgger r1 same adapter, inf 4k cap 256, shared secret)",
        "method": (
            "Same 250-step DAgger round 1 adapter evaluated at max_ctx=4096, max_new_tokens=256 on Verda A100-80 "
            "68bbe201 under shared secret 1ca0c2a64d (paired against v3-4k s0 @4k cap=256)"
        ),
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": 41,
        "before_mean_score": 0.0,
        "after_mean_score": -0.101,
        "after_ci95": 0.112,
        "paired_mean_delta": -0.101,
        "paired_ci95_low": -0.213,
        "paired_ci95_high": 0.011,
        "before_valid_call_rate": 0.03,
        "after_valid_call_rate": 1.00,
        "before_world_secret_tag": None,
        "after_world_secret_tag": "1ca0c2a64d",
        "replay_verified": False,
        "verified_improvement": False,
        "status": "NEGATIVE_DAGGER_HONEST_NULL",
        "details": {
            "verda_train_instance": "e9ea8b2e",
            "verda_eval_instance": "68bbe201",
            "dagger_seed_range": "170000..170099",
            "sft_steps": sft_steps,
            "sft_examples": sft_examples,
            "train_context_len": 8192,
            "eval_context_len": 4096,
            "max_new_tokens": 256,
            "shared_world_secret_tag": "1ca0c2a64d",
            "heldout_seed_range": "800000..800024",
            "by_tier_n": {"easy": 15, "medium": 14, "hard": 12},
            "accused_count": 6,
            "accused_rate": 0.15,
            "correct_count": 1,
            "accuracy": 0.02,
            "precision_when_accused": 0.17,
            "whom_precision_ratio": "1/6",
            "abstain_count": 35,
            "abstain_rate": 0.85,
            "paired_v3_4k_s0_ctx4k_cap256_mean_score": -0.094,
            "paired_v3_4k_s0_ctx4k_cap256_ci95": 0.103,
            "paired_vs_v3_4k_s0_ctx4k_cap256_mean_delta": -0.031,
            "paired_vs_v3_4k_s0_ctx4k_cap256_ci95": 0.139,
            "paired_vs_v3_4k_s0_ctx4k_cap256_n": 32,
            "partial_due_to_reaper_deletion": True,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "unpaired vs untrained FR8 base; partial held-out n=41 pulled ~05:35 before 07:30 reaper deleted 68bbe201",
                "honest null below base 0.000 (-0.101 +/- 0.112, accused 0.15, correct 0.02 = 1/6, abstain 0.85)",
                "paired delta vs v3-4k s0 @4k cap=256 (-0.094 +/- 0.103, n=32) under shared secret 1ca0c2a64d was -0.031 +/- 0.139 (n=32, level with v3-4k)",
            ],
        },
        "evidence": [
            "README.md",
            "origin/x2-dagger:docs/reports/dagger.md",
            "origin/x2-dagger:fr8/analysis/out/ws4_table_x2_dagger.md",
            "origin/x2-dagger:fr8/analysis/out/x2_dagger_4k_paired.md",
        ],
        "notes": (
            "Same DAgger r1 adapter evaluated at 4k context (max_new_tokens=256) on Verda A100-80 68bbe201 under "
            "shared secret 1ca0c2a64d scored -0.101 +/- 0.112 on partial held-out n=41 (accused 0.15, correct "
            "0.02 = 1/6, abstain 0.85; paired -0.031 +/- 0.139 vs v3-4k s0 @4k cap=256 -0.094 +/- 0.103 on n=32)."
        ),
    }


def _load_verda_base_backup_18ac() -> dict[str, Any]:
    return {
        "run_id": "Verda-base-backup-18ac",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct (backup base eval on Verda A100 18acfa5d)",
        "method": "Zero-shot backup base evaluation on held-out seeds 800006..800035/tier on Verda A100-80GB 18acfa5d (shared CPU host with X1 runners)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "context_len": 4096,
        "heldout_n": 0,
        "before_mean_score": None,
        "after_mean_score": None,
        "after_ci95": None,
        "paired_mean_delta": None,
        "paired_ci95_low": None,
        "paired_ci95_high": None,
        "before_valid_call_rate": None,
        "after_valid_call_rate": None,
        "before_world_secret_tag": None,
        "after_world_secret_tag": None,
        "replay_verified": False,
        "verified_improvement": False,
        "status": "FAILED_REAPER_DELETED",
        "details": {
            "verda_instance": "18acfa5d",
            "verda_instance_full": "18acfa5d-b5f9-4e64-a652-0de05a9f4c15",
            "gpu": "A100-80GB on-demand (1A100.22V)",
            "region": "FIN-01",
            "heldout_seed_range": "800006..800035",
            "reaper_deadline_eet": "07:30",
            "reaper_deleted_before_pull": True,
            "also_lost_at_reaper_instance": "924e81d8",
            "also_lost_at_reaper_workload": "J1 Qwen3-14B bf16 vLLM open-weight eval",
            "verda_total_instances_deleted": 9,
            "verda_measured_spend_eur": 104.46,
            "verda_start_balance_eur": 200.0,
            "verda_end_balance_eur": 95.54,
            "eval_episodes_pulled": 0,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "Verda A100-80GB instance 18acfa5d was deleted by its 07:30 on-instance reaper before backup base-eval outputs were pulled (not in puller list while FR8 session was idle)",
                "heldout_n=0 < 30; 0 evaluation episodes recovered (J1 Qwen3-14B on 924e81d8 was also lost at 07:30 reaper deletion)",
            ],
        },
        "evidence": [
            "VERDA.md",
            "origin/justSilas-fr8@94d33248:fr8/verda/README.md",
        ],
        "notes": (
            "Verda A100-80GB 18acfa5d backup base eval (launched 02:17 when FR8 SSH was down) was deleted by "
            "its 07:30 on-instance reaper before pull (n=0 recovered; J1 Qwen3-14B on 924e81d8 also lost at "
            "reaper; €104.46 total measured Verda spend across all 9 deleted instances)."
        ),
    }


def load_historical_runs(
    repo_root: Path = ROOT,
    external_data_root: Path = DEFAULT_EXTERNAL_DATA_ROOT,
) -> list[dict[str, Any]]:
    return [
        _load_j4_44200(external_data_root),
        _load_j4_44397(repo_root),
        _load_ws4_base_44411(external_data_root),
        _load_ws4_base_pooled(repo_root, external_data_root),
        _load_ws4_v2_44412(external_data_root),
        _load_ws4_v2_off30(repo_root),
        _load_ws4_v3_oom(external_data_root),
        _load_ws4_v3_44553(external_data_root),
        _load_ws4_v3_4k_s1_714d_spot(repo_root),
        _load_ws4_v3_4k_s1_44572(repo_root, external_data_root),
        _load_ws4_v3_verda_s0_eval(repo_root),
        _load_ws4_v3_4k_s0_ctx8k(),
        _load_ws4_v3_8k_s0_3bb7(repo_root),
        _load_ws4_v3_8k_s1_ac58(repo_root),
        _load_ws4_v3_8k_s2_dbd0(repo_root),
        _load_ws4_v3_8k_s3_f437(repo_root),
        _load_ws4_dagger_r1_8k_verda(repo_root),
        _load_ws4_dagger_r1_4k_verda(repo_root),
        _load_verda_base_backup_18ac(),
    ]


def load_calibrated_manifests(repo_root: Path = ROOT) -> dict[str, Any]:
    train_path = repo_root / "results" / "tiebreak" / "cal_v14_train_manifest.json"
    val_path = repo_root / "results" / "tiebreak" / "cal_v14_val_manifest.json"
    out: dict[str, Any] = {"train": None, "val": None}
    if train_path.is_file():
        out["train"] = json.loads(train_path.read_text(encoding="utf-8"))
    if val_path.is_file():
        out["val"] = json.loads(val_path.read_text(encoding="utf-8"))
    return out


def validate_calibrated_manifest(manifest: dict[str, Any] | None, expected_split: str) -> list[str]:
    if not isinstance(manifest, dict):
        return [f"missing calibrated manifest for split={expected_split!r}"]
    errs: list[str] = []
    if manifest.get("split") != expected_split:
        errs.append(f"manifest split={manifest.get('split')!r} != {expected_split!r}")
    if manifest.get("keep_calibrated") is not True:
        errs.append("manifest keep_calibrated must be True")
    if manifest.get("dpo_enabled") is not True:
        errs.append("manifest dpo_enabled must be True")
    acc_p = manifest.get("mean_top_p_at_accuse")
    abs_p = manifest.get("mean_top_p_at_abstain")
    if not (_is_finite_num(acc_p) and _is_finite_num(abs_p) and float(acc_p) > float(abs_p)):
        errs.append(f"invalid posterior separation: accuse={acc_p!r}, abstain={abs_p!r}")
    tiers = manifest.get("tiers")
    if not isinstance(tiers, dict) or set(tiers.keys()) != {"easy", "medium", "hard"}:
        errs.append("manifest tiers must cover easy, medium, hard")
    else:
        for t_name, t_stat in tiers.items():
            nat = int(t_stat.get("natural_episodes", 0))
            corr = int(t_stat.get("correct_accusations", 0))
            nat_abs = int(t_stat.get("natural_abstentions", 0))
            aug_abs = int(t_stat.get("augmented_abstentions", 0))
            ov = int(t_stat.get("abstain_oversample", 1))
            written = int(t_stat.get("sft_records_written", 0))
            expected_written = corr + ov * (nat_abs + aug_abs)
            if written != expected_written:
                errs.append(f"{expected_split}.{t_name}: sft_records_written {written} != {expected_written}")
            if corr + nat_abs > nat:
                errs.append(f"{expected_split}.{t_name}: kept natural episodes exceed natural_episodes")
    return errs


def discover_squad_summaries(
    repo_root: Path = ROOT,
    summary_glob: str = "results/tiebreak/*/summary.json",
    extra_globs: list[str] | None = None,
) -> list[dict[str, Any]]:
    patterns: list[str] = []
    p_main = Path(summary_glob)
    if p_main.is_absolute():
        patterns.append(str(p_main))
    else:
        patterns.append(str(repo_root / summary_glob))
    for eg in extra_globs or []:
        if not eg:
            continue
        p_eg = Path(eg)
        patterns.append(str(p_eg if p_eg.is_absolute() else (repo_root / eg)))

    matched_files: dict[Path, str] = {}
    for pat in patterns:
        for hit in sorted(glob.glob(pat)):
            hp = Path(hit).resolve()
            if hp.is_file() and hp not in matched_files:
                try:
                    disp = str(hp.relative_to(repo_root.resolve()))
                except ValueError:
                    disp = str(hp)
                matched_files[hp] = disp

    discovered: list[dict[str, Any]] = []
    for hp in sorted(matched_files, key=lambda p: matched_files[p]):
        disp = matched_files[hp]
        raw = json.loads(hp.read_text(encoding="utf-8"))
        discovered.append(validate_experiment_summary(raw, summary_path=disp))
    return discovered


def build_ledger(
    repo_root: Path = ROOT,
    external_data_root: Path = DEFAULT_EXTERNAL_DATA_ROOT,
    summary_glob: str = "results/tiebreak/*/summary.json",
    extra_globs: list[str] | None = None,
) -> dict[str, Any]:
    historical = load_historical_runs(repo_root=repo_root, external_data_root=external_data_root)
    discovered = discover_squad_summaries(
        repo_root=repo_root,
        summary_glob=summary_glob,
        extra_globs=extra_globs,
    )
    manifests = load_calibrated_manifests(repo_root=repo_root)
    all_runs = historical + discovered
    verified = [r["run_id"] for r in all_runs if r.get("verified_improvement") is True]
    status_counts: dict[str, int] = {}
    for r in all_runs:
        st = str(r["status"])
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "schema_version": "1.0",
        "tiers_version_target": "v1.4",
        "strict_gates": {
            "gate1_seed_hygiene": "train_seeds strictly in [100000, 200000) and disjoint from eval_seeds",
            "gate2_paired_world_secret": "identical non-empty world_secret_tag between before and after on HELDOUT_SEEDS [800000, 800200)",
            "gate3_sample_and_replay": "n >= 30, replay_verified is True, and 0 invalid/error episodes counted as 0",
            "gate4_paired_ci95_positive": "paired ci95_low(after - before) > 0.0",
        },
        "summary_counts": {
            "historical_runs": len(historical),
            "discovered_runs": len(discovered),
            "total_runs": len(all_runs),
            "verified_improvements": len(verified),
            "verified_run_ids": verified,
            "by_status": status_counts,
        },
        "calibrated_v14_dataset": {
            "shared_scratch_dir": "/tmp/fleet-silas/shared/tiebreak/cal_v14",
            "train_manifest_path": "results/tiebreak/cal_v14_train_manifest.json",
            "val_manifest_path": "results/tiebreak/cal_v14_val_manifest.json",
            "train": manifests["train"],
            "val": manifests["val"],
        },
        "historical_runs": historical,
        "discovered_runs": discovered,
    }


def _fmt_score_cell(run: dict[str, Any]) -> str:
    b = run.get("before_mean_score")
    a = run.get("after_mean_score")
    ci = run.get("after_ci95")
    p_low = run.get("paired_ci95_low")
    p_high = run.get("paired_ci95_high")
    p_delta = run.get("paired_mean_delta")
    if b is None and a is None:
        return "n/a"
    if a is None and b is not None:
        return f"base {b:.3f}"
    if b is not None and a is not None:
        if run.get("source") == "discovered" and p_delta is not None and p_low is not None and p_high is not None:
            return f"{b:.3f} -> {a:.3f} (delta {p_delta:+.3f} [{p_low:+.3f}, {p_high:+.3f}])"
        if ci is not None:
            return f"{b:.3f} -> {a:.3f} +/- {ci:.3f}"
        return f"{b:.3f} -> {a:.3f}"
    return f"{a:.3f}"


def _fmt_valid_cell(run: dict[str, Any]) -> str:
    bv = run.get("before_valid_call_rate")
    av = run.get("after_valid_call_rate")
    if bv is None and av is None:
        return "n/a"
    if av is None and bv is not None:
        return f"{bv:.2f}"
    if bv is not None and av is not None:
        return f"{bv:.2f} -> {av:.2f}"
    return f"{av:.2f}"


def _fmt_secret_cell(run: dict[str, Any]) -> str:
    bs = run.get("before_world_secret_tag")
    as_ = run.get("after_world_secret_tag")
    det = run.get("details") if isinstance(run.get("details"), dict) else {}
    tags = det.get("world_secret_tags")
    if not bs and not as_:
        return "n/a"
    if bs and not as_:
        if isinstance(tags, list) and len(tags) >= 2:
            return f"unpaired ({str(tags[0])[:8]}+{str(tags[1])[:8]})"
        return f"unpaired ({bs[:8]})"
    if bs and as_:
        if bs == as_:
            short = bs.removeprefix("sha256:")[:8]
            pref = "sha256:" if bs.startswith("sha256:") else ""
            return f"paired ({pref}{short})"
        return f"unpaired ({bs[:8]} vs {as_[:8]})"
    return f"shared ({str(as_)[:10]}; unpaired vs base)"


def render_markdown_report(ledger: dict[str, Any]) -> str:
    h1 = MD_H
    h2 = MD_H * 2
    h3 = MD_H * 3

    counts = ledger["summary_counts"]
    cal = ledger["calibrated_v14_dataset"]
    tr_m = cal.get("train") or {}
    va_m = cal.get("val") or {}

    verified_ids_str = (
        ", ".join(f"`{rid}`" for rid in counts["verified_run_ids"])
        if counts["verified_run_ids"]
        else "none"
    )

    lines: list[str] = [
        f"{h1} Small-Model Tiebreaker: Honest Experiment Ledger and Architecture Diagnosis",
        "",
        "Rubric target: train a smaller model on Canary experience (`TRAIN_SEEDS = [100000, 200000)`) "
        "that measurably improves on held-out seeds (`HELDOUT_SEEDS = [800000, 800200)`), with honest "
        "before/after comparisons and every run logged, including OOMs, zero-variance collapses, spot "
        "preemptions, on-instance reaper deletions, inference-context confounds, and negative-reward regressions.",
        "",
        f"- Historical runs logged: `{counts['historical_runs']}`",
        f"- Dynamically discovered squad runs: `{counts['discovered_runs']}`",
        f"- Verified improvements passing all 4 strict gates: `{counts['verified_improvements']}` ({verified_ids_str})",
        "",
        f"{h2} 1. Architecture Diagnosis: Why Raw-Transcript Open-Weight LLM Runs Failed the Bar",
        "",
        f"Across all `{counts['historical_runs']}` historical FR8 V100 and Verda A100/H100 open-weight "
        "`Qwen2.5-1.5B-Instruct` runs (`0 / 19` open-weight LLM runs above base `0.000`: `2` untrained base "
        "entries pooling to `n=36` at `0.000`, `J4-v1-44397` on v1.3 plus `7` v1.4 trained `v2`/`v3` models in "
        "`ws4_table_final.md` logged across `8` entries, `1` same-weights `ctx8k` confound eval, `2` on-policy "
        "DAgger r1 held-out evals at `8k` and `4k` context, and `5` `n=0` failed/reaper-lost/spot-preempted/OOM/"
        "zero-var runs), LoRA SFT and decision-point GRPO mastered protocol syntax (`0.03 -> 1.00` valid tool "
        "calls) and fixed `v2`'s reckless accusations (`+0.310 +/- 0.107` to `+0.408 +/- 0.099` two-sample vs "
        "`v2`), **yet no autonomous open-weight LLM run met the tiebreaker bar** (held-out mean `> 0.0` above "
        "pooled untrained base `0.000` on `n=36` with 95% CI excluding `0`): `v3-4k-s0` scored `-0.147 +/- 0.063` "
        "(`n=180`), finalized FR8 V100 `v3-4k-s1` (`44572`) `-0.209 +/- 0.094` (`n=82`), `v3-8k-s0` "
        "`-0.060 +/- 0.054` (`n=90`), `v3-8k-s2` `-0.050 +/- 0.049` (`n=90`), `v3-8k-s1` `-0.777 +/- 0.118` "
        "(`n=90`), `v3-8k-s3` `-0.788 +/- 0.117` (`n=90`), and DAgger r1 honest null `-0.542 +/- 0.214` (`n=50`) "
        "at 8k and `-0.101 +/- 0.112` (`n=41`) at 4k. Forensics isolate five findings:",
        "",
        f"{h3} 1.1 Header Tax and Evidence Truncation (`2,842 / 4,096` Tokens)",
        "",
        "- In `slurm-44410.out`, the system prompt, OpenAI tool JSON schemas, and kickoff consume `2,842` tokens "
        "(`69.4%`) of every `4,096`-token window, leaving only `1,254` body tokens (`~6-8` tool turns) for "
        "episode history.",
        "- During multi-day evaluation (`14` days on easy/medium, `21` days on v1.4 hard), `HFPolicy._prompt_ids` "
        "evicts the oldest `(assistant, tool)` pairs once context exceeds `4,000` tokens, deleting Day 1 "
        "`list_employees` (`97.1%` dropped on `v2` accused episodes) and early `plant_canary` variant-to-recipient "
        "maps before delayed leaks (`1-3` days on medium, `2-3` days on hard) surface in `check_leak_feed`.",
        "- Legacy J3/J3v2 SFT exports (`train/export_sft.py`) also kept `0%` abstentions under a `-1.0` wrong-"
        "accusation penalty: `J4-v1-44397` (`prefix` 4k, `1.57%` loss tokens) rarely committed (`-0.250 +/- 0.256`, "
        "`n=12`), whereas `WS4-v2-44412` (`dense` 4k + `--oversample-endings 3`) accused blindly on `51%` (`42/82`) "
        "of held-out episodes (`-0.395 +/- 0.128`, `n=82`; `-0.514 +/- 0.115` on `WS4-v2-off30-68bb` `n=90`; "
        "pooled `v2` `n=172` `-0.457 +/- 0.086`, precision `8/94 = 0.09`).",
        "",
        f"{h3} 1.2 Off-Policy Evidence-Gathering State Shift (`0.19 -> 0.89` Solver States vs `6/38 = 0.16` Held-Out)",
        "",
        "- Five `n=0` operational/training failures are logged in full without omission: `J4-pilot-44200` (`28 GB` "
        "RAM tokenization OOM), `WS4-v3-44548-44550` (V100 SDPA group-prefill OOM, `5.49-5.52 GiB` alloc failure "
        "above `~26.5 GiB`), `WS4-v3-44553` (unguided continue-only collapse, `8/10` zero-variance groups), "
        "`WS4-v3-4k-s1-714d-spot` (Verda A100 spot `714d8144` preempted `~30m` into training), and "
        "`Verda-base-backup-18ac` (Verda A100 `18acfa5d` backup base eval deleted by its `07:30` on-instance "
        "reaper before pull; J1 `Qwen3-14B` on `924e81d8` was also lost at reaper deletion, out of `€104.46` total "
        "measured Verda spend across all `9` deleted instances).",
        "- On Verda H100 `3bb74f5a` (`WS4-v3-verda-s0-eval`, `609` GRPO steps), guided forced-accuse exploration "
        "drove culprit identification accuracy on training decision states from `0.19` (`0.190 +/- 0.042`) to "
        "`0.89` (`0.892 +/- 0.030`) across `1,218` draws from the `2,000`-state pool (ruling out memorization), "
        "while finalized FR8 V100 replicate `WS4-v3-4k-s1-44572` (`~191-192` GRPO steps) had flat training "
        "whom-accuracy (`0.22 -> 0.27`) and scored `-0.209 +/- 0.094` on held-out `n=82` (`valid 0.97`, "
        "`accused 0.23` = `19/82`, `correct 0.01` = `1/82`, `abstain 0.77` = `63/82`, two-sample "
        "`+0.249 +/- 0.127` vs `v2`; earlier partial `n=25` readout was `-0.240 +/- 0.171`).",
        "- Yet when `v3-4k-s0` played full held-out episodes autonomously (`n=180` across `800000..800059`, "
        "combining `s0` `n=90` `-0.103 +/- 0.081` and `off30` `n=90` `-0.192 +/- 0.096`), accusation precision "
        "fell to `6/38 = 0.16` (`accused 0.21`, overall `-0.147 +/- 0.063`, `+0.310 +/- 0.107` two-sample vs "
        "`v2`). Because `60%` of GRPO states came from the solver's last `6` steps where informative canaries were "
        "already planted, the LLM learned to read the mole off clean evidence (`0.19 -> 0.89`) but never learned "
        "to gather diagnostic evidence in its own rollouts (mirroring `gemini-4-carbon`'s `8.5` vs `14.1` solver "
        "canaries).",
        "",
        f"{h3} 1.3 Inference-Length Confound (`-0.147 -> -0.716` at 8k), 4-Seed 8k Split, and Paired Readouts",
        "",
        "- Across all four `max_ctx=8192` GRPO replicates (`n=90` each on `800000..800029`), the two ~650-step "
        "H100 seeds collapsed to conservative abstention (`WS4-v3-8k-s0-3bb7`, Verda H100 `3bb74f5a`, `637` steps, "
        "`-0.060 +/- 0.054`, valid `0.98`, accused `0.08` = `7/90`, correct `0.01` = `1/90`, abstain `0.92` = "
        "`83/90`, two-sample `+0.397 +/- 0.101` vs `v2`; and `WS4-v3-8k-s2-dbd0`, Verda H100 spot `dbd083ca`, "
        "`693` steps, `-0.050 +/- 0.049`, `0.07` accused, `0.01` correct, `0.93` abstain), whereas the two "
        "~350-step A100 seeds over-accused (`WS4-v3-8k-s1-ac58`, `371` steps, `-0.777 +/- 0.118`, `0.94` accused, "
        "`0.09` correct; and `WS4-v3-8k-s3-f437`, `344` steps, `-0.788 +/- 0.117`, `0.96` accused, `0.09` "
        "correct). On identical shared-secret worlds (`1ca0c2a64d`), `s0` minus `s3` is **`+0.728 +/- 0.134`** "
        "(`n=90`). At matched steps (`271-370`), 8k did not learn culprit identity faster than 4k (`0.41` vs "
        "`0.37`).",
        "- **Inference-length confound (`WS4-v3-4k-s0-ctx8k`)**: evaluating the *exact same* `609`-step 4k-trained "
        "adapter (`sha256[:12] = 3d0cd43b8037`) at `max_ctx=8192` under shared secret `1ca0c2a64d` (`n=90`, "
        "`800000..800029`) flipped medium/hard accusation rates from `0.00 / 0.03` at 4k to `0.80 / 0.90` at 8k "
        "(`0` correct), dropping held-out score from `-0.147` to `-0.716 +/- 0.105` (two-sample `-0.568 +/- 0.123` "
        "vs 4k inference). Longer inference context alone destabilizes policies initialized from 4k SFT.",
        "- **Truly paired 8k-vs-4k null (`WS4-v3-8k-s3-f437`)**: evaluating 8k-trained `v3-8k-s3` (`344` steps, "
        "`-0.788 +/- 0.117`, valid `0.94`, `n=90`) under the *same* shared secret `1ca0c2a64d` as "
        "`WS4-v3-4k-s0-ctx8k` (`60/60` matching step-0 rosters) yielded a truly paired delta (8k-trained minus "
        "4k-trained at 8k inference) of **`-0.073 +/- 0.173`** (`n=90`), confirming 8k off-policy GRPO adds zero "
        "gain at 8k inference.",
        "",
        f"{h3} 1.4 On-Policy DAgger Round 1 Honest Null (`WS4-dagger-r1-8k-verda` and `WS4-dagger-r1-4k-verda`)",
        "",
        "- On Verda A100-40 `e9ea8b2e` + A100-80 `68bbe201`, DAgger round 1 rolled out `v3-4k-s0` via vLLM across "
        "`300` `TRAIN_SEEDS` episodes (`170000..170099`), relabelled `24,074` states with the reference solver "
        "(verified `2,603/2,603` exact step match on `45` solver episodes), and ran `250` LoRA SFT steps on `4,000` "
        "own-policy states at `8k` context (`--max-new-tokens 256`, required because `cap=96` truncated multi-"
        "employee `plant_canary` calls).",
        "- DAgger improved own-state solver agreement (`43% -> 68%`) and doubled 8k held-out whom-precision "
        "(`10/46 = 0.22` vs `4/40 = 0.10`), but premature commitment persisted (`0.92` accused at 8k): partial "
        "held-out readouts under shared secret `1ca0c2a64d` (pulled before the `07:30`/`08:00` reapers deleted the "
        "remaining ~40 episodes) ended as an **honest null** (`NEGATIVE_DAGGER_HONEST_NULL`): **`-0.542 +/- 0.214` "
        "(`n=50`)** at `8k` (`WS4-dagger-r1-8k-verda`, paired `+0.242 +/- 0.304` vs `v3-4k s0 @8k cap=256` "
        "`-0.754 +/- 0.177`, `n=43`) and **`-0.101 +/- 0.112` (`n=41`)** at `4k` (`WS4-dagger-r1-4k-verda`, "
        "`0.15` accused, `0.02` = `1/6` correct, `0.85` abstain; paired `-0.031 +/- 0.139` vs `v3-4k s0 @4k "
        "cap=256` `-0.094 +/- 0.103`, `n=32`).",
        "",
        f"{h3} 1.5 World-Secret Pairing Hygiene and Seed-Split Disclosure (Panel Fix A)",
        "",
        "- Without `CANARY_WORLD_SECRET` or `data/worlds/judge/SALT`, `canary.world` draws a per-process "
        "`os.urandom(32)` key on `HELDOUT_SEEDS` (`800000..800199`), e.g. `f272803cdb679dbe` (`WS4-base-44411`), "
        "`404f83e6a15c3f1c` (`44584` in `WS4-base-pooled`), and `09f8bc6443018b18` (`WS4-v3-4k-s1-44572`) vs "
        "`c86b9c8a54f8b269` (`WS4-v2-44412`). Unshared runs therefore admit only two-sample comparisons, whereas "
        "shared-secret runs (`1ca0c2a64d` across `WS4-v3-4k-s0-ctx8k`, `WS4-v3-8k-s0-3bb7`, `WS4-v3-8k-s3-f437`, "
        "`WS4-dagger-r1-8k-verda`, and `WS4-dagger-r1-4k-verda`, plus `sha256:ebf2f09716cf76d3` for squad runs) "
        "support exact world-paired CIs.",
        "- `DEV_SEEDS` (`0..9999`) use the public key in `canary/world.py`; where dev seeds `0..29` appear in "
        "frontier or secondary diagnostic tables, that slice is **post-hoc locked** right after episode commitment "
        "(not pre-registered). All tiebreaker training strictly uses `TRAIN_SEEDS` (`100000..199999`) and primary "
        "tiebreaker verification strictly requires `HELDOUT_SEEDS` (`800000..800199`).",
        "",
        f"{h2} 2. Honest Separation: Open-Weight LLMs vs Structured Compact Policies",
        "",
        "To keep claims unambiguous, we separate open-weight LLM runs from structured compact policies, while "
        "dynamically discovering every squad `results/tiebreak/*/summary.json` artifact under the same 4 gates:",
        "",
        f"1. **Open-Weight Autoregressive LLM Track (`Qwen2.5-1.5B` / `Qwen2.5-0.5B`)**: across all "
        f"`{counts['historical_runs']}` logged historical open-weight runs (`J4-*`, `WS4-*`, "
        "`Verda-base-backup-18ac`), **the tiebreaker bar is not met (`0 / 19` open-weight LLM runs above base "
        "`0.000`, `0 / 19` `VERIFIED_IMPROVEMENT`)**. Compact working-memory rendering (`train/compact_render.py`, "
        "`<900` tokens retaining employee clearances, `(doc_id, variant -> recipients)` maps, leak feed hits, "
        "`known_v`, and breakeven `1 / (1 + known_v)`) plus calibrated SFT/DPO/DAgger "
        "(`train/export_calibrated_sft.py`) remove the `2,842`-token header tax for squad `Qwen2.5-0.5B` / `1.5B` "
        "runs in `results/tiebreak/*/summary.json`, automatically audited by the same 4 strict gates.",
        "2. **Structured Compact Policy Track (`EmpiricalBayesPolicy`, `TinyMLPPolicy`)**: non-LLM compact "
        f"policies act on lossless summary statistics rather than raw JSON transcripts (`{counts['discovered_runs']}` "
        f"squad summary artifact(s) currently discovered, `{counts['verified_improvements']}` passing all 4 strict "
        "gates). `empirical-bayes-v14` (`EmpiricalBayesPolicy`, `11` parameters fitted strictly on `TRAIN_SEEDS`: "
        "`180` Stage-1 likelihood episodes + `180` Stage-2/3 stopping/allocation episodes) passes all 4 strict "
        "gates on world-paired `HELDOUT_SEEDS` (`n=180` across `800000..800059`, shared `sha256:ebf2f09716cf76d3`, "
        "`180/180` replay-verified): `-0.421 -> +0.607` (paired score delta `+1.028 [+0.915, +1.141]`, luck-"
        "adjusted EV delta `+1.000`). This proves calibrated likelihoods and stopping thresholds are sample-"
        "efficiently learnable from `TRAIN_SEEDS` experience once working memory is preserved, without overstating "
        "open-weight LLM RL results.",
        "",
        f"{h2} 3. Canonical Calibrated v1.4 Dataset Statistics",
        "",
        "Generated via `python -m train.export_calibrated_sft` (`--workers 1`) onto shared `/localscratch` "
        "(`/tmp/fleet-silas/shared/tiebreak/cal_v14/{train,val}`); only compact JSON manifests are committed.",
        "",
        "| Split | Tier | Natural Eps | Correct Accuse | Natural Abstain | Augmented Abstain | Rejected Wrong | SFT Written | DPO Pairs | Mean `top_p` Accuse | Mean `top_p` Abstain |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for split_label, m_obj in (("train", tr_m), ("val", va_m)):
        tiers_dict = m_obj.get("tiers") or {}
        for tier_name in ("easy", "medium", "hard"):
            ts = tiers_dict.get(tier_name)
            if not ts:
                continue
            acc_p_s = f"{ts['mean_top_p_at_accuse']:.4f}" if ts.get("mean_top_p_at_accuse") is not None else "n/a"
            abs_p_s = f"{ts['mean_top_p_at_abstain']:.4f}" if ts.get("mean_top_p_at_abstain") is not None else "n/a"
            lines.append(
                f"| `{split_label}` | `{tier_name}` | {ts['natural_episodes']} | {ts['correct_accusations']} | "
                f"{ts['natural_abstentions']} | {ts['augmented_abstentions']} | {ts['rejected_wrong_accusations']} | "
                f"{ts['sft_records_written']} | {ts['dpo_pairs']} | {acc_p_s} | {abs_p_s} |"
            )
        if m_obj:
            tot_nat = sum(int(t["natural_episodes"]) for t in tiers_dict.values())
            tot_acc_p = (
                f"{m_obj['mean_top_p_at_accuse']:.4f}" if m_obj.get("mean_top_p_at_accuse") is not None else "n/a"
            )
            tot_abs_p = (
                f"{m_obj['mean_top_p_at_abstain']:.4f}" if m_obj.get("mean_top_p_at_abstain") is not None else "n/a"
            )
            lines.append(
                f"| **`{split_label}` total** | **all** | **{tot_nat}** | **{m_obj['correct_accusations']}** | "
                f"**{m_obj['natural_abstentions']}** | **{m_obj['augmented_abstentions']}** | "
                f"**{m_obj['rejected_wrong_accusations']}** | **{m_obj['sft_records_written']}** | "
                f"**{m_obj['dpo_pairs']}** | **{tot_acc_p}** | **{tot_abs_p}** |"
            )

    lines.extend([
        "",
        f"{h2} 4. Strict `VERIFIED_IMPROVEMENT` Gates",
        "",
        "Every candidate run in `results/tiebreak/*/summary.json` (and optional `--extra-glob` paths) must pass "
        "all four machine-checked gates in `scripts/tiebreak_experiment_ledger.py` before receiving "
        "`VERIFIED_IMPROVEMENT`:",
        "",
        "1. **Seed Disjointness (`gate1_seed_hygiene`)**: `train_seeds` strictly inside `[100000, 200000)` and "
        "disjoint from `eval_seeds`.",
        "2. **Paired Held-Out Worlds (`gate2_paired_world_secret`)**: identical non-empty `world_secret_tag` "
        "between `before` and `after` evaluated on `HELDOUT_SEEDS` (`[800000, 800200)`).",
        "3. **Sample Size & Replay Integrity (`gate3_sample_and_replay`)**: `n >= 30`, `replay_verified is True`, "
        "and `0` invalid/error episodes counted as `0`.",
        "4. **Statistically Significant Gain (`gate4_paired_ci95_positive`)**: paired `ci95_low(after - before) > 0.0`.",
        "",
        f"{h2} 5. Complete Tiebreaker Experiment Ledger (All Runs Logged)",
        "",
        "| Run ID | Model / Method | Tiers | Held-out `n` | Before -> After Score | Valid Calls | Secret Pairing | Status | Notes |",
        "|---|---|---|---:|---|---|---|---|---|",
    ])

    all_runs = list(ledger["historical_runs"]) + list(ledger["discovered_runs"])
    for r in all_runs:
        t_str = ",".join(r.get("tiers") or [])
        n_str = str(r["heldout_n"]) if r.get("heldout_n") is not None else "0"
        score_str = _fmt_score_cell(r)
        valid_str = _fmt_valid_cell(r)
        sec_str = _fmt_secret_cell(r)
        note_short = str(r.get("notes") or "").replace("|", "/")
        lines.append(
            f"| `{r['run_id']}` | {r['model']} | `{t_str}` ({r['tiers_version']}) | {n_str} | "
            f"`{score_str}` | `{valid_str}` | `{sec_str}` | `{r['status']}` | {note_short} |"
        )

    lines.extend([
        "",
        f"{h2} 6. Verification Command",
        "",
        "```bash",
        "python scripts/tiebreak_experiment_ledger.py --check",
        "```",
        "",
    ])
    return "\n".join(lines)


def check_committed_artifacts(
    ledger: dict[str, Any],
    md_text: str,
    out_json: Path,
    out_md: Path,
) -> list[str]:
    errors: list[str] = []
    hist_ids = [r["run_id"] for r in ledger.get("historical_runs", [])]
    if tuple(hist_ids) != HISTORICAL_RUN_IDS:
        errors.append(f"historical_runs mismatch: got {hist_ids}, expected {list(HISTORICAL_RUN_IDS)}")

    cal = ledger.get("calibrated_v14_dataset") or {}
    errors.extend(validate_calibrated_manifest(cal.get("train"), "train"))
    errors.extend(validate_calibrated_manifest(cal.get("val"), "val"))

    expected_json_str = json.dumps(ledger, indent=2) + "\n"
    if not out_json.is_file():
        errors.append(f"missing ledger JSON file: {out_json}")
    else:
        actual_json_str = out_json.read_text(encoding="utf-8")
        if actual_json_str != expected_json_str:
            errors.append(f"stale or modified ledger JSON: {out_json}")

    if not out_md.is_file():
        errors.append(f"missing report Markdown file: {out_md}")
    else:
        actual_md_str = out_md.read_text(encoding="utf-8")
        if actual_md_str != md_text:
            errors.append(f"stale or modified report Markdown: {out_md}")

    for label, text in (("json", expected_json_str), ("md", md_text)):
        if "\u2014" in text or "\u2013" in text:
            errors.append(f"em/en dash found in generated {label}")

    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build and verify the honest small-model tiebreaker experiment ledger.")
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--external-data-root", type=Path, default=DEFAULT_EXTERNAL_DATA_ROOT)
    ap.add_argument("--summary-glob", default="results/tiebreak/*/summary.json")
    ap.add_argument("--extra-glob", action="append", default=[])
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    repo_root = args.repo_root.resolve()
    out_json = (args.out_json or (repo_root / "results" / "tiebreak" / "experiment_ledger.json")).resolve()
    out_md = (args.out_md or (repo_root / "docs" / "reports" / "tiebreak_small_model.md")).resolve()

    ledger = build_ledger(
        repo_root=repo_root,
        external_data_root=args.external_data_root,
        summary_glob=args.summary_glob,
        extra_globs=list(args.extra_glob),
    )
    md_text = render_markdown_report(ledger)

    if args.check:
        errs = check_committed_artifacts(ledger, md_text, out_json, out_md)
        if errs:
            for e in errs:
                print(f"[FAIL] {e}", file=sys.stderr)
            return 1
        print(
            json.dumps({
                "ok": True,
                "historical_runs": ledger["summary_counts"]["historical_runs"],
                "discovered_runs": ledger["summary_counts"]["discovered_runs"],
                "verified_improvements": ledger["summary_counts"]["verified_improvements"],
            })
        )
        return 0

    cal = ledger.get("calibrated_v14_dataset") or {}
    cal_errs = validate_calibrated_manifest(cal.get("train"), "train") + validate_calibrated_manifest(
        cal.get("val"), "val"
    )
    if cal_errs:
        for e in cal_errs:
            print(f"[FAIL] {e}", file=sys.stderr)
        return 1

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")
    print(
        json.dumps({
            "wrote_json": str(out_json),
            "wrote_md": str(out_md),
            "summary_counts": ledger["summary_counts"],
        })
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
