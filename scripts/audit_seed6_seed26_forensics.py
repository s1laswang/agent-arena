from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
TARGET_SEEDS: tuple[int, int] = (6, 26)
TIER = "hard"

OPENCODE_REL = "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"
INPROC_REL = "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl"
SOLVER_RELS: tuple[str, ...] = (
    "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
    "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
)
FAILURE_ANALYSIS_REL = "results/failure_analysis_v1.4.json"


def compute_v14_hash() -> tuple[str, str]:
    from canary import rules

    payload = {
        "tiers": {k: v.to_dict() for k, v in rules.TIERS.items()},
        "known_v_mode": rules.KNOWN_V_MODE,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]
    return rules.TIERS_VERSION, digest


def breakeven_prob(v_val: float, wrong_score: float = -1.0) -> float:
    denom = v_val - wrong_score
    if denom <= 0.0:
        return 1.0
    return (-wrong_score) / denom


def load_episodes_by_seed(root: Path, rel_paths: tuple[str, ...], seeds: tuple[int, ...]) -> dict[int, dict[str, Any]]:
    wanted = set(seeds)
    found: dict[int, dict[str, Any]] = {}
    for rel in rel_paths:
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"missing committed episode file: {rel}")
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            ep = json.loads(raw_line)
            if ep.get("tier") != TIER:
                continue
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            s_val = int(ep["seed"])
            if s_val in wanted:
                found[s_val] = ep
    missing = sorted(wanted - set(found))
    if missing:
        raise ValueError(f"missing seeds {missing} in {rel_paths}")
    return found


def _ok(step_obj: Any) -> bool:
    return bool((step_obj.result or {}).get("ok"))


def _steps_of(ep: dict[str, Any]) -> list[Any]:
    from canary.types import Step

    return [
        Step(
            t=s.get("t"),
            day=s.get("day"),
            tool=s.get("tool"),
            args=s.get("args"),
            result=s.get("result"),
        )
        for s in (ep.get("steps") or [])
    ]


def _planted_assignments(steps: list[Any], upto: int) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for st in steps[:upto]:
        if st.tool == "plant_canary" and _ok(st):
            cid = ((st.result or {}).get("data") or {}).get("canary_id")
            if cid:
                out[str(cid)] = dict((st.args or {}).get("assignment") or {})
    return out


def _last_seen_feed(steps: list[Any], upto: int) -> list[dict[str, Any]]:
    feed_items: list[dict[str, Any]] = []
    for st in steps[:upto]:
        if st.tool == "check_leak_feed" and _ok(st):
            feed_items = list(((st.result or {}).get("data") or {}).get("items") or [])
    return feed_items


def _consistent_suspects(env: Any, steps: list[Any], upto: int) -> list[str]:
    asg = _planted_assignments(steps, upto)
    docs = env._doc_by_id
    cand = set(env._ids)
    for item in _last_seen_feed(steps, upto):
        doc_id = item.get("doc_id")
        variant = item.get("variant")
        if variant is not None and doc_id in asg:
            cand &= {emp for emp, lab in asg[doc_id].items() if lab == variant}
        elif doc_id in docs:
            cand &= set(docs[doc_id].get("recipients") or [])
    return sorted(cand)


def _all_canary_flips(env: Any) -> list[dict[str, Any]]:
    mole_id = env._world.mole
    docs = env._doc_by_id
    flips: list[dict[str, Any]] = []
    for item in env._feed:
        doc = docs.get(item["doc_id"])
        if doc and doc.get("is_canary") and "variant" in item:
            true_var = next(k for k, v in doc["variants"].items() if mole_id in v)
            if item["variant"] != true_var:
                flips.append(
                    {
                        "doc_id": item["doc_id"],
                        "planted_day": int(doc["day"]),
                        "surfaced_day": int(item["surfaced_day"]),
                        "shown_variant": item["variant"],
                        "true_variant": true_var,
                    }
                )
    return flips


def replay_and_audit_episode(ep: dict[str, Any]) -> dict[str, Any]:
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    from canary.env import Env
    from canary.rules import tier_params_for_episode
    from canary.solver.policy import SolverPolicy, accuse_value
    from canary.types import INVESTIGATIVE_TOOLS

    seed = int(ep["seed"])
    steps = _steps_of(ep)
    params = tier_params_for_episode(TIER, steps)
    n_emp = int(params.n_employees)
    wrong_pen = float(params.wrong_accusation_score)

    env = Env(TIER, seed)
    mole_views: list[Any] = []
    orig_mole_view = env._mole_view

    def _hook_mole_view(d_val: int, _orig: Any = orig_mole_view, _views: list[Any] = mole_views) -> Any:
        v_obj = _orig(d_val)
        _views.append(v_obj)
        return v_obj

    env._mole_view = _hook_mole_view
    sp = SolverPolicy(params)

    mole_id = env._world.mole
    decoy_id = env._world.decoy
    recorded_accused = ep.get("accused")

    day_canaries: list[dict[str, Any]] = []
    day_surfaced_seen: list[dict[str, Any]] = []
    day_interviews: list[dict[str, Any]] = []
    day_log_calls = 0
    day_log_ranges: list[list[int]] = []
    day_actions = 0
    seen_feed_doc_ids: set[str] = set()
    daily_rows: list[dict[str, Any]] = []
    tool_counts: dict[str, int] = {}
    all_canaries: list[dict[str, Any]] = []

    for idx, st in enumerate(steps):
        tool_counts[st.tool] = tool_counts.get(st.tool, 0) + 1
        if st.tool in ("advance_day", "accuse"):
            post = sp.belief()
            post_sum = sum(post.values())
            top_id = max(post, key=post.get)
            p_top = float(post[top_id])
            p_mole = float(post.get(mole_id, 0.0))
            p_acc = float(post.get(recorded_accused, 0.0)) if recorded_accused else None
            exp_v = float(sp.expected_true_V())
            vis_v = float(env.visible_V())
            true_v = float(env.V)
            p_star_exp = breakeven_prob(exp_v, wrong_pen)
            p_star_true = breakeven_prob(true_v, wrong_pen)
            ev_top = float(accuse_value(p_top, exp_v, params))
            ev_acc = float(accuse_value(p_acc, exp_v, params)) if p_acc is not None else None
            last_day = int(st.day) >= int(params.n_days)
            fires = bool(ev_top > 0.0 and (p_top >= 0.85 or last_day))
            cons = _consistent_suspects(env, steps, idx)

            ah_by_emp = {e: int(sp.obs.access_counts.get(e, [0, 0])[1]) for e in env._ids}
            non_decoy_emps = [e for e in env._ids if e != decoy_id]
            top_ah_emp = max(non_decoy_emps, key=lambda e: (ah_by_emp[e], e))

            daily_rows.append(
                {
                    "day": int(st.day),
                    "step_idx": idx,
                    "step_t": int(st.t),
                    "decision_tool": st.tool,
                    "actions_used": day_actions,
                    "canaries_planted": list(day_canaries),
                    "surfaced_leaks_seen": list(day_surfaced_seen),
                    "interview_count": len(day_interviews),
                    "interviews": list(day_interviews),
                    "access_log_reads": day_log_calls,
                    "access_log_day_ranges": list(day_log_ranges),
                    "cum_after_hours": {
                        "mole": ah_by_emp[mole_id],
                        "accused": ah_by_emp[recorded_accused] if recorded_accused else None,
                        "decoy": ah_by_emp[decoy_id] if decoy_id else None,
                        "top_non_decoy_emp": top_ah_emp,
                        "top_non_decoy_count": ah_by_emp[top_ah_emp],
                    },
                    "consistent_suspects": cons,
                    "n_consistent": len(cons),
                    "posterior_sum": round(post_sum, 12),
                    "p_mole": p_mole,
                    "p_accused": p_acc,
                    "top_suspect": top_id,
                    "p_top": p_top,
                    "top_is_mole": bool(top_id == mole_id),
                    "visible_V": vis_v,
                    "true_V_before_close": true_v,
                    "expected_true_V": exp_v,
                    "p_breakeven_expected_V": p_star_exp,
                    "p_breakeven_true_V": p_star_true,
                    "ev_top": ev_top,
                    "ev_accused": ev_acc,
                    "solver_rule_fires": fires,
                }
            )
            day_canaries = []
            day_surfaced_seen = []
            day_interviews = []
            day_log_calls = 0
            day_log_ranges = []
            day_actions = 0

        if not env.done:
            env.call(st.tool, st.args or {})

        if _ok(st) and st.tool in INVESTIGATIVE_TOOLS:
            day_actions += 1

        if st.tool == "plant_canary" and _ok(st):
            cid = str(((st.result or {}).get("data") or {}).get("canary_id") or "")
            asg = dict((st.args or {}).get("assignment") or {})
            rec_count = len(asg)
            share = rec_count / float(n_emp)
            c_rec = {
                "canary_id": cid,
                "day": int(st.day),
                "title": str((st.args or {}).get("doc_title") or ""),
                "recipient_count": rec_count,
                "recipient_share": share,
                "careful_weight": 1.0 - share,
                "variant_count": len(set(asg.values())),
                "mole_variant": asg.get(mole_id),
                "accused_variant": asg.get(recorded_accused) if recorded_accused else None,
            }
            day_canaries.append(c_rec)
            all_canaries.append(c_rec)
        elif st.tool == "check_leak_feed" and _ok(st):
            for item in ((st.result or {}).get("data") or {}).get("items") or []:
                doc_id = str(item["doc_id"])
                if doc_id not in seen_feed_doc_ids:
                    seen_feed_doc_ids.add(doc_id)
                    doc_meta = env._doc_by_id[doc_id]
                    is_can = bool(doc_meta["is_canary"])
                    shown_var = item.get("variant")
                    true_var = (
                        next(k for k, v in doc_meta["variants"].items() if mole_id in v)
                        if is_can
                        else None
                    )
                    day_surfaced_seen.append(
                        {
                            "doc_id": doc_id,
                            "title": str(item.get("title") or doc_meta["title"]),
                            "is_canary": is_can,
                            "planted_day": int(doc_meta["day"]),
                            "surfaced_day": int(item["surfaced_day"]),
                            "observed_day": int(st.day),
                            "recipient_count": len(doc_meta["recipients"]),
                            "shown_variant": shown_var,
                            "true_variant": true_var,
                            "is_flip": bool(is_can and shown_var != true_var),
                        }
                    )
        elif st.tool == "read_access_logs" and _ok(st):
            day_log_calls += 1
            d_from = int((st.args or {}).get("day_from", st.day))
            d_to = int((st.args or {}).get("day_to", st.day))
            day_log_ranges.append([d_from, d_to])

        prev_iv_len = len(sp.obs.interviews)
        sp._ingest(st)
        if st.tool == "interview" and _ok(st) and len(sp.obs.interviews) > prev_iv_len:
            emp_iv, is_evasive = sp.obs.interviews[-1]
            day_interviews.append(
                {
                    "employee": str(emp_iv),
                    "topic": str((st.args or {}).get("topic") or ""),
                    "evasive_parsed_by_solver": bool(is_evasive),
                }
            )

    replay_res = env.result("replay")
    score_diff = abs(float(replay_res.score) - float(ep["score"]))
    accused_match = replay_res.accused == ep.get("accused")
    correct_match = bool(replay_res.correct) is bool(ep.get("correct"))
    day_match = int(replay_res.final_day) == int(ep.get("final_day"))
    discrepancies = int(score_diff > 1e-9) + int(not accused_match) + int(not correct_match) + int(not day_match)

    ledger_entries = env.ledger()
    acc_step = next((s for s in steps if s.tool == "accuse" and _ok(s)), None)
    t_cutoff = int(acc_step.t) if acc_step is not None else 10**9
    leak_entries = [x for x in ledger_entries if x.event == "leak" and int(x.t) <= t_cutoff]
    total_leaks = len(leak_entries)
    canary_doc_ids = {d_id for d_id, meta in env._doc_by_id.items() if meta.get("is_canary")}
    observed_canary_leaks = sum(1 for x in leak_entries if x.detail.get("doc_id") in canary_doc_ids)

    leak_opp_days = 0
    exp_careful = 0.0
    exp_uniform = 0.0
    for v_obj in mole_views:
        if not (v_obj.can_leak and v_obj.docs):
            continue
        leak_opp_days += 1
        is_can_flags = [d_item.doc_id in canary_doc_ids for d_item in v_obj.docs]
        weights = list(v_obj.select_weights) if v_obj.select_weights is not None else [1.0] * len(v_obj.docs)
        w_sum = sum(weights)
        if w_sum > 0.0:
            exp_careful += sum(w_val for w_val, flag in zip(weights, is_can_flags) if flag) / w_sum
        exp_uniform += sum(is_can_flags) / float(len(is_can_flags))

    by_day_canaries: dict[int, list[set[str]]] = {}
    for d_id in sorted(canary_doc_ids):
        meta = env._doc_by_id[d_id]
        by_day_canaries.setdefault(int(meta["day"]), []).append(set(meta["recipients"]))
    same_day_jaccards: list[float] = []
    for rec_sets in by_day_canaries.values():
        if len(rec_sets) >= 2:
            union_sz = len(rec_sets[0] | rec_sets[1])
            inter_sz = len(rec_sets[0] & rec_sets[1])
            same_day_jaccards.append((inter_sz / float(union_sz)) if union_sz else 0.0)

    commit_row = next((r for r in daily_rows if r["decision_tool"] == "accuse"), None)
    if commit_row is not None and commit_row["p_accused"] is not None:
        p_acc_final = float(commit_row["p_accused"])
        luck_adj = p_acc_final * float(env.V) + (1.0 - p_acc_final) * wrong_pen
    else:
        p_acc_final = None
        luck_adj = 0.0

    shares = [c["recipient_share"] for c in all_canaries]
    tiny_count = sum(1 for c in all_canaries if c["recipient_count"] <= 3)

    return {
        "seed": seed,
        "tier": TIER,
        "agent": str(ep["agent"]),
        "mole_id": mole_id,
        "decoy_id": decoy_id,
        "accused_id": replay_res.accused,
        "correct": bool(replay_res.correct),
        "outcome_label": "caught" if replay_res.correct else ("fooled" if replay_res.accused else "abstained"),
        "recorded_score": float(ep["score"]),
        "replay_score": float(replay_res.score),
        "luck_adjusted_score": luck_adj,
        "luck_realization": float(replay_res.score) - luck_adj,
        "final_day": int(replay_res.final_day),
        "accuse_day": int(acc_step.day) if acc_step is not None else None,
        "true_V_end": float(env.V),
        "visible_V_end": float(env.visible_V()),
        "total_leaks": total_leaks,
        "total_steps": len(steps),
        "invalid_calls": sum(1 for s in steps if not _ok(s)),
        "tool_counts": tool_counts,
        "canary_summary": {
            "planted_count": len(all_canaries),
            "first_canary_day": min((c["day"] for c in all_canaries), default=None),
            "mean_recipient_count": (sum(c["recipient_count"] for c in all_canaries) / len(all_canaries)) if all_canaries else 0.0,
            "mean_recipient_share": (sum(shares) / len(shares)) if shares else 0.0,
            "max_recipient_share": max(shares, default=0.0),
            "mean_careful_weight": (sum(1.0 - x for x in shares) / len(shares)) if shares else 0.0,
            "tiny_confirmation_count": tiny_count,
            "two_canary_days": len(same_day_jaccards),
            "mean_same_day_jaccard": (sum(same_day_jaccards) / len(same_day_jaccards)) if same_day_jaccards else 0.0,
            "leak_opportunity_days": leak_opp_days,
            "observed_canary_leaks": observed_canary_leaks,
            "expected_canary_leaks_careful": exp_careful,
            "expected_canary_leaks_uniform": exp_uniform,
            "careful_retention_ratio": (exp_careful / exp_uniform) if exp_uniform > 0.0 else 1.0,
            "surfaced_canary_leaks": [
                s_it
                for row in daily_rows
                for s_it in row["surfaced_leaks_seen"]
                if s_it["is_canary"]
            ],
            "ground_truth_flips": _all_canary_flips(env),
        },
        "commitment": {
            "p_mole": commit_row["p_mole"] if commit_row else None,
            "p_accused": p_acc_final,
            "p_top": commit_row["p_top"] if commit_row else None,
            "top_suspect": commit_row["top_suspect"] if commit_row else None,
            "expected_true_V": commit_row["expected_true_V"] if commit_row else None,
            "p_breakeven_expected_V": commit_row["p_breakeven_expected_V"] if commit_row else None,
            "p_breakeven_true_V": breakeven_prob(float(env.V), wrong_pen),
            "ev_accused": commit_row["ev_accused"] if commit_row else None,
            "consistent_suspects": commit_row["consistent_suspects"] if commit_row else [],
        },
        "replay_discrepancies": discrepancies,
        "daily_trace": daily_rows,
    }


def compute_careful_mole_curve(n_employees: int = 40) -> dict[str, Any]:
    non_decoy = n_employees - 1
    pool_rows: list[dict[str, Any]] = []
    best_k = 1
    best_hit = -1.0
    for k_val in range(1, n_employees + 1):
        share = k_val / float(n_employees)
        cw = 1.0 - share
        cov = min(1.0, k_val / float(non_decoy))
        hit_w = cov * cw
        if k_val <= non_decoy and hit_w > best_hit:
            best_hit = hit_w
            best_k = k_val
        if k_val in (1, 2, 3, 10, 13, 20, 30, 39, 40):
            pool_rows.append(
                {
                    "pool_size_k": k_val,
                    "recipient_share": share,
                    "careful_weight": cw,
                    "mole_coverage": cov,
                    "unconditional_hit_weight": hit_w,
                }
            )
    w_k3 = (3.0 / float(non_decoy)) * (1.0 - 3.0 / float(n_employees))
    w_k10 = (10.0 / float(non_decoy)) * (1.0 - 10.0 / float(n_employees))
    w_k39 = 1.0 * (1.0 - float(non_decoy) / float(n_employees))
    return {
        "n_employees": n_employees,
        "non_decoy_suspects": non_decoy,
        "optimal_single_canary_k": best_k,
        "max_single_hit_weight": best_hit,
        "disjoint_pair_k10_hit_weight": 2.0 * w_k10,
        "ratio_k20_vs_k3": best_hit / w_k3,
        "ratio_k20_vs_k39": best_hit / w_k39,
        "sampled_pool_curve": pool_rows,
    }


def _check_against_failure_analysis(root: Path, audits: dict[str, dict[int, dict[str, Any]]]) -> list[str]:
    fa_path = root / FAILURE_ANALYSIS_REL
    if not fa_path.is_file():
        return []
    fa = json.loads(fa_path.read_text(encoding="utf-8"))
    errs: list[str] = []
    mapping = (("opencode", "G"), ("inproc", "I"), ("solver", "S"))
    for local_key, fa_key in mapping:
        block = fa.get(fa_key) or {}
        for seed in TARGET_SEEDS:
            ref = block.get(str(seed))
            if ref is None:
                errs.append(f"missing {fa_key}[{seed}] in {FAILURE_ANALYSIS_REL}")
                continue
            got = audits[local_key][seed]
            if abs(got["replay_score"] - float(ref["score"])) > 1e-9:
                errs.append(f"{local_key} seed {seed} score mismatch vs failure_analysis_v1.4.json")
            if got["accused_id"] != ref["accused"]:
                errs.append(f"{local_key} seed {seed} accused mismatch vs failure_analysis_v1.4.json")
            if got["mole_id"] != ref["mole"]:
                errs.append(f"{local_key} seed {seed} mole mismatch vs failure_analysis_v1.4.json")
            if got["decoy_id"] != ref["decoy"]:
                errs.append(f"{local_key} seed {seed} decoy mismatch vs failure_analysis_v1.4.json")
            if abs(got["luck_adjusted_score"] - float(ref["luck_adjusted"])) > 1e-9:
                errs.append(f"{local_key} seed {seed} luck_adjusted mismatch vs failure_analysis_v1.4.json")
            if ref["accused"] is None:
                if got["commitment"]["p_accused"] is not None or got["commitment"]["ev_accused"] is not None:
                    errs.append(f"{local_key} seed {seed} abstention commitment fields expected None")
            else:
                if abs((got["commitment"]["p_accused"] or 0.0) - float(ref["p_accused"])) > 1e-9:
                    errs.append(f"{local_key} seed {seed} p_accused mismatch vs failure_analysis_v1.4.json")
                if abs((got["commitment"]["ev_accused"] or 0.0) - float(ref["ev_accused"])) > 1e-9:
                    errs.append(f"{local_key} seed {seed} ev_accused mismatch vs failure_analysis_v1.4.json")
                if got["commitment"]["consistent_suspects"] != ref["consistent_at_accusation"]:
                    errs.append(f"{local_key} seed {seed} consistent_at_accusation mismatch vs failure_analysis_v1.4.json")
    return errs


def run_forensic_audit(root: Path = ROOT) -> dict[str, Any]:
    t0 = time.monotonic()
    tiers_version, v14_hash = compute_v14_hash()
    opencode_eps = load_episodes_by_seed(root, (OPENCODE_REL,), TARGET_SEEDS)
    inproc_eps = load_episodes_by_seed(root, (INPROC_REL,), TARGET_SEEDS)
    solver_eps = load_episodes_by_seed(root, SOLVER_RELS, TARGET_SEEDS)

    audits: dict[str, dict[int, dict[str, Any]]] = {
        "opencode": {s: replay_and_audit_episode(opencode_eps[s]) for s in TARGET_SEEDS},
        "inproc": {s: replay_and_audit_episode(inproc_eps[s]) for s in TARGET_SEEDS},
        "solver": {s: replay_and_audit_episode(solver_eps[s]) for s in TARGET_SEEDS},
    }

    comparisons: dict[str, dict[str, Any]] = {}
    for s in TARGET_SEEDS:
        g_ep = audits["opencode"][s]
        ip_ep = audits["inproc"][s]
        sv_ep = audits["solver"][s]
        comparisons[str(s)] = {
            "seed": s,
            "mole_id": g_ep["mole_id"],
            "decoy_id": g_ep["decoy_id"],
            "gemini_outcome": g_ep["outcome_label"],
            "inproc_outcome": ip_ep["outcome_label"],
            "solver_outcome": sv_ep["outcome_label"],
            "raw_score_gap_solver_minus_gemini": sv_ep["replay_score"] - g_ep["replay_score"],
            "luck_adjusted_gap_solver_minus_gemini": sv_ep["luck_adjusted_score"] - g_ep["luck_adjusted_score"],
            "raw_score_gap_solver_minus_inproc": sv_ep["replay_score"] - ip_ep["replay_score"],
            "luck_adjusted_gap_solver_minus_inproc": sv_ep["luck_adjusted_score"] - ip_ep["luck_adjusted_score"],
            "gemini_canaries_planted": g_ep["canary_summary"]["planted_count"],
            "inproc_canaries_planted": ip_ep["canary_summary"]["planted_count"],
            "solver_canaries_planted": sv_ep["canary_summary"]["planted_count"],
            "gemini_first_canary_day": g_ep["canary_summary"]["first_canary_day"],
            "inproc_first_canary_day": ip_ep["canary_summary"]["first_canary_day"],
            "solver_first_canary_day": sv_ep["canary_summary"]["first_canary_day"],
            "gemini_interviews": g_ep["tool_counts"].get("interview", 0),
            "inproc_interviews": ip_ep["tool_counts"].get("interview", 0),
            "solver_interviews": sv_ep["tool_counts"].get("interview", 0),
            "gemini_flips": len(g_ep["canary_summary"]["ground_truth_flips"]),
            "inproc_flips": len(ip_ep["canary_summary"]["ground_truth_flips"]),
            "solver_flips": len(sv_ep["canary_summary"]["ground_truth_flips"]),
        }

    fa_errors = _check_against_failure_analysis(root, audits)
    total_discrepancies = sum(
        audits[k][s]["replay_discrepancies"] for k in ("opencode", "inproc", "solver") for s in TARGET_SEEDS
    )
    careful_curve = compute_careful_mole_curve(n_employees=40)

    elapsed = time.monotonic() - t0
    return {
        "tiers_version": tiers_version,
        "v14_hash": v14_hash,
        "seeds": list(TARGET_SEEDS),
        "total_replay_discrepancies": total_discrepancies,
        "failure_analysis_parity_errors": fa_errors,
        "elapsed_s": round(elapsed, 4),
        "careful_mole_monitoring_analysis": careful_curve,
        "episodes": {
            "seed_6": {
                "opencode_gemini_4_carbon": audits["opencode"][6],
                "inproc_gemini_4_carbon": audits["inproc"][6],
                "reference_solver": audits["solver"][6],
            },
            "seed_26": {
                "opencode_gemini_4_carbon": audits["opencode"][26],
                "inproc_gemini_4_carbon": audits["inproc"][26],
                "reference_solver": audits["solver"][26],
            },
        },
        "paired_comparison": comparisons,
    }


def validate_audit_payload(payload: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if payload.get("tiers_version") != EXPECTED_TIERS_VERSION:
        errs.append(f"tiers_version={payload.get('tiers_version')!r} != {EXPECTED_TIERS_VERSION!r}")
    if payload.get("v14_hash") != EXPECTED_V14_HASH:
        errs.append(f"v14_hash={payload.get('v14_hash')!r} != {EXPECTED_V14_HASH!r}")
    if payload.get("total_replay_discrepancies") != 0:
        errs.append(f"total_replay_discrepancies={payload.get('total_replay_discrepancies')} != 0")
    if payload.get("failure_analysis_parity_errors"):
        errs.extend(payload["failure_analysis_parity_errors"])

    cm = payload.get("careful_mole_monitoring_analysis") or {}
    if cm.get("optimal_single_canary_k") != 20 or not math.isclose(cm.get("max_single_hit_weight", 0.0), 20.0 / 78.0, abs_tol=1e-12):
        errs.append("careful_mole optimal Day-1 pool k*=20 mismatch")

    s6_g = payload["episodes"]["seed_6"]["opencode_gemini_4_carbon"]
    s6_i = payload["episodes"]["seed_6"]["inproc_gemini_4_carbon"]
    s6_s = payload["episodes"]["seed_6"]["reference_solver"]
    s26_g = payload["episodes"]["seed_26"]["opencode_gemini_4_carbon"]
    s26_i = payload["episodes"]["seed_26"]["inproc_gemini_4_carbon"]
    s26_s = payload["episodes"]["seed_26"]["reference_solver"]

    if not (s6_g["mole_id"] == s6_i["mole_id"] == s6_s["mole_id"] == "e34" and s6_g["decoy_id"] == "e20"):
        errs.append("seed 6 ground-truth mole/decoy mismatch")
    if not (s6_g["correct"] is True and s6_g["accused_id"] == "e34" and math.isclose(s6_g["replay_score"], 0.73, abs_tol=1e-9)):
        errs.append("seed 6 opencode outcome/score mismatch")
    if not (s6_i["correct"] is False and s6_i["accused_id"] == "e18" and s6_i["accuse_day"] == 15 and math.isclose(s6_i["replay_score"], -1.0, abs_tol=1e-9)):
        errs.append("seed 6 inproc outcome/score mismatch")
    if not (s6_s["correct"] is True and s6_s["accused_id"] == "e34" and math.isclose(s6_s["replay_score"], 0.71, abs_tol=1e-9)):
        errs.append("seed 6 solver outcome/score mismatch")
    if s6_g["canary_summary"]["ground_truth_flips"] or s6_s["canary_summary"]["ground_truth_flips"]:
        errs.append("seed 6 opencode/solver expected zero canary flips")
    flips_6_i = s6_i["canary_summary"]["ground_truth_flips"]
    if len(flips_6_i) != 1 or flips_6_i[0]["doc_id"] != "c4-2" or flips_6_i[0]["shown_variant"] != "Z" or flips_6_i[0]["true_variant"] != "Y":
        errs.append(f"seed 6 inproc expected single c4-2 Y->Z flip, got {flips_6_i}")

    if not (s26_g["mole_id"] == s26_i["mole_id"] == s26_s["mole_id"] == "e08" and s26_g["decoy_id"] == "e38"):
        errs.append("seed 26 ground-truth mole/decoy mismatch")
    if not (s26_g["correct"] is False and s26_g["accused_id"] == "e04" and math.isclose(s26_g["replay_score"], -1.0, abs_tol=1e-9)):
        errs.append("seed 26 opencode outcome/score mismatch")
    if not (s26_i["correct"] is False and s26_i["accused_id"] is None and s26_i["final_day"] == 21 and math.isclose(s26_i["replay_score"], 0.0, abs_tol=1e-9)):
        errs.append("seed 26 inproc outcome/score mismatch")
    if not (s26_s["correct"] is True and s26_s["accused_id"] == "e08" and math.isclose(s26_s["replay_score"], 0.69, abs_tol=1e-9)):
        errs.append("seed 26 solver outcome/score mismatch")

    flips_26 = s26_g["canary_summary"]["ground_truth_flips"]
    if len(flips_26) != 1 or flips_26[0]["doc_id"] != "c6-2" or flips_26[0]["shown_variant"] != "S1" or flips_26[0]["true_variant"] != "S3":
        errs.append(f"seed 26 expected single c6-2 S3->S1 flip, got {flips_26}")
    flips_26_i = s26_i["canary_summary"]["ground_truth_flips"]
    if len(flips_26_i) != 1 or flips_26_i[0]["doc_id"] != "c4" or flips_26_i[0]["shown_variant"] != "v2" or flips_26_i[0]["true_variant"] != "v1":
        errs.append(f"seed 26 inproc expected single c4 v1->v2 flip, got {flips_26_i}")

    for ep_label, ep_data in (
        ("seed6_opencode", s6_g),
        ("seed6_inproc", s6_i),
        ("seed6_solver", s6_s),
        ("seed26_opencode", s26_g),
        ("seed26_inproc", s26_i),
        ("seed26_solver", s26_s),
    ):
        cs = ep_data["canary_summary"]
        if not (0.5 < cs["careful_retention_ratio"] <= 1.0):
            errs.append(f"{ep_label} unexpected careful_retention_ratio={cs['careful_retention_ratio']}")
        for row in ep_data["daily_trace"]:
            if not math.isclose(row["posterior_sum"], 1.0, abs_tol=1e-7):
                errs.append(f"{ep_label} day {row['day']} posterior sum {row['posterior_sum']} != 1.0")
            exp_be = 1.0 / (1.0 + row["expected_true_V"])
            if not math.isclose(row["p_breakeven_expected_V"], exp_be, abs_tol=1e-12):
                errs.append(f"{ep_label} day {row['day']} breakeven formula mismatch")
    return errs


def format_human_summary(payload: dict[str, Any], errors: list[str]) -> str:
    cm = payload["careful_mole_monitoring_analysis"]
    lines = [
        f"Canary v1.4 ({payload['v14_hash']}) Forensic Replay Audit: Seed 6 (Caught OpenCode / Fooled InProc) vs Seed 26 (Fooled OpenCode / Abstained InProc)",
        f"Replay discrepancies: {payload['total_replay_discrepancies']} | Failure-analysis parity errors: {len(payload['failure_analysis_parity_errors'])} | careful_mole k*={cm['optimal_single_canary_k']} (W={cm['max_single_hit_weight']:.4f}, 2x10={cm['disjoint_pair_k10_hit_weight']:.4f}) | Elapsed: {payload['elapsed_s']:.3f}s",
    ]
    for seed_key, label in (("seed_6", "SEED 6"), ("seed_26", "SEED 26")):
        g = payload["episodes"][seed_key]["opencode_gemini_4_carbon"]
        ip = payload["episodes"][seed_key]["inproc_gemini_4_carbon"]
        sv = payload["episodes"][seed_key]["reference_solver"]
        ip_p_acc = f"{ip['commitment']['p_accused']:.4f}" if ip["commitment"]["p_accused"] is not None else "None"
        lines.append(
            f"[{label}] mole={g['mole_id']} decoy={g['decoy_id']} | "
            f"OpenCode: {g['outcome_label']} accused={g['accused_id']} day={g['accuse_day']} score={g['replay_score']:+.2f} "
            f"la={g['luck_adjusted_score']:+.4f} canaries={g['canary_summary']['planted_count']} "
            f"(d1={g['canary_summary']['first_canary_day']}, cw={g['canary_summary']['mean_careful_weight']:.3f}, "
            f"keep={g['canary_summary']['careful_retention_ratio']:.3f}) ivs={g['tool_counts'].get('interview', 0)} "
            f"P(acc)={g['commitment']['p_accused']:.4f} flips={len(g['canary_summary']['ground_truth_flips'])} | "
            f"InProc: {ip['outcome_label']} accused={ip['accused_id']} day={ip['accuse_day']} score={ip['replay_score']:+.2f} "
            f"la={ip['luck_adjusted_score']:+.4f} canaries={ip['canary_summary']['planted_count']} "
            f"(d1={ip['canary_summary']['first_canary_day']}, cw={ip['canary_summary']['mean_careful_weight']:.3f}, "
            f"keep={ip['canary_summary']['careful_retention_ratio']:.3f}) ivs={ip['tool_counts'].get('interview', 0)} "
            f"P(acc)={ip_p_acc} flips={len(ip['canary_summary']['ground_truth_flips'])} | "
            f"SolverPolicy: {sv['outcome_label']} accused={sv['accused_id']} day={sv['accuse_day']} score={sv['replay_score']:+.2f} "
            f"la={sv['luck_adjusted_score']:+.4f} canaries={sv['canary_summary']['planted_count']} "
            f"(d1={sv['canary_summary']['first_canary_day']}, cw={sv['canary_summary']['mean_careful_weight']:.3f}, "
            f"keep={sv['canary_summary']['careful_retention_ratio']:.3f}) P(mole)={sv['commitment']['p_mole']:.4f}"
        )
    status = "PASS" if not errors else f"FAIL ({len(errors)} error(s))"
    lines.append(f"CHECK STATUS: {status}")
    for err in errors:
        lines.append(f"  - {err}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic forensic replay audit of v1.4 hard seed 6 vs seed 26.")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    payload = run_forensic_audit(root=args.root.resolve())
    errors = validate_audit_payload(payload)
    payload["check_passed"] = not errors
    payload["check_errors"] = errors

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_human_summary(payload, errors))

    if args.check and errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
