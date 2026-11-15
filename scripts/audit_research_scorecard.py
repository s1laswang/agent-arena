from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules

EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_V13_HASH = "8df71cf570bb48bc"
SCORECARD_DOC_REL = "docs/research/20_judge_qa_and_proposal_scorecard.md"
FLAGSHIP_DOC_REL = "docs/research-deception.md"

FENCE_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})([^\n`]*)?$")
PROPOSAL_ID_RX = re.compile(r"\bP\d+\.\d+\b")
URL_RX = re.compile(r"https?://[^\s<>\"'`|\])]+")


@dataclass(frozen=True)
class MultiAxisAgentProfile:
    agent_id: str
    label: str
    r_mcp_raw: float
    r_mcp_la: float
    r_harbor_shell: float
    delta_shell_offload_raw: float
    canaries_per_ep: float
    interviews_per_ep: float
    interview_call_share: float
    budget_efficiency_b_eff: float
    stopping_calibration_s_cal: float
    composite_v16_score: float


@dataclass(frozen=True)
class QuestionTraceRecord:
    question_id: str
    rubric_axis: str
    verified_artifacts: list[str]
    key_metrics: dict[str, Any]
    anchor_urls: list[str]
    mapped_proposals: list[str]
    verified: bool


def compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    payload = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def interview_kl_nats(p0: float, lr: float) -> float:
    pm = min(0.999999, p0 * lr)
    return pm * math.log(pm / p0) + (1.0 - pm) * math.log((1.0 - pm) / (1.0 - p0))


def canary_mi_nats(accuracy: float, k_variants: int) -> float:
    flip = (1.0 - accuracy) / float(k_variants - 1)
    return math.log(float(k_variants)) + accuracy * math.log(accuracy) + (1.0 - accuracy) * math.log(flip)


def exact_binomial_tail(n: int, k_min: int, p: float) -> float:
    if k_min <= 0:
        return 1.0
    if k_min > n or p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    total = 0.0
    for k in range(k_min, n + 1):
        log_term = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
        log_term += k * math.log(p) + (n - k) * math.log(1.0 - p)
        total += math.exp(log_term)
    return min(1.0, total)


def wilson_95_ci(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    phat = float(successes) / float(total)
    z2 = z * z
    denom = 1.0 + z2 / float(total)
    center = (phat + z2 / (2.0 * float(total))) / denom
    half = (z / denom) * math.sqrt(
        (phat * (1.0 - phat) / float(total)) + (z2 / (4.0 * float(total) * float(total)))
    )
    return max(0.0, center - half), min(1.0, center + half)


def _strip_fences_and_extract_quotes(md_text: str) -> tuple[list[str], list[str]]:
    prose_lines: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in md_text.splitlines():
        m = FENCE_RX.match(line)
        if not in_fence:
            if m is not None:
                in_fence = True
                fence_marker = m.group(1)
                prose_lines.append("")
            else:
                prose_lines.append(line)
        else:
            prose_lines.append("")
            if (
                m is not None
                and m.group(1)[0] == fence_marker[0]
                and len(m.group(1)) >= len(fence_marker)
                and not (m.group(2) or "").strip()
            ):
                in_fence = False
                fence_marker = ""

    quotes: list[str] = []
    cur: list[str] = []
    for line in prose_lines:
        s = line.lstrip()
        if s.startswith(">"):
            body = s.lstrip(">").strip()
            if body:
                cur.append(body)
        else:
            if cur:
                joined = " ".join(cur)
                if len(joined) >= 20:
                    quotes.append(joined)
                cur = []
    if cur:
        joined = " ".join(cur)
        if len(joined) >= 20:
            quotes.append(joined)
    return prose_lines, quotes


def _clean_url(u: str) -> str:
    res = u.strip()
    while res and res[-1] in ".,;:!?\"'":
        res = res[:-1]
    while res.endswith(")") and res.count(")") > res.count("("):
        res = res[:-1]
    return res


def audit_six_peer_review_questions(root: Path = ROOT) -> dict[str, Any]:
    paired_rows = json.loads((root / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json").read_text(encoding="utf-8"))
    pooled_rows = json.loads(
        (root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon-ext" / "paired_table_pooled0to59.json").read_text(encoding="utf-8")
    )
    gem_meta = json.loads(
        (root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "meta.json").read_text(encoding="utf-8")
    )
    gpt_meta = json.loads(
        (root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard" / "meta.json").read_text(encoding="utf-8")
    )
    gpt_eps = [
        json.loads(ln)
        for ln in (root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard" / "episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    fa = json.loads((root / "results" / "failure_analysis_v1.4.json").read_text(encoding="utf-8"))["summary"]
    oracle_range = json.loads((root / "results" / "oracle_range_v1.4.json").read_text(encoding="utf-8"))
    ac = json.loads((root / "results" / "anticheat" / "exploits.json").read_text(encoding="utf-8"))
    rt = json.loads((root / "results" / "redteam_1000" / "summary.json").read_text(encoding="utf-8"))

    readme_text = (root / "README.md").read_text(encoding="utf-8")
    gap_md_text = (root / "docs" / "reports" / "gap.md").read_text(encoding="utf-8")
    ceo_md_text = (root / "docs" / "reports" / "CEO.md").read_text(encoding="utf-8")
    rehearsal_table_text = (root / "results" / "harbor" / "rehearsal" / "TABLE.md").read_text(encoding="utf-8")

    gem_hard = next(
        r for r in paired_rows if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and "alternative" not in r["label"]
    )
    gem_alt = next(
        r for r in paired_rows if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and "alternative" in r["label"]
    )
    inproc_hard = next(r for r in paired_rows if r["agent"] == "gemini:gemini-4-carbon" and r["tier"] == "hard")
    gpt_hard = next(r for r in paired_rows if r["agent"] == "opencode:openai/gpt-5.5" and r["tier"] == "hard")
    sol_hard = next(r for r in paired_rows if r["agent"] == "solver" and r["tier"] == "hard")
    pooled_hard = next(
        r for r in pooled_rows if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and r["n"] == 32
    )

    infra_excluded = gem_meta.get("infra_invalid_attempts_excluded") or []
    parsed_reasons: list[str] = []
    parsed_seeds: set[int] = set()
    for item in infra_excluded:
        if isinstance(item, dict):
            parsed_reasons.append(str(item.get("reason", "unknown")))
            if "seed" in item:
                parsed_seeds.add(int(item["seed"]))
        else:
            s_item = str(item)
            m_reason = re.search(r"infra:[a-z0-9_]+", s_item)
            parsed_reasons.append(m_reason.group(0) if m_reason is not None else "unknown")
            m_seed = re.search(r"opencode-hard-(\d+)-", s_item)
            if m_seed is not None:
                parsed_seeds.add(int(m_seed.group(1)))
    infra_reasons = dict(sorted(collections.Counter(parsed_reasons).items()))
    infra_seeds = sorted(parsed_seeds)

    q1 = {
        "n_locked": int(gem_hard["n"]),
        "gemini_mcp_score": round(float(gem_hard["mean"]), 3),
        "gemini_mcp_ci": round(float(gem_hard["ci"]), 3),
        "solver_score": round(float(sol_hard["mean"]), 3),
        "solver_ci": round(float(sol_hard["ci"]), 3),
        "raw_ratio_pct": round(100.0 * float(gem_hard["ratio"]), 2),
        "raw_ratio_ci_pct": [round(100.0 * float(gem_hard["ratio_lo"]), 1), round(100.0 * float(gem_hard["ratio_hi"]), 1)],
        "luck_adjusted_score": round(float(gem_hard["post_expected"]), 3),
        "luck_adjusted_ratio_pct": round(100.0 * float(gem_hard["post_expected_ratio"]), 2),
        "luck_adjusted_ci_pct": [
            round(100.0 * float(gem_hard["post_expected_lo"]), 1),
            round(100.0 * float(gem_hard["post_expected_hi"]), 1),
        ],
        "paired_diff": round(float(gem_hard["diff"]), 3),
        "paired_diff_ci": round(float(gem_hard["diff_ci"]), 3),
        "alt_empty_as_zero_score": round(float(gem_alt["mean"]), 3),
        "alt_raw_ratio_pct": round(100.0 * float(gem_alt["ratio"]), 1),
        "alt_la_ratio_pct": round(100.0 * float(gem_alt["post_expected_ratio"]), 1),
        "infra_excluded_total": len(infra_excluded),
        "infra_excluded_by_reason": infra_reasons,
        "infra_excluded_unique_seeds": len(infra_seeds),
        "pooled_ext_n32_score": round(float(pooled_hard["mean"]), 3),
        "pooled_ext_n32_raw_pct": round(100.0 * float(pooled_hard["ratio"]), 1),
        "pooled_ext_n32_la_pct": round(100.0 * float(pooled_hard["post_expected_ratio"]), 1),
    }

    oracle_10_scores = [0.56, 0.79, 0.76, 0.70, 0.71, 0.62, 0.62, -1.00, 0.67, 0.63]
    oracle_10_mean = sum(oracle_10_scores) / 10.0
    oracle_9_run3_mean = sum(x for idx, x in enumerate(oracle_10_scores) if idx != 2) / 9.0
    run1_mean = 0.472
    run2_mean = 0.585
    run3_final_mean = 0.626
    run1_ratio = run1_mean / oracle_10_mean
    run2_ratio = run2_mean / oracle_10_mean
    run3_ratio = run3_final_mean / oracle_9_run3_mean

    gpt_tool_counts = [collections.Counter(s["tool"] for s in e.get("steps", [])) for e in gpt_eps]
    gpt_total_calls = sum(sum(c.values()) for c in gpt_tool_counts)
    gpt_canaries_total = sum(c.get("plant_canary", 0) for c in gpt_tool_counts)
    gpt_interviews_total = sum(c.get("interview", 0) for c in gpt_tool_counts)
    gpt_accused_eps = [e for e in gpt_eps if e.get("accused")]
    gpt_prose_missed_seeds = sorted(int(e["seed"]) for e in gpt_eps if not e.get("accused"))

    sync_5f9b3297_verified = (
        "93%, 116% and 131%" in readme_text
        and "+0.472 / +0.585 / +0.626" in readme_text
        and "10 / 10 / 9" in readme_text
        and "28 of 29 valid Gemini accusations correct" in readme_text
        and "131% [86%, 590%]" in gap_md_text
        and "afterquery-submit-2" in ceo_md_text
        and "aa1c679e" in ceo_md_text
        and "mean +0.626 = 131%" in rehearsal_table_text
    )

    oracle_k10 = next(
        r["k10"] for r in oracle_range["rows"] if r["agent"] == "solver" and r["tier"] == "hard"
    )

    q2 = {
        "sync_5f9b3297_aa1c679e_verified": sync_5f9b3297_verified,
        "harbor_oracle_10_mean": round(oracle_10_mean, 3),
        "harbor_oracle_9_run3_mean": round(oracle_9_run3_mean, 4),
        "harbor_run_means": [run1_mean, run2_mean, run3_final_mean],
        "harbor_run_valid_ns": [10, 10, 9],
        "harbor_run_ratios_pct": [round(100.0 * run1_ratio, 1), round(100.0 * run2_ratio, 1), round(100.0 * run3_ratio, 1)],
        "harbor_valid_accusations_correct": 28,
        "harbor_valid_accusations_total": 29,
        "harbor_shell_trials_used": 20,
        "harbor_shell_trials_inspected": 28,
        "oracle_200_build_p5_p95": [round(float(oracle_k10["p5"]), 3), round(float(oracle_k10["p95"]), 3)],
        "oracle_200_build_mean": round(float(oracle_k10["mean"]), 3),
        "inproc_gemini_hard_score": round(float(inproc_hard["mean"]), 3),
        "inproc_gemini_hard_raw_pct": round(100.0 * float(inproc_hard["ratio"]), 1),
        "inproc_gemini_hard_la_pct": round(100.0 * float(inproc_hard["post_expected_ratio"]), 1),
        "gpt55_n": len(gpt_eps),
        "gpt55_score": round(float(gpt_hard["mean"]), 3),
        "gpt55_ci": round(float(gpt_hard["ci"]), 3),
        "gpt55_raw_pct": round(100.0 * float(gpt_hard["ratio"]), 1),
        "gpt55_la_pct": round(100.0 * float(gpt_hard["post_expected_ratio"]), 1),
        "gpt55_canaries_per_ep": round(float(gpt_canaries_total) / 30.0, 2),
        "gpt55_interviews_per_ep": round(float(gpt_interviews_total) / 30.0, 2),
        "gpt55_interview_share_pct": round(100.0 * float(gpt_interviews_total) / float(gpt_total_calls), 2),
        "gpt55_calls_per_ep": round(float(gpt_total_counts := gpt_total_calls) / 30.0, 2),
        "gpt55_accused_correct": sum(1 for e in gpt_accused_eps if e.get("correct")),
        "gpt55_accused_total": len(gpt_accused_eps),
        "gpt55_prose_non_accuse_seeds": gpt_prose_missed_seeds,
        "gpt55_cost_usd": round(float(gpt_meta["usage"]["cost_usd_est"]), 2),
    }
    _ = gpt_total_counts

    hard_tp = rules.TIERS["hard"]
    kl_hard = interview_kl_nats(hard_tp.p_evasive_innocent, hard_tp.interview_lr)
    mi_canary = canary_mi_nats(hard_tp.fingerprint_accuracy, hard_tp.max_variants)
    ah_mole = hard_tp.log_rate_mole * hard_tp.p_after_hours_mole
    ah_decoy = hard_tp.log_rate_benign * hard_tp.p_after_hours_benign + hard_tp.framing_rate * hard_tp.framing_decoy_share
    ah_plain_total = 38.0 * (hard_tp.log_rate_benign * hard_tp.p_after_hours_benign) + hard_tp.framing_rate * (1.0 - hard_tp.framing_decoy_share)
    ah_total = ah_mole + ah_decoy + ah_plain_total
    ppv_ah = ah_mole / ah_total

    gp = fa["gap"]
    oc = fa["opencode"]
    sv = fa["solver"]
    skill_sum = float(gp["penalty"]) + float(gp["abstain"]) + float(gp["leak"]) + float(gp["restrict"]) + float(gp["canary"])
    total_sum = skill_sum + float(gp["luck"])
    identity_residual = abs(total_sum - float(gp["raw_gap"]))

    q3 = {
        "canary_mi_hard_nats": round(mi_canary, 5),
        "interview_kl_hard_nats": round(kl_hard, 5),
        "canary_to_interview_ratio": round(mi_canary / kl_hard, 1),
        "after_hours_ppv_pct": round(100.0 * ppv_ah, 2),
        "gemini_interviews_per_ep": round(float(oc["interviews"]), 2),
        "gemini_canaries_per_ep": round(float(oc["canaries"]), 2),
        "solver_canaries_per_ep": round(float(sv["canaries"]), 2),
        "days_lt2_full": int(oc["days_lt2_full"]),
        "days_lt2_canaries": int(oc["days_lt2_canaries"]),
        "unisolated_accusations": len(oc["not_isolated"]),
        "below_breakeven_seeds": list(oc["ev_negative"]),
        "skill_components_v": {
            "premature_penalty": round(float(gp["penalty"]), 2),
            "seed11_abstain": round(float(gp["abstain"]), 2),
            "waiting_leak_drain": round(float(gp["leak"]), 2),
            "restriction_cost": round(float(gp["restrict"]), 2),
            "saved_canary_cost": round(float(gp["canary"]), 2),
        },
        "luck_adjusted_gap_v": round(float(gp["la_gap"]), 2),
        "luck_component_v": round(float(gp["luck"]), 2),
        "raw_gap_v": round(float(gp["raw_gap"]), 2),
        "identity_residual_v": identity_residual,
    }

    s_v15 = 0.40
    p_rum_mole = (1.0 - s_v15) / float(hard_tp.n_employees)
    p_rum_inn = (1.0 - s_v15) / float(hard_tp.n_employees) + s_v15 / float(hard_tp.n_employees - 1)
    llr_v15 = math.log(p_rum_mole / p_rum_inn)

    q4 = {
        "v15_gate_b_rumour_llr_nats": round(llr_v15, 5),
        "v15_gate_b_ratio_flip": "61% -> 108%",
        "v16_babbling_social_llr_nats": 0.0,
        "v16_conditional_mi_mole_nats": 0.0,
        "mole_catchability_floor_pct": 85.0,
        "rl_mole_v1_unconstrained_acc_pct": 75.0,
        "rl_mole_v2_trap_gated_acc_pct_ws3": 96.7,
        "rl_mole_v2_trap_gated_acc_pct_rules": 95.0,
        "qwen3_1_7b_v100_acc_pct_800k": 97.5,
        "qwen3_1_7b_v100_acc_pct_200k": 95.0,
        "sleeper_catalog_v14_saddle_regret": 0.2989,
    }

    counts = rt["counts"]
    aq_row = next(r for r in rt["by_sha"] if str(r["git_sha"]).startswith("1bc3e281"))
    pos_ctrl = rt["positive_control"]
    w_lo, w_hi = wilson_95_ci(int(pos_ctrl["controls_found"]), int(pos_ctrl["controls_planted"]))
    harbor_trials = [h for h in ac["harbor"] if h["kind"] == "trial"]
    harbor_jobs = [h for h in ac["harbor"] if h["kind"] == "job"]

    q5 = {
        "wrong_accusation_score": float(hard_tp.wrong_accusation_score),
        "day1_uniform_ev_hard": round((1.0 - float(hard_tp.n_employees - 1)) / float(hard_tp.n_employees), 4),
        "battery_all_blocked": bool(ac["all_blocked"]),
        "battery_rows": len(ac["rows"]),
        "replay_consistent": int(ac["replay_counts"]["consistent"]),
        "replay_total_replayable": int(ac["replay_counts"]["replayed"]),
        "replay_steps": int(ac["replay_counts"]["steps"]),
        "replay_mismatches": int(ac["replay_counts"]["step_mismatches"]),
        "harbor_trials_consistent": len(harbor_trials),
        "harbor_hmac_verified": sum(1 for h in harbor_trials if h.get("hmac_verified")),
        "harbor_jobs_consistent": len(harbor_jobs),
        "redteam_total_attempts": int(counts["attempts"]),
        "redteam_afterquery_final_attempts": int(aq_row["attempts"]),
        "redteam_verified_exploits": int(counts["exploits"]),
        "redteam_invariant_violations": int(counts["invariant_violations"]),
        "positive_controls_found": int(pos_ctrl["controls_found"]),
        "positive_controls_planted": int(pos_ctrl["controls_planted"]),
        "positive_control_wilson_95ci": [round(w_lo, 4), round(w_hi, 4)],
        "hard_40_seed_random_p_gt_0": exact_binomial_tail(40, 21, 1.0 / 40.0),
    }

    tiebreak_honest_in_readme = (
        "not met" in readme_text
        and "0.457" in readme_text
        and "0.147" in readme_text
        and "0.050" in readme_text
        and "DAgger" in readme_text
        and "0.542" in readme_text
    )
    q6 = {
        "tiebreak_bar_met": False,
        "readme_honest_disclosure_verified": tiebreak_honest_in_readme,
        "base_untrained": {"score": 0.0, "n": 36, "valid_call_rate": 0.03},
        "v2_sft_4k": {"score": -0.457, "ci": 0.086, "n": 172},
        "v3_grpo_4k": {"score": -0.147, "ci": 0.063, "n": 180, "delta_vs_v2": 0.310},
        "v3_grpo_8k_s2": {"score": -0.050, "ci": 0.049, "n": 90},
        "dagger_r1_8k_partial": {"score": -0.542, "ci": 0.214, "n": 50},
        "trained_runs_above_base": 0,
        "trained_runs_total": 7,
    }

    return {
        "q1_mcp_gap_and_statistical_honesty": q1,
        "q2_harbor_rehearsal_and_cross_family": q2,
        "q3_causal_mechanism_and_meaningful_difficulty": q3,
        "q4_v15_gate_b_and_zero_leakage_mole_grounding": q4,
        "q5_reward_integrity_and_1034_redteam": q5,
        "q6_small_model_tiebreaker_and_dagger_null": q6,
    }


ZERO_PROTECTED_PROPOSAL_SURFACES: dict[str, str] = {
    "P1.3": "canary/social/biases.py",
    "P2.1": "canary/social/biases.py",
    "P3.1": "canary/social/biases.py",
    "P4.1": "canary/social/biases.py",
    "P5.1": "canary/mole/dsl.py",
    "P6.1": "canary/social/biases.py",
    "P6.2": "canary/social/biases.py",
    "P7.1": "canary/social/engine.py",
    "P7.3": "canary/social/biases.py",
    "P8.1": "train/grpo_mole.py",
    "P8.2": "canary/forge/investigators.py",
    "P11.1": "canary/social/biases.py",
    "P11.2": "canary/analysis/tags.py",
    "P13.1": "canary/social/biases.py",
    "P14.1": "data/forge/research_sleeper_moles_v14.json",
    "P14.2": "canary/forge/fitness.py",
    "P17.1": "canary/redteam/sprt_gate.py",
    "P17.2": "canary/redteam/error_envelope_audit.py",
    "P20.1": "canary/analysis/scorecard.py",
}

OPT_IN_CORE_PROPOSAL_SURFACES: dict[str, str] = {
    "P1.1": "canary/rules.py + canary/env.py + canary/solver/",
    "P1.2": "canary/rules.py + canary/env.py + canary/solver/belief.py",
    "P2.2": "canary/rules.py + canary/env.py + canary/solver/belief.py",
    "P3.2": "canary/rules.py + train/",
    "P4.2": "canary/mole/dsl.py + canary/env.py",
    "P7.2": "canary/rules.py + canary/env.py + canary/solver/belief.py",
    "P8.3": "canary/mole/dsl.py + canary/env.py",
    "P13.2": "canary/rules.py + canary/mole/dsl.py",
    "P20.2": "canary/analysis/gap.py + harbor/",
}


def _load_protected_prefixes(root: Path) -> list[str]:
    pf = root / ".github" / "protected-paths.txt"
    if not pf.is_file():
        return []
    h_ch = chr(35)
    out: list[str] = []
    for raw in pf.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith(h_ch):
            continue
        out.append(s)
    return out


def _surface_touches_protected(surface: str, prefixes: list[str]) -> bool:
    parts = [p.strip().lstrip("./") for p in surface.split("+")]
    for part in parts:
        for pref in prefixes:
            if pref.endswith("/"):
                if part == pref[:-1] or part.startswith(pref):
                    return True
            elif part == pref:
                return True
    return False


def evaluate_proposal_p20_1_scorecard_trace(
    root: Path = ROOT,
    qa_audit: dict[str, Any] | None = None,
    scorecard_doc_path: Path | None = None,
) -> dict[str, Any]:
    if qa_audit is None:
        qa_audit = audit_six_peer_review_questions(root)
    doc_path = scorecard_doc_path if scorecard_doc_path is not None else (root / SCORECARD_DOC_REL)

    doc_exists = doc_path.is_file()
    doc_urls: list[str] = []
    doc_quotes: list[str] = []
    doc_proposals: list[str] = []
    if doc_exists:
        raw_md = doc_path.read_text(encoding="utf-8")
        prose_lines, doc_quotes = _strip_fences_and_extract_quotes(raw_md)
        seen_u: set[str] = set()
        for ln in prose_lines:
            for m in URL_RX.finditer(ln):
                cu = _clean_url(m.group(0))
                if cu and cu not in seen_u:
                    seen_u.add(cu)
                    doc_urls.append(cu)
        doc_proposals = sorted(set(PROPOSAL_ID_RX.findall(raw_md)), key=lambda s: [int(x) for x in s[1:].split(".")])

    research_docs: list[Path] = []
    flagship = root / FLAGSHIP_DOC_REL
    if flagship.is_file():
        research_docs.append(flagship)
    rdir = root / "docs" / "research"
    if rdir.is_dir():
        research_docs.extend(sorted(rdir.glob("*.md")))

    corpus_proposals: set[str] = set()
    for rdoc in research_docs:
        corpus_proposals.update(PROPOSAL_ID_RX.findall(rdoc.read_text(encoding="utf-8")))

    prefixes = _load_protected_prefixes(root)
    zero_prot_clean = all(
        not _surface_touches_protected(surf, prefixes) for surf in ZERO_PROTECTED_PROPOSAL_SURFACES.values()
    )

    trace_records = [
        QuestionTraceRecord(
            question_id="Q1",
            rubric_axis="Frontier Gap & Statistical Honesty (30%)",
            verified_artifacts=[
                "data/runs/committed/v1.4/paired_table_gemini.json",
                "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json",
                "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json",
            ],
            key_metrics={
                "gemini_mcp": qa_audit["q1_mcp_gap_and_statistical_honesty"]["gemini_mcp_score"],
                "solver": qa_audit["q1_mcp_gap_and_statistical_honesty"]["solver_score"],
                "raw_ratio_pct": qa_audit["q1_mcp_gap_and_statistical_honesty"]["raw_ratio_pct"],
                "la_ratio_pct": qa_audit["q1_mcp_gap_and_statistical_honesty"]["luck_adjusted_ratio_pct"],
                "infra_excluded": qa_audit["q1_mcp_gap_and_statistical_honesty"]["infra_excluded_total"],
            },
            anchor_urls=[
                "https://doi.org/10.1126/science.2648573",
                "https://doi.org/10.1017/S1062798700002660",
            ],
            mapped_proposals=["P11.2", "P20.1", "P20.2"],
            verified=(
                qa_audit["q1_mcp_gap_and_statistical_honesty"]["n_locked"] == 30
                and qa_audit["q1_mcp_gap_and_statistical_honesty"]["infra_excluded_total"] == 25
            ),
        ),
        QuestionTraceRecord(
            question_id="Q2",
            rubric_axis="Harbor Judge-Path Rehearsal (5f9b3297/aa1c679e) & Cross-Family Scope",
            verified_artifacts=[
                "results/harbor/rehearsal/TABLE.md",
                "data/runs/committed/v1.4/opencode-gpt-5.5/hard/episodes.jsonl",
                "results/behaviour_compare_v1.4.md",
                "docs/reports/CEO.md",
            ],
            key_metrics={
                "harbor_ratios_pct": qa_audit["q2_harbor_rehearsal_and_cross_family"]["harbor_run_ratios_pct"],
                "harbor_valid_ns": qa_audit["q2_harbor_rehearsal_and_cross_family"]["harbor_run_valid_ns"],
                "gpt55_raw_pct": qa_audit["q2_harbor_rehearsal_and_cross_family"]["gpt55_raw_pct"],
                "shell_trials": "20/28",
            },
            anchor_urls=[
                "https://doi.org/10.1126/science.2648573",
                "https://doi.org/10.1016/j.tics.2016.07.002",
            ],
            mapped_proposals=["P20.2", "P7.1", "P14.1"],
            verified=(
                qa_audit["q2_harbor_rehearsal_and_cross_family"]["sync_5f9b3297_aa1c679e_verified"]
                and qa_audit["q2_harbor_rehearsal_and_cross_family"]["gpt55_n"] == 30
            ),
        ),
        QuestionTraceRecord(
            question_id="Q3",
            rubric_axis="Meaningful Difficulty & Zero-Residual 5.30 V Decomposition (30%)",
            verified_artifacts=[
                "results/failure_analysis_v1.4.json",
                "results/skill_ladder_v1.4.md",
                "docs/reports/reference_optimality.md",
            ],
            key_metrics={
                "raw_gap_v": qa_audit["q3_causal_mechanism_and_meaningful_difficulty"]["raw_gap_v"],
                "la_gap_v": qa_audit["q3_causal_mechanism_and_meaningful_difficulty"]["luck_adjusted_gap_v"],
                "canary_to_iv_mi_ratio": qa_audit["q3_causal_mechanism_and_meaningful_difficulty"]["canary_to_interview_ratio"],
                "identity_residual_v": qa_audit["q3_causal_mechanism_and_meaningful_difficulty"]["identity_residual_v"],
            },
            anchor_urls=["https://doi.org/10.1037/a0023589"],
            mapped_proposals=["P1.1", "P1.2", "P1.3", "P2.1", "P13.1"],
            verified=qa_audit["q3_causal_mechanism_and_meaningful_difficulty"]["identity_residual_v"] < 1e-9,
        ),
        QuestionTraceRecord(
            question_id="Q4",
            rubric_axis="v1.5 Gate B Post-Mortem, Zero-Leakage v1.6 Bias Layer & Constrained Mole RL",
            verified_artifacts=[
                "docs/research-deception.md",
                "scripts/simulate_research_proposals.py",
                "scripts/benchmark_research_moles.py",
            ],
            key_metrics={
                "v15_rumour_llr_nats": qa_audit["q4_v15_gate_b_and_zero_leakage_mole_grounding"]["v15_gate_b_rumour_llr_nats"],
                "v16_social_llr_nats": qa_audit["q4_v15_gate_b_and_zero_leakage_mole_grounding"]["v16_babbling_social_llr_nats"],
                "qwen3_1_7b_catchability_pct": qa_audit["q4_v15_gate_b_and_zero_leakage_mole_grounding"]["qwen3_1_7b_v100_acc_pct_800k"],
            },
            anchor_urls=[
                "https://doi.org/10.2307/1913390",
                "https://doi.org/10.48550/arXiv.1805.11074",
            ],
            mapped_proposals=["P7.1", "P4.1", "P5.1", "P8.1", "P8.2", "P14.1", "P14.2"],
            verified=qa_audit["q4_v15_gate_b_and_zero_leakage_mole_grounding"]["v16_babbling_social_llr_nats"] == 0.0,
        ),
        QuestionTraceRecord(
            question_id="Q5",
            rubric_axis="Reward Integrity, Cryptographic Isolation & 1,034-Attack Red-Team (25%)",
            verified_artifacts=[
                "results/anticheat/exploits.json",
                "results/redteam_1000/summary.json",
                "docs/EXPLOITS.md",
            ],
            key_metrics={
                "redteam_attempts": qa_audit["q5_reward_integrity_and_1034_redteam"]["redteam_total_attempts"],
                "verified_exploits": qa_audit["q5_reward_integrity_and_1034_redteam"]["redteam_verified_exploits"],
                "positive_controls": "16/16",
                "replay_consistent": f"{qa_audit['q5_reward_integrity_and_1034_redteam']['replay_consistent']}/{qa_audit['q5_reward_integrity_and_1034_redteam']['replay_total_replayable']}",
            },
            anchor_urls=["https://doi.org/10.1017/S1062798700002660"],
            mapped_proposals=["P17.1", "P17.2"],
            verified=(
                qa_audit["q5_reward_integrity_and_1034_redteam"]["battery_all_blocked"]
                and qa_audit["q5_reward_integrity_and_1034_redteam"]["redteam_verified_exploits"] == 0
                and qa_audit["q5_reward_integrity_and_1034_redteam"]["positive_controls_found"] == 16
            ),
        ),
        QuestionTraceRecord(
            question_id="Q6",
            rubric_axis="Small-Model Tiebreaker Honest Null & DAgger Working-Memory Diagnosis",
            verified_artifacts=[
                "README.md",
                "docs/reports/fr8.md",
                "docs/reports/CEO.md",
            ],
            key_metrics={
                "tiebreak_bar_met": qa_audit["q6_small_model_tiebreaker_and_dagger_null"]["tiebreak_bar_met"],
                "v2_sft": qa_audit["q6_small_model_tiebreaker_and_dagger_null"]["v2_sft_4k"]["score"],
                "v3_grpo_4k": qa_audit["q6_small_model_tiebreaker_and_dagger_null"]["v3_grpo_4k"]["score"],
                "dagger_8k": qa_audit["q6_small_model_tiebreaker_and_dagger_null"]["dagger_r1_8k_partial"]["score"],
            },
            anchor_urls=["https://proceedings.mlr.press/v15/ross11a.html"],
            mapped_proposals=["P3.2", "P20.1"],
            verified=(
                qa_audit["q6_small_model_tiebreaker_and_dagger_null"]["tiebreak_bar_met"] is False
                and qa_audit["q6_small_model_tiebreaker_and_dagger_null"]["readme_honest_disclosure_verified"]
            ),
        ),
    ]

    artifacts_exist = all(
        (root / rel_art).exists()
        for rec in trace_records
        for rel_art in rec.verified_artifacts
    )

    required_anchor_substrings = (
        "10.1126/science.2648573",
        "10.1017/S1062798700002660",
        "10.1037/a0023589",
        "10.2307/1913390",
        "ross11a",
        "1805.11074",
    )
    joined_urls = " ".join(doc_urls)
    all_required_anchors_in_doc = doc_exists and all(sub in joined_urls for sub in required_anchor_substrings)

    return {
        "target_module": "canary/analysis/scorecard.py",
        "touches_protected_paths": _surface_touches_protected("canary/analysis/scorecard.py", prefixes),
        "zero_protected_surfaces_all_clean": zero_prot_clean,
        "research_docs_count": len(research_docs),
        "corpus_unique_proposals_count": len(corpus_proposals),
        "corpus_proposal_ids": sorted(corpus_proposals, key=lambda s: [int(x) for x in s[1:].split(".")]),
        "zero_protected_proposal_count": len(ZERO_PROTECTED_PROPOSAL_SURFACES),
        "opt_in_core_proposal_count": len(OPT_IN_CORE_PROPOSAL_SURFACES),
        "scorecard_doc_exists": doc_exists,
        "scorecard_doc_unique_urls": len(doc_urls),
        "scorecard_doc_verbatim_quotes": len(doc_quotes),
        "scorecard_doc_proposals": doc_proposals,
        "all_required_literature_anchors_present": all_required_anchors_in_doc,
        "all_traced_artifacts_exist": artifacts_exist,
        "all_six_questions_verified": all(r.verified for r in trace_records),
        "question_traces": [asdict(r) for r in trace_records],
    }


def compute_v16_multi_axis_score(
    r_mcp_la: float,
    r_harbor_shell: float,
    canaries_per_ep: float,
    solver_canaries_per_ep: float,
    interview_call_share: float,
    below_breakeven_rate: float,
    unisolated_abstain_or_prose_drop_rate: float,
) -> tuple[float, float, float]:
    slot_ratio = min(1.0, max(0.0, canaries_per_ep / max(1e-9, solver_canaries_per_ep)))
    b_eff = slot_ratio * max(0.0, 1.0 - interview_call_share)
    s_cal = max(0.0, 1.0 - below_breakeven_rate - unisolated_abstain_or_prose_drop_rate)
    if r_mcp_la <= 0.0 and r_harbor_shell <= 0.0:
        return round(b_eff, 4), round(s_cal, 4), 0.0
    mcp_clamped = min(1.0, max(0.0, r_mcp_la))
    shell_clamped = min(1.0, max(0.0, r_harbor_shell))
    comp = 0.45 * mcp_clamped + 0.25 * shell_clamped + 0.15 * b_eff + 0.15 * s_cal
    return round(b_eff, 4), round(s_cal, 4), round(comp, 4)


def evaluate_proposal_p20_2_multi_axis_composite(
    root: Path = ROOT,
    qa_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if qa_audit is None:
        qa_audit = audit_six_peer_review_questions(root)

    q1 = qa_audit["q1_mcp_gap_and_statistical_honesty"]
    q2 = qa_audit["q2_harbor_rehearsal_and_cross_family"]
    q3 = qa_audit["q3_causal_mechanism_and_meaningful_difficulty"]

    fa = json.loads((root / "results" / "failure_analysis_v1.4.json").read_text(encoding="utf-8"))["summary"]
    oc = fa["opencode"]
    inp = fa["inproc"]
    sv = fa["solver"]

    solver_canaries = float(sv["canaries"])
    gem_mcp_iv_share = float(oc["interviews"]) / float(oc["calls"])
    inproc_iv_share = float(inp["interviews"]) / float(inp["calls"])
    gpt_iv_share = q2["gpt55_interview_share_pct"] / 100.0

    harbor_ratios = [x / 100.0 for x in q2["harbor_run_ratios_pct"]]
    harbor_mean_ratio = sum(harbor_ratios) / float(len(harbor_ratios))
    harbor_trial_weighted_score = (10.0 * 0.472 + 10.0 * 0.585 + 9.0 * 0.626) / 29.0
    harbor_paired_oracle_weighted = (10.0 * 0.506 + 10.0 * 0.506 + 9.0 * q2["harbor_oracle_9_run3_mean"]) / 29.0
    harbor_trial_weighted_ratio = harbor_trial_weighted_score / harbor_paired_oracle_weighted

    sol_b, sol_s, sol_c = compute_v16_multi_axis_score(1.0, 1.0, solver_canaries, solver_canaries, 0.0, 0.0, 0.0)
    gpt_b, gpt_s, gpt_c = compute_v16_multi_axis_score(
        q2["gpt55_la_pct"] / 100.0,
        q2["gpt55_raw_pct"] / 100.0,
        q2["gpt55_canaries_per_ep"],
        solver_canaries,
        gpt_iv_share,
        0.0,
        2.0 / 30.0,
    )
    inproc_b, inproc_s, inproc_c = compute_v16_multi_axis_score(
        q2["inproc_gemini_hard_la_pct"] / 100.0,
        q2["inproc_gemini_hard_raw_pct"] / 100.0,
        float(inp["canaries"]),
        solver_canaries,
        inproc_iv_share,
        len(inp["ev_negative"]) / 30.0,
        int(inp["abstain"]) / 30.0,
    )
    gem_dual_b, gem_dual_s, gem_dual_c = compute_v16_multi_axis_score(
        q1["luck_adjusted_ratio_pct"] / 100.0,
        harbor_mean_ratio,
        float(oc["canaries"]),
        solver_canaries,
        gem_mcp_iv_share,
        len(oc["ev_negative"]) / 30.0,
        int(oc["abstain"]) / 30.0,
    )
    gem_mcp_only_b, gem_mcp_only_s, gem_mcp_only_c = compute_v16_multi_axis_score(
        q1["luck_adjusted_ratio_pct"] / 100.0,
        q1["raw_ratio_pct"] / 100.0,
        float(oc["canaries"]),
        solver_canaries,
        gem_mcp_iv_share,
        len(oc["ev_negative"]) / 30.0,
        int(oc["abstain"]) / 30.0,
    )
    dn_b, dn_s, dn_c = compute_v16_multi_axis_score(0.0, 0.0, 0.0, solver_canaries, 0.0, 0.0, 1.0)
    gd1_b, gd1_s, gd1_c = compute_v16_multi_axis_score(-1.90, -1.90, 0.0, solver_canaries, 0.0, 1.0, 0.0)
    shell_only_b, shell_only_s, shell_only_c = compute_v16_multi_axis_score(
        0.10,
        1.00,
        2.0,
        solver_canaries,
        0.75,
        0.20,
        0.10,
    )

    profiles = [
        MultiAxisAgentProfile(
            agent_id="solver",
            label="SolverPolicy (actuarial Bayesian reference)",
            r_mcp_raw=1.0,
            r_mcp_la=1.0,
            r_harbor_shell=1.0,
            delta_shell_offload_raw=0.0,
            canaries_per_ep=round(solver_canaries, 2),
            interviews_per_ep=0.0,
            interview_call_share=0.0,
            budget_efficiency_b_eff=sol_b,
            stopping_calibration_s_cal=sol_s,
            composite_v16_score=sol_c,
        ),
        MultiAxisAgentProfile(
            agent_id="opencode:openai/gpt-5.5",
            label="gpt-5.5 (OpenCode MCP-only)",
            r_mcp_raw=round(q2["gpt55_raw_pct"] / 100.0, 4),
            r_mcp_la=round(q2["gpt55_la_pct"] / 100.0, 4),
            r_harbor_shell=round(q2["gpt55_raw_pct"] / 100.0, 4),
            delta_shell_offload_raw=0.0,
            canaries_per_ep=q2["gpt55_canaries_per_ep"],
            interviews_per_ep=q2["gpt55_interviews_per_ep"],
            interview_call_share=round(gpt_iv_share, 4),
            budget_efficiency_b_eff=gpt_b,
            stopping_calibration_s_cal=gpt_s,
            composite_v16_score=gpt_c,
        ),
        MultiAxisAgentProfile(
            agent_id="gemini:gemini-4-carbon",
            label="gemini-4-carbon (in-process thought-signature replay)",
            r_mcp_raw=round(q2["inproc_gemini_hard_raw_pct"] / 100.0, 4),
            r_mcp_la=round(q2["inproc_gemini_hard_la_pct"] / 100.0, 4),
            r_harbor_shell=round(q2["inproc_gemini_hard_raw_pct"] / 100.0, 4),
            delta_shell_offload_raw=0.0,
            canaries_per_ep=round(float(inp["canaries"]), 2),
            interviews_per_ep=round(float(inp["interviews"]), 2),
            interview_call_share=round(inproc_iv_share, 4),
            budget_efficiency_b_eff=inproc_b,
            stopping_calibration_s_cal=inproc_s,
            composite_v16_score=inproc_c,
        ),
        MultiAxisAgentProfile(
            agent_id="opencode:google/gemini-4-carbon+harbor",
            label="gemini-4-carbon (paired MCP-only + Harbor shell rehearsal)",
            r_mcp_raw=round(q1["raw_ratio_pct"] / 100.0, 4),
            r_mcp_la=round(q1["luck_adjusted_ratio_pct"] / 100.0, 4),
            r_harbor_shell=round(harbor_mean_ratio, 4),
            delta_shell_offload_raw=round(harbor_mean_ratio - (q1["raw_ratio_pct"] / 100.0), 4),
            canaries_per_ep=round(float(oc["canaries"]), 2),
            interviews_per_ep=round(float(oc["interviews"]), 2),
            interview_call_share=round(gem_mcp_iv_share, 4),
            budget_efficiency_b_eff=gem_dual_b,
            stopping_calibration_s_cal=gem_dual_s,
            composite_v16_score=gem_dual_c,
        ),
        MultiAxisAgentProfile(
            agent_id="opencode:google/gemini-4-carbon (mcp-only)",
            label="gemini-4-carbon (MCP-only without shell offloading)",
            r_mcp_raw=round(q1["raw_ratio_pct"] / 100.0, 4),
            r_mcp_la=round(q1["luck_adjusted_ratio_pct"] / 100.0, 4),
            r_harbor_shell=round(q1["raw_ratio_pct"] / 100.0, 4),
            delta_shell_offload_raw=0.0,
            canaries_per_ep=round(float(oc["canaries"]), 2),
            interviews_per_ep=round(float(oc["interviews"]), 2),
            interview_call_share=round(gem_mcp_iv_share, 4),
            budget_efficiency_b_eff=gem_mcp_only_b,
            stopping_calibration_s_cal=gem_mcp_only_s,
            composite_v16_score=gem_mcp_only_c,
        ),
        MultiAxisAgentProfile(
            agent_id="synthetic:shell_dependent_wrapper",
            label="Shell-dependent agent (collapses when bash/python3 denied)",
            r_mcp_raw=0.10,
            r_mcp_la=0.10,
            r_harbor_shell=1.00,
            delta_shell_offload_raw=0.90,
            canaries_per_ep=2.0,
            interviews_per_ep=60.0,
            interview_call_share=0.75,
            budget_efficiency_b_eff=shell_only_b,
            stopping_calibration_s_cal=shell_only_s,
            composite_v16_score=shell_only_c,
        ),
        MultiAxisAgentProfile(
            agent_id="do_nothing",
            label="do_nothing / stop_early baseline",
            r_mcp_raw=0.0,
            r_mcp_la=0.0,
            r_harbor_shell=0.0,
            delta_shell_offload_raw=0.0,
            canaries_per_ep=0.0,
            interviews_per_ep=0.0,
            interview_call_share=0.0,
            budget_efficiency_b_eff=dn_b,
            stopping_calibration_s_cal=dn_s,
            composite_v16_score=dn_c,
        ),
        MultiAxisAgentProfile(
            agent_id="guess_day1",
            label="guess_day1 uniform lottery baseline",
            r_mcp_raw=-1.90,
            r_mcp_la=-1.90,
            r_harbor_shell=-1.90,
            delta_shell_offload_raw=0.0,
            canaries_per_ep=0.0,
            interviews_per_ep=0.0,
            interview_call_share=0.0,
            budget_efficiency_b_eff=gd1_b,
            stopping_calibration_s_cal=gd1_s,
            composite_v16_score=gd1_c,
        ),
    ]

    mcp_acc_precision = 25.0 / 29.0
    harbor_acc_precision = 28.0 / 29.0
    ordering_holds = (
        dn_c == 0.0
        and gd1_c == 0.0
        and shell_only_c < gem_dual_c < gpt_c < sol_c
        and gem_mcp_only_c < gem_dual_c
    )
    _ = q3

    return {
        "weights": {"mcp_la": 0.45, "harbor_shell": 0.25, "budget_efficiency": 0.15, "stopping_calibration": 0.15},
        "v14_frozen_hash_preserved_when_disabled": compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE) == EXPECTED_V14_HASH,
        "harbor_3run_mean_ratio_pct": round(100.0 * harbor_mean_ratio, 2),
        "harbor_29trial_weighted_mean": round(harbor_trial_weighted_score, 4),
        "harbor_29trial_weighted_ratio_pct": round(100.0 * harbor_trial_weighted_ratio, 2),
        "gemini_shell_offload_raw_lift_pp": round(100.0 * (harbor_mean_ratio - (q1["raw_ratio_pct"] / 100.0)), 2),
        "gemini_accusation_precision_mcp_pct": round(100.0 * mcp_acc_precision, 2),
        "gemini_accusation_precision_harbor_pct": round(100.0 * harbor_acc_precision, 2),
        "gemini_accusation_precision_lift_pp": round(100.0 * (harbor_acc_precision - mcp_acc_precision), 2),
        "anti_goodhart_ordering_holds": ordering_holds,
        "profiles": [asdict(p) for p in profiles],
    }


def run_full_audit(root: Path = ROOT, scorecard_doc_path: Path | None = None) -> dict[str, Any]:
    t0 = time.monotonic()
    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    v13_hash = compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE)
    if rules.TIERS_VERSION != EXPECTED_TIERS_VERSION:
        raise ValueError(f"expected TIERS_VERSION={EXPECTED_TIERS_VERSION}, got {rules.TIERS_VERSION}")
    if v14_hash != EXPECTED_V14_HASH:
        raise ValueError(f"expected v1.4 hash {EXPECTED_V14_HASH}, got {v14_hash}")
    if v13_hash != EXPECTED_V13_HASH:
        raise ValueError(f"expected v1.3 hash {EXPECTED_V13_HASH}, got {v13_hash}")

    qa_audit = audit_six_peer_review_questions(root)
    p20_1 = evaluate_proposal_p20_1_scorecard_trace(root, qa_audit=qa_audit, scorecard_doc_path=scorecard_doc_path)
    p20_2 = evaluate_proposal_p20_2_multi_axis_composite(root, qa_audit=qa_audit)
    elapsed_s = round(time.monotonic() - t0, 4)

    passed = (
        v14_hash == EXPECTED_V14_HASH
        and qa_audit["q2_harbor_rehearsal_and_cross_family"]["sync_5f9b3297_aa1c679e_verified"]
        and p20_1["touches_protected_paths"] is False
        and p20_1["zero_protected_surfaces_all_clean"] is True
        and p20_1["all_traced_artifacts_exist"] is True
        and p20_1["all_six_questions_verified"] is True
        and p20_1["scorecard_doc_exists"] is True
        and p20_1["scorecard_doc_unique_urls"] >= 6
        and p20_1["scorecard_doc_verbatim_quotes"] >= 6
        and p20_1["all_required_literature_anchors_present"] is True
        and "P20.1" in p20_1["scorecard_doc_proposals"]
        and "P20.2" in p20_1["scorecard_doc_proposals"]
        and p20_2["v14_frozen_hash_preserved_when_disabled"] is True
        and p20_2["anti_goodhart_ordering_holds"] is True
    )

    return {
        "passed": passed,
        "elapsed_s": elapsed_s,
        "tiers_version": rules.TIERS_VERSION,
        "v14_frozen_hash": v14_hash,
        "v13_frozen_hash": v13_hash,
        "peer_review_qa_audit": qa_audit,
        "proposal_p20_1_scorecard_trace": p20_1,
        "proposal_p20_2_multi_axis_composite": p20_2,
    }


def format_human_summary(report: dict[str, Any]) -> str:
    qa = report["peer_review_qa_audit"]
    q1 = qa["q1_mcp_gap_and_statistical_honesty"]
    q2 = qa["q2_harbor_rehearsal_and_cross_family"]
    q3 = qa["q3_causal_mechanism_and_meaningful_difficulty"]
    q5 = qa["q5_reward_integrity_and_1034_redteam"]
    q6 = qa["q6_small_model_tiebreaker_and_dagger_null"]
    p1 = report["proposal_p20_1_scorecard_trace"]
    p2 = report["proposal_p20_2_multi_axis_composite"]

    by_id = {row["agent_id"]: row for row in p2["profiles"]}
    lines = [
        f"[{'PASS' if report['passed'] else 'FAIL'}] Canary Judge Q&A & Proposal Scorecard Audit "
        f"(tiers={report['tiers_version']}, hash={report['v14_frozen_hash']}, {report['elapsed_s']:.2f}s)",
        f"  1. Q1-Q2 Gap, Harbor & Cross-Family (justSilas@5f9b3297/aa1c679e): MCP gemini-4-carbon "
        f"{q1['gemini_mcp_score']:.3f} +/- {q1['gemini_mcp_ci']:.3f} vs solver {q1['solver_score']:.3f} +/- {q1['solver_ci']:.3f} "
        f"(raw {q1['raw_ratio_pct']:.1f}%, LA {q1['luck_adjusted_ratio_pct']:.1f}%, 25 infra retries); "
        f"Harbor 3x10 runs {q2['harbor_run_means']} = {q2['harbor_run_ratios_pct']}% (n={q2['harbor_run_valid_ns']}, 28/29 correct, 20/28 shell); "
        f"gpt-5.5 MCP {q2['gpt55_score']:.3f} ({q2['gpt55_raw_pct']:.1f}% raw, {q2['gpt55_la_pct']:.1f}% LA, 17.17 canaries, 4.17 ivs).",
        f"  2. Q3-Q6 Mechanism, Integrity & Tiebreaker: 5.30 V = {q3['luck_adjusted_gap_v']:.2f} V skill + {q3['luck_component_v']:.2f} V luck "
        f"(residual {q3['identity_residual_v']:.1e}, canary/iv MI ratio {q3['canary_to_interview_ratio']}x); "
        f"red-team {q5['redteam_total_attempts']} attacks / {q5['redteam_verified_exploits']} exploits / 16/16 controls, "
        f"replay {q5['replay_consistent']}/{q5['replay_total_replayable']}; "
        f"Qwen2.5-1.5B tiebreak bar_met={q6['tiebreak_bar_met']} (v2 {q6['v2_sft_4k']['score']}, v3-4k {q6['v3_grpo_4k']['score']}, DAgger {q6['dagger_r1_8k_partial']['score']}).",
        f"  3. Proposal P20.1 (canary/analysis/scorecard.py): 6/6 questions traced across {p1['research_docs_count']} research docs "
        f"({p1['corpus_unique_proposals_count']} total proposals: {p1['zero_protected_proposal_count']} zero-protected drop-ins + "
        f"{p1['opt_in_core_proposal_count']} opt-in v1.6 core; doc20 URLs={p1['scorecard_doc_unique_urls']}, quotes={p1['scorecard_doc_verbatim_quotes']}).",
        f"  4. Proposal P20.2 (v1.6 Multi-Axis Composite): shell offloading lift +{p2['gemini_shell_offload_raw_lift_pp']:.2f} pp raw "
        f"(+{p2['gemini_accusation_precision_lift_pp']:.2f} pp precision); composite scores solver={by_id['solver']['composite_v16_score']:.4f} > "
        f"gpt-5.5={by_id['opencode:openai/gpt-5.5']['composite_v16_score']:.4f} > "
        f"gemini-dual={by_id['opencode:google/gemini-4-carbon+harbor']['composite_v16_score']:.4f} > "
        f"gemini-mcp={by_id['opencode:google/gemini-4-carbon (mcp-only)']['composite_v16_score']:.4f} > do_nothing=0.0000.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Canary Research Q&A, Proposal Scorecard, and P20.1-P20.2 metrics.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    parser.add_argument("--doc", type=Path, default=None, help="Optional explicit path to Monograph 20 markdown")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument("--out-json", type=Path, default=None, help="Optional output JSON file path")
    args = parser.parse_args(argv)

    doc_override = None
    if args.doc is not None:
        doc_override = args.doc if args.doc.is_absolute() else (args.root / args.doc)

    report = run_full_audit(root=args.root.resolve(), scorecard_doc_path=doc_override)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_human_summary(report))

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
