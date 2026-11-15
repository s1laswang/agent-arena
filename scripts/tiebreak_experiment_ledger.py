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
    "WS4-v2-44412",
    "WS4-v3-44548-44550",
    "WS4-v3-44553",
    "WS4-v3-verda-s0-44572",
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


def _load_ws4_v3_verda_44572(external_data_root: Path) -> dict[str, Any]:
    n_states = 2000
    s1_seed_start = 151000
    step_milestone = 140
    valid_only_gain = 0.091
    forced_accuse_whom_acc = 0.19

    slurm_file = external_data_root / "v3" / "slurm-44572.out"
    if slurm_file.is_file():
        with slurm_file.open("r", encoding="utf-8", errors="replace") as fh:
            head_lines = "".join(fh.readline() for _ in range(5))
        m = re.search(r"(\d+)\s+states from TRAIN seeds\s+(\d+)\+", head_lines)
        if m:
            n_states = int(m.group(1))
            s1_seed_start = int(m.group(2))

    return {
        "run_id": "WS4-v3-verda-s0-44572",
        "source": "historical",
        "model": "Qwen2.5-1.5B-Instruct LoRA (v3 guided GRPO 4k)",
        "method": "Guided decision-point GRPO (Verda H100 s0 + FR8 V100 job 44572 s1)",
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
        "status": "IN_PROGRESS_PARTIAL",
        "details": {
            "verda_instance": "3bb74f5a",
            "fr8_slurm_job_id": 44572,
            "n_states": n_states,
            "s1_train_seed_start": s1_seed_start,
            "step_milestone": step_milestone,
            "valid_only_gain_vs_solver": valid_only_gain,
            "forced_accuse_whom_accuracy": forced_accuse_whom_acc,
        },
        "gates": {
            "gate1_seed_hygiene": True,
            "gate2_paired_world_secret": False,
            "gate3_sample_and_replay": False,
            "gate4_paired_ci95_positive": False,
            "all_passed": False,
            "reasons": [
                "training-time decision-point metric only; no completed n>=30 paired held-out evaluation",
                "forced-accuse whom-accuracy remained flat (~0.19) at 4k raw context due to recipient truncation",
            ],
        },
        "evidence": [
            "docs/reports/CEO.md",
            "docs/reports/verda-evidence.md",
            "/home/silas/agent-arena-data/v3/slurm-44572.out",
        ],
        "notes": (
            "Guided GRPO reached +0.091 valid-only gain at step 140 without tool collapse, "
            "but forced-accuse whom-accuracy stayed flat around ~0.19 at 4k context because raw transcripts "
            "still drop early canary-to-recipient assignments."
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
        _load_ws4_v2_44412(external_data_root),
        _load_ws4_v3_oom(external_data_root),
        _load_ws4_v3_44553(external_data_root),
        _load_ws4_v3_verda_44572(external_data_root),
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
    if not bs and not as_:
        return "n/a"
    if bs and not as_:
        return f"unpaired ({bs[:8]})"
    if bs and as_:
        if bs == as_:
            return f"paired ({bs[:8]})"
        return f"unpaired ({bs[:8]} vs {as_[:8]})"
    return "unpaired"


def render_markdown_report(ledger: dict[str, Any]) -> str:
    h1 = MD_H
    h2 = MD_H * 2
    h3 = MD_H * 3

    counts = ledger["summary_counts"]
    cal = ledger["calibrated_v14_dataset"]
    tr_m = cal.get("train") or {}
    va_m = cal.get("val") or {}

    lines: list[str] = [
        f"{h1} Small-Model Tiebreaker: Honest Experiment Ledger and Architecture Diagnosis",
        "",
        "Rubric target: train a smaller model on Canary experience (`TRAIN_SEEDS = [100000, 200000)`) "
        "that measurably improves on held-out seeds (`HELDOUT_SEEDS = [800000, 800200)`), with honest "
        "before/after comparisons and every run logged, including OOMs, zero-variance collapses, and "
        "negative-reward regressions.",
        "",
        f"- Historical runs logged: `{counts['historical_runs']}`",
        f"- Dynamically discovered squad runs: `{counts['discovered_runs']}`",
        f"- Verified improvements passing all 4 strict gates: `{counts['verified_improvements']}`",
        "",
        f"{h2} 1. Architecture Diagnosis: Why Raw 4k Transcripts Failed",
        "",
        "Across three generations of raw-transcript GPU runs (`J4-pilot-44200`, `J4-v1-44397`, `WS4-v2-44412`, "
        "and `WS4-v3-*`), Qwen2.5-1.5B-Instruct learned valid tool syntax (`0.08 -> 0.99` valid calls) yet failed "
        "to produce positive held-out reward. Log forensics isolate three compounding root causes:",
        "",
        f"{h3} 1.1 Prompt Header Crowding and Evidence Truncation (`2,842 / 4,096` Tokens)",
        "",
        "- In `slurm-44410.out`, the system prompt, OpenAI tool JSON schemas, and kickoff consume `2,842` tokens "
        "of every `4,096`-token window, leaving only `1,254` tokens (`~6-8` tool turns) for episode history.",
        "- During multi-day evaluation (`14` days on easy/medium, `21` days on v1.4 hard), `HFPolicy._prompt_ids` "
        "drops the oldest `(assistant, tool)` pairs once context exceeds `4,000` tokens.",
        "- That sticky prefix eviction deletes Day 1 `list_employees` (departments and clearances) and early "
        "`plant_canary` variant-to-recipient maps before delayed leaks (`delay_choices = (1, 2, 3)` on medium, "
        "`(2, 3)` on hard) surface in `check_leak_feed`. When the model later sees a leaked variant, the "
        "mapping from variant to employee has already scrolled out of its `1,254`-token body window.",
        "",
        f"{h3} 1.2 Survivorship-Biased SFT Endings (`0%` Abstentions Under `-1.0` Penalty)",
        "",
        "- Under Canary v0.3+ scoring, a correct accusation earns `+V`, abstaining to the horizon scores `0.0`, "
        "and a wrong accusation scores `-1.0` (breakeven posterior `p* = 1 / (1 + V) ~ 0.56` to `0.72`).",
        "- Legacy J3/J3v2 exports (`train/export_sft.py`) kept only `correct=True` accusations (`0%` abstentions).",
        "- In `J4-v1-44397` (`prefix` 4k windows, `1.57%` loss-token share across `287M` tokens), terminal `accuse` "
        "turns were `<1.5%` of assistant turns: LoRA mastered tool syntax (`0.08 -> 0.99` valid calls, `~0.85` "
        "solver action-type agreement) but rarely accused, scoring `-0.250 +/- 0.256` on deduplicated held-out "
        "episodes (`n=12`) vs base `0.000`.",
        "- In `WS4-v2-44412` (`dense` 4k windows + `--oversample-endings 3`), oversampling `accuse` endings 4x "
        "forced the model to accuse on `51%` (`42/82`) of held-out episodes while `1,254`-token truncation hid "
        "who received each canary variant. Accuracy collapsed to `6.1%` (`5/82` overall, `0/27` on hard), "
        "driving mean score down to `-0.395 +/- 0.128`.",
        "",
        f"{h3} 1.3 Decision-Point GRPO Bottlenecks at 4k Context (`44548-44572`)",
        "",
        "- `WS4-v3-44548-44550`: unchunked group prefill and full-logit sampling OOMed V100-32GB (`5.49-5.52 GiB` "
        "allocation failure above `~26.5 GiB` reserved).",
        "- `WS4-v3-44553`: after enabling gradient checkpointing, unguided sampling hit `8/10` zero-variance "
        "groups (`continue_frac=1.0`, `accuse_frac=0.0`) because avoiding `-1.0` dominates uninformed guesses.",
        "- `WS4-v3-verda-s0-44572`: guided forced-accuse exploration lifted step-140 valid-only decision gain to "
        "`+0.091` without single-tool collapse, but forced-accuse target (`whom`) accuracy remained flat at "
        "`~0.19` under 4k raw context because recipient assignments were still truncated.",
        "",
        f"{h3} 1.4 Paired World-Secret Hygiene (`44411` vs `44412` Caveat)",
        "",
        "- Without `CANARY_WORLD_SECRET`, `canary.world` draws a fresh per-process `os.urandom(32)` key "
        "(`f272803cdb679dbe` in `WS4-base-44411` vs `c86b9c8a54f8b269` in `WS4-v2-44412`). Honest held-out "
        "claims require an identical `world_secret_tag` across `before` and `after` on `HELDOUT_SEEDS`.",
        "",
        f"{h2} 2. Calibrated Working-Memory Solution",
        "",
        "1. **Compact Working-Memory State (`train/compact_render.py`)**: replaces raw multi-thousand-token "
        "tool logs with a lossless `<900`-token working-memory state tracking employee clearances, planted "
        "canary `(doc_id, variant -> recipients)` tables, surfaced leak feed matches, candidate consistency "
        "counts, `known_v`, and the exact breakeven threshold `1 / (1 + known_v)`.",
        "2. **Posterior-Calibrated SFT + EV-Margin DPO (`train/export_calibrated_sft.py`)**: filters natural "
        "rollouts by exact Bayesian calibration (`top_p >= breakeven_p` for accusations; `top_p < breakeven_p` "
        "for horizon abstentions), synthesizes censored low-posterior horizon abstentions (`score = 0.0`), "
        "oversamples abstentions `2x` in train, and exports step-level DPO pairs penalizing negative-EV "
        "premature accusations and runner-up guesses.",
        "3. **Multi-Scale Small-Model Tiebreaker Ladder**: evaluates compact-state LoRA/DPO (`Qwen2.5-0.5B` and "
        "`Qwen2.5-1.5B`) alongside lightweight learned policies (`TinyMLPPolicy`, `EmpiricalBayesPolicy`) trained "
        "strictly on `TRAIN_SEEDS` and paired on identical `HELDOUT_SEEDS` worlds.",
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
