from __future__ import annotations

import argparse
from collections import Counter
import io
import json
import math
from pathlib import Path
import sys
import time
import tokenize
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "canary.tiebreak.failure_taxonomy_matrix.v1"
H = chr(35)
EUR = chr(0x20AC)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

MAX_JSON_BYTES = 80 * 1024
MAX_CHECK_SECONDS = 0.2

DEFAULT_OUT_JSON = Path("results/tiebreak/failure_taxonomy/failure_taxonomy_matrix.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_failure_taxonomy.md")

LEDGER_REL = Path("results/tiebreak/experiment_ledger.json")
FORENSICS_REL = Path("results/tiebreak/forensics_prior_runs.json")
MULTISEED_REL = Path("results/tiebreak/verda_multiseed/multiseed_summary.json")
CONFOUND_REL = Path("results/tiebreak/context_confound/audit_summary.json")
DAGGER_MECH_REL = Path("results/tiebreak/dagger_mechanism/dagger_mechanism_summary.json")

CANONICAL_HISTORICAL_RUN_IDS: tuple[str, ...] = (
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

BUCKET_SPECS: tuple[dict[str, Any], ...] = (
    {
        "bucket_id": "infra_oom_zerovar_spot_reaper_n0",
        "short_label": "n=0 Infra / OOM / Zero-Var / Spot / Reaper",
        "title": "n=0 Infrastructure, Host/CUDA OOM, Zero-Variance Collapse, Spot Preemption, and Reaper Deletion Failures",
        "expected_count": 5,
        "run_ids": (
            "J4-pilot-44200",
            "WS4-v3-44548-44550",
            "WS4-v3-44553",
            "WS4-v3-4k-s1-714d-spot",
            "Verda-base-backup-18ac",
        ),
        "primary_bottleneck": "Host 28G cgroup RAM tokenization OOM, V100-32GB SDPA group-prefill OOM, unguided continue-only zero-variance GRPO collapse, Verda A100 spot preemption, and 07:30 on-instance reaper deletion before output sync.",
    },
    {
        "bucket_id": "untrained_base_protocol_stall",
        "short_label": "Untrained Base Protocol Stalls",
        "title": "Untrained Qwen2.5-1.5B Zero-Shot Tool-Call Protocol Stalls",
        "expected_count": 2,
        "run_ids": (
            "WS4-base-44411",
            "WS4-base-pooled",
        ),
        "primary_bottleneck": "97% invalid tool-call syntax (0.03 valid call rate) stalls every episode at eval_cap=120 on Day 1 with 0 canaries planted and 0.000 passive abstention score under unpaired os.urandom(32) world keys.",
    },
    {
        "bucket_id": "prefix_4k_sft_v13_sparse_loss",
        "short_label": "Prefix-4k v1.3 SFT Sparse-Loss Underfit",
        "title": "Prefix-4k v1.3 SFT Protocol Syntax Gain with 1.57% Sparse-Loss Under-Commitment",
        "expected_count": 1,
        "run_ids": (
            "J4-v1-44397",
        ),
        "primary_bottleneck": "Prefix-window 4k SFT (1.57% loss-token fraction, 5% of an epoch in 450 steps) solved tool syntax (0.08 -> 0.99 valid calls) but underfit multi-day stopping and culprit attribution (-0.250 +/- 0.256, 0/3 correct accusations on v1.3).",
    },
    {
        "bucket_id": "dense_4k_sft_blind_accuse",
        "short_label": "Dense-4k SFT Blind-Accuse Collapse",
        "title": "Dense-4k Accuse-Only SFT Header Crowding and Blind-Accusation Collapse",
        "expected_count": 2,
        "run_ids": (
            "WS4-v2-44412",
            "WS4-v2-off30-68bb",
        ),
        "primary_bottleneck": "2,842 / 4,096 prompt header tokens (69.4%) leave 1,254 body tokens, evicting Day-1 rosters and 67.5%-90.0% of planted canary maps while 3x oversampled accuse-only SFT drives 95.7% (90/94) below-breakeven accusations (-0.457 +/- 0.086 pooled n=172).",
    },
    {
        "bucket_id": "grpo_4k_offpolicy_evidence_shift",
        "short_label": "4k GRPO Off-Policy Evidence Shift",
        "title": "4k Guided Decision-Point GRPO Off-Policy Solver-State Evidence Shift",
        "expected_count": 2,
        "run_ids": (
            "WS4-v3-4k-s1-44572",
            "WS4-v3-verda-s0-eval",
        ),
        "primary_bottleneck": "60% of GRPO states came from the solver's final 6 pre-commit steps (whom-accuracy 0.19 -> 0.89 on clean solver evidence), but standalone rollouts plant only 3.53 canaries/ep (100% evicted at 4k) and hit 6/38 = 0.16 precision (-0.147 +/- 0.063 on s0 n=180; -0.209 +/- 0.094 on flat 192-step V100 s1 n=82).",
    },
    {
        "bucket_id": "same_weights_8k_inference_confound",
        "short_label": "Same-Weights 8k Inference Confound",
        "title": "Same-Weights 4k-to-8k Inference Context-Length Shift Confound",
        "expected_count": 1,
        "run_ids": (
            "WS4-v3-4k-s0-ctx8k",
        ),
        "primary_bottleneck": "Evaluating the exact same 609-step 4k-trained adapter (3d0cd43b8037) at max_ctx=8192 pushes prompt lengths outside 4k SFT/GRPO support, flipping medium/hard accusations from 0.00/0.03 to 0.80/0.90 (0/51 correct; 70/70 below breakeven) and dropping score from -0.147 to -0.716 +/- 0.105 (two-sample -0.568 +/- 0.123).",
    },
    {
        "bucket_id": "grpo_8k_high_step_abstention_collapse",
        "short_label": "~650-Step 8k GRPO Abstention Collapse",
        "title": "High-Step (~650-Step H100) 8k GRPO Global Abstention Collapse",
        "expected_count": 2,
        "run_ids": (
            "WS4-v3-8k-s0-3bb7",
            "WS4-v3-8k-s2-dbd0",
        ),
        "primary_bottleneck": "Crossing ~500 GRPO steps on H100 (637 and 693 steps, mean 665.0) suppresses negative-EV 8k over-accusations (free_accuse_frac 0.08-0.12 -> 0.023-0.041, paired +0.728 +/- 0.134 over s3) by collapsing to 92.8% (167/180) global abstention, missing 21/167 positive-EV commits and still trailing 0.000 (-0.060 and -0.050).",
    },
    {
        "bucket_id": "grpo_8k_low_step_over_accuse",
        "short_label": "~350-Step 8k GRPO Over-Accuse & Paired Null",
        "title": "Low-Step (~350-Step A100) 8k GRPO Off-Policy Over-Accusation and Paired Null",
        "expected_count": 2,
        "run_ids": (
            "WS4-v3-8k-s1-ac58",
            "WS4-v3-8k-s3-f437",
        ),
        "primary_bottleneck": "Terminating at 371 and 344 GRPO steps in 3.0h on A100 (mean 357.5 steps) leaves free_accuse_frac at 0.108-0.118 under 4k->8k shift: 95.0% (171/180) episodes accuse early (~Day 4-5) with 97.7% (167/171) below breakeven (-0.777 and -0.788) and world-paired s3 - 4k@8k = -0.073 +/- 0.173 (60/60 rosters).",
    },
    {
        "bucket_id": "verda_x2_dagger_r1_honest_null",
        "short_label": "Verda X2 DAgger r1 8k/4k Honest Nulls",
        "title": "Verda X2 On-Policy Raw-Transcript DAgger Round 1 Honest Nulls (8k and 4k)",
        "expected_count": 2,
        "run_ids": (
            "WS4-dagger-r1-8k-verda",
            "WS4-dagger-r1-4k-verda",
        ),
        "primary_bottleneck": "250 SFT steps on 4,000 solver-relabelled own-policy states (cap=256 required because cap=96 truncates 73.9% of hard DAgger plant_canary relabels) raised own-state agreement 43% -> 68% and doubled 8k whom-precision 0.10 -> 0.22, but 159/4,000 implicit next-token accuse labels failed to calibrate stopping: 92% premature accuse at 8k (-0.542 +/- 0.214, n=50) vs 85% abstain at 4k (-0.101 +/- 0.112, n=41).",
    },
)

VERDA_INSTANCE_LEDGER: tuple[dict[str, Any], ...] = (
    {
        "instance_id": "3bb74f5a",
        "gpu_spec": "H100 80GB on-demand",
        "pricing_mode": "on-demand",
        "eur_per_hour": 4.7421,
        "max_gpu_hours": 8.73,
        "max_cost_eur": 41.41,
        "termination": "07:30 on-instance reaper",
        "workloads": ["WS4-v3-verda-s0-eval", "WS4-v3-8k-s0-3bb7", "shared Meta YOLOv8n (0.15h)"],
    },
    {
        "instance_id": "ac58df04",
        "gpu_spec": "A100 80GB spot",
        "pricing_mode": "spot",
        "eur_per_hour": 1.0794,
        "max_gpu_hours": 3.83,
        "max_cost_eur": 4.13,
        "termination": "03:50 manual delete after eval pull",
        "workloads": ["WS4-v3-8k-s1-ac58"],
    },
    {
        "instance_id": "dbd083ca",
        "gpu_spec": "H100 80GB spot",
        "pricing_mode": "spot",
        "eur_per_hour": 2.3711,
        "max_gpu_hours": 3.93,
        "max_cost_eur": 9.33,
        "termination": "04:20 manual delete after eval pull",
        "workloads": ["WS4-v3-8k-s2-dbd0"],
    },
    {
        "instance_id": "924e81d8",
        "gpu_spec": "A100 80GB spot",
        "pricing_mode": "spot",
        "eur_per_hour": 1.0794,
        "max_gpu_hours": 6.68,
        "max_cost_eur": 7.21,
        "termination": "07:30 on-instance reaper (lost before pull)",
        "workloads": ["J1 Qwen3-14B bf16 vLLM open-weight agent (0 episodes recovered)"],
    },
    {
        "instance_id": "68bbe201",
        "gpu_spec": "A100 80GB on-demand",
        "pricing_mode": "on-demand",
        "eur_per_hour": 2.1589,
        "max_gpu_hours": 6.48,
        "max_cost_eur": 14.00,
        "termination": "07:30 on-instance reaper (partial 4k DAgger pulled ~05:35)",
        "workloads": [
            "WS4-v2-off30-68bb",
            "WS4-v3-verda-s0-eval (off30)",
            "WS4-v3-4k-s0-ctx8k",
            "WS4-dagger-r1-8k-verda (eval)",
            "WS4-dagger-r1-4k-verda (eval)",
        ],
    },
    {
        "instance_id": "f4378173",
        "gpu_spec": "A100 80GB on-demand",
        "pricing_mode": "on-demand",
        "eur_per_hour": 2.1589,
        "max_gpu_hours": 3.97,
        "max_cost_eur": 8.56,
        "termination": "05:06 manual delete after eval pull",
        "workloads": ["WS4-v3-8k-s3-f437", "shared Meta PaliGemma 2 3B (0.65h)"],
    },
    {
        "instance_id": "18acfa5d",
        "gpu_spec": "A100 80GB on-demand",
        "pricing_mode": "on-demand",
        "eur_per_hour": 2.1589,
        "max_gpu_hours": 5.22,
        "max_cost_eur": 11.26,
        "termination": "07:30 on-instance reaper (lost before pull)",
        "workloads": ["Verda-base-backup-18ac (0 episodes recovered)", "shared X1 OpenCode CPU runners"],
    },
    {
        "instance_id": "714d8144",
        "gpu_spec": "A100 80GB spot",
        "pricing_mode": "spot",
        "eur_per_hour": 1.0794,
        "max_gpu_hours": 0.35,
        "max_cost_eur": 0.38,
        "termination": "~03:00 spot preemption (~29 min in, 0 episodes)",
        "workloads": ["WS4-v3-4k-s1-714d-spot"],
    },
    {
        "instance_id": "e9ea8b2e",
        "gpu_spec": "A100 40GB on-demand",
        "pricing_mode": "on-demand",
        "eur_per_hour": 1.5373,
        "max_gpu_hours": 4.97,
        "max_cost_eur": 7.64,
        "termination": "08:00 on-instance reaper (partial 8k DAgger n=50 pulled ~05:35)",
        "workloads": ["WS4-dagger-r1-8k-verda (train)", "WS4-dagger-r1-4k-verda (train)"],
    },
)


def _approx_eq(a: float, b: float, tol: float = 1e-3) -> bool:
    return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tol


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"missing required backing artifact: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _collect_verda_instances_from_ledger(hist_runs: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    instance_keys = (
        "verda_instance",
        "verda_off30_instance",
        "verda_eval_instance",
        "verda_train_instance",
        "also_lost_at_reaper_instance",
    )
    for r in hist_runs:
        det = r.get("details") or {}
        for k in instance_keys:
            val = det.get(k)
            if isinstance(val, str) and val.strip():
                found.add(val.strip())
    return found


def build_taxonomy_matrix(repo_root: Path = ROOT) -> dict[str, Any]:
    ledger = _load_json(repo_root / LEDGER_REL)
    forensics = _load_json(repo_root / FORENSICS_REL)
    multiseed = _load_json(repo_root / MULTISEED_REL)
    confound = _load_json(repo_root / CONFOUND_REL)
    dagger_mech = _load_json(repo_root / DAGGER_MECH_REL)

    hist_runs: list[dict[str, Any]] = list(ledger.get("historical_runs") or [])
    disc_runs: list[dict[str, Any]] = list(ledger.get("discovered_runs") or [])
    sc = ledger.get("summary_counts") or {}

    _require(len(hist_runs) == 19, f"expected 19 historical runs, got {len(hist_runs)}")
    _require(int(sc.get("historical_runs", -1)) == 19, "summary_counts.historical_runs != 19")

    ledger_ids = tuple(str(r.get("run_id")) for r in hist_runs)
    _require(
        ledger_ids == CANONICAL_HISTORICAL_RUN_IDS,
        f"historical run_id order mismatch: {ledger_ids}",
    )

    by_id: dict[str, dict[str, Any]] = {str(r["run_id"]): r for r in hist_runs}

    bucket_for_run: dict[str, str] = {}
    for bspec in BUCKET_SPECS:
        rids = tuple(bspec["run_ids"])
        _require(
            len(rids) == int(bspec["expected_count"]),
            f"bucket {bspec['bucket_id']} count mismatch",
        )
        for rid in rids:
            _require(rid in by_id, f"bucket {bspec['bucket_id']} references unknown {rid}")
            _require(rid not in bucket_for_run, f"duplicate bucket assignment for {rid}")
            bucket_for_run[rid] = str(bspec["bucket_id"])
    _require(len(bucket_for_run) == 19, f"expected 19 bucketed runs, got {len(bucket_for_run)}")

    status_counts = Counter(str(r.get("status")) for r in (hist_runs + disc_runs))
    expected_by_status = {str(k): int(v) for k, v in (sc.get("by_status") or {}).items()}
    _require(dict(status_counts) == expected_by_status, "ledger status histogram mismatch")

    for r in hist_runs:
        rid = str(r["run_id"])
        _require(r.get("verified_improvement") is False, f"{rid}: verified_improvement must be False")
        _require(r.get("replay_verified") is False, f"{rid}: replay_verified must be False")
        after_s = r.get("after_mean_score")
        if after_s is not None:
            _require(float(after_s) < 0.0, f"{rid}: expected open-weight after_mean_score < 0.0, got {after_s}")
        before_s = r.get("before_mean_score")
        if before_s is not None:
            _require(float(before_s) <= 0.0, f"{rid}: expected before_mean_score <= 0.0, got {before_s}")

    f_j4 = forensics["j4_runs"]
    f_v3 = forensics["v3_grpo_runs"]
    f_vm = forensics["verda_v3_complete_matrix"]
    f_rc = forensics["ws4_v2_root_cause"]

    _require(
        int(f_j4["pilot_44200"]["job_id"]) == int(by_id["J4-pilot-44200"]["details"]["slurm_job_id"]) == 44200,
        "J4-pilot-44200 job_id mismatch",
    )
    _require(int(f_j4["pilot_44200"]["oom_kill_events"]) == 1, "J4-pilot-44200 oom_kill_events != 1")

    v1_tr = f_j4["v1_44397"]["train"]
    v1_ev = f_j4["v1_44397"]["eval"]["eval_lora_dedup_first_seen"]["overall"]
    v1_det = by_id["J4-v1-44397"]["details"]
    _require(int(v1_tr["steps_completed"]) == int(v1_det["train_steps"]) == 450, "J4-v1-44397 steps != 450")
    _require(
        int(v1_tr["train_tokens_processed"]) == int(v1_det["tokens_trained"]) == 14313726,
        "J4-v1-44397 tokens_trained != 14313726",
    )
    _require(
        _approx_eq(v1_tr["loss_token_frac_exact"], v1_det["loss_token_fraction"], 1e-4),
        "J4-v1-44397 loss_token_fraction mismatch",
    )
    _require(
        int(v1_ev["n"]) == int(by_id["J4-v1-44397"]["heldout_n"]) == 12
        and _approx_eq(v1_ev["mean_score"], by_id["J4-v1-44397"]["after_mean_score"], 1e-3),
        "J4-v1-44397 eval mismatch",
    )

    b11_ev = f_j4["ws4_v2_44410"]["eval_base_44411"]["episodes"]["overall"]
    b84_ev = f_j4["ws4_v2_44410"]["eval_base_44584_snapshot"]["episodes"]["overall"]
    _require(int(b11_ev["n"]) == int(by_id["WS4-base-44411"]["heldout_n"]) == 16, "WS4-base-44411 n != 16")
    _require(int(b84_ev["n"]) == 20, "eval_base_44584 n != 20")
    _require(
        int(f_vm["pooled_base"]["n"]) == int(by_id["WS4-base-pooled"]["heldout_n"]) == 36
        and int(b11_ev["n"]) + int(b84_ev["n"]) == 36,
        "WS4-base-pooled n != 36",
    )

    v2_tr = f_j4["ws4_v2_44410"]["train"]
    v2_12 = f_j4["ws4_v2_44410"]["eval_v2_44412"]["episodes"]["overall"]
    v2_det = by_id["WS4-v2-44412"]["details"]
    v2_off_det = by_id["WS4-v2-off30-68bb"]["details"]
    v2_conf = confound["runs"]["v2-off30"]["by_tier"]["all"]
    _require(int(v2_tr["steps_completed"]) == int(v2_det["train_steps"]) == 887, "WS4-v2 train_steps != 887")
    _require(
        int(v2_tr["header_tokens"]) == int(v2_det["header_tokens"]) == int(f_rc["window_model"]["header_tokens"]) == 2842
        and int(confound["header_and_token_calibration"]["slurm_44410_reference_header_tokens"]) == 2842,
        "WS4-v2 header_tokens != 2842",
    )
    _require(
        int(v2_tr["body_budget_tokens"]) == int(v2_det["body_budget_tokens"]) == 1254,
        "WS4-v2 body_budget_tokens != 1254",
    )
    _require(
        int(v2_12["n"]) == int(by_id["WS4-v2-44412"]["heldout_n"]) == 82
        and _approx_eq(v2_12["mean_score"], by_id["WS4-v2-44412"]["after_mean_score"], 1e-3)
        and int(v2_12["accused_count"]) == int(v2_det["accused_count"]) == 42,
        "WS4-v2-44412 forensics mismatch",
    )
    _require(
        int(v2_conf["n"]) == int(by_id["WS4-v2-off30-68bb"]["heldout_n"]) == 90
        and _approx_eq(v2_conf["mean_score_3d"], by_id["WS4-v2-off30-68bb"]["after_mean_score"], 1e-3)
        and int(v2_conf["accused_count"]) == int(v2_off_det["accused_count"]) == 52,
        "WS4-v2-off30 context_confound mismatch",
    )
    v2_below_be_pooled = int(f_rc["overall"]["below_breakeven_count"]) + int(
        v2_conf["belief_replay"]["below_breakeven_count"]
    )
    v2_accused_pooled = int(f_rc["overall"]["accused_episodes"]) + int(
        v2_conf["belief_replay"]["accused_episodes"]
    )
    _require(
        v2_below_be_pooled == 90 and v2_accused_pooled == 94 and int(f_vm["pooled_v2"]["n"]) == 172,
        "pooled v2 below-breakeven 90/94 or n=172 mismatch",
    )

    oom_list = f_v3["attempt1_cuda_oom"]
    _require(
        len(oom_list) == 2
        and [int(x["job_id"]) for x in oom_list] == [44548, 44550]
        and _approx_eq(oom_list[0]["tried_allocate_gib"], 5.49, 1e-2)
        and _approx_eq(oom_list[1]["tried_allocate_gib"], 5.52, 1e-2),
        "WS4-v3-44548-44550 forensics OOM mismatch",
    )
    _require(
        int(f_v3["attempt2_zero_variance_44553"]["n_steps"]) == int(by_id["WS4-v3-44553"]["details"]["steps_logged"]) == 6,
        "WS4-v3-44553 steps_logged != 6",
    )
    spot_lost = multiseed["lost_replicates"][0]
    _require(
        f_vm["v3_4k_family"]["v3_4k_s1_spot_714d"]["verda_instance"] == "714d8144"
        and "714d8144" in spot_lost["where_trained"]
        and _approx_eq(spot_lost["gpu_hours"], 0.35, 1e-3)
        and _approx_eq(spot_lost["cost_eur"], 0.38, 1e-3),
        "WS4-v3-4k-s1-714d-spot cross-artifact mismatch",
    )

    ms_by_id: dict[str, dict[str, Any]] = {}
    for entry in list(multiseed.get("seeds_8k") or []) + list(multiseed.get("seeds_4k") or []):
        ms_by_id[str(entry["run_id"])] = entry
    ctrl_8k = multiseed["inference_context_control_4k_at_8k"]
    ms_by_id[str(ctrl_8k["run_id"])] = ctrl_8k

    ledger_to_multiseed = (
        ("WS4-v3-verda-s0-eval", "v3_4k_s0"),
        ("WS4-v3-4k-s1-44572", "v3_4k_s1"),
        ("WS4-v3-4k-s0-ctx8k", "v3_4k_s0_ctx8k"),
        ("WS4-v3-8k-s0-3bb7", "v3_8k_s0"),
        ("WS4-v3-8k-s1-ac58", "v3_8k_s1"),
        ("WS4-v3-8k-s2-dbd0", "v3_8k_s2"),
        ("WS4-v3-8k-s3-f437", "v3_8k_s3"),
    )
    for l_id, m_id in ledger_to_multiseed:
        lr = by_id[l_id]
        mr = ms_by_id[m_id]
        mo = mr["overall"]
        _require(int(lr["heldout_n"]) == int(mo["n"]), f"{l_id} vs {m_id}: n mismatch")
        _require(
            int(lr["details"]["grpo_steps"]) == int(mr["grpo_steps"]),
            f"{l_id} vs {m_id}: grpo_steps mismatch",
        )
        _require(
            _approx_eq(lr["after_mean_score"], mo["mean_score_3d"], 1.5e-3)
            and _approx_eq(lr["after_ci95"], mo["ci95_3d"], 1.5e-3),
            f"{l_id} vs {m_id}: score/ci95 mismatch",
        )
        _require(
            int(lr["details"]["accused_count"]) == int(mo["accused_count"])
            and int(lr["details"]["correct_count"]) == int(mo["correct_count"]),
            f"{l_id} vs {m_id}: accused/correct count mismatch",
        )

    ms_tot = multiseed["totals"]
    replayed_sum = sum(int(ms_by_id[m_id]["overall"]["n"]) for _, m_id in ledger_to_multiseed)
    grpo_6_steps = sum(
        int(ms_by_id[m_id]["grpo_steps"])
        for _, m_id in ledger_to_multiseed
        if m_id != "v3_4k_s0_ctx8k"
    )
    _require(
        int(ms_tot["total_episodes_replayed"]) == replayed_sum == 712
        and int(ms_tot["total_replay_invariant_errors"]) == 0,
        "multiseed 712 episodes or 0 replay invariant errors mismatch",
    )
    _require(
        int(ms_tot["total_training_curve_steps_audited"]) == grpo_6_steps == 2846,
        "multiseed 2846 GRPO curve steps mismatch",
    )

    bm = multiseed["bimodal_regime_split"]
    hi_8k = bm["high_step_8k_cluster"]
    lo_8k = bm["low_step_8k_cluster"]
    _require(
        hi_8k["steps_per_seed"] == [637, 693]
        and _approx_eq(hi_8k["mean_steps"], 665.0, 1e-6)
        and int(hi_8k["pooled_episodes"]) == 180
        and int(hi_8k["belief_replay"]["abstained_episodes"]) == 167
        and int(hi_8k["belief_replay"]["missed_commit_abstain_count"]) == 21,
        "high-step 8k cluster mismatch",
    )
    _require(
        lo_8k["steps_per_seed"] == [371, 344]
        and _approx_eq(lo_8k["mean_steps"], 357.5, 1e-6)
        and int(lo_8k["pooled_episodes"]) == 180
        and int(lo_8k["belief_replay"]["accused_episodes"]) == 171
        and int(lo_8k["belief_replay"]["below_breakeven_count"]) == 167,
        "low-step 8k cluster mismatch",
    )
    wp = multiseed["world_paired_shared_secret_comparisons"]
    _require(
        _approx_eq(wp["s0_minus_s3"]["mean_delta_3d"], 0.728, 1e-3)
        and _approx_eq(wp["s3_minus_4k_at_8k"]["mean_delta_3d"], -0.073, 1e-3)
        and _approx_eq(wp["s0_minus_4k_at_8k"]["mean_delta_3d"], 0.655, 1e-3)
        and _approx_eq(bm["paired_triangle_decomposition_residual"], 0.0, 1e-6)
        and int(bm["beats_always_abstain_base_count"]) == 0,
        "world-paired 8k triangle mismatch",
    )

    _require(int(confound["n"]) == 450, "context_confound n != 450")
    c_all450 = confound["pooled_views"]["all_450_verda"]["all"]
    c_inf = confound["inference_length_confound_v3_4k_s0_at_8k"]
    _require(
        c_inf["adapter_sha256_prefix"] == "3d0cd43b8037"
        and _approx_eq(c_inf["eval_at_4k"]["by_tier"]["all"]["mean_score"], -0.147, 1e-3)
        and _approx_eq(c_inf["eval_at_8k"]["by_tier"]["all"]["mean_score"], -0.716, 1e-3)
        and _approx_eq(c_inf["two_sample_delta_8k_minus_4k"]["all"]["mean_delta"], -0.568, 1e-3)
        and int(c_all450["compact_transcript"]["canary_map_evicted_count"]) == 0,
        "context_confound 4k@8k or compact 0-eviction mismatch",
    )

    dm_rq = dagger_mech["cross_track_dagger_comparison"]["raw_qwen_dagger_r1"]
    dm_tc = dagger_mech["token_cap_audit"]
    dm_sc = dagger_mech["stopping_calibration_contrast"]["all"]
    dm_st = dagger_mech["cross_track_dagger_comparison"]["structured_compact_dagger"]
    _require(
        dm_rq["run_8k_id"] == "WS4-dagger-r1-8k-verda"
        and dm_rq["run_4k_id"] == "WS4-dagger-r1-4k-verda"
        and int(dm_rq["vllm_rollout_episodes"]) == 300
        and int(dm_rq["relabelled_states"]) == 24074
        and int(dm_rq["solver_match_checked"]) == int(dm_rq["solver_match_equal"]) == 2603
        and int(dm_rq["sft_examples"]) == 4000
        and int(dm_rq["sft_steps"]) == 250
        and _approx_eq(dm_rq["eval_8k"]["mean_score"], by_id["WS4-dagger-r1-8k-verda"]["after_mean_score"], 1e-3)
        and _approx_eq(dm_rq["eval_4k"]["mean_score"], by_id["WS4-dagger-r1-4k-verda"]["after_mean_score"], 1e-3),
        "dagger_mechanism raw_qwen_dagger_r1 mismatch",
    )
    _require(
        int(dm_tc["by_tier"]["hard"]["dagger_student_state_relabel"]["exceed_cap96_count"]) == 133
        and int(dm_tc["by_tier"]["hard"]["dagger_student_state_relabel"]["n_calls"]) == 180
        and int(dm_sc["below_breakeven_states"]) == 250
        and int(dm_sc["daily_decision_states"]) == 322,
        "dagger_mechanism cap=96 or stopping contrast mismatch",
    )

    reaper_det = by_id["Verda-base-backup-18ac"]["details"]
    verda_spend_eur = float(reaper_det["verda_measured_spend_eur"])
    verda_start_eur = float(reaper_det["verda_start_balance_eur"])
    verda_end_eur = float(reaper_det["verda_end_balance_eur"])
    verda_deleted_n = int(reaper_det["verda_total_instances_deleted"])
    _require(
        verda_deleted_n == 9
        and _approx_eq(verda_start_eur - verda_end_eur, verda_spend_eur, 1e-6)
        and _approx_eq(verda_spend_eur, 104.46, 1e-6),
        "Verda EUR 104.46 spend or 9 deleted instances mismatch",
    )

    ledger_verda_ids = _collect_verda_instances_from_ledger(hist_runs)
    table_verda_ids = {row["instance_id"] for row in VERDA_INSTANCE_LEDGER}
    _require(
        ledger_verda_ids == table_verda_ids and len(table_verda_ids) == 9,
        f"Verda 9-instance ID set mismatch: {ledger_verda_ids} vs {table_verda_ids}",
    )
    verda_max_gpu_hours_sum = round(sum(float(x["max_gpu_hours"]) for x in VERDA_INSTANCE_LEDGER), 2)
    verda_max_cost_eur_sum = round(sum(float(x["max_cost_eur"]) for x in VERDA_INSTANCE_LEDGER), 2)

    run_Step_Meta: dict[str, tuple[str, int, int, str, list[str]]] = {
        "J4-pilot-44200": ("sft_pilot_oom", 0, 0, "FR8 V100-32GB (job 44200)", ["experiment_ledger.json", "forensics_prior_runs.json"]),
        "J4-v1-44397": ("sft_prefix_4k", 450, 450, "FR8 V100-32GB (job 44397)", ["experiment_ledger.json", "forensics_prior_runs.json"]),
        "WS4-base-44411": ("untrained_base", 0, 0, "FR8 V100-32GB (eval 44411)", ["experiment_ledger.json", "forensics_prior_runs.json"]),
        "WS4-base-pooled": ("untrained_base_pooled", 0, 0, "FR8 V100-32GB (evals 44411 + 44584)", ["experiment_ledger.json", "forensics_prior_runs.json"]),
        "WS4-v2-44412": ("sft_dense_4k", 887, 887, "FR8 V100-32GB (train 44410 / eval 44412)", ["experiment_ledger.json", "forensics_prior_runs.json"]),
        "WS4-v2-off30-68bb": ("sft_dense_4k_reuse", 0, 887, "Verda A100-80GB 68bbe201 (adapter 44410)", ["experiment_ledger.json", "forensics_prior_runs.json", "context_confound/audit_summary.json"]),
        "WS4-v3-44548-44550": ("grpo_cuda_oom", 0, 0, "FR8 V100-32GB (jobs 44548, 44550)", ["experiment_ledger.json", "forensics_prior_runs.json"]),
        "WS4-v3-44553": ("grpo_unguided_zerovar", 6, 6, "FR8 V100-32GB (job 44553)", ["experiment_ledger.json", "forensics_prior_runs.json"]),
        "WS4-v3-4k-s1-714d-spot": ("grpo_spot_preempted", 0, 0, "Verda A100-80GB spot 714d8144", ["experiment_ledger.json", "forensics_prior_runs.json", "verda_multiseed/multiseed_summary.json"]),
        "WS4-v3-4k-s1-44572": ("grpo_4k", 192, 192, "FR8 V100-32GB (jobs 44572 / 44573)", ["experiment_ledger.json", "forensics_prior_runs.json", "verda_multiseed/multiseed_summary.json"]),
        "WS4-v3-verda-s0-eval": ("grpo_4k", 609, 609, "Verda H100 3bb74f5a + A100 68bbe201", ["experiment_ledger.json", "forensics_prior_runs.json", "verda_multiseed/multiseed_summary.json", "context_confound/audit_summary.json"]),
        "WS4-v3-4k-s0-ctx8k": ("grpo_4k_eval_at_8k_reuse", 0, 609, "Verda A100-80GB 68bbe201 (adapter 3d0cd43b8037)", ["experiment_ledger.json", "forensics_prior_runs.json", "verda_multiseed/multiseed_summary.json", "context_confound/audit_summary.json"]),
        "WS4-v3-8k-s0-3bb7": ("grpo_8k_high_step", 637, 637, "Verda H100-80GB on-demand 3bb74f5a", ["experiment_ledger.json", "verda_multiseed/multiseed_summary.json"]),
        "WS4-v3-8k-s1-ac58": ("grpo_8k_low_step", 371, 371, "Verda A100-80GB spot ac58df04", ["experiment_ledger.json", "forensics_prior_runs.json", "verda_multiseed/multiseed_summary.json", "context_confound/audit_summary.json"]),
        "WS4-v3-8k-s2-dbd0": ("grpo_8k_high_step", 693, 693, "Verda H100-80GB spot dbd083ca", ["experiment_ledger.json", "forensics_prior_runs.json", "verda_multiseed/multiseed_summary.json", "context_confound/audit_summary.json"]),
        "WS4-v3-8k-s3-f437": ("grpo_8k_low_step", 344, 344, "Verda A100-80GB on-demand f4378173", ["experiment_ledger.json", "forensics_prior_runs.json", "verda_multiseed/multiseed_summary.json", "context_confound/audit_summary.json"]),
        "WS4-dagger-r1-8k-verda": ("dagger_r1_sft", 250, 250, "Verda A100-40GB e9ea8b2e + A100-80GB 68bbe201", ["experiment_ledger.json", "dagger_mechanism/dagger_mechanism_summary.json"]),
        "WS4-dagger-r1-4k-verda": ("dagger_r1_sft_reuse", 0, 250, "Verda A100-80GB 68bbe201 (same DAgger r1 adapter)", ["experiment_ledger.json", "dagger_mechanism/dagger_mechanism_summary.json"]),
        "Verda-base-backup-18ac": ("untrained_base_reaper_lost", 0, 0, "Verda A100-80GB on-demand 18acfa5d", ["experiment_ledger.json"]),
    }

    run_rows: list[dict[str, Any]] = []
    for idx, r in enumerate(hist_runs, start=1):
        rid = str(r["run_id"])
        det = r.get("details") or {}
        stage_kind, uniq_steps, adapter_steps, compute_loc, backing = run_Step_Meta[rid]

        if rid == "WS4-base-44411":
            seed_span = "800000..800005"
            dedup_eps = 0
        elif rid == "J4-v1-44397":
            seed_span = "v1.3_heldout_dedup12"
            dedup_eps = int(r["heldout_n"])
        else:
            seed_span = det.get("heldout_seed_range")
            if seed_span is None and int(r["heldout_n"]) > 0 and rid == "WS4-v2-44412":
                seed_span = "800000..800027"
            dedup_eps = int(r["heldout_n"])

        secret_mode = "none_n0"
        if int(r["heldout_n"]) > 0:
            if r.get("after_world_secret_tag") == "1ca0c2a64d" or det.get("shared_world_secret_tag") == "1ca0c2a64d":
                secret_mode = "shared_verda_1ca0c2a64d_unpaired_vs_base"
            else:
                secret_mode = "ephemeral_unpaired_urandom"

        accused_rate = det.get("accused_rate")
        if accused_rate is None and rid == "J4-v1-44397":
            accused_rate = 0.25
        elif accused_rate is None and rid in ("WS4-base-44411", "WS4-base-pooled"):
            accused_rate = 0.0
        elif accused_rate is None and rid == "WS4-v2-off30-68bb":
            accused_rate = round(52 / 90, 4)

        abstain_rate = det.get("abstain_rate")
        if abstain_rate is None and accused_rate is not None and int(r["heldout_n"]) > 0:
            abstain_rate = round(1.0 - float(accused_rate), 4)

        valid_rate = r.get("after_valid_call_rate")
        if valid_rate is None and rid in ("WS4-base-44411", "WS4-base-pooled"):
            valid_rate = r.get("before_valid_call_rate")

        mean_score = r.get("after_mean_score")
        if mean_score is None and rid in ("WS4-base-44411", "WS4-base-pooled"):
            mean_score = r.get("before_mean_score")

        run_rows.append(
            {
                "order": idx,
                "run_id": rid,
                "bucket_id": bucket_for_run[rid],
                "status": str(r["status"]),
                "tiers_version": str(r["tiers_version"]),
                "context_len": int(r["context_len"]),
                "stage_kind": stage_kind,
                "compute_target": compute_loc,
                "unique_optimizer_steps": uniq_steps,
                "adapter_optimizer_steps": adapter_steps,
                "heldout_n": int(r["heldout_n"]),
                "dedup_unique_heldout_n": dedup_eps,
                "seed_span": seed_span,
                "mean_score": mean_score,
                "ci95": r.get("after_ci95"),
                "valid_call_rate": valid_rate,
                "accused_rate": accused_rate,
                "abstain_rate": abstain_rate,
                "secret_provenance": secret_mode,
                "beats_base_zero": False,
                "verified_improvement": False,
                "backing_artifacts": backing,
            }
        )

    raw_heldout_sum = sum(int(x["heldout_n"]) for x in run_rows)
    dedup_heldout_sum = sum(int(x["dedup_unique_heldout_n"]) for x in run_rows)
    trained_heldout_sum = sum(
        int(x["heldout_n"])
        for x in run_rows
        if x["bucket_id"] not in ("infra_oom_zerovar_spot_reaper_n0", "untrained_base_protocol_stall")
    )
    _require(
        raw_heldout_sum == 1039 and dedup_heldout_sum == 1023 and trained_heldout_sum == 987,
        f"unexpected episode totals: raw={raw_heldout_sum}, dedup={dedup_heldout_sum}, trained={trained_heldout_sum}",
    )

    sft_unique_steps = sum(
        int(x["unique_optimizer_steps"])
        for x in run_rows
        if x["stage_kind"] in ("sft_prefix_4k", "sft_dense_4k", "dagger_r1_sft")
    )
    grpo_completed_steps = sum(
        int(x["unique_optimizer_steps"])
        for x in run_rows
        if x["stage_kind"] in ("grpo_4k", "grpo_8k_high_step", "grpo_8k_low_step")
    )
    grpo_aborted_zerovar_steps = int(by_id["WS4-v3-44553"]["details"]["steps_logged"])
    total_unique_steps = sum(int(x["unique_optimizer_steps"]) for x in run_rows)
    _require(
        sft_unique_steps == 1587
        and grpo_completed_steps == 2846
        and grpo_aborted_zerovar_steps == 6
        and total_unique_steps == 4439,
        "optimizer step accounting mismatch",
    )

    buckets_out: list[dict[str, Any]] = []
    for bspec in BUCKET_SPECS:
        bid = str(bspec["bucket_id"])
        b_runs = [x for x in run_rows if x["bucket_id"] == bid]
        scores = [float(x["mean_score"]) for x in b_runs if x["mean_score"] is not None]
        buckets_out.append(
            {
                "bucket_id": bid,
                "short_label": str(bspec["short_label"]),
                "title": str(bspec["title"]),
                "run_count": len(b_runs),
                "run_ids": [x["run_id"] for x in b_runs],
                "statuses": sorted({x["status"] for x in b_runs}),
                "raw_heldout_episodes": sum(int(x["heldout_n"]) for x in b_runs),
                "dedup_unique_heldout_episodes": sum(int(x["dedup_unique_heldout_n"]) for x in b_runs),
                "unique_optimizer_steps": sum(int(x["unique_optimizer_steps"]) for x in b_runs),
                "min_mean_score": min(scores) if scores else None,
                "max_mean_score": max(scores) if scores else None,
                "runs_above_base_zero": 0,
                "primary_bottleneck": str(bspec["primary_bottleneck"]),
            }
        )

    cl_ctrl = dm_st["compact_linear_dagger"]
    tm_ctrl = dm_st["tiny_mlp_dagger"]
    eb_disc = next(r for r in disc_runs if r.get("run_id") == "empirical-bayes-v14")

    return {
        "schema": SCHEMA_VERSION,
        "tiers_version": "v1.4",
        "train_seed_range": "108000..108044",
        "dagger_seed_range": "170000..170099",
        "heldout_seed_range": "800000..800059",
        "disclosures": {
            "panel_fix_a": (
                "All tiebreaker training strictly uses TRAIN_SEEDS [100000, 200000) and all held-out "
                "tiebreaker evaluations use disjoint HELDOUT_SEEDS [800000, 800200) with 0 JUDGE_SEEDS "
                "(900000+) touched. Where DEV_SEEDS 0..29 appear in Canary frontier tables, they are "
                "post-hoc locked, not pre-registered. Pre-04:05 EET runs without CANARY_WORLD_SECRET "
                "used per-process os.urandom(32) world keys (reported strictly two-sample), whereas "
                "post-04:05 EET Verda runs under shared secret 1ca0c2a64d support exact world-paired deltas."
            ),
            "panel_fix_e": (
                "0 / 19 open-weight Qwen2.5-1.5B-Instruct runs beat untrained base 0.000 (0 / 19 "
                "VERIFIED_IMPROVEMENT; README.md Qwen addendum remains withheld). Non-LLM structured and "
                "compact neural policies (CompactLinearDAggerPolicy, TinyMLPPolicy, EmpiricalBayesPolicy, "
                "ScalingLogisticPolicy; is_open_weight_llm=False) are strictly separated on their own track "
                "and never conflated with open-weight Qwen2.5 LoRA runs."
            ),
        },
        "headline_totals": {
            "historical_open_weight_runs": 19,
            "root_cause_bucket_count": len(buckets_out),
            "runs_beating_base_zero": 0,
            "verified_open_weight_improvements": 0,
            "n0_failed_or_lost_runs": 5,
            "untrained_base_runs": 2,
            "trained_eval_runs": 12,
            "best_trained_open_weight_run_id": "WS4-v3-8k-s2-dbd0",
            "best_trained_open_weight_score": -0.05,
            "worst_trained_open_weight_run_id": "WS4-v3-8k-s3-f437",
            "worst_trained_open_weight_score": -0.788,
        },
        "episode_step_spend_accounting": {
            "episodes": {
                "raw_ledger_heldout_episodes_sum": raw_heldout_sum,
                "deduplicated_unique_heldout_episodes": dedup_heldout_sum,
                "untrained_base_unique_episodes": 36,
                "untrained_base_overlap_episodes_44411": 16,
                "trained_open_weight_heldout_episodes": trained_heldout_sum,
                "v13_trained_heldout_episodes": 12,
                "v14_trained_heldout_episodes": 975,
                "verda_multiseed_belief_replayed_episodes": 712,
                "verda_multiseed_replay_invariant_errors": 0,
                "context_confound_verda_audited_episodes": 450,
                "dagger_r1_vllm_train_rollout_episodes": 300,
                "dagger_r1_relabelled_states": 24074,
                "dagger_mechanism_train_audit_episodes": 45,
                "reaper_and_spot_lost_planned_episodes_approx": {
                    "ws4_v3_4k_s1_spot_714d": 90,
                    "verda_base_backup_18ac": 90,
                    "ws4_dagger_r1_8k_remaining": 40,
                    "ws4_dagger_r1_4k_remaining": 49,
                },
            },
            "steps": {
                "unique_sft_and_dagger_steps": sft_unique_steps,
                "j4_v1_44397_sft_steps": 450,
                "ws4_v2_44410_sft_steps": 887,
                "ws4_dagger_r1_sft_steps": 250,
                "sft_and_dagger_tokens_processed": 66708973,
                "completed_grpo_steps_6_seeds": grpo_completed_steps,
                "aborted_zerovar_grpo_steps_44553": grpo_aborted_zerovar_steps,
                "precursor_cancelled_v100_44555_steps": int(f_v3["v100_curve_44555"]["n_steps"]),
                "total_unique_ledger_optimizer_steps": total_unique_steps,
                "adapter_reuse_eval_only_runs": [
                    "WS4-v2-off30-68bb",
                    "WS4-v3-4k-s0-ctx8k",
                    "WS4-dagger-r1-4k-verda",
                ],
            },
            "verda_spend": {
                "start_balance_eur": verda_start_eur,
                "end_balance_eur": verda_end_eur,
                "measured_spend_eur": verda_spend_eur,
                "deleted_instances_count": verda_deleted_n,
                "h100_instances_count": 2,
                "a100_instances_count": 7,
                "spot_instances_count": 4,
                "on_demand_instances_count": 5,
                "reaper_deleted_instances_count": 5,
                "spot_preempted_instances_count": 1,
                "manual_deleted_after_pull_count": 3,
                "instance_table_max_gpu_hours_sum": verda_max_gpu_hours_sum,
                "instance_table_max_cost_eur_sum": verda_max_cost_eur_sum,
                "workload_attributed_eur_approx": {
                    "tiebreaker_grpo_and_evals": 72.7,
                    "x2_dagger_r1": 16.1,
                    "j1_qwen3_14b_lost_at_reaper": 7.2,
                    "x1_agent_cpu_hosting_shared": 5.8,
                    "meta_glasses_yolo_paligemma_shared": 2.1,
                },
                "instances": [dict(row) for row in VERDA_INSTANCE_LEDGER],
            },
        },
        "cross_artifact_reconciliation": {
            "backing_files_verified": [
                str(LEDGER_REL),
                str(FORENSICS_REL),
                str(MULTISEED_REL),
                str(CONFOUND_REL),
                str(DAGGER_MECH_REL),
            ],
            "mece_partition_verified": True,
            "ledger_vs_forensics_verified": True,
            "ledger_vs_multiseed_712ep_2846st_verified": True,
            "ledger_vs_context_confound_450ep_verified": True,
            "ledger_vs_dagger_mechanism_verified": True,
            "key_mechanistic_numbers": {
                "raw_4k_header_tokens_44410": 2842,
                "raw_4k_body_budget_tokens_44410": 1254,
                "raw_4k_header_fraction": 0.6938,
                "verda_450_plant_canary_evicted_4k_pct": float(c_all450["raw_transcript"]["plant_canary_evicted_4k_pct"]),
                "verda_450_plant_canary_evicted_8k_pct": float(c_all450["raw_transcript"]["plant_canary_evicted_8k_pct"]),
                "compact_state_canary_evicted_pct": 0.0,
                "pooled_v2_below_breakeven_ratio": "90/94",
                "v3_4k_s0_train_whom_first_to_last": [0.19, 0.892],
                "v3_4k_s0_heldout_precision_ratio": "6/38",
                "same_weights_4k_to_8k_two_sample_delta": -0.568,
                "paired_8k_s0_minus_s3_delta": 0.728,
                "paired_8k_s3_minus_4k_at_8k_delta": -0.073,
                "paired_8k_s0_minus_4k_at_8k_delta": 0.655,
                "high_step_8k_missed_commits_ratio": "21/167",
                "low_step_8k_below_breakeven_ratio": "167/171",
                "hard_dagger_cap96_truncation_ratio": "133/180",
                "hard_dagger_cap96_truncation_rate": 0.738889,
                "train_below_breakeven_daily_states_ratio": "250/322",
                "dagger_r1_accuse_sft_labels_ratio": "159/4000",
                "dagger_r1_own_state_agreement_before_after": [0.43, 0.68],
                "dagger_r1_8k_whom_precision_before_after": [0.10, 0.22],
            },
        },
        "non_llm_structured_contrast": {
            "is_open_weight_llm": False,
            "shared_world_secret_tag": str(dm_st["world_secret_tag"]),
            "compact_linear_dagger": {
                "run_id": str(cl_ctrl["run_id"]),
                "param_count": int(cl_ctrl["param_count"]),
                "n": int(cl_ctrl["n"]),
                "after_mean_score": float(cl_ctrl["stage3_dagger_r2_mean_score"]),
                "paired_delta_vs_untrained": float(cl_ctrl["dagger_r2_minus_untrained"]["mean_delta"]),
                "paired_delta_vs_calibrated_bc": float(cl_ctrl["dagger_r2_minus_calibrated_bc"]["mean_delta"]),
            },
            "tiny_mlp_dagger": {
                "run_id": str(tm_ctrl["run_id"]),
                "param_count": int(tm_ctrl["param_count"]),
                "n": int(tm_ctrl["n"]),
                "after_mean_score": float(tm_ctrl["stage3_dagger_r2_mean_score"]),
                "paired_delta_vs_untrained": float(tm_ctrl["dagger_r2_minus_untrained"]["mean_delta"]),
                "paired_delta_vs_uncalibrated_sft": float(tm_ctrl["dagger_r2_minus_uncalibrated_sft"]["mean_delta"]),
            },
            "empirical_bayes": {
                "run_id": str(eb_disc["run_id"]),
                "param_count": 11,
                "n": int(eb_disc["heldout_n"]),
                "after_mean_score": float(eb_disc["after_mean_score"]),
                "paired_delta_vs_naive": float(eb_disc["paired_mean_delta"]),
            },
        },
        "buckets": buckets_out,
        "runs": run_rows,
    }


def _fmt_score_ci(score: float | None, ci: float | None, heldout_n: int, bucket_id: str) -> str:
    if heldout_n == 0 or score is None:
        return "n/a (n=0)"
    if bucket_id == "untrained_base_protocol_stall":
        return "0.000 +/- 0.000 (base)"
    if ci is not None:
        return f"{float(score):+.3f} +/- {float(ci):.3f}"
    return f"{float(score):+.3f}"


def _fmt_rate(val: float | None) -> str:
    if val is None:
        return "n/a"
    return f"{float(val):.2f}"


def render_markdown_report(matrix: dict[str, Any]) -> str:
    h1 = H
    h2 = H * 2
    h3 = H * 3

    ht = matrix["headline_totals"]
    acct = matrix["episode_step_spend_accounting"]
    ep_a = acct["episodes"]
    st_a = acct["steps"]
    vs_a = acct["verda_spend"]
    km = matrix["cross_artifact_reconciliation"]["key_mechanistic_numbers"]
    nl = matrix["non_llm_structured_contrast"]

    lines: list[str] = [
        f"{h1} Open-Weight Qwen2.5-1.5B Failure Taxonomy Matrix (19 Historical Runs, v1.4)",
        "",
        f"Deterministic cross-artifact audit and root-cause synthesis cross-tabulating all `{ht['historical_open_weight_runs']}` historical open-weight `Qwen2.5-1.5B-Instruct` runs in `results/tiebreak/experiment_ledger.json` against `results/tiebreak/forensics_prior_runs.json`, `results/tiebreak/verda_multiseed/multiseed_summary.json`, `results/tiebreak/context_confound/audit_summary.json`, and `results/tiebreak/dagger_mechanism/dagger_mechanism_summary.json` (`0` API calls).",
        "",
        f"- **Honest Open-Weight Outcome (`0 / 19 > 0.000`)**: Across all `19` historical FR8 V100 and Verda A100/H100 open-weight runs, **`0 / 19` beat untrained base `0.000`** (`0 / 19` `VERIFIED_IMPROVEMENT`; highest trained held-out mean is `WS4-v3-8k-s2-dbd0` at `-0.050 +/- 0.049`, lowest is `WS4-v3-8k-s3-f437` at `-0.788 +/- 0.117`). Per `README.md` and `docs/agents/PANEL-0500.md` (`Fix E`), the `README.md` open-weight Qwen addendum remains withheld.",
        f"- **Panel Fix A Disclosure (Seed & World-Secret Provenance)**: All tiebreaker training strictly uses `TRAIN_SEEDS [100000, 200000)` and all held-out tiebreaker evaluations use disjoint `HELDOUT_SEEDS [800000, 800200)` with `0` `JUDGE_SEEDS` (`900000+`) touched. Where `DEV_SEEDS 0..29` appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**. Pre-04:05 EET evaluations ran without `CANARY_WORLD_SECRET` (`os.urandom(32)` per process, reported strictly two-sample), whereas post-04:05 EET Verda evaluations share `1ca0c2a64d` (`60/60` and `61/61` step-0 roster identity verified).",
        f"- **Panel Fix E Disclosure (Strict Track Separation)**: Non-LLM structured and compact neural policies (`CompactLinearDAggerPolicy` `+{nl['compact_linear_dagger']['after_mean_score']:.4f}`, `TinyMLPPolicy` `+{nl['tiny_mlp_dagger']['after_mean_score']:.4f}`, `EmpiricalBayesPolicy` `+{nl['empirical_bayes']['after_mean_score']:.4f}`; `is_open_weight_llm = False`) operate on lossless public-ledger sufficient statistics under shared world secret `{nl['shared_world_secret_tag']}` and are never conflated with open-weight `Qwen2.5-1.5B` LoRA runs.",
        "",
        f"{h2} 1. Mutually Exclusive Root-Cause Bucket Partition (`19 / 19` Open-Weight Runs)",
        "",
        "| Bucket ID | Root-Cause Bucket | Runs | Held-Out Eps (Raw / Unique) | Unique Train Steps | Score Span | `> 0.000` | Primary Mechanistic Bottleneck |",
        "|---|---|---:|---:|---:|---|---:|---|",
    ]

    for b in matrix["buckets"]:
        if b["min_mean_score"] is None:
            sc_span = "`n/a (n=0)`"
        elif _approx_eq(b["min_mean_score"], b["max_mean_score"], 1e-6):
            v_sc = float(b["min_mean_score"])
            sc_span = "`0.000`" if abs(v_sc) < 1e-9 else f"`{v_sc:+.3f}`"
        else:
            sc_span = f"`{float(b['min_mean_score']):+.3f} .. {float(b['max_mean_score']):+.3f}`"
        lines.append(
            f"| `{b['bucket_id']}` | {b['short_label']} | {b['run_count']} | "
            f"`{b['raw_heldout_episodes']} / {b['dedup_unique_heldout_episodes']}` | "
            f"{b['unique_optimizer_steps']} | {sc_span} | `0/{b['run_count']}` | {b['primary_bottleneck']} |"
        )

    lines.append(
        f"| **Total (MECE)** | **All 9 Root-Cause Buckets** | **{ht['historical_open_weight_runs']}** | "
        f"**`{ep_a['raw_ledger_heldout_episodes_sum']} / {ep_a['deduplicated_unique_heldout_episodes']}`** | "
        f"**{st_a['total_unique_ledger_optimizer_steps']}** | **`-0.788 .. 0.000`** | **`0/19`** | "
        "Raw transcript eviction (`2,842/4,096` header), off-policy GRPO state shift, `4k->8k` shift, `cap=96` JSON truncation, and uncalibrated stopping |"
    )

    lines.extend(
        [
            "",
            f"{h2} 2. Complete 19-Run Cross-Tabulation Across All 5 Backing Artifacts",
            "",
            f"| {H} | Run ID | Bucket | Status | Ctx | Unique / Adapter Steps | Held-Out `n` (`seed_span`) | Score +/- 95% CI | Valid | Acc / Abst | Secret Provenance | Backing Artifacts |",
            "|---:|---|---|---|---:|---|---:|---|---:|---|---|---|",
        ]
    )

    for r in matrix["runs"]:
        span_lbl = str(r["seed_span"]) if r["seed_span"] is not None else "none"
        score_cell = _fmt_score_ci(r["mean_score"], r["ci95"], int(r["heldout_n"]), r["bucket_id"])
        acc_abst = (
            "n/a"
            if int(r["heldout_n"]) == 0
            else f"`{_fmt_rate(r['accused_rate'])} / {_fmt_rate(r['abstain_rate'])}`"
        )
        b_short = ", ".join(Path(p).name for p in r["backing_artifacts"])
        lines.append(
            f"| {r['order']} | `{r['run_id']}` | `{r['bucket_id']}` | `{r['status']}` | {r['context_len']} | "
            f"`{r['unique_optimizer_steps']} / {r['adapter_optimizer_steps']}` | "
            f"`{r['heldout_n']}` (`{span_lbl}`) | `{score_cell}` | `{_fmt_rate(r['valid_call_rate'])}` | "
            f"{acc_abst} | `{r['secret_provenance']}` | `{b_short}` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 3. Exact Episode, Optimizer-Step, and `{EUR}104.46` Verda Spend Accounting",
            "",
            f"{h3} 3.1 Held-Out Episode and Training-Rollout Reconciliation",
            "",
            f"- **Ledger Held-Out Episodes (`1,039` raw / `1,023` deduplicated unique / `987` trained)**: `5` `n=0` failures (`0` episodes), `2` untrained base rows (`WS4-base-44411` `n=16` + `WS4-base-pooled` `n=36` = `52` raw, `36` unique after deduplicating `44411` inside `WS4-base-pooled` = `16 + 20`), and `12` trained LoRA evaluation rows totaling **`987` episodes** (`12` `v1.3` in `J4-v1-44397` + `975` `v1.4` across `v2` `172`, `4k` GRPO `262`, `4k@8k` `90`, `8k` GRPO `360`, and X2 `DAgger r1` `91`).",
            f"- **Cross-Artifact Replay Subsets**: `verda_multiseed/multiseed_summary.json` belief-replays **`{ep_a['verda_multiseed_belief_replayed_episodes']}`** episodes (`180 + 82 + 90*5`, **`{ep_a['verda_multiseed_replay_invariant_errors']}`** invariant errors); `context_confound/audit_summary.json` audits **`{ep_a['context_confound_verda_audited_episodes']}`** raw vs compact Verda episodes (`{km['verda_450_plant_canary_evicted_4k_pct']:.2f}%` `4k` and `{km['verda_450_plant_canary_evicted_8k_pct']:.2f}%` `8k` `plant_canary_ok` eviction vs `0.0%` compact eviction); `dagger_mechanism/dagger_mechanism_summary.json` audits **`{ep_a['dagger_mechanism_train_audit_episodes']}`** `TRAIN_SEEDS` episodes (`108000..108044`, `0` held-out/dev/judge episodes touched) alongside X2 DAgger r1's **`{ep_a['dagger_r1_vllm_train_rollout_episodes']}`** vLLM rollouts (`{ep_a['dagger_r1_relabelled_states']}` relabelled states, `2,603/2,603` solver match).",
            "- **Unpulled / Preempted Episode Losses Logged Without Omission**: `~90` planned episodes on spot-preempted `714d8144`, `90` planned backup base episodes on reaper-deleted `18acfa5d`, `~40` remaining `8k` DAgger episodes on reaper-deleted `e9ea8b2e`, `~49` remaining `4k` DAgger episodes on reaper-deleted `68bbe201`, plus `0` scored episodes from J1 `Qwen3-14B` vLLM on reaper-deleted `924e81d8`.",
            "",
            f"{h3} 3.2 Optimizer-Step Reconciliation (`4,439` Unique Steps)",
            "",
            f"- **SFT + DAgger SFT (`{st_a['unique_sft_and_dagger_steps']}` unique steps, `{st_a['sft_and_dagger_tokens_processed']:,}` tokens)**: `450` steps (`J4-v1-44397`, `14,313,726` tokens) + `887` steps (`WS4-v2` job `44410`, `26,686,128` tokens) + `250` steps (`WS4-dagger-r1` on `e9ea8b2e`, `25,709,119` tokens on `4,000` states). Three evaluation rows (`WS4-v2-off30-68bb`, `WS4-v3-4k-s0-ctx8k`, `WS4-dagger-r1-4k-verda`) reuse an already-counted checkpoint (`0` additional optimizer steps).",
            f"- **Decision-Point GRPO (`{st_a['completed_grpo_steps_6_seeds']}` completed steps + `{st_a['aborted_zerovar_grpo_steps_44553']}` zero-variance steps = `2,852` ledger GRPO steps)**: `609` (`v3-4k-s0`) + `192` (`v3-4k-s1`) + `637` (`v3-8k-s0`) + `371` (`v3-8k-s1`) + `693` (`v3-8k-s2`) + `344` (`v3-8k-s3`) = **`2,846`** completed curve steps (exact match to `multiseed_summary.json`), plus `6` logged steps in `WS4-v3-44553` (and `{st_a['precursor_cancelled_v100_44555_steps']}` precursor V100 steps in `run-44555`).",
            "",
            f"{h3} 3.3 Verda Cloud Spend Accounting (`{EUR}{vs_a['measured_spend_eur']:.2f}` Across `{vs_a['deleted_instances_count']}` Deleted Instances)",
            "",
            f"Account balance moved from **`{EUR}{vs_a['start_balance_eur']:.2f}` -> `{EUR}{vs_a['end_balance_eur']:.2f}`** = **`{EUR}{vs_a['measured_spend_eur']:.2f}` measured Verda spend** across **`{vs_a['deleted_instances_count']}` deleted instances** (`2` `H100-80GB`, `6` `A100-80GB`, `1` `A100-40GB`; `{vs_a['instance_table_max_gpu_hours_sum']:.2f}` max GPU-h, `{EUR}{vs_a['instance_table_max_cost_eur_sum']:.2f}` sum of per-instance caps vs `{EUR}{vs_a['measured_spend_eur']:.2f}` exact balance delta; FR8 Slurm V100 runs incurred `{EUR}0.00` Verda spend):",
            "",
            f"| Instance ID | GPU & Mode | `{EUR}/h` | Max GPU-h | Max `{EUR}` | Termination | Hosted Workloads |",
            "|---|---|---:|---:|---:|---|---|",
        ]
    )

    for inst in vs_a["instances"]:
        wl = ", ".join(inst["workloads"])
        lines.append(
            f"| `{inst['instance_id']}` | {inst['gpu_spec']} | `{inst['eur_per_hour']:.4f}` | "
            f"`{inst['max_gpu_hours']:.2f}` | `{inst['max_cost_eur']:.2f}` | {inst['termination']} | {wl} |"
        )
    lines.append(
        f"| **Total (`9` deleted)** | **`2` H100 + `7` A100** | n/a | **`{vs_a['instance_table_max_gpu_hours_sum']:.2f}`** | "
        f"**`{vs_a['instance_table_max_cost_eur_sum']:.2f}` (measured `{EUR}{vs_a['measured_spend_eur']:.2f}`)** | "
        "`5` reaper, `3` manual, `1` spot preempted | Tiebreaker `~72.7`, X2 DAgger `<=16.1`, J1 `~7.2`, X1 `<=5.8`, Meta `2.1` |"
    )

    lines.extend(
        [
            "",
            f"{h2} 4. Cross-Artifact Mechanistic Chain: Why Open-Weight Raw-Context Runs Failed While Structured Policies Succeeded",
            "",
            f"1. **Raw Prompt Header Crowding & Sliding-Window Eviction (`{km['raw_4k_header_tokens_44410']}/{4096}` = `69.4%`)**: Tool schemas and system prompt leave `{km['raw_4k_body_budget_tokens_44410']}` body tokens at `4k`, evicting `{km['verda_450_plant_canary_evicted_4k_pct']:.2f}%` (`4k`) and `{km['verda_450_plant_canary_evicted_8k_pct']:.2f}%` (`8k`) of planted canary maps across the `450` audited Verda episodes before `1-3`d (`medium`) and `2-3`d (`hard`) leaks surface, driving `{km['pooled_v2_below_breakeven_ratio']}` (`95.7%`) below-breakeven accusations in `v2`.",
            f"2. **Off-Policy GRPO Evidence Shift & Inference-Length Confound**: Decision-point GRPO learned culprit reading on clean solver pre-commit states (`0.19 -> 0.892` on `v3-4k-s0`) but planted only `3.53` canaries/ep autonomously (`{km['v3_4k_s0_heldout_precision_ratio']}` precision). Raising inference context to `8k` on the identical `3d0cd43b8037` weights (`WS4-v3-4k-s0-ctx8k`) shifted score by `{km['same_weights_4k_to_8k_two_sample_delta']:+.3f}` (`-0.716 +/- 0.105`, `70/70` below breakeven). Across `8k` GRPO seeds, `~350`-step A100 runs stayed in the over-accuse regime (`{km['low_step_8k_below_breakeven_ratio']}` below breakeven; paired `s3 - 4k@8k = {km['paired_8k_s3_minus_4k_at_8k_delta']:+.3f} +/- 0.173`), while `~650`-step H100 runs suppressed accusations globally (`paired s0 - s3 = +{km['paired_8k_s0_minus_s3_delta']:.3f} +/- 0.134`) at the cost of `{km['high_step_8k_missed_commits_ratio']}` missed positive-EV commits.",
            f"3. **Action-Serialization `cap=96` Truncation & Implicit Stopping Dilution in Raw DAgger r1**: Each assigned employee in Qwen2.5 `<tool_call>` JSON costs `8` BPE tokens, truncating `{km['hard_dagger_cap96_truncation_ratio']}` (`73.9%`) of `hard` DAgger `plant_canary` relabels under `max_new_tokens=96`. Even with `max_new_tokens=256`, `{km['train_below_breakeven_daily_states_ratio']}` (`77.6%`) of daily states on `TRAIN_SEEDS 108000..108044` lie below breakeven `1/(1+V_known)`, and `{km['dagger_r1_accuse_sft_labels_ratio']}` (`3.98%`) implicit next-token `accuse` labels failed to override `8k` premature commitment (`92%` accused, `-0.542 +/- 0.214` despite `43% -> 68%` own-state agreement and `0.10 -> 0.22` whom-precision). Replacing raw transcripts and JSON action strings with lossless compact sufficient statistics + explicit EV-calibrated breakeven stopping yields verified gains on the strictly separated non-LLM track (`CompactLinearDAggerPolicy` `+{nl['compact_linear_dagger']['after_mean_score']:.4f}`, `TinyMLPPolicy` `+{nl['tiny_mlp_dagger']['after_mean_score']:.4f}`, `EmpiricalBayesPolicy` `+{nl['empirical_bayes']['after_mean_score']:.4f}`).",
            "",
            f"{h2} 5. Offline Verification Commands",
            "",
            "```bash",
            "python scripts/tiebreak_failure_taxonomy_matrix.py --check",
            "python -m pytest -q tests/test_tiebreak_failure_taxonomy.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def check_python_source_hygiene(py_path: Path) -> list[str]:
    errs: list[str] = []
    if not py_path.is_file():
        return [f"missing python file: {py_path}"]
    src = py_path.read_text(encoding="utf-8")
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    if any(t.type == tokenize.COMMENT for t in toks) or H in src:
        errs.append(f"{py_path.name}: contains Python comment or hash character")
    for bad_ch, ch_name in (
        (EM_DASH, "em dash"),
        (EN_DASH, "en dash"),
        (UNICODE_MINUS, "unicode minus"),
    ):
        if bad_ch in src:
            errs.append(f"{py_path.name}: contains forbidden {ch_name}")
    return errs


def verify_committed_artifacts(
    json_path: Path,
    md_path: Path,
    repo_root: Path = ROOT,
) -> list[str]:
    errors: list[str] = []
    if not json_path.is_file():
        return [f"missing taxonomy JSON: {json_path}"]
    if not md_path.is_file():
        return [f"missing taxonomy markdown report: {md_path}"]

    tax_dir = json_path.parent
    for forbidden_sibling in ("summary.json", "table.md"):
        if (tax_dir / forbidden_sibling).exists():
            errors.append(f"forbidden file present in {tax_dir}: {forbidden_sibling}")

    size_bytes = json_path.stat().st_size
    if size_bytes >= MAX_JSON_BYTES:
        errors.append(f"{json_path.name}: size {size_bytes} bytes >= {MAX_JSON_BYTES} bytes limit")

    raw_json = json_path.read_text(encoding="utf-8")
    md_txt = md_path.read_text(encoding="utf-8")
    for bad_ch, ch_name in (
        (EM_DASH, "em dash"),
        (EN_DASH, "en dash"),
        (UNICODE_MINUS, "unicode minus"),
    ):
        if bad_ch in raw_json:
            errors.append(f"{json_path.name}: contains forbidden {ch_name}")
        if bad_ch in md_txt:
            errors.append(f"{md_path.name}: contains forbidden {ch_name}")

    script_py = repo_root / "scripts" / "tiebreak_failure_taxonomy_matrix.py"
    if script_py.is_file():
        errors.extend(check_python_source_hygiene(script_py))
    test_py = repo_root / "tests" / "test_tiebreak_failure_taxonomy.py"
    if test_py.is_file():
        errors.extend(check_python_source_hygiene(test_py))

    try:
        committed_matrix = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return [*errors, f"{json_path.name}: invalid JSON ({exc})"]

    try:
        expected_matrix = build_taxonomy_matrix(repo_root=repo_root)
    except Exception as exc:
        return [*errors, f"cross-artifact synthesis failed: {exc}"]

    if committed_matrix != expected_matrix:
        errors.append(f"{json_path.name}: out of sync with live cross-artifact synthesis")

    expected_md = render_markdown_report(expected_matrix)
    if md_txt != expected_md:
        errors.append(f"{md_path.name}: out of sync with render_markdown_report(matrix)")

    required_tokens = (
        "0 / 19",
        f"{EUR}104.46",
        "post-hoc locked, not pre-registered",
        "is_open_weight_llm = False",
        "infra_oom_zerovar_spot_reaper_n0",
        "untrained_base_protocol_stall",
        "dense_4k_sft_blind_accuse",
        "grpo_4k_offpolicy_evidence_shift",
        "same_weights_8k_inference_confound",
        "grpo_8k_high_step_abstention_collapse",
        "grpo_8k_low_step_over_accuse",
        "verda_x2_dagger_r1_honest_null",
    )
    for tok in required_tokens:
        if tok not in md_txt:
            errors.append(f"{md_path.name}: missing required claim token {tok!r}")

    return errors


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Deterministic cross-artifact failure taxonomy matrix for all 19 open-weight Qwen2.5-1.5B runs."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = args.root.resolve()
    out_json = args.out_json if args.out_json.is_absolute() else (root / args.out_json)
    out_md = args.out_md if args.out_md.is_absolute() else (root / args.out_md)

    if args.check:
        t0 = time.perf_counter()
        errs = verify_committed_artifacts(out_json, out_md, repo_root=root)
        elapsed = time.perf_counter() - t0
        if elapsed > MAX_CHECK_SECONDS:
            errs.append(f"--check runtime {elapsed:.4f}s exceeded {MAX_CHECK_SECONDS:.2f}s limit")
        if args.json:
            print(
                json.dumps(
                    {
                        "passed": len(errs) == 0,
                        "elapsed_seconds": round(elapsed, 4),
                        "errors": errs,
                    },
                    indent=2,
                )
            )
            return 0 if not errs else 1
        if errs:
            for err in errs:
                print(f"FAIL: {err}", file=sys.stderr)
            return 1
        print(
            f"OK: verified {out_json.relative_to(root)} and {out_md.relative_to(root)} in {elapsed:.4f}s"
        )
        return 0

    t0 = time.perf_counter()
    matrix = build_taxonomy_matrix(repo_root=root)
    md_text = render_markdown_report(matrix)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")

    errs = verify_committed_artifacts(out_json, out_md, repo_root=root)
    elapsed = time.perf_counter() - t0
    if errs:
        for err in errs:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(matrix, indent=2))
    else:
        print(
            f"Wrote {out_json.relative_to(root)} ({out_json.stat().st_size} bytes) and "
            f"{out_md.relative_to(root)} in {elapsed:.4f}s (19/19 runs across 9 buckets, 0 errors)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
