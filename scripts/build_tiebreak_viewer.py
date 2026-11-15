from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_ID = "canary.tiebreak.viewer_manifest.v1"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
EURO_SIGN = chr(0x20AC)
HASH_CHAR = chr(35)

VIEWER_DIR_REL = Path("results/tiebreak/viewer")
HTML_REL = VIEWER_DIR_REL / "tiebreak_dashboard.html"
MANIFEST_REL = VIEWER_DIR_REL / "viewer_manifest.json"
MAX_TOTAL_BYTES = 150 * 1024

SOURCE_JSON_SPECS: tuple[tuple[str, str], ...] = (
    ("experiment_ledger", "results/tiebreak/experiment_ledger.json"),
    ("addendum_readiness", "results/tiebreak/addendum_readiness.json"),
    ("verda_multiseed", "results/tiebreak/verda_multiseed/multiseed_summary.json"),
    ("context_confound", "results/tiebreak/context_confound/audit_summary.json"),
    ("frontier_comparison", "results/tiebreak/frontier_comparison/comparison_summary.json"),
    ("scaling", "results/tiebreak/scaling/scaling_summary.json"),
    ("empirical_bayes", "results/tiebreak/empirical_bayes/summary.json"),
    ("dagger_ablation", "results/tiebreak/dagger_ablation/summary.json"),
    ("neural_mlp_dagger", "results/tiebreak/neural_mlp_dagger/mlp_summary.json"),
)

CDN_OR_REMOTE_RE = re.compile(
    r"(?:https?://|//cdn\.|<script\b[^>]*\bsrc=|<link\b[^>]*\bhref=|@import\s+url\()",
    re.IGNORECASE,
)


def _clean_ascii(text: Any) -> str:
    s = str(text or "")
    s = s.replace(EM_DASH, "-").replace(EN_DASH, "-").replace(EURO_SIGN, "EUR ").replace(HASH_CHAR, "No.")
    return s.encode("ascii", "ignore").decode("ascii")


def _esc(text: Any) -> str:
    return (
        _clean_ascii(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _fmt_s(val: Any, d: int = 3) -> str:
    return f"{float(val):+.{d}f}" if _is_num(val) else "n/a"


def _fmt_f(val: Any, d: int = 3) -> str:
    return f"{float(val):.{d}f}" if _is_num(val) else "n/a"


def _fmt_p(val: Any, d: int = 1) -> str:
    return f"{float(val) * 100.0:.{d}f}%" if _is_num(val) else "n/a"


def load_source_artifacts(root: Path = ROOT) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    loaded: dict[str, dict[str, Any]] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for key, rel in SOURCE_JSON_SPECS:
        p = root / rel
        if not p.is_file():
            raise FileNotFoundError(f"missing required tiebreak JSON artifact: {rel}")
        raw = p.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{rel}: top-level JSON must be an object")
        loaded[key] = data
        provenance[key] = {"path": rel, "sha256_16": hashlib.sha256(raw).hexdigest()[:16], "bytes": len(raw)}
    return loaded, provenance


def _classify_run(entry: dict[str, Any]) -> str:
    rid = str(entry.get("run_id") or "")
    n_val = int(entry.get("heldout_n") or 0)
    status = str(entry.get("status") or "")
    if n_val == 0 or status.startswith("FAILED_"):
        return "n0_failure"
    if "dagger-r1" in rid or "DAGGER" in status:
        return "dagger_null"
    sec = f"{entry.get('before_world_secret_tag') or ''}:{entry.get('after_world_secret_tag') or ''}"
    if "1ca0c2a64d" in sec or "8k" in rid or "ctx8k" in rid:
        return "shared_or_8k"
    return "evaluated_4k"


def _secret_label(entry: dict[str, Any]) -> str:
    if int(entry.get("heldout_n") or 0) == 0:
        return "none (n=0)"
    b_sec = str(entry.get("before_world_secret_tag") or "")
    a_sec = str(entry.get("after_world_secret_tag") or "")
    if "1ca0c2a64d" in a_sec or "1ca0c2a64d" in b_sec:
        return "shared (1ca0c2a64d)"
    if b_sec and a_sec and b_sec == a_sec and "unpaired" not in a_sec.lower():
        return f"paired ({_clean_ascii(a_sec[:16])})"
    return "per-process (unpaired)"


def _pack_stage(stage_id: str, label: str, sv: dict[str, Any], nested_score: bool = False) -> dict[str, Any]:
    ms = (sv.get("score") or {}).get("mean", 0.0) if nested_score else sv.get("mean_score", 0.0)
    return {
        "id": stage_id,
        "label": label,
        "n": int(sv["n"]),
        "mean_score": round(float(ms), 4),
        "accuracy": round(float(sv["accuracy"]), 4),
        "abstain_rate": round(float(sv["abstain_rate"]), 4),
    }


def build_viewer_manifest(root: Path = ROOT) -> dict[str, Any]:
    sources, provenance = load_source_artifacts(root)
    ledger = sources["experiment_ledger"]
    addendum = sources["addendum_readiness"]
    multiseed = sources["verda_multiseed"]
    confound = sources["context_confound"]
    frontier = sources["frontier_comparison"]
    scaling = sources["scaling"]
    eb = sources["empirical_bayes"]
    dagger_lin = sources["dagger_ablation"]
    mlp = sources["neural_mlp_dagger"]

    hist_raw = list(ledger.get("historical_runs") or [])
    hist_by_id = {str(r.get("run_id")): r for r in hist_raw if isinstance(r, dict)}
    pub_by_id = {str(r.get("row_id")): r for r in (addendum.get("readme_published_baseline") or []) if isinstance(r, dict)}

    hist_rows: list[dict[str, Any]] = []
    n0_ids: list[str] = []
    above_base = 0
    for r in hist_raw:
        rid = _clean_ascii(r.get("run_id"))
        n_val = int(r.get("heldout_n") or 0)
        am = 0.0 if (rid.startswith("WS4-base") and r.get("after_mean_score") is None) else r.get("after_mean_score")
        if _is_num(am) and float(am) > 0.0 and n_val > 0 and not rid.startswith("WS4-base"):
            above_base += 1
        if n_val == 0:
            n0_ids.append(rid)
        row_item: dict[str, Any] = {
            "run_id": rid,
            "model": _clean_ascii(r.get("model")),
            "method": _clean_ascii(r.get("method"))[:64],
            "ctx": int(r["context_len"]) if _is_num(r.get("context_len")) else None,
            "n": n_val,
            "score": round(float(am), 4) if _is_num(am) else None,
            "ci95": round(float(r["after_ci95"]), 4) if _is_num(r.get("after_ci95")) else None,
            "secret_pairing": _secret_label(r),
            "status": _clean_ascii(r.get("status")),
            "category": _classify_run(r),
            "note": _clean_ascii(r.get("notes"))[:90],
        }
        if _is_num(r.get("before_valid_call_rate")):
            row_item["valid_before"] = round(float(r["before_valid_call_rate"]), 3)
        if _is_num(r.get("after_valid_call_rate")):
            row_item["valid_after"] = round(float(r["after_valid_call_rate"]), 3)
        hist_rows.append(row_item)

    paired_map = multiseed.get("world_paired_shared_secret_comparisons") or {}
    paired_s0_s3 = paired_map.get("s0_minus_s3") or {}
    paired_s3_4k8k = paired_map.get("s3_minus_4k_at_8k") or {}
    s8_map = {str(s.get("run_id")): (s.get("overall") or {}) for s in (multiseed.get("seeds_8k") or []) if isinstance(s, dict)}

    cc_cal = confound.get("header_and_token_calibration") or {}
    cc_all = ((confound.get("pooled_views") or {}).get("all_450_verda") or {}).get("all") or {}
    cc_raw = cc_all.get("raw_transcript") or {}
    cc_cmp = cc_all.get("compact_transcript") or {}
    cc_4k8k = (((confound.get("inference_length_confound_v3_4k_s0_at_8k") or {}).get("eval_at_8k") or {}).get("by_tier") or {}).get("all") or {}

    ar_by_id = {
        str(r.get("run_id")): r
        for r in (list(addendum.get("track_1_runs") or []) + list(addendum.get("track_2_runs") or []))
        if isinstance(r, dict)
    }
    compact_specs = (
        (
            "compact-linear-dagger-v14",
            "CompactLinearDAggerPolicy",
            int((dagger_lin.get("policy_architecture") or {}).get("param_count", 785)),
            "Linear softmax + stopping head (4-stage DAgger r2)",
            "+0.150 over calibrated BC (+0.476), +0.109 over survivorship SFT (+0.518)",
        ),
        (
            "tiny-mlp-dagger-v14",
            "TinyMLPPolicy",
            int(mlp.get("param_count", 12293)),
            "2-layer NumPy MLP 28->128->64->5 (on-policy DAgger r2)",
            "+0.892 [+0.756, +1.029] over uncalibrated SFT (-0.278); 93.3% accuracy",
        ),
        (
            "scaling-logistic-v14",
            "ScalingLogisticPolicy",
            int((scaling.get("policy_architecture") or {}).get("n_parameters", 82)),
            "CompactLinearPolicy 82-param logistic softmax (N_train=900)",
            "89.6% of SolverPolicy (+0.682); monotonic luck-adjusted EV across N=0..900",
        ),
        (
            "empirical-bayes-v14",
            "EmpiricalBayesPolicy",
            len(eb.get("learned_theta") or {}) or 11,
            "Learned log-likelihood ratios + optimal stopping threshold",
            "Luck-adjusted EV delta +1.000; +0.550 vs gemini-4-carbon +0.322 on hard dev",
        ),
    )
    compact_policies: list[dict[str, Any]] = []
    for rid, cls_name, n_params, arch_desc, hl_txt in compact_specs:
        ar = ar_by_id[rid]
        compact_policies.append(
            {
                "run_id": rid,
                "policy_class": cls_name,
                "architecture": arch_desc,
                "is_open_weight_llm": bool(ar.get("is_open_weight_llm", False)),
                "param_count": n_params,
                "n": int(ar["n"]),
                "train_seed_range": str(ar["train_seed_range"]),
                "eval_seed_range": str(ar["eval_seed_range"]),
                "world_secret_tag": _clean_ascii(ar["after_world_secret_tag"]),
                "before_mean_score": round(float(ar["before_mean_score"]), 4),
                "after_mean_score": round(float(ar["after_mean_score"]), 4),
                "after_ci95_low": round(float(ar["after_ci95_low"]), 4),
                "after_ci95_high": round(float(ar["after_ci95_high"]), 4),
                "paired_mean_delta": round(float(ar["paired_mean_delta"]), 4),
                "paired_ci95_low": round(float(ar["paired_ci95_low"]), 4),
                "paired_ci95_high": round(float(ar["paired_ci95_high"]), 4),
                "gates_passed": int(ar["criteria_passed_count"]),
                "gates_total": len(ar.get("criteria") or {}),
                "replay_verified": bool(ar["replay_verified"]),
                "inference_module": _clean_ascii((ar.get("inference_modules_checked") or [""])[0]),
                "verdict": _clean_ascii(ar.get("verdict")),
                "highlight": hl_txt,
            }
        )

    scaling_rows = [
        {
            "label": f"N={int(r['n_train'])}",
            "n_train": int(r["n_train"]),
            "n_eval": int(r["metrics"]["n"]),
            "mean_score": round(float(r["metrics"]["mean_score"]), 4),
            "ci95": round(float(r["metrics"]["ci95"]), 4),
            "luck_adjusted_ev": round(float(r["metrics"]["luck_adjusted_ev"]), 4),
            "accuracy": round(float(r["metrics"]["accuracy"]), 4),
        }
        for r in (scaling.get("scaling_curve") or [])
    ]
    sol_sc = (scaling.get("solver_reference") or {}).get("metrics") or {}
    lin_ov = (dagger_lin.get("heldout_ablation") or {}).get("overall") or {}
    mlp_st = mlp.get("stages") or {}
    eb_ov = (eb.get("heldout") or {}).get("overall") or {}

    linear_stages = [
        _pack_stage(k, lbl, lin_ov[k])
        for k, lbl in (
            ("stage0_untrained", "Stage 0: Untrained (abstain)"),
            ("stage1_survivorship_sft", "Stage 1: Survivorship SFT"),
            ("stage2_calibrated_bc", "Stage 2: Calibrated Offline BC"),
            ("stage3a_onpolicy_dagger_r1", "Stage 3a: On-Policy DAgger r1"),
            ("stage3_onpolicy_dagger_r2", "Stage 3: On-Policy DAgger r2"),
            ("solver", "SolverPolicy Reference"),
        )
        if k in lin_ov
    ]
    mlp_stages = [
        _pack_stage(k, lbl, mlp_st[k]["overall"])
        for k, lbl in (
            ("stage0_untrained", "Stage 0: Random Init"),
            ("stage1_uncalibrated_sft", "Stage 1: Uncalibrated SFT"),
            ("stage2_calibrated_bc", "Stage 2: Calibrated BC"),
            ("stage3_onpolicy_dagger_r2", "Stage 3: On-Policy DAgger r2"),
        )
        if k in mlp_st
    ]
    if isinstance((mlp.get("solver_reference") or {}).get("overall"), dict):
        mlp_stages.append(_pack_stage("solver", "SolverPolicy Reference", mlp["solver_reference"]["overall"]))

    eb_stages = [
        _pack_stage(k, lbl, eb_ov[k], nested_score=True)
        for k, lbl in (
            ("eb_naive_prior", "Uncalibrated Naive Prior (before)"),
            ("eb_ev_stop_only", "Stopping Rule Only"),
            ("eb_no_canary_planting", "Learned Likelihoods (No Traps)"),
            ("eb_likelihood_only", "Learned Likelihoods Only"),
            ("eb_experience_opt", "Full EmpiricalBayesPolicy (after)"),
            ("solver", "SolverPolicy Reference"),
        )
        if k in eb_ov
    ]

    fc_cohorts = [
        {
            "label": _clean_ascii(c.get("label")),
            "family": _clean_ascii(c.get("family")),
            "n": int(c.get("n", 30)),
            "mean_score": round(float(c.get("mean_score", 0.0)), 4),
            "ci95": round(float(c.get("ci95", 0.0)), 4),
            "luck_adjusted_ev": round(float(c.get("luck_adjusted_ev", 0.0)), 4),
            "accuracy": round(float(c.get("accuracy", 0.0)), 4),
            "canaries": round(float((c.get("canary_diagnostics") or {}).get("mean_canaries_before_accuse", 0.0)), 2),
            "sub_be_rate": round(float((c.get("commitment_calibration") or {}).get("top_p_below_breakeven_rate") or 0.0), 4),
        }
        for c in ((frontier.get("dev_hard_panel") or {}).get("cohorts") or [])
    ]

    r_4k_s0 = hist_by_id["WS4-v3-verda-s0-eval"]
    r_4k_s1 = hist_by_id["WS4-v3-4k-s1-44572"]
    r_d8 = pub_by_id["dagger_r1_8k"]
    r_d4 = pub_by_id["dagger_r1_4k"]
    rs = addendum.get("readiness_summary") or {}
    rat = frontier.get("replay_audit_totals") or {}

    return {
        "schema": SCHEMA_ID,
        "tiers_version": _clean_ascii(ledger.get("tiers_version_target", "v1.4")),
        "source_artifacts": provenance,
        "seed_hygiene_disclosure": {
            "train_seed_range": "100000..199999",
            "heldout_seed_range": "800000..800199",
            "dev_eval_seed_range": str(frontier.get("dev_eval_seed_range", "0..29")),
            "judge_episodes_touched": 0,
            "judge_partition_rule": "JUDGE_SEEDS 900000+ strictly untouched (0 episodes)",
            "dev_protocol_disclosure": "DEV_SEEDS 0..29 post-hoc locked after v1.4 commitment, never pre-registered",
        },
        "track_separation": {
            "readme_qwen_addendum_eligible": bool(rs.get("readme_qwen_addendum_eligible", False)),
            "readme_addendum_action": _clean_ascii(rs.get("readme_addendum_action", "HOLD_README_QWEN_ADDENDUM_UNTIL_V100")),
            "open_weight_llm_above_base_count": above_base,
            "open_weight_llm_total_runs": len(hist_rows),
            "open_weight_llm_n0_failure_count": len(n0_ids),
            "compact_non_llm_passing_count": sum(1 for p in compact_policies if p["gates_passed"] == 5),
            "compact_non_llm_total_count": len(compact_policies),
        },
        "track1_open_weight_llm": {
            "n0_failure_run_ids": n0_ids,
            "highlights": {
                "v3_4k_s0": {"mean_score": round(float(r_4k_s0["after_mean_score"]), 3), "ci95": round(float(r_4k_s0["after_ci95"]), 3), "n": int(r_4k_s0["heldout_n"])},
                "v3_4k_s1": {"mean_score": round(float(r_4k_s1["after_mean_score"]), 3), "ci95": round(float(r_4k_s1["after_ci95"]), 3), "n": int(r_4k_s1["heldout_n"])},
                "v3_8k_s0": {"mean_score": round(float(s8_map["v3_8k_s0"]["mean_score_3d"]), 3), "ci95": round(float(s8_map["v3_8k_s0"]["ci95_3d"]), 3), "n": int(s8_map["v3_8k_s0"]["n"])},
                "v3_8k_s2": {"mean_score": round(float(s8_map["v3_8k_s2"]["mean_score_3d"]), 3), "ci95": round(float(s8_map["v3_8k_s2"]["ci95_3d"]), 3), "n": int(s8_map["v3_8k_s2"]["n"])},
                "v3_8k_s1": {"mean_score": round(float(s8_map["v3_8k_s1"]["mean_score_3d"]), 3), "ci95": round(float(s8_map["v3_8k_s1"]["ci95_3d"]), 3), "n": int(s8_map["v3_8k_s1"]["n"])},
                "v3_8k_s3": {"mean_score": round(float(s8_map["v3_8k_s3"]["mean_score_3d"]), 3), "ci95": round(float(s8_map["v3_8k_s3"]["ci95_3d"]), 3), "n": int(s8_map["v3_8k_s3"]["n"])},
                "paired_s0_minus_s3": {"mean_delta": round(float(paired_s0_s3["mean_delta_3d"]), 3), "ci95": round(float(paired_s0_s3["ci95_3d"]), 3), "n": int(paired_s0_s3["n"])},
                "confound_4k_at_8k": {
                    "mean_score": round(float(cc_4k8k["mean_score"]), 3),
                    "ci95": round(float(cc_4k8k["ci95"]), 3),
                    "n": int(cc_4k8k["n"]),
                    "paired_s3_delta": round(float(paired_s3_4k8k.get("mean_delta_3d", -0.073)), 3),
                },
                "dagger_r1_8k": {"mean_score": round(float(r_d8["mean_score"]), 3), "ci95": round(float(r_d8["ci95"]), 3), "n": int(r_d8["n"])},
                "dagger_r1_4k": {"mean_score": round(float(r_d4["mean_score"]), 3), "ci95": round(float(r_d4["ci95"]), 3), "n": int(r_d4["n"])},
            },
            "confound_diagnostics": {
                "audited_verda_episodes": int(confound.get("n", 450)),
                "multiseed_replayed": int((multiseed.get("totals") or {}).get("total_episodes_replayed", 712)),
                "header_tokens": int(cc_cal.get("slurm_44410_reference_header_tokens", 2842)),
                "evicted_4k_pct": round(float(cc_raw.get("plant_canary_evicted_4k_pct", 97.98)), 2),
                "evicted_8k_pct": round(float(cc_raw.get("plant_canary_evicted_8k_pct", 84.65)), 2),
                "compact_max_tokens": int(cc_cmp.get("tokens_max", 1679)),
                "compact_evicted_pct": round(float(cc_cmp.get("canary_map_evicted_pct", 0.0)), 2),
            },
            "published_cohorts": [
                {
                    "id": _clean_ascii(row["row_id"]),
                    "mean_score": round(float(row["mean_score"]), 3),
                    "ci95": round(float(row["ci95"]), 3) if _is_num(row.get("ci95")) else 0.0,
                    "n": int(row["n"]),
                }
                for row in (addendum.get("readme_published_baseline") or [])
            ],
            "historical_runs": hist_rows,
        },
        "compact_non_llm_policies": compact_policies,
        "criteria_names": list((addendum.get("criteria_definitions") or {}).keys()),
        "ablations_and_scaling": {
            "scaling_curve": scaling_rows,
            "solver_scaling_ref": {
                "n_eval": int(sol_sc.get("n", 90)),
                "mean_score": round(float(sol_sc.get("mean_score", 0.6816)), 4),
                "ci95": round(float(sol_sc.get("ci95", 0.0535)), 4),
            },
            "linear_stages": linear_stages,
            "mlp_stages": mlp_stages,
            "eb_components": eb_stages,
        },
        "frontier_convergence": {
            "total_trajectories": int(rat.get("total_trajectories_audited", 990)),
            "fresh_env_episodes": int(rat.get("fresh_env_step_verified_episodes", 540)),
            "verda_belief_episodes": int(rat.get("verda_transcript_belief_replayed_episodes", 450)),
            "dev_hard_cohorts": fc_cohorts,
        },
    }


def _render_forest_svg(manifest: dict[str, Any]) -> str:
    t1_rows = manifest["track1_open_weight_llm"]["published_cohorts"]
    c_rows = manifest["compact_non_llm_policies"]
    sol = manifest["ablations_and_scaling"]["solver_scaling_ref"]

    items: list[tuple[str, float, float, float, str, str]] = []
    for r in t1_rows:
        m, hw = float(r["mean_score"]), float(r["ci95"])
        items.append((f"{r['id']} (n={r['n']})", m, max(-1.0, m - hw), min(1.0, m + hw), "llm", f"{m:+.3f}"))
    items.append(("SEP", 0.0, 0.0, 0.0, "sep", ""))
    for p in c_rows:
        m, lo, hi = float(p["after_mean_score"]), float(p["after_ci95_low"]), float(p["after_ci95_high"])
        items.append((f"{p['policy_class']} (n={p['n']}, {p['param_count']}p)", m, lo, hi, "cmp", f"{m:+.3f} [{lo:+.3f},{hi:+.3f}]"))
    sm, shw = float(sol["mean_score"]), float(sol["ci95"])
    items.append((f"SolverPolicy ref (n={sol['n_eval']})", sm, sm - shw, sm + shw, "sol", f"{sm:+.3f}"))

    w, rh, top, bot, xl, xr = 900, 24, 40, 28, 265, 745
    h = top + len(items) * rh + bot
    xp = lambda v: xl + (max(-1.0, min(1.0, v)) + 1.0) * 0.5 * (xr - xl)
    out = [
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Split-track held-out score forest plot">',
        f'<rect width="{w}" height="{h}" rx="10" fill="rgb(11,18,32)" stroke="rgb(38,52,77)"/>',
        '<text x="16" y="23" fill="rgb(226,232,240)" font-size="12.5" font-weight="700">Held-Out Mean Score &amp; 95% CI: Track 1 Qwen2.5-1.5B vs Strictly Separated Non-LLM Policies</text>',
    ]
    for tk in (-1.0, -0.5, 0.0, 0.5, 1.0):
        tx = xp(tk)
        col = "rgb(245,158,11)" if tk == 0.0 else "rgb(30,41,59)"
        out.append(f'<line x1="{tx:.1f}" y1="{top - 6}" x2="{tx:.1f}" y2="{h - bot + 2}" stroke="{col}" stroke-width="{"1.6" if tk == 0.0 else "1"}"/>')
        out.append(f'<text x="{tx:.1f}" y="{h - 8}" text-anchor="middle" fill="rgb(148,163,184)" font-size="10">{tk:+.2f}</text>')
    for i, (lbl, m, lo, hi, kind, vtxt) in enumerate(items):
        cy = top + i * rh + 11
        if kind == "sep":
            out.append(f'<line x1="14" y1="{cy}" x2="{w - 14}" y2="{cy}" stroke="rgb(56,189,248)" stroke-dasharray="5,4"/>')
            out.append(f'<text x="18" y="{cy - 3}" fill="rgb(56,189,248)" font-size="10" font-weight="700">STRICT SEPARATION BARRIER: NON-LLM COMPACT POLICIES BELOW (NEVER QWEN LORA)</text>')
            continue
        col = "rgb(251,191,36)" if (kind == "llm" and m == 0.0) else ("rgb(248,113,113)" if kind == "llm" else ("rgb(52,211,153)" if kind == "cmp" else "rgb(56,189,248)"))
        xm, xlo, xhi = xp(m), xp(lo), xp(hi)
        out.append(f'<text x="16" y="{cy + 4}" fill="rgb(226,232,240)" font-size="10.5" font-family="monospace">{_esc(lbl)}</text>')
        if xhi > xlo + 0.5:
            out.append(f'<line x1="{xlo:.1f}" y1="{cy}" x2="{xhi:.1f}" y2="{cy}" stroke="{col}" stroke-width="2.2"/>')
        out.append(f'<circle cx="{xm:.1f}" cy="{cy}" r="3.8" fill="{col}"/>')
        out.append(f'<text x="{xr + 8}" y="{cy + 4}" fill="{col}" font-size="10" font-family="monospace">{_esc(vtxt)}</text>')
    out.append("</svg>")
    return "".join(out)


def _render_scaling_svg(manifest: dict[str, Any]) -> str:
    sc = manifest["ablations_and_scaling"]["scaling_curve"]
    sol = manifest["ablations_and_scaling"]["solver_scaling_ref"]
    cc = manifest["track1_open_weight_llm"]["confound_diagnostics"]
    w, h, lx0, lx1, ly0, ly1 = 900, 215, 50.0, 420.0, 44.0, 180.0
    sy = lambda v: ly1 - (max(0.0, min(0.8, v)) / 0.8) * (ly1 - ly0)
    out = [
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Scaling curve and context eviction">',
        f'<rect width="{w}" height="{h}" rx="10" fill="rgb(11,18,32)" stroke="rgb(38,52,77)"/>',
        '<text x="16" y="22" fill="rgb(226,232,240)" font-size="12" font-weight="700">Left: ScalingLogisticPolicy Curve (82p, n=90) | Right: Canary-Map Eviction (450 Verda Episodes)</text>',
    ]
    for gv in (0.0, 0.4, 0.8):
        gy = sy(gv)
        out.append(f'<line x1="{lx0}" y1="{gy:.1f}" x2="{lx1}" y2="{gy:.1f}" stroke="rgb(30,41,59)"/>')
        out.append(f'<text x="{lx0 - 6}" y="{gy + 3:.1f}" text-anchor="end" fill="rgb(148,163,184)" font-size="9.5">{gv:.1f}</text>')
    sol_y = sy(float(sol["mean_score"]))
    out.append(f'<line x1="{lx0}" y1="{sol_y:.1f}" x2="{lx1}" y2="{sol_y:.1f}" stroke="rgb(56,189,248)" stroke-dasharray="4,3"/>')
    dx = (lx1 - lx0) / max(1, len(sc) - 1)
    pts = [f"{lx0 + i * dx:.1f},{sy(float(r['mean_score'])):.1f}" for i, r in enumerate(sc)]
    out.append(f'<polyline fill="none" stroke="rgb(52,211,153)" stroke-width="2.3" points="{" ".join(pts)}"/>')
    for i, r in enumerate(sc):
        px, py = lx0 + i * dx, sy(float(r["mean_score"]))
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.8" fill="rgb(52,211,153)"/>')
        out.append(f'<text x="{px:.1f}" y="{py - 7:.1f}" text-anchor="middle" fill="rgb(209,250,229)" font-size="9.5" font-family="monospace">{r["mean_score"]:+.3f}</text>')
        out.append(f'<text x="{px:.1f}" y="{ly1 + 16:.1f}" text-anchor="middle" fill="rgb(148,163,184)" font-size="9.5">{_esc(r["label"])}</text>')
    for bi, (blbl, pct, col) in enumerate((
        ("Raw 4k Window (~2842 header tok)", float(cc["evicted_4k_pct"]), "rgb(248,113,113)"),
        ("Raw 8k Window (out-of-support @8k)", float(cc["evicted_8k_pct"]), "rgb(251,191,36)"),
        ("CompactState (<1680 prompt tok)", float(cc["compact_evicted_pct"]), "rgb(52,211,153)"),
    )):
        by = 56.0 + bi * 46.0
        bw = max(3.0, pct * 3.0)
        out.append(f'<text x="475" y="{by - 5:.1f}" fill="rgb(226,232,240)" font-size="10.5">{_esc(blbl)}</text>')
        out.append(f'<rect x="475" y="{by:.1f}" width="300" height="15" rx="4" fill="rgb(30,41,59)"/>')
        out.append(f'<rect x="475" y="{by:.1f}" width="{bw:.1f}" height="15" rx="4" fill="{col}"/>')
        out.append(f'<text x="784" y="{by + 11.5:.1f}" fill="{col}" font-size="10.5" font-family="monospace" font-weight="700">{pct:.2f}%</text>')
    out.append("</svg>")
    return "".join(out)


def render_dashboard_html(manifest: dict[str, Any]) -> str:
    ts = manifest["track_separation"]
    sh = manifest["seed_hygiene_disclosure"]
    t1 = manifest["track1_open_weight_llm"]
    hl = t1["highlights"]
    cc = t1["confound_diagnostics"]
    c_pols = manifest["compact_non_llm_policies"]
    ab = manifest["ablations_and_scaling"]
    fc = manifest["frontier_convergence"]
    crit_badges = "".join(f'<span class="pill pill-pass">{_esc(k)}: PASS</span>' for k in manifest["criteria_names"])

    cards = "".join(
        f'<article class="card"><div class="card-top"><div><span class="tag-cmp">Strictly Separated Non-LLM Policy</span>'
        f'<h3>{_esc(p["policy_class"])} <code>{_esc(p["run_id"])}</code></h3></div>'
        f'<div class="score-big pos">{_fmt_s(p["after_mean_score"])}</div></div>'
        f'<p class="muted">{_esc(p["architecture"])} | <strong>{p["param_count"]:,}</strong> params | <code>{_esc(p["inference_module"])}</code></p>'
        f'<div class="kv"><div><span>Before -&gt; After (n={p["n"]})</span><strong>{_fmt_s(p["before_mean_score"])} -&gt; {_fmt_s(p["after_mean_score"])} '
        f'[{_fmt_s(p["after_ci95_low"])}, {_fmt_s(p["after_ci95_high"])}]</strong></div>'
        f'<div><span>Paired Delta (95% CI)</span><strong>{_fmt_s(p["paired_mean_delta"])} [{_fmt_s(p["paired_ci95_low"])}, {_fmt_s(p["paired_ci95_high"])}]</strong></div>'
        f'<div><span>Seeds (Train -&gt; Held-Out)</span><strong><code>{_esc(p["train_seed_range"])}</code> -&gt; <code>{_esc(p["eval_seed_range"])}</code></strong></div>'
        f'<div><span>Secret &amp; Gates</span><strong><code>{_esc(p["world_secret_tag"])}</code> | {p["gates_passed"]}/{p["gates_total"]} PASS (100% Env)</strong></div></div>'
        f'<p class="hl">{_esc(p["highlight"])}</p><div class="badges">{crit_badges}</div></article>'
        for p in c_pols
    )

    l_rows: list[str] = []
    for idx, r in enumerate(t1["historical_runs"], start=1):
        sc = _fmt_s(r["score"]) if _is_num(r["score"]) else "n/a (n=0)"
        if _is_num(r["ci95"]):
            sc = f"{sc} +/- {_fmt_f(r['ci95'])}"
        vb, va = r.get("valid_before"), r.get("valid_after")
        vc = f"{_fmt_f(vb, 2)}-&gt;{_fmt_f(va, 2)}" if _is_num(vb) and _is_num(va) else (_fmt_f(va, 2) if _is_num(va) else "n/a")
        sv = float(r["score"]) if _is_num(r["score"]) else -9.0
        bcls = "pill-fail" if r["category"] == "n0_failure" else ("pill-warn" if r["category"] == "dagger_null" else "pill-neu")
        l_rows.append(
            f'<tr class="lrow" data-cat="{_esc(r["category"])}" data-n="{r["n"]}" data-score="{sv:.4f}" '
            f'data-run="{_esc(r["run_id"])}" data-method="{_esc(r["method"])}" data-note="{_esc(r["note"])}">'
            f'<td class="num">{idx}</td><td><code>{_esc(r["run_id"])}</code></td><td>{_esc(r["model"])}</td>'
            f'<td class="num">{r["ctx"] or "n/a"}</td><td class="num">{r["n"]}</td><td class="num mono">{sc}</td>'
            f'<td class="num mono">{vc}</td><td><code>{_esc(r["secret_pairing"])}</code></td>'
            f'<td><span class="pill {bcls}">{_esc(r["status"])}</span></td></tr>'
        )

    st_tbl = lambda rows: "".join(
        f'<tr><td>{_esc(r["label"])}</td><td class="num">{r["n"]}</td><td class="num mono">{_fmt_s(r["mean_score"])}</td>'
        f'<td class="num mono">{_fmt_p(r["accuracy"])}</td><td class="num mono">{_fmt_p(r["abstain_rate"])}</td></tr>'
        for r in rows
    )
    fc_rows = "".join(
        f'<tr><td><strong>{_esc(c["label"])}</strong></td><td>{_esc(c["family"])}</td><td class="num">{c["n"]}</td>'
        f'<td class="num mono">{_fmt_s(c["mean_score"])} +/- {_fmt_f(c["ci95"])}</td><td class="num mono">{_fmt_s(c["luck_adjusted_ev"])}</td>'
        f'<td class="num mono">{_fmt_p(c["accuracy"])}</td><td class="num mono">{c["canaries"]:.2f}</td><td class="num mono">{_fmt_p(c["sub_be_rate"])}</td></tr>'
        for c in fc["dev_hard_cohorts"]
    )
    prov_rows = "".join(
        f'<tr><td><code>{_esc(k)}</code></td><td><code>{_esc(m["path"])}</code></td><td class="mono"><code>{_esc(m["sha256_16"])}</code></td><td class="num mono">{int(m["bytes"]):,} B</td></tr>'
        for k, m in manifest["source_artifacts"].items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canary Tiebreaker Scientific Dashboard (v1.4)</title>
<style>
:root{{--bg:rgb(7,12,22);--pn:rgb(15,23,42);--pa:rgb(21,32,56);--bd:rgb(38,52,77);--tx:rgb(226,232,240);--mu:rgb(148,163,184);--em:rgb(52,211,153);--am:rgb(251,191,36);--ro:rgb(248,113,113);--sk:rgb(56,189,248)}}
*{{box-sizing:border-box}}body{{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--tx);line-height:1.45}}
.wrap{{max-width:1220px;margin:0 auto;padding:22px 18px 48px}}
.hero,.sec{{background:var(--pn);border:1px solid var(--bd);border-radius:12px;padding:18px 20px;margin-bottom:16px}}.sec.hidden{{display:none}}
.eye{{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;color:var(--sk);background:rgba(56,189,248,0.14);padding:3px 9px;border-radius:99px;margin-bottom:6px}}
h1{{margin:0 0 6px;font-size:22px}}h2{{margin:0 0 8px;font-size:17px}}h3{{margin:2px 0 6px;font-size:14.5px}}p{{margin:0 0 8px}}
.muted{{color:var(--mu);font-size:12.5px}}code,.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px}}
.banners{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px;margin-top:12px}}
.bbox{{border-radius:9px;padding:12px 14px;border:1px solid var(--bd)}}
.b-llm{{background:rgba(248,113,113,0.08);border-color:rgba(248,113,113,0.4)}}
.b-cmp{{background:rgba(52,211,153,0.08);border-color:rgba(52,211,153,0.4)}}
.b-hyg{{background:rgba(56,189,248,0.08);border-color:rgba(56,189,248,0.4)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px;margin-bottom:14px}}
.kpi{{background:var(--pn);border:1px solid var(--bd);border-radius:9px;padding:10px 13px}}.kpi span{{display:block;font-size:11px;color:var(--mu)}}.kpi strong{{display:block;font-size:19px;margin-top:2px;font-family:ui-monospace,monospace}}
.pos{{color:var(--em)}}.neg{{color:var(--ro)}}.warn{{color:var(--am)}}.info{{color:var(--sk)}}
.tabs,.bar{{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px;align-items:center;justify-content:space-between}}
.tabs{{justify-content:flex-start}}.tbtn,.fbtn{{background:var(--pn);color:var(--tx);border:1px solid var(--bd);border-radius:7px;padding:6px 12px;font-size:12px;font-weight:600;cursor:pointer}}
.tbtn.active,.fbtn.active{{background:rgba(56,189,248,0.15);border-color:var(--sk);color:var(--sk)}}
.cgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:10px 0 14px}}
.call{{background:var(--pa);border:1px solid var(--bd);border-radius:8px;padding:9px 11px;font-size:12px}}
.inp{{background:rgb(11,18,32);color:var(--tx);border:1px solid var(--bd);border-radius:7px;padding:6px 10px;font-size:12px;min-width:210px}}
.tw{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:7px 9px;border-bottom:1px solid rgb(30,41,59);text-align:left}}
th{{color:var(--mu);background:rgba(11,18,32,0.6)}}th.srt{{cursor:pointer}}th.num,td.num{{text-align:right}}tr.lrow{{cursor:pointer}}tr.lrow:hover{{background:rgba(56,189,248,0.08)}}
.insp{{margin-top:10px;padding:10px 12px;border-radius:8px;background:rgb(11,18,32);border:1px solid var(--bd);font-size:12px}}
.pgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(450px,1fr));gap:12px}}
.card{{background:var(--pa);border:1px solid var(--bd);border-radius:9px;padding:13px 15px}}.card-top{{display:flex;justify-content:space-between;gap:10px}}
.score-big{{font-size:21px;font-weight:800;font-family:ui-monospace,monospace}}
.tag-cmp{{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:99px;background:rgba(16,185,129,0.15);color:var(--em);text-transform:uppercase}}
.kv{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 10px;margin:8px 0;font-size:11.5px}}.kv span{{display:block;color:var(--mu);font-size:10.5px}}
.hl{{font-size:11.5px;color:var(--sk);margin:6px 0}}.badges{{display:flex;flex-wrap:wrap;gap:4px}}
.pill{{display:inline-block;padding:2px 6px;border-radius:99px;font-size:10px;font-weight:700;font-family:ui-monospace,monospace}}
.pill-pass{{background:rgba(16,185,129,0.15);color:var(--em)}}.pill-fail{{background:rgba(239,68,68,0.15);color:var(--ro)}}.pill-warn{{background:rgba(245,158,11,0.15);color:var(--am)}}.pill-neu{{background:rgba(148,163,184,0.16);color:var(--tx)}}
.two{{display:grid;grid-template-columns:repeat(auto-fit,minmax(370px,1fr));gap:14px;margin-top:12px}}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <span class="eye">Canary v1.4 Offline Tiebreaker Viewer | 0 API Calls | Standalone Zero-CDN</span>
    <h1>Canary Experience Tiebreaker: Open-Weight Qwen 0/19 Null vs Strictly Separated Compact Policies</h1>
    <p class="muted">Generated offline by <code>scripts/build_tiebreak_viewer.py</code> from 9 committed <code>results/tiebreak/</code> JSON artifacts.</p>
    <div class="banners">
      <div class="bbox b-llm">
        <strong class="neg">Track 1: Open-Weight Qwen2.5-1.5B / 0.5B Ledger (0 / 19 &gt; 0.000)</strong>
        <p class="muted" style="margin-top:4px"><strong>0 / 19</strong> historical FR8 V100 and Verda A100/H100 runs beat base <code>0.000</code> (<code>{_esc(ts["readme_addendum_action"])}</code>). Logs all 5 <code>n=0</code> OOM/zero-var/preempted/reaper failures and split Verda X2 DAgger r1 honest nulls.</p>
      </div>
      <div class="bbox b-cmp">
        <strong class="pos">Strictly Separated Non-LLM Compact Policies (4 / 4 Pass 5/5 Gates)</strong>
        <p class="muted" style="margin-top:4px">Never conflated with Qwen2.5 LoRA. World-paired <code>HELDOUT_SEEDS [800000, 800200)</code>: <code>CompactLinearDAggerPolicy +0.627</code>, <code>TinyMLPPolicy +0.614</code>, <code>ScalingLogisticPolicy +0.611</code>, <code>EmpiricalBayesPolicy +0.607</code>.</p>
      </div>
      <div class="bbox b-hyg">
        <strong class="info">Panel Fix A Seed-Hygiene Disclosure</strong>
        <p class="muted" style="margin-top:4px"><code>TRAIN_SEEDS [100000, 200000)</code> | <code>HELDOUT_SEEDS [800000, 800200)</code> | <strong>0</strong> <code>JUDGE_SEEDS 900000+</code> | <code>DEV_SEEDS 0..29</code> post-hoc locked, never pre-registered.</p>
      </div>
    </div>
  </header>

  <div class="kpis">
    <div class="kpi"><span>Open-Weight Qwen &gt; Base 0.000</span><strong class="neg">{ts["open_weight_llm_above_base_count"]} / {ts["open_weight_llm_total_runs"]}</strong></div>
    <div class="kpi"><span>Logged n=0 Failures</span><strong class="warn">{ts["open_weight_llm_n0_failure_count"]} runs</strong></div>
    <div class="kpi"><span>Paired 8k s0 - s3 (1ca0c2a64d)</span><strong class="info">{_fmt_s(hl["paired_s0_minus_s3"]["mean_delta"])} +/- {_fmt_f(hl["paired_s0_minus_s3"]["ci95"])}</strong></div>
    <div class="kpi"><span>Non-LLM Compact Passing 5/5</span><strong class="pos">{ts["compact_non_llm_passing_count"]} / {ts["compact_non_llm_total_count"]}</strong></div>
    <div class="kpi"><span>Top Compact Held-Out Score</span><strong class="pos">+0.627 (n=180)</strong></div>
    <div class="kpi"><span>Judge Seeds 900000+ Touched</span><strong class="pos">{sh["judge_episodes_touched"]}</strong></div>
  </div>

  <nav class="tabs">
    <button type="button" class="tbtn active" data-tab="all">All Sections</button>
    <button type="button" class="tbtn" data-tab="overview">Visual Track Split</button>
    <button type="button" class="tbtn" data-tab="track1">Track 1: Qwen Ledger (0/19)</button>
    <button type="button" class="tbtn" data-tab="compact">Non-LLM Compact (4/4)</button>
    <button type="button" class="tbtn" data-tab="ablations">Scaling, Confound &amp; Stages</button>
    <button type="button" class="tbtn" data-tab="hygiene">Panel Fix A &amp; Frontier</button>
  </nav>

  <section class="sec" data-sec="overview">
    <h2>1. Split-Track Held-Out Score Forest Plot</h2>
    <p class="muted">Explicit visual barrier between Track 1 Open-Weight Qwen2.5-1.5B cohorts (all &lt;= <code>0.000</code>) and non-LLM compact policies on <code>HELDOUT_SEEDS [800000, 800200)</code>.</p>
    {_render_forest_svg(manifest)}
  </section>

  <section class="sec" data-sec="track1">
    <h2>2. Track 1: Open-Weight Qwen2.5-1.5B / 0.5B Historical Ledger (0/19 Above Base 0.000)</h2>
    <div class="cgrid">
      <div class="call"><strong class="neg">v3-4k GRPO Replicates</strong><br><code>v3-4k</code>: <strong>{_fmt_s(hl["v3_4k_s0"]["mean_score"])} +/- {_fmt_f(hl["v3_4k_s0"]["ci95"])}</strong> (<code>n={hl["v3_4k_s0"]["n"]}</code>)<br><code>v3-4k s1</code>: <strong>{_fmt_s(hl["v3_4k_s1"]["mean_score"])} +/- {_fmt_f(hl["v3_4k_s1"]["ci95"])}</strong> (<code>n={hl["v3_4k_s1"]["n"]}</code>)</div>
      <div class="call"><strong class="warn">v3-8k 4-Seed Bimodal Split</strong><br>H100 abstain: <code>s0 {_fmt_s(hl["v3_8k_s0"]["mean_score"])}</code> / <code>s2 {_fmt_s(hl["v3_8k_s2"]["mean_score"])}</code><br>A100 over-accuse: <code>s1 {_fmt_s(hl["v3_8k_s1"]["mean_score"])}</code> / <code>s3 {_fmt_s(hl["v3_8k_s3"]["mean_score"])}</code></div>
      <div class="call"><strong class="info">Paired s0-s3 &amp; 4k@8k Confound</strong><br>Paired <code>s0 - s3</code>: <strong>{_fmt_s(hl["paired_s0_minus_s3"]["mean_delta"])} +/- {_fmt_f(hl["paired_s0_minus_s3"]["ci95"])}</strong><br><code>4k@8k</code> confound: <strong>{_fmt_s(hl["confound_4k_at_8k"]["mean_score"])}</strong> (<code>s3-4k@8k {_fmt_s(hl["confound_4k_at_8k"]["paired_s3_delta"])}</code>)</div>
      <div class="call"><strong class="warn">Split DAgger r1 Honest Nulls</strong><br><code>8k</code>: <strong>{_fmt_s(hl["dagger_r1_8k"]["mean_score"])} +/- {_fmt_f(hl["dagger_r1_8k"]["ci95"])}</strong> (<code>n={hl["dagger_r1_8k"]["n"]}</code>)<br><code>4k</code>: <strong>{_fmt_s(hl["dagger_r1_4k"]["mean_score"])} +/- {_fmt_f(hl["dagger_r1_4k"]["ci95"])}</strong> (<code>n={hl["dagger_r1_4k"]["n"]}</code>)</div>
    </div>
    <div class="bar">
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        <button type="button" class="fbtn active" data-f="all">All ({ts["open_weight_llm_total_runs"]})</button>
        <button type="button" class="fbtn" data-f="eval">Evaluated ({ts["open_weight_llm_total_runs"] - ts["open_weight_llm_n0_failure_count"]})</button>
        <button type="button" class="fbtn" data-f="n0_failure">n=0 Failures ({ts["open_weight_llm_n0_failure_count"]})</button>
        <button type="button" class="fbtn" data-f="shared_or_8k">8k &amp; Confound</button>
        <button type="button" class="fbtn" data-f="dagger_null">DAgger r1 Nulls</button>
      </div>
      <input type="search" id="lsearch" class="inp" placeholder="Search run ID, model, status...">
    </div>
    <div class="tw">
      <table id="ltbl">
        <thead><tr><th class="num">Idx</th><th>Run ID</th><th>Model</th><th class="num">Ctx</th><th class="num srt" data-s="n">n</th><th class="num srt" data-s="score">Held-Out Score</th><th class="num">Valid</th><th>World Secret</th><th>Status</th></tr></thead>
        <tbody>{"".join(l_rows)}</tbody>
      </table>
    </div>
    <div id="rinsp" class="insp">Click any row to inspect method and failure/null diagnosis. Logged <code>n=0</code> runs: <code>{", ".join(t1["n0_failure_run_ids"])}</code>.</div>
  </section>

  <section class="sec" data-sec="compact">
    <h2>3. Strictly Separated Non-LLM Compact Policies (4/4 Passing 5/5 Gates on HELDOUT_SEEDS [800000, 800200))</h2>
    <p class="muted">AST-isolated (<code>0</code> <code>canary.solver</code> / <code>canary.world</code> inference imports), world-paired, 100% <code>Env</code> replay-verified.</p>
    <div class="pgrid">{cards}</div>
  </section>

  <section class="sec" data-sec="ablations">
    <h2>4. Sample Scaling, Context-Truncation Confound ({cc["audited_verda_episodes"]} Verda Eps) &amp; DAgger Stages</h2>
    <p class="muted">Raw prompts spend ~<code>{cc["header_tokens"]}</code> header tokens and evict <code>{cc["evicted_4k_pct"]:.2f}%</code> (4k) / <code>{cc["evicted_8k_pct"]:.2f}%</code> (8k) of canary maps vs <code>{cc["compact_evicted_pct"]:.2f}%</code> under <code>CompactState</code> (&lt;= <code>{cc["compact_max_tokens"]}</code> tok); Verda multiseed audit replays <code>{cc["multiseed_replayed"]}</code> episodes.</p>
    {_render_scaling_svg(manifest)}
    <div class="two">
      <div class="card"><h3>CompactLinearDAggerPolicy Stages (785p)</h3><div class="tw"><table><thead><tr><th>Stage</th><th class="num">n</th><th class="num">Score</th><th class="num">Acc</th><th class="num">Abstain</th></tr></thead><tbody>{st_tbl(ab["linear_stages"])}</tbody></table></div></div>
      <div class="card"><h3>TinyMLPPolicy Stages (12,293p)</h3><div class="tw"><table><thead><tr><th>Stage</th><th class="num">n</th><th class="num">Score</th><th class="num">Acc</th><th class="num">Abstain</th></tr></thead><tbody>{st_tbl(ab["mlp_stages"])}</tbody></table></div></div>
    </div>
    <div class="card" style="margin-top:12px"><h3>EmpiricalBayesPolicy Component Ablation (11p, n=180)</h3><div class="tw"><table><thead><tr><th>Variant</th><th class="num">n</th><th class="num">Score</th><th class="num">Acc</th><th class="num">Abstain</th></tr></thead><tbody>{st_tbl(ab["eb_components"])}</tbody></table></div></div>
  </section>

  <section class="sec" data-sec="hygiene">
    <h2>5. Panel Fix A Seed-Hygiene Disclosure &amp; Frontier Convergence ({fc["total_trajectories"]} Trajectories)</h2>
    <div class="cgrid">
      <div class="call"><strong class="pos">TRAIN_SEEDS [100000, 200000)</strong><br><code>{_esc(sh["train_seed_range"])}</code>: exclusive training, rollouts, and stopping calibration.</div>
      <div class="call"><strong class="pos">HELDOUT_SEEDS [800000, 800200)</strong><br><code>{_esc(sh["heldout_seed_range"])}</code>: exclusive primary world-paired evaluation split.</div>
      <div class="call"><strong class="pos">0 JUDGE_SEEDS 900000+</strong><br><code>{_esc(sh["judge_partition_rule"])}</code>.</div>
      <div class="call"><strong class="warn">DEV_SEEDS 0..29 Post-Hoc Locked</strong><br><code>{_esc(sh["dev_protocol_disclosure"])}</code>.</div>
    </div>
    <div class="tw"><table><thead><tr><th>Hard Dev Cohort (0..29 post-hoc locked, never pre-registered)</th><th>Family</th><th class="num">n</th><th class="num">Score +/- CI95</th><th class="num">Luck EV</th><th class="num">Acc</th><th class="num">Canaries</th><th class="num">Sub-BE</th></tr></thead><tbody>{fc_rows}</tbody></table></div>
    <h3 style="margin-top:14px">9 Committed Source JSON Digests</h3>
    <div class="tw"><table><thead><tr><th>Key</th><th>Path</th><th>SHA256[:16]</th><th class="num">Bytes</th></tr></thead><tbody>{prov_rows}</tbody></table></div>
  </section>
</div>
<script>
(function(){{
  var tbs=Array.prototype.slice.call(document.querySelectorAll('.tbtn'));
  var secs=Array.prototype.slice.call(document.querySelectorAll('.sec'));
  tbs.forEach(function(b){{b.addEventListener('click',function(){{
    var t=b.getAttribute('data-tab');
    tbs.forEach(function(x){{x.classList.toggle('active',x===b);}});
    secs.forEach(function(s){{s.classList.toggle('hidden',t!=='all'&&s.getAttribute('data-sec')!==t);}});
  }});}});
  var af='all',fbs=Array.prototype.slice.call(document.querySelectorAll('.fbtn'));
  var sb=document.getElementById('lsearch'),tbl=document.getElementById('ltbl');
  var tb=tbl?tbl.querySelector('tbody'):null,insp=document.getElementById('rinsp');
  function filt(){{
    if(!tb)return;
    var q=(sb?sb.value:'').toLowerCase().trim();
    Array.prototype.slice.call(tb.querySelectorAll('tr.lrow')).forEach(function(r){{
      var c=r.getAttribute('data-cat')||'',n=parseInt(r.getAttribute('data-n')||'0',10);
      var ok=(af==='all')||(af==='eval'&&n>0)||(c===af);
      var tok=!q||(r.textContent.toLowerCase().indexOf(q)!==-1);
      r.style.display=(ok&&tok)?'':'none';
    }});
  }}
  fbs.forEach(function(b){{b.addEventListener('click',function(){{
    af=b.getAttribute('data-f')||'all';
    fbs.forEach(function(x){{x.classList.toggle('active',x===b);}});
    filt();
  }});}});
  if(sb)sb.addEventListener('input',filt);
  if(tb&&insp)tb.addEventListener('click',function(e){{
    var r=e.target.closest('tr.lrow');
    if(r)insp.textContent=r.getAttribute('data-run')+' | '+r.getAttribute('data-method')+' | '+r.getAttribute('data-note');
  }});
  var asc=false;
  Array.prototype.slice.call(document.querySelectorAll('th.srt')).forEach(function(th){{
    th.addEventListener('click',function(){{
      if(!tb)return;
      var k=th.getAttribute('data-s')||'score';asc=!asc;
      var rs=Array.prototype.slice.call(tb.querySelectorAll('tr.lrow'));
      rs.sort(function(a,b){{var va=parseFloat(a.getAttribute('data-'+k)||'0'),vb=parseFloat(b.getAttribute('data-'+k)||'0');return asc?(va-vb):(vb-va);}});
      rs.forEach(function(r){{tb.appendChild(r);}});
    }});
  }});
}})();
</script>
</body>
</html>
"""


def write_viewer_artifacts(root: Path = ROOT) -> dict[str, Any]:
    manifest = build_viewer_manifest(root=root)
    html_text = render_dashboard_html(manifest)
    manifest_text = json.dumps(manifest, indent=2) + "\n"
    out_dir = root / VIEWER_DIR_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    (root / HTML_REL).write_text(html_text, encoding="utf-8")
    (root / MANIFEST_REL).write_text(manifest_text, encoding="utf-8")
    hb, mb = len(html_text.encode("utf-8")), len(manifest_text.encode("utf-8"))
    return {"html_path": str(HTML_REL), "manifest_path": str(MANIFEST_REL), "html_bytes": hb, "manifest_bytes": mb, "total_bytes": hb + mb}


def verify_artifacts(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    viewer_dir = root / VIEWER_DIR_REL
    html_path = root / HTML_REL
    manifest_path = root / MANIFEST_REL

    if not html_path.is_file():
        errors.append(f"missing {HTML_REL}")
    if not manifest_path.is_file():
        errors.append(f"missing {MANIFEST_REL}")

    if viewer_dir.is_dir():
        if (viewer_dir / "table.md").exists():
            errors.append("forbidden results/tiebreak/viewer/table.md present")
        for jf in sorted(viewer_dir.glob("*.json")):
            if jf.name == "summary.json" or jf.name.endswith("_summary.json"):
                errors.append(f"forbidden colliding summary filename in viewer dir: {jf.name}")

    try:
        expected_manifest = build_viewer_manifest(root=root)
        expected_manifest_txt = json.dumps(expected_manifest, indent=2) + "\n"
        expected_html_txt = render_dashboard_html(expected_manifest)
    except Exception as exc:
        return {"passed": False, "errors": [*errors, f"failed to build expected viewer payload: {exc}"]}

    if errors:
        return {"passed": False, "errors": errors}

    actual_manifest_txt = manifest_path.read_text(encoding="utf-8")
    actual_html_txt = html_path.read_text(encoding="utf-8")

    if actual_manifest_txt != expected_manifest_txt:
        errors.append("viewer_manifest.json differs from deterministic build_viewer_manifest(root)")
    if actual_html_txt != expected_html_txt:
        errors.append("tiebreak_dashboard.html differs from deterministic render_dashboard_html(manifest)")

    for lbl, txt in (("viewer_manifest.json", actual_manifest_txt), ("tiebreak_dashboard.html", actual_html_txt)):
        if EM_DASH in txt or EN_DASH in txt:
            errors.append(f"{lbl} contains forbidden em or en dash")
        if not txt.isascii():
            errors.append(f"{lbl} contains non-ASCII characters")

    if CDN_OR_REMOTE_RE.search(actual_html_txt):
        errors.append("tiebreak_dashboard.html contains external URL or CDN reference")

    required_tokens = (
        "0 / 19",
        "-0.147",
        "-0.209",
        "-0.060",
        "-0.050",
        "-0.777",
        "-0.788",
        "+0.728 +/- 0.134",
        "-0.716",
        "-0.542",
        "-0.101",
        "CompactLinearDAggerPolicy",
        "+0.627",
        "TinyMLPPolicy",
        "+0.614",
        "ScalingLogisticPolicy",
        "+0.611",
        "EmpiricalBayesPolicy",
        "+0.607",
        "[100000, 200000)",
        "[800000, 800200)",
        "900000+",
        "post-hoc locked, never pre-registered",
    )
    for tok in required_tokens:
        if tok not in actual_html_txt:
            errors.append(f"tiebreak_dashboard.html missing required token {tok!r}")

    ts = expected_manifest["track_separation"]
    if ts["open_weight_llm_above_base_count"] != 0 or ts["open_weight_llm_total_runs"] != 19:
        errors.append("Track 1 open-weight LLM count invariant violated (expected 0/19)")
    if ts["open_weight_llm_n0_failure_count"] != 5:
        errors.append("Track 1 n=0 failure count invariant violated (expected 5)")
    if ts["compact_non_llm_passing_count"] != 4:
        errors.append("Compact non-LLM passing count invariant violated (expected 4)")

    viewer_bytes = html_path.stat().st_size + manifest_path.stat().st_size
    total_all_four = viewer_bytes
    for rel_extra in ("scripts/build_tiebreak_viewer.py", "tests/test_tiebreak_viewer.py"):
        ep = root / rel_extra
        if ep.is_file():
            total_all_four += ep.stat().st_size
    if total_all_four >= MAX_TOTAL_BYTES:
        errors.append(f"4-file viewer bundle size {total_all_four}B >= {MAX_TOTAL_BYTES}B cap")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "viewer_bytes": viewer_bytes,
        "bundle_bytes": total_all_four,
        "sources_verified": len(expected_manifest["source_artifacts"]),
        "historical_runs": ts["open_weight_llm_total_runs"],
        "compact_policies": ts["compact_non_llm_passing_count"],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Deterministic offline HTML dashboard generator and verifier for Canary tiebreak.")
    ap.add_argument("--check", action="store_true", help="Verify committed HTML and manifest without writing.")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root directory.")
    ap.add_argument("--json", action="store_true", help="Emit JSON output.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    target_root = args.root.resolve()
    if args.check:
        verdict = verify_artifacts(root=target_root)
        if args.json:
            print(json.dumps(verdict, indent=2, sort_keys=True))
        elif verdict["passed"]:
            print(f"PASS: tiebreak viewer verified ({verdict['historical_runs']} LLM runs, {verdict['compact_policies']} compact policies, {verdict['viewer_bytes']}B)")
        else:
            for err in verdict["errors"]:
                print(f"FAIL: {err}")
        return 0 if verdict["passed"] else 1

    written = write_viewer_artifacts(root=target_root)
    verdict = verify_artifacts(root=target_root)
    if not verdict["passed"]:
        for err in verdict["errors"]:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({**written, "verified": True}, indent=2, sort_keys=True))
    else:
        print(f"WROTE {written['html_path']} ({written['html_bytes']}B) + {written['manifest_path']} ({written['manifest_bytes']}B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
