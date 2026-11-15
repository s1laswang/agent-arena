from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from canary.env import Env
from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy, accuse_value
from canary.types import Step

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_JSON = ROOT / "results" / "gemini" / "out_think_gemini.json"
DEFAULT_EPISODES_GZ = ROOT / "results" / "gemini" / "ladder_episodes.jsonl.gz"
DEFAULT_OUT = ROOT / "results" / "gemini" / "outthink_regret.json"

THINKING_LEVEL_ORDER = ("minimal", "low", "medium", "high", "xhigh")

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FORBIDDEN_NET = "fetch" + "("


def clean_zero(val: float, digits: int = 6) -> float:
    rounded = round(float(val), digits)
    return 0.0 if abs(rounded) < (10.0 ** (-digits)) else rounded


def clean_text(val: Any) -> str:
    if val is None:
        return ""
    txt = str(val).replace(EM_DASH, "-").replace(EN_DASH, "-")
    txt = txt.replace(FORBIDDEN_NET, "retrieve(")
    return " ".join(txt.split())


def shannon_entropy_bits(probs: dict[str, float]) -> float:
    total = -sum(float(p) * math.log2(float(p)) for p in probs.values() if float(p) > 0.0)
    return max(0.0, total)


def load_cases_payload(cases_json: Path = DEFAULT_CASES_JSON) -> dict[str, Any]:
    return json.loads(cases_json.read_text(encoding="utf-8"))


def load_ladder_index(
    episodes_gz: Path = DEFAULT_EPISODES_GZ,
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    by_cell: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    with gzip.open(episodes_gz, "rt", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            ep = json.loads(line)
            meta = ep.get("meta") or {}
            if meta.get("valid") is False or ep.get("end_reason") == "error":
                continue
            lad = meta.get("ladder") or {}
            model = str(lad.get("model") or "")
            level = str(lad.get("level") or "")
            tier = str(lad.get("tier") or ep.get("tier") or "")
            seed = int(lad.get("seed") if lad.get("seed") is not None else ep["seed"])
            key = (model, level, tier, seed)
            if key not in by_cell:
                by_cell[key] = ep
    return by_cell


def steps_from_episode(ep: dict[str, Any]) -> list[Step]:
    raw_steps = ep.get("steps") or []
    return [Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")}) for s in raw_steps]


def consistent_suspects(
    env: Env,
    canary_assignments: dict[str, dict[str, str]],
    feed_items: list[dict[str, Any]],
) -> set[str]:
    cand = set(env._ids)
    docs = env._doc_by_id
    for item in feed_items:
        doc_id = str(item.get("doc_id") or "")
        variant = item.get("variant")
        if variant is not None and doc_id in canary_assignments:
            asg = canary_assignments[doc_id]
            cand &= {emp for emp, v_label in asg.items() if v_label == variant}
        elif doc_id in docs:
            recips = docs[doc_id].get("recipients") or []
            if recips:
                cand &= {str(r) for r in recips}
    return cand


def replay_prefix_belief(
    tier: str,
    seed: int,
    steps: list[Step],
    upto: int,
) -> dict[str, Any]:
    env = Env(tier, seed)
    params = tier_params_for_episode(tier, steps)
    sp = SolverPolicy(params)
    canary_assignments: dict[str, dict[str, str]] = {}
    latest_feed: list[dict[str, Any]] = []

    for st in steps[:upto]:
        live_res = env.call(st.tool, st.args or {})
        recorded_ok = bool((st.result or {}).get("ok"))
        if live_res.ok != recorded_ok:
            raise ValueError(f"replay ok mismatch on {tier}/{seed} at step {st.t}")
        sp._ingest(
            Step(
                t=st.t,
                day=st.day,
                tool=st.tool,
                args=st.args,
                result=asdict(live_res),
            )
        )
        if not live_res.ok:
            continue
        data = live_res.data or {}
        tool_name = st.tool.strip()
        if tool_name == "plant_canary":
            cid = str(data.get("canary_id") or "")
            if cid:
                canary_assignments[cid] = {
                    str(k): str(v) for k, v in (st.args or {}).get("assignment", {}).items()
                }
        elif tool_name == "check_leak_feed":
            latest_feed = list(data.get("items") or [])

    sp.seen = upto
    sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
    post = sp.belief()
    consistent = consistent_suspects(env, canary_assignments, latest_feed)
    return {
        "env": env,
        "params": params,
        "solver_policy": sp,
        "posterior": post,
        "canary_assignments": canary_assignments,
        "latest_feed": latest_feed,
        "consistent_suspects": consistent,
    }


def replay_episode_outcome(tier: str, seed: int, ep: dict[str, Any]) -> dict[str, Any]:
    steps = steps_from_episode(ep)
    acc_idx: int | None = None
    for idx, st in enumerate(steps):
        if st.tool == "accuse" and bool((st.result or {}).get("ok")):
            acc_idx = idx
            break
    upto = acc_idx if acc_idx is not None else len(steps)
    prefix = replay_prefix_belief(tier, seed, steps, upto)
    env: Env = prefix["env"]
    for st in steps[upto:]:
        if env.done:
            break
        env.call(st.tool, st.args or {})
    if abs(float(env.score()) - float(ep["score"])) > 1e-6 or env._accused != ep.get("accused"):
        raise ValueError(f"episode replay mismatch on {tier}/{seed}")
    post = prefix["posterior"]
    prior_h = math.log2(len(env._ids))
    final_h = min(prior_h, shannon_entropy_bits(post))
    return {
        "final_entropy_bits": final_h,
        "mutual_information_bits": max(0.0, prior_h - final_h),
        "score": float(env.score()),
        "accused": env._accused,
        "correct": bool(env._correct) if env._accused else False,
    }


def analyze_case(
    case_obj: dict[str, Any],
    ladder_index: dict[tuple[str, str, str, int], dict[str, Any]],
) -> dict[str, Any]:
    case_id = str(case_obj["id"])
    title = clean_text(case_obj["title"])
    model = str(case_obj["model"])
    anchor_level = str(case_obj["anchor_level"])
    tier = str(case_obj["tier"])
    seed = int(case_obj["seed"])
    decision_day = int(case_obj["decision_day"])
    decision_step = int(case_obj["decision_step"])

    anchor_ep = ladder_index.get((model, anchor_level, tier, seed))
    if anchor_ep is None:
        raise ValueError(f"missing anchor episode for {case_id}: {model}/{anchor_level}/{tier}/{seed}")
    steps = steps_from_episode(anchor_ep)
    if decision_step >= len(steps) or steps[decision_step].tool != "accuse":
        raise ValueError(f"{case_id}: decision_step {decision_step} does not point to accuse step")
    if not bool((steps[decision_step].result or {}).get("ok")):
        raise ValueError(f"{case_id}: accuse step at {decision_step} is not ok")

    prefix = replay_prefix_belief(tier, seed, steps, decision_step)
    env: Env = prefix["env"]
    params = prefix["params"]
    post_raw: dict[str, float] = prefix["posterior"]
    consistent: set[str] = prefix["consistent_suspects"]

    n_suspects = len(env._ids)
    prior_h = math.log2(n_suspects)
    post_h = min(prior_h, shannon_entropy_bits(post_raw))
    mi_bits = max(0.0, prior_h - post_h)
    entropy_reduction_ratio = (mi_bits / prior_h) if prior_h > 0.0 else 0.0
    effective_suspects = 2.0 ** post_h

    consistent_count = len(consistent)
    eliminated_count = n_suspects - consistent_count
    eliminated_fraction = eliminated_count / n_suspects

    case_elim_count = sum(1 for s in case_obj.get("suspects", []) if s.get("eliminated"))
    if eliminated_count != case_elim_count:
        raise ValueError(
            f"{case_id}: eliminated_count mismatch ({eliminated_count} vs {case_elim_count})"
        )

    v_val = clean_zero(float(env.V), 4)
    if abs(v_val - float(case_obj["value_at_decision"])) > 1e-4:
        raise ValueError(f"{case_id}: value_at_decision mismatch ({v_val} vs {case_obj['value_at_decision']})")
    if int(env.day) != decision_day:
        raise ValueError(f"{case_id}: decision_day mismatch ({env.day} vs {decision_day})")

    true_mole = str(env._world.mole)
    if true_mole != str(case_obj["true_mole"]):
        raise ValueError(f"{case_id}: true_mole mismatch ({true_mole} vs {case_obj['true_mole']})")

    for st in steps[decision_step:]:
        if env.done:
            break
        env.call(st.tool, st.args or {})
    if abs(float(env.score()) - float(anchor_ep["score"])) > 1e-6 or env._accused != anchor_ep.get("accused"):
        raise ValueError(f"{case_id}: full anchor episode replay mismatch")

    wrong_score = float(params.wrong_accusation_score)
    break_even_prob = (-wrong_score) / (v_val - wrong_score) if v_val > 0.0 else 1.0
    top_suspect = str(max(post_raw, key=post_raw.get))
    top_prob = float(post_raw[top_suspect])
    true_mole_prob = float(post_raw[true_mole])
    ev_accuse_top = float(accuse_value(top_prob, v_val, params))

    solver_block = case_obj["solver"]
    solver_final_score = clean_zero(float(solver_block["final_score"]), 4)
    solver_final_day = int(solver_block["final_day"])
    solver_final_accused = solver_block.get("final_accused")
    solver_correct = bool(solver_block["correct"])
    ev_hold_fire = clean_zero(max(0.0, solver_final_score), 4)
    recommended_call = "accuse" if top_prob >= break_even_prob else "hold_fire"

    if top_suspect != str(solver_block["top_suspect"]):
        raise ValueError(f"{case_id}: top_suspect mismatch ({top_suspect} vs {solver_block['top_suspect']})")
    if recommended_call != str(solver_block["recommended_call"]):
        raise ValueError(
            f"{case_id}: recommended_call mismatch ({recommended_call} vs {solver_block['recommended_call']})"
        )
    if abs(break_even_prob - float(solver_block["break_even_prob"])) > 1e-4:
        raise ValueError(f"{case_id}: break_even_prob mismatch against out_think_gemini.json")
    if abs(ev_accuse_top - float(solver_block["ev_accuse_top"])) > 1e-4:
        raise ValueError(f"{case_id}: ev_accuse_top mismatch against out_think_gemini.json")

    opt_binary_ev = max(ev_accuse_top, 0.0)
    level_rows: list[dict[str, Any]] = []
    for lv_item in case_obj["thinking_levels"]:
        lv = str(lv_item["thinking_level"])
        lv_ep = ladder_index.get((model, lv, tier, seed))
        if lv_ep is None:
            raise ValueError(f"{case_id}: missing ladder episode for {model}/{lv}/{tier}/{seed}")
        ep_outcome = replay_episode_outcome(tier, seed, lv_ep)

        call_at_t = str(lv_item["call_at_t"])
        matched_rec = call_at_t == recommended_call
        accused_raw = lv_item.get("accused")
        accused = str(accused_raw) if accused_raw is not None else None
        matched_top = bool(accused is not None and accused == top_suspect)
        accused_prob = clean_zero(float(post_raw.get(accused, 0.0)), 6) if accused is not None else None

        chosen_binary_ev = ev_accuse_top if call_at_t == "accuse" else 0.0
        binary_call_regret = max(0.0, opt_binary_ev - chosen_binary_ev)

        if call_at_t == "accuse" and accused is not None:
            chosen_action_ev = float(accuse_value(float(post_raw.get(accused, 0.0)), v_val, params))
        elif call_at_t == "accuse":
            chosen_action_ev = ev_accuse_top
        else:
            chosen_action_ev = 0.0
        decision_regret_ev = max(0.0, opt_binary_ev - chosen_action_ev)

        lv_score = clean_zero(ep_outcome["score"], 4)
        if abs(lv_score - float(lv_item["score"])) > 1e-4:
            raise ValueError(f"{case_id}/{lv}: score mismatch ({lv_score} vs {lv_item['score']})")
        score_delta_vs_solver = clean_zero(lv_score - solver_final_score, 4)
        realized_regret_vs_solver = clean_zero(max(0.0, solver_final_score - lv_score), 4)

        level_rows.append(
            {
                "thinking_level": lv,
                "model": model,
                "run_id": str(lv_item["run_id"]),
                "call_at_t": call_at_t,
                "recommended_call": recommended_call,
                "matched_recommended_call": matched_rec,
                "accused": accused,
                "accused_day": int(lv_item["accused_day"]) if lv_item.get("accused_day") is not None else None,
                "end_reason": str(lv_item["end_reason"]),
                "correct": bool(lv_item["correct"]),
                "matched_top_suspect": matched_top,
                "accused_prob_at_decision": accused_prob,
                "binary_call_regret_ev": clean_zero(binary_call_regret, 6),
                "decision_regret_ev": clean_zero(decision_regret_ev, 6),
                "score": lv_score,
                "solver_final_score": solver_final_score,
                "score_delta_vs_solver": score_delta_vs_solver,
                "realized_regret_vs_solver": realized_regret_vs_solver,
                "episode_final_entropy_bits": clean_zero(ep_outcome["final_entropy_bits"], 6),
                "episode_mutual_information_bits": clean_zero(ep_outcome["mutual_information_bits"], 6),
                "thinking_tokens": int(lv_item["thinking_tokens"]),
                "cost_usd": clean_zero(float(lv_item["cost_usd"]), 6),
                "failure_tag": lv_item.get("failure_tag"),
            }
        )

    prior_bits_clean = clean_zero(prior_h, 6)
    post_bits_clean = clean_zero(post_h, 6)
    mi_bits_clean = clean_zero(mi_bits, 6)

    return {
        "id": case_id,
        "title": title,
        "model": model,
        "anchor_level": anchor_level,
        "tier": tier,
        "seed": seed,
        "decision_day": decision_day,
        "decision_step": decision_step,
        "n_suspects": n_suspects,
        "prior_entropy_bits": prior_bits_clean,
        "posterior_entropy_bits": post_bits_clean,
        "mutual_information_bits": mi_bits_clean,
        "entropy_reduction_ratio": clean_zero(entropy_reduction_ratio, 6),
        "effective_suspects": clean_zero(effective_suspects, 6),
        "eliminated_count": eliminated_count,
        "consistent_count": consistent_count,
        "eliminated_fraction": clean_zero(eliminated_fraction, 6),
        "value_at_decision": v_val,
        "wrong_accusation_score": clean_zero(wrong_score, 4),
        "true_mole": true_mole,
        "true_mole_prob": clean_zero(true_mole_prob, 6),
        "top_suspect": top_suspect,
        "top_prob": clean_zero(top_prob, 6),
        "break_even_prob": clean_zero(break_even_prob, 6),
        "ev_accuse_top": clean_zero(ev_accuse_top, 6),
        "ev_hold_fire": ev_hold_fire,
        "recommended_call": recommended_call,
        "solver_final_score": solver_final_score,
        "solver_final_day": solver_final_day,
        "solver_final_accused": str(solver_final_accused) if solver_final_accused is not None else None,
        "solver_correct": solver_correct,
        "thinking_levels": level_rows,
    }


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    n_cases = len(cases)
    all_runs = [lv for c in cases for lv in c["thinking_levels"]]
    n_runs = len(all_runs)

    by_level: dict[str, dict[str, Any]] = {}
    for lv_name in THINKING_LEVEL_ORDER:
        rows = [r for r in all_runs if r["thinking_level"] == lv_name]
        if not rows:
            continue
        rc = len(rows)
        matched_cnt = sum(1 for r in rows if r["matched_recommended_call"])
        correct_cnt = sum(1 for r in rows if r["correct"])
        by_level[lv_name] = {
            "run_count": rc,
            "matched_recommended_call_count": matched_cnt,
            "matched_recommended_call_rate": clean_zero(matched_cnt / rc, 6),
            "correct_count": correct_cnt,
            "accuracy": clean_zero(correct_cnt / rc, 6),
            "mean_score": clean_zero(sum(r["score"] for r in rows) / rc, 6),
            "mean_score_delta_vs_solver": clean_zero(sum(r["score_delta_vs_solver"] for r in rows) / rc, 6),
            "mean_realized_regret_vs_solver": clean_zero(
                sum(r["realized_regret_vs_solver"] for r in rows) / rc, 6
            ),
            "mean_binary_call_regret_ev": clean_zero(sum(r["binary_call_regret_ev"] for r in rows) / rc, 6),
            "mean_decision_regret_ev": clean_zero(sum(r["decision_regret_ev"] for r in rows) / rc, 6),
            "mean_episode_final_entropy_bits": clean_zero(
                sum(r["episode_final_entropy_bits"] for r in rows) / rc, 6
            ),
            "mean_thinking_tokens": clean_zero(sum(r["thinking_tokens"] for r in rows) / rc, 2),
            "mean_cost_usd": clean_zero(sum(r["cost_usd"] for r in rows) / rc, 6),
        }

    matched_total = sum(1 for r in all_runs if r["matched_recommended_call"])
    correct_total = sum(1 for r in all_runs if r["correct"])
    return {
        "mean_prior_entropy_bits": clean_zero(sum(c["prior_entropy_bits"] for c in cases) / n_cases, 6),
        "mean_posterior_entropy_bits": clean_zero(
            sum(c["posterior_entropy_bits"] for c in cases) / n_cases, 6
        ),
        "mean_mutual_information_bits": clean_zero(
            sum(c["mutual_information_bits"] for c in cases) / n_cases, 6
        ),
        "mean_eliminated_fraction": clean_zero(sum(c["eliminated_fraction"] for c in cases) / n_cases, 6),
        "matched_recommended_call_count": matched_total,
        "matched_recommended_call_rate": clean_zero(matched_total / n_runs, 6),
        "correct_count": correct_total,
        "accuracy": clean_zero(correct_total / n_runs, 6),
        "mean_score_delta_vs_solver": clean_zero(
            sum(r["score_delta_vs_solver"] for r in all_runs) / n_runs, 6
        ),
        "mean_realized_regret_vs_solver": clean_zero(
            sum(r["realized_regret_vs_solver"] for r in all_runs) / n_runs, 6
        ),
        "mean_binary_call_regret_ev": clean_zero(
            sum(r["binary_call_regret_ev"] for r in all_runs) / n_runs, 6
        ),
        "mean_decision_regret_ev": clean_zero(sum(r["decision_regret_ev"] for r in all_runs) / n_runs, 6),
        "by_thinking_level": by_level,
    }


def build_payload(
    cases_json: Path = DEFAULT_CASES_JSON,
    episodes_gz: Path = DEFAULT_EPISODES_GZ,
) -> dict[str, Any]:
    cases_doc = load_cases_payload(cases_json)
    ladder_index = load_ladder_index(episodes_gz)
    raw_cases = cases_doc.get("cases") or []

    analyzed_cases: list[dict[str, Any]] = []
    models_seen: list[str] = []
    levels_seen: set[str] = set()
    hold_fire_count = 0
    accuse_count = 0

    for c_obj in raw_cases:
        analyzed = analyze_case(c_obj, ladder_index)
        analyzed_cases.append(analyzed)
        if analyzed["model"] not in models_seen:
            models_seen.append(analyzed["model"])
        for lv in analyzed["thinking_levels"]:
            levels_seen.add(lv["thinking_level"])
        if analyzed["recommended_call"] == "hold_fire":
            hold_fire_count += 1
        else:
            accuse_count += 1

    ordered_levels = [lv for lv in THINKING_LEVEL_ORDER if lv in levels_seen]
    total_runs = sum(len(c["thinking_levels"]) for c in analyzed_cases)
    summary = summarize_cases(analyzed_cases)

    return {
        "meta": {
            "title": "Out-Think Gemini: Bayesian Entropy and Decision-Regret Analysis",
            "tiers_version": str((cases_doc.get("meta") or {}).get("tiers_version") or "v1.4"),
            "source_cases_json": "results/gemini/out_think_gemini.json",
            "source_episodes_gz": "results/gemini/ladder_episodes.jsonl.gz",
            "case_count": len(analyzed_cases),
            "level_run_count": total_runs,
            "hold_fire_cases": hold_fire_count,
            "accuse_cases": accuse_count,
            "models": models_seen,
            "thinking_levels": ordered_levels,
        },
        "summary": summary,
        "cases": analyzed_cases,
    }


def render_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=True) + "\n"


def validate_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    meta = payload.get("meta")
    summary = payload.get("summary")
    cases = payload.get("cases")
    if not isinstance(meta, dict):
        return ["missing meta dict"]
    if not isinstance(summary, dict):
        return ["missing summary dict"]
    if not isinstance(cases, list) or len(cases) != 12:
        return ["cases must be a list of exactly 12 playable cases"]

    if int(meta.get("case_count", -1)) != len(cases):
        errors.append("meta.case_count does not match len(cases)")

    seen_ids: set[str] = set()
    rec_calls: set[str] = set()
    levels_covered: set[str] = set()
    total_runs = 0

    for idx, c in enumerate(cases):
        cid = str(c.get("id") or f"idx_{idx}")
        if cid in seen_ids:
            errors.append(f"duplicate case id {cid}")
        seen_ids.add(cid)

        for req_key in (
            "id",
            "title",
            "model",
            "anchor_level",
            "tier",
            "seed",
            "decision_day",
            "decision_step",
            "n_suspects",
            "prior_entropy_bits",
            "posterior_entropy_bits",
            "mutual_information_bits",
            "entropy_reduction_ratio",
            "effective_suspects",
            "eliminated_count",
            "consistent_count",
            "eliminated_fraction",
            "value_at_decision",
            "wrong_accusation_score",
            "true_mole",
            "true_mole_prob",
            "top_suspect",
            "top_prob",
            "break_even_prob",
            "ev_accuse_top",
            "ev_hold_fire",
            "recommended_call",
            "solver_final_score",
            "thinking_levels",
        ):
            if req_key not in c:
                errors.append(f"{cid}: missing key {req_key}")

        if errors:
            continue

        tier = str(c["tier"])
        n_sus = int(c["n_suspects"])
        expected_n = 40 if tier == "hard" else (20 if tier == "medium" else -1)
        if n_sus != expected_n:
            errors.append(f"{cid}: expected {expected_n} suspects for {tier}, got {n_sus}")

        prior_h = float(c["prior_entropy_bits"])
        post_h = float(c["posterior_entropy_bits"])
        mi_h = float(c["mutual_information_bits"])
        err_ratio = float(c["entropy_reduction_ratio"])
        eff_sus = float(c["effective_suspects"])

        if abs(prior_h - math.log2(max(1, n_sus))) > 1e-5:
            errors.append(f"{cid}: prior_entropy_bits {prior_h} != log2({n_sus})")
        if post_h < -1e-9 or post_h > prior_h + 1e-5:
            errors.append(f"{cid}: posterior_entropy_bits {post_h} out of [0, {prior_h}]")
        if mi_h < -1e-9 or abs((prior_h - post_h) - mi_h) > 2e-5:
            errors.append(f"{cid}: mutual_information_bits {mi_h} != prior - posterior")
        if prior_h > 0.0 and abs(err_ratio - (mi_h / prior_h)) > 2e-5:
            errors.append(f"{cid}: entropy_reduction_ratio {err_ratio} mismatch")
        if abs(eff_sus - (2.0 ** post_h)) > 1e-4:
            errors.append(f"{cid}: effective_suspects {eff_sus} != 2**posterior_entropy_bits")

        elim_cnt = int(c["eliminated_count"])
        cons_cnt = int(c["consistent_count"])
        elim_frac = float(c["eliminated_fraction"])
        if elim_cnt < 0 or elim_cnt > n_sus or cons_cnt != (n_sus - elim_cnt):
            errors.append(f"{cid}: invalid eliminated/consistent counts ({elim_cnt}, {cons_cnt})")
        if abs(elim_frac - (elim_cnt / max(1, n_sus))) > 2e-5 or not (0.0 <= elim_frac <= 1.0):
            errors.append(f"{cid}: eliminated_fraction {elim_frac} mismatch")

        v_val = float(c["value_at_decision"])
        if not (0.0 < v_val <= 1.0):
            errors.append(f"{cid}: invalid value_at_decision {v_val}")
        be_prob = float(c["break_even_prob"])
        expected_be = 1.0 / (1.0 + v_val)
        if abs(be_prob - expected_be) > 2e-5:
            errors.append(f"{cid}: break_even_prob {be_prob} != 1/(1+V) ({expected_be})")

        top_p = float(c["top_prob"])
        mole_p = float(c["true_mole_prob"])
        if not (0.0 <= top_p <= 1.0) or not (0.0 <= mole_p <= 1.0):
            errors.append(f"{cid}: probability out of [0, 1]")

        ev_acc = float(c["ev_accuse_top"])
        expected_ev = (top_p * v_val) - (1.0 - top_p)
        if abs(ev_acc - expected_ev) > 2e-5:
            errors.append(f"{cid}: ev_accuse_top {ev_acc} != p*V - (1-p) ({expected_ev})")

        rec = str(c["recommended_call"])
        expected_rec = "accuse" if top_p >= be_prob else "hold_fire"
        if rec != expected_rec:
            errors.append(f"{cid}: recommended_call {rec} != {expected_rec}")
        rec_calls.add(rec)

        t_levels = c["thinking_levels"]
        if not isinstance(t_levels, list) or len(t_levels) < 2:
            errors.append(f"{cid}: fewer than 2 thinking_levels")
            continue

        sol_score = float(c["solver_final_score"])
        for lv in t_levels:
            total_runs += 1
            lv_name = str(lv.get("thinking_level") or "")
            levels_covered.add(lv_name)
            call_t = str(lv.get("call_at_t") or "")
            if call_t not in {"accuse", "hold_fire"}:
                errors.append(f"{cid}/{lv_name}: invalid call_at_t {call_t}")
            if str(lv.get("recommended_call")) != rec:
                errors.append(f"{cid}/{lv_name}: recommended_call mismatch")
            matched = lv.get("matched_recommended_call")
            if not isinstance(matched, bool) or matched != (call_t == rec):
                errors.append(f"{cid}/{lv_name}: matched_recommended_call mismatch")

            bin_reg = float(lv.get("binary_call_regret_ev", -1.0))
            dec_reg = float(lv.get("decision_regret_ev", -1.0))
            expected_bin = 0.0 if (call_t == rec) else abs(ev_acc)
            if abs(bin_reg - expected_bin) > 3e-5:
                errors.append(f"{cid}/{lv_name}: binary_call_regret_ev {bin_reg} != {expected_bin}")
            if dec_reg < -1e-9 or dec_reg + 1e-5 < bin_reg:
                errors.append(f"{cid}/{lv_name}: invalid decision_regret_ev {dec_reg}")

            sc = float(lv.get("score", 0.0))
            delta = float(lv.get("score_delta_vs_solver", 0.0))
            real_reg = float(lv.get("realized_regret_vs_solver", -1.0))
            if abs(delta - (sc - sol_score)) > 2e-4:
                errors.append(f"{cid}/{lv_name}: score_delta_vs_solver {delta} != {sc - sol_score}")
            if abs(real_reg - max(0.0, sol_score - sc)) > 2e-4:
                errors.append(f"{cid}/{lv_name}: realized_regret_vs_solver mismatch")

            ep_h = float(lv.get("episode_final_entropy_bits", -1.0))
            if ep_h < -1e-9 or ep_h > prior_h + 1e-5:
                errors.append(f"{cid}/{lv_name}: episode_final_entropy_bits {ep_h} out of bounds")

    if int(meta.get("level_run_count", -1)) != total_runs:
        errors.append(f"meta.level_run_count {meta.get('level_run_count')} != {total_runs}")
    if rec_calls != {"accuse", "hold_fire"}:
        errors.append(f"expected both accuse and hold_fire recommended_call values, got {sorted(rec_calls)}")
    for req_lv in THINKING_LEVEL_ORDER:
        if req_lv not in levels_covered:
            errors.append(f"missing thinking level {req_lv} across cases")

    if not errors:
        expected_summary = summarize_cases(cases)
        if summary != expected_summary:
            errors.append("summary does not match deterministic aggregation over cases")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canary.gemini.outthink_regret")
    parser.add_argument("--out", "--json-out", dest="out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cases-json", type=Path, default=DEFAULT_CASES_JSON)
    parser.add_argument("--episodes-gz", type=Path, default=DEFAULT_EPISODES_GZ)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = build_payload(cases_json=args.cases_json, episodes_gz=args.episodes_gz)
    except Exception as exc:
        sys.stderr.write(f"ERROR: failed to build regret payload: {exc}\n")
        return 1

    errors = validate_payload(payload)
    if errors:
        for err in errors:
            sys.stderr.write(f"ERROR: {err}\n")
        return 1

    expected_json = render_json_text(payload)
    if EM_DASH in expected_json or EN_DASH in expected_json:
        sys.stderr.write("ERROR: dash character found in json\n")
        return 1
    if FORBIDDEN_NET in expected_json:
        sys.stderr.write("ERROR: forbidden network call token in json\n")
        return 1

    if args.check:
        if not args.out.is_file():
            sys.stderr.write(f"ERROR: missing {args.out}\n")
            return 1
        actual_json = args.out.read_text(encoding="utf-8")
        try:
            actual_doc = json.loads(actual_json)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"ERROR: invalid JSON in {args.out}: {exc}\n")
            return 1
        actual_errors = validate_payload(actual_doc)
        if actual_errors:
            for err in actual_errors:
                sys.stderr.write(f"ERROR: {err}\n")
            return 1
        if actual_json != expected_json:
            sys.stderr.write(f"ERROR: {args.out} is out of date with deterministic build\n")
            return 1
        sys.stdout.write(
            f"OK: {len(payload['cases'])} cases, {payload['meta']['level_run_count']} ladder runs verified.\n"
        )
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(expected_json, encoding="utf-8")
    sys.stdout.write(
        f"Wrote {args.out} ({len(payload['cases'])} cases, {payload['meta']['level_run_count']} ladder runs).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
