from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import math
import os
import random
import re
import statistics as st
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary import rules
from canary.analysis.accuse import audit_episode
from canary.analysis.gap import mean_ci
from canary.analysis.tags import to_result
from canary.baselines import GrokTactics, Heuristic, _params_from_instruction
from canary.env import Env
from canary.forge.fitness import default_solver_factory, evaluate
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical, default_strategy_json
from canary.mole.dsl import DEFAULT_STRATEGY, OPS, MoleStrategy, MoleView
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts
from canary.types import INVESTIGATIVE_TOOLS, Step

HASH_MARK = chr(35)
EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_PREREG_GPT55_PREFIX = "cf394894"
PRIMARY_SEEDS: tuple[int, ...] = tuple(range(30))
MIN_SOLVER_ACC = 0.85

PROSE_ACCUSE_RX = re.compile(r"\bAccusing\s+(e\d{2})\b", re.IGNORECASE)

CADENCE_EVADER_SLEEPER_V14: dict[str, Any] = {
    "name": "cadence_evader_sleeper_v14",
    "rules": [
        {
            "if": [["i_am_restricted", "==", 1]],
            "then": {"leak": "none", "frame": "most_restricted_peer"},
        },
        {
            "if": [["day", "<=", 8], ["recent_low_recipient_docs", ">=", 2]],
            "then": {"leak": "most_recipients", "frame": "decoy"},
        },
        {
            "if": [["n_restricted_colleagues", ">=", 1], ["recent_low_recipient_docs", ">=", 1]],
            "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
        },
    ],
    "default": {"leak": "random_seeded", "frame": "none"},
}


def compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    payload = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def boot_ratio(f_vals: list[float], s_vals: list[float], b_resamples: int = 10000, rng_seed: int = 0) -> tuple[float, float]:
    rng = random.Random(rng_seed)
    randrange = rng.randrange
    n = len(f_vals)
    inv_n = 1.0 / float(n)
    ratios: list[float] = []
    append = ratios.append
    for _ in range(b_resamples):
        sf = 0.0
        ss = 0.0
        for _ in range(n):
            idx = randrange(n)
            sf += f_vals[idx]
            ss += s_vals[idx]
        ms = ss * inv_n
        if ms > 0.0:
            append((sf * inv_n) / ms)
    ratios.sort()
    return ratios[int(0.025 * len(ratios))], ratios[int(0.975 * len(ratios)) - 1]


def interview_kl_nats(p0: float, lr: float) -> float:
    pm = min(0.999999, p0 * lr)
    return pm * math.log(pm / p0) + (1.0 - pm) * math.log((1.0 - pm) / (1.0 - p0))


def canary_mi_nats(accuracy: float, k_variants: int) -> float:
    flip = (1.0 - accuracy) / float(k_variants - 1)
    return math.log(float(k_variants)) + accuracy * math.log(accuracy) + (1.0 - accuracy) * math.log(flip)


def blackwell_garbling_hard() -> dict[str, Any]:
    hard = rules.TIERS["hard"]
    q_acc = float(hard.fingerprint_accuracy)
    flip = (1.0 - q_acc) / float(hard.max_variants - 1)
    p0 = float(hard.p_evasive_innocent)
    pm = p0 * float(hard.interview_lr)
    denom = q_acc - flip
    g_non_a = p0 - (flip / denom) * (pm - p0)
    g_a = pm + ((1.0 - q_acc) / denom) * (pm - p0)
    row_mole = [
        q_acc * g_a + 2.0 * flip * g_non_a,
        q_acc * (1.0 - g_a) + 2.0 * flip * (1.0 - g_non_a),
    ]
    row_inn = [
        flip * g_a + (q_acc + flip) * g_non_a,
        flip * (1.0 - g_a) + (q_acc + flip) * (1.0 - g_non_a),
    ]
    err = max(
        abs(row_mole[0] - pm),
        abs(row_mole[1] - (1.0 - pm)),
        abs(row_inn[0] - p0),
        abs(row_inn[1] - (1.0 - p0)),
    )
    mi_can = canary_mi_nats(q_acc, int(hard.max_variants))
    kl_iv = interview_kl_nats(p0, float(hard.interview_lr))
    return {
        "g_match_evasive": round(g_a, 8),
        "g_match_rational": "224/925",
        "g_mismatch_evasive": round(g_non_a, 8),
        "g_mismatch_rational": "184/925",
        "max_reconstruction_err": err,
        "canary_mi_nats": round(mi_can, 6),
        "interview_kl_nats": round(kl_iv, 6),
        "mi_to_kl_ratio": round(mi_can / kl_iv, 2),
    }


def steps_of_episode(ep: dict[str, Any]) -> list[Step]:
    return [
        Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")})
        for s in (ep.get("steps") or [])
    ]


def replay_episode(seed: int, steps: list[Step], upto: int | None = None, accuse_emp: str | None = None) -> Env:
    env = Env("hard", seed)
    seq = steps[:upto] if upto is not None else steps
    for stp in seq:
        if env.done:
            break
        env.call(stp.tool, stp.args or {})
    if accuse_emp is not None and not env.done:
        env.call("accuse", {"employee": accuse_emp})
    return env


def consistent_set_from_public_steps(all_employees: list[str], steps: list[Step], upto: int) -> list[str]:
    asg: dict[str, dict[str, str]] = {}
    reg_docs: dict[str, list[str]] = {}
    last_feed_items: list[dict[str, Any]] = []
    for stp in steps[:upto]:
        res = stp.result or {}
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        if stp.tool == "plant_canary":
            cid = data.get("canary_id")
            if cid:
                asg[str(cid)] = dict((stp.args or {}).get("assignment") or {})
        elif stp.tool == "list_documents":
            for doc in data.get("documents") or []:
                if not doc.get("is_canary"):
                    reg_docs[str(doc["doc_id"])] = list(doc.get("recipients") or [])
        elif stp.tool == "check_leak_feed":
            last_feed_items = list(data.get("items") or [])

    cand = set(all_employees)
    for item in last_feed_items:
        doc_id = str(item.get("doc_id") or "")
        variant = item.get("variant")
        if variant is not None and doc_id in asg:
            cand &= {emp for emp, lab in asg[doc_id].items() if lab == variant}
        elif doc_id in reg_docs:
            cand &= set(reg_docs[doc_id])
    return sorted(cand)


def consistent_set_from_env(env: Env, steps: list[Step], upto: int) -> list[str]:
    asg = {
        (s.result.get("data") or {}).get("canary_id"): dict((s.args or {}).get("assignment") or {})
        for s in steps[:upto]
        if s.tool == "plant_canary" and bool((s.result or {}).get("ok"))
    }
    feed: list[dict[str, Any]] = []
    for s in steps[:upto]:
        if s.tool == "check_leak_feed" and bool((s.result or {}).get("ok")):
            feed = list(((s.result or {}).get("data") or {}).get("items") or [])
    docs = env._doc_by_id
    cand = set(env._ids)
    for it in feed:
        if it.get("variant") is not None and it["doc_id"] in asg:
            cand &= {e for e, lab in asg[it["doc_id"]].items() if lab == it["variant"]}
        elif it["doc_id"] in docs:
            cand &= set(docs[it["doc_id"]].get("recipients") or [])
    return sorted(cand)


def daily_action_profile(steps: list[Step]) -> list[dict[str, Any]]:
    by_day: dict[int, dict[str, Any]] = {}
    for stp in steps:
        day_num = int(stp.day or 1)
        row = by_day.setdefault(
            day_num,
            {"day": day_num, "actions": 0, "canaries": 0, "interviews": 0, "limit_hit": False},
        )
        ok_flag = bool((stp.result or {}).get("ok"))
        if stp.tool in INVESTIGATIVE_TOOLS and ok_flag:
            row["actions"] += 1
        if stp.tool == "plant_canary" and ok_flag:
            row["canaries"] += 1
        if stp.tool == "interview" and ok_flag:
            row["interviews"] += 1
        if "daily action limit" in str((stp.result or {}).get("error") or ""):
            row["limit_hit"] = True
    return [by_day[k] for k in sorted(by_day)]


def load_v14_hard_cohort(root: Path, pattern: str, agent_id: str, seeds: Iterable[int] = PRIMARY_SEEDS) -> dict[int, dict[str, Any]]:
    seed_set = set(int(s) for s in seeds)
    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    out: dict[int, dict[str, Any]] = {}
    for fpath in sorted(glob.glob(str(v14_dir / pattern / "episodes.jsonl"))):
        for line in Path(fpath).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if (
                ep.get("agent") == agent_id
                and ep.get("tier") == "hard"
                and int(ep.get("seed", -1)) in seed_set
                and (ep.get("meta") or {}).get("valid") is not False
            ):
                out[int(ep["seed"])] = ep
    return out


def extract_opencode_final_text(transcript_path: Path, include_usage: bool = False) -> dict[str, Any]:
    if not transcript_path.is_file():
        return {"final_text": "", "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cost_usd": 0.0}
    final_text = ""
    in_tok = 0
    out_tok = 0
    reas_tok = 0
    cost_usd = 0.0
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        if not include_usage and '"text"' not in line:
            continue
        obj = json.loads(line)
        kind = obj.get("type")
        part = obj.get("part") or {}
        if kind == "text":
            txt = str(part.get("text") or "").strip()
            if txt and not txt.startswith("thought\n"):
                final_text = txt
        elif include_usage and kind == "step_finish":
            tok = part.get("tokens") or {}
            in_tok += int(tok.get("input") or 0)
            out_tok += int(tok.get("output") or 0)
            reas_tok += int(tok.get("reasoning") or 0)
            cost_usd += float(part.get("cost") or 0.0)
    return {
        "final_text": final_text,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "reasoning_tokens": reas_tok,
        "cost_usd": round(cost_usd, 6),
    }


def compute_episode_posterior_and_ev(ep: dict[str, Any], steps: list[Step] | None = None) -> tuple[float | None, float]:
    if not ep.get("accused"):
        return None, 0.0
    ep_res = to_result(ep) if steps is None else to_result({**ep, "steps": []})
    if steps is not None:
        ep_res.steps = steps
    audited = audit_episode(ep_res)
    p_val = audited["p_accused"]
    meta = ep.get("meta") or {}
    v_val = meta.get("V", meta.get("V_final"))
    if p_val is None or v_val is None:
        raise ValueError(f"missing p_accused or V metadata on seed {ep.get('seed')}")
    ev = float(p_val) * float(v_val) - (1.0 - float(p_val))
    return float(p_val), ev


def audit_single_cohort(
    cohort_key: str,
    display_label: str,
    episodes_by_seed: dict[int, dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
    solver_p_and_ev: dict[int, tuple[float | None, float]],
    transcript_dir: Path | None = None,
    fast_replay: bool = False,
) -> dict[str, Any]:
    seeds = sorted(episodes_by_seed)
    if tuple(seeds) != PRIMARY_SEEDS:
        raise ValueError(f"{cohort_key}: expected seeds 0..29, got {seeds}")
    all_emps = [f"e{i:02d}" for i in range(40)]
    fast_replay_seeds = {0, 17}

    scores: list[float] = []
    solver_scores: list[float] = []
    p_accused_list: list[float] = []
    luck_evs: list[float] = []
    solver_luck_evs: list[float] = []
    cset_sizes_at_accuse: list[int] = []
    accuse_days: list[int] = []
    tool_totals: Counter[str] = Counter()
    ok_tool_totals: Counter[str] = Counter()
    total_calls_per_ep: list[int] = []
    day1_canary_starts = 0
    correct_count = 0
    wrong_count = 0
    no_accuse_count = 0

    total_days = 0
    two_canary_days = 0
    one_canary_days = 0
    zero_canary_days = 0
    pre_terminal_days = 0
    pre_terminal_two_canary = 0
    pre_terminal_one_canary = 0
    pre_terminal_zero_canary = 0
    under_planted_days = 0
    under_planted_full_budget = 0

    prose_action_slips: list[dict[str, Any]] = []
    per_seed_records: dict[int, dict[str, Any]] = {}

    replayed_count = 0
    for s in seeds:
        ep = episodes_by_seed[s]
        sol_ep = solver_by_seed[s]
        steps = steps_of_episode(ep)
        env: Env | None = None
        if not fast_replay or s in fast_replay_seeds:
            env = replay_episode(s, steps)
            replayed_count += 1
            replayed_score = float(env.score())
            if abs(replayed_score - float(ep["score"])) > 1e-9:
                raise ValueError(f"{cohort_key} seed {s}: replay score {replayed_score} != recorded {ep['score']}")

        scores.append(float(ep["score"]))
        solver_scores.append(float(sol_ep["score"]))

        ep_tools = Counter(stp.tool for stp in steps)
        ep_ok_tools = Counter(stp.tool for stp in steps if bool((stp.result or {}).get("ok")))
        tool_totals.update(ep_tools)
        ok_tool_totals.update(ep_ok_tools)
        total_calls_per_ep.append(sum(ep_tools.values()))

        if any(stp.tool == "plant_canary" and stp.day == 1 and bool((stp.result or {}).get("ok")) for stp in steps):
            day1_canary_starts += 1

        acc_idx = next((i for i, stp in enumerate(steps) if stp.tool == "accuse" and bool((stp.result or {}).get("ok"))), None)
        upto = acc_idx if acc_idx is not None else len(steps)
        cset = consistent_set_from_env(env, steps, upto) if env is not None else consistent_set_from_public_steps(all_emps, steps, upto)

        p_val, pe_val = solver_p_and_ev[s] if cohort_key == "solver" else compute_episode_posterior_and_ev(ep, steps)
        _, sol_pe_val = solver_p_and_ev[s]
        luck_evs.append(pe_val)
        solver_luck_evs.append(sol_pe_val)

        if ep.get("accused"):
            accuse_days.append(int(ep.get("final_day") or 0))
            cset_sizes_at_accuse.append(len(cset))
            if p_val is not None:
                p_accused_list.append(p_val)
            if ep.get("correct"):
                correct_count += 1
            else:
                wrong_count += 1
        else:
            no_accuse_count += 1

        dy_rows = daily_action_profile(steps)
        for idx_d, drow in enumerate(dy_rows):
            total_days += 1
            if drow["canaries"] >= 2:
                two_canary_days += 1
            elif drow["canaries"] == 1:
                one_canary_days += 1
            else:
                zero_canary_days += 1
            if drow["canaries"] < 2:
                under_planted_days += 1
                if drow["actions"] >= 8 or drow["limit_hit"]:
                    under_planted_full_budget += 1
            if idx_d < len(dy_rows) - 1:
                pre_terminal_days += 1
                if drow["canaries"] >= 2:
                    pre_terminal_two_canary += 1
                elif drow["canaries"] == 1:
                    pre_terminal_one_canary += 1
                else:
                    pre_terminal_zero_canary += 1

        tx_info = extract_opencode_final_text(transcript_dir / f"{s}.txt") if transcript_dir is not None else {"final_text": ""}
        prose_match = PROSE_ACCUSE_RX.search(tx_info["final_text"]) if acc_idx is None else None
        prose_emp = prose_match.group(1).lower() if prose_match is not None else None

        if acc_idx is None and prose_emp is not None:
            if env is None:
                env = replay_episode(s, steps)
                replayed_count += 1
            sp = SolverPolicy(rules.tier_params_for_episode("hard", steps))
            for stp in steps:
                sp._ingest(stp)
            post = sp.belief()
            p_prose = round(float(post.get(prose_emp, 0.0)), 3)
            p_top = round(float(max(post.values())) if post else 0.0, 3)
            env_cf = replay_episode(s, steps, accuse_emp=prose_emp)
            cf_score = float(env_cf.score())
            cf_correct = bool(env._world.mole == prose_emp)
            cf_pe = p_prose * cf_score - (1.0 - p_prose) if cf_correct else p_prose * abs(cf_score) - (1.0 - p_prose)
            last_day_seen = int(steps[-1].day) if steps else 0
            prose_action_slips.append(
                {
                    "seed": s,
                    "prose_accused": prose_emp,
                    "true_mole_matched": cf_correct,
                    "stop_day": last_day_seen,
                    "tool_calls": len(steps),
                    "consistent_set_size": len(cset),
                    "consistent_set_is_singleton_target": (cset == [prose_emp]),
                    "solver_posterior_p_prose": p_prose,
                    "solver_posterior_p_top": p_top,
                    "counterfactual_score_if_accused": round(cf_score, 6),
                    "counterfactual_luck_adjusted_ev": round(cf_pe, 6),
                    "final_text": tx_info["final_text"],
                }
            )

        per_seed_records[s] = {
            "seed": s,
            "score": float(ep["score"]),
            "accused": ep.get("accused"),
            "correct": bool(ep.get("correct")),
            "end_reason": ep.get("end_reason"),
            "final_day": int(ep.get("final_day") or 0),
            "consistent_set_size": len(cset),
            "p_accused": p_val,
            "luck_adjusted_ev": pe_val,
            "prose_slip_target": prose_emp,
            "final_text": tx_info.get("final_text", ""),
        }

    n = len(seeds)
    b_resamples = 500 if fast_replay else 10000
    mean_score, ci_score = mean_ci(scores)
    mean_solver = sum(solver_scores) / float(n)
    diff_mean, diff_ci = mean_ci([a - b for a, b in zip(scores, solver_scores)])
    is_solver = cohort_key == "solver"
    raw_ratio = (sum(scores) / sum(solver_scores)) if sum(solver_scores) > 0 else float("nan")
    raw_lo, raw_hi = (1.0, 1.0) if is_solver else boot_ratio(scores, solver_scores, b_resamples=b_resamples)
    pe_mean = sum(luck_evs) / float(n)
    pe_ratio = (sum(luck_evs) / sum(solver_luck_evs)) if sum(solver_luck_evs) > 0 else float("nan")
    pe_lo, pe_hi = (1.0, 1.0) if is_solver else boot_ratio(luck_evs, solver_luck_evs, b_resamples=b_resamples)

    tot_calls_sum = sum(total_calls_per_ep)
    tot_canaries = int(tool_totals.get("plant_canary", 0))
    ok_canaries = int(ok_tool_totals.get("plant_canary", 0))
    tot_interviews = int(tool_totals.get("interview", 0))
    ok_interviews = int(ok_tool_totals.get("interview", 0))

    return {
        "cohort": cohort_key,
        "label": display_label,
        "n": n,
        "replay_verified_count": replayed_count,
        "score_mean": round(mean_score, 6),
        "score_ci95": round(ci_score, 6),
        "solver_same_seeds_mean": round(mean_solver, 6),
        "raw_ratio_to_solver": round(raw_ratio, 6),
        "raw_ratio_boot95": [round(raw_lo, 6), round(raw_hi, 6)],
        "paired_diff_mean": round(diff_mean, 6),
        "paired_diff_ci95": round(diff_ci, 6),
        "luck_adjusted_mean": round(pe_mean, 6),
        "luck_adjusted_ratio_to_solver": round(pe_ratio, 6),
        "luck_adjusted_boot95": [round(pe_lo, 6), round(pe_hi, 6)],
        "total_canaries": tot_canaries,
        "canaries_per_ep": round(tot_canaries / float(n), 4),
        "accepted_ok_canaries": ok_canaries,
        "accepted_ok_canaries_per_ep": round(ok_canaries / float(n), 4),
        "total_interviews": tot_interviews,
        "interviews_per_ep": round(tot_interviews / float(n), 4),
        "accepted_ok_interviews": ok_interviews,
        "accepted_ok_interviews_per_ep": round(ok_interviews / float(n), 4),
        "interview_share_of_calls": round(tot_interviews / float(max(1, tot_calls_sum)), 6),
        "total_tool_calls": tot_calls_sum,
        "tool_calls_per_ep": round(tot_calls_sum / float(n), 4),
        "read_access_logs_total": int(tool_totals.get("read_access_logs", 0)),
        "message_tools_total": int(tool_totals.get("search_messages", 0) + tool_totals.get("read_message", 0)),
        "restrict_access_total": int(tool_totals.get("restrict_access", 0)),
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "no_accusation_count": no_accuse_count,
        "accusation_precision": round(correct_count / float(max(1, correct_count + wrong_count)), 6),
        "overall_accuracy": round(correct_count / float(n), 6),
        "accused_rate": round((correct_count + wrong_count) / float(n), 6),
        "accuse_day_mean": round(st.mean(accuse_days), 4) if accuse_days else 0.0,
        "accuse_day_1dp_str": f"{st.mean(accuse_days):.1f}" if accuse_days else "nan",
        "day1_canary_start_count": day1_canary_starts,
        "day1_canary_start_rate": round(day1_canary_starts / float(n), 6),
        "consistent_set_at_accuse_mean": round(st.mean(cset_sizes_at_accuse), 4) if cset_sizes_at_accuse else 0.0,
        "consistent_set_singleton_count": sum(1 for x in cset_sizes_at_accuse if x == 1),
        "consistent_set_ge2_count": sum(1 for x in cset_sizes_at_accuse if x >= 2),
        "solver_posterior_p_accused_mean": round(st.mean(p_accused_list), 6) if p_accused_list else 0.0,
        "solver_posterior_p_accused_min": round(min(p_accused_list), 6) if p_accused_list else 0.0,
        "below_060_posterior_count": sum(1 for p in p_accused_list if p < 0.6),
        "cadence_days": {
            "total_days": total_days,
            "two_canary_days": two_canary_days,
            "one_canary_days": one_canary_days,
            "zero_canary_days": zero_canary_days,
            "pre_terminal_days": pre_terminal_days,
            "pre_terminal_two_canary_days": pre_terminal_two_canary,
            "pre_terminal_one_canary_days": pre_terminal_one_canary,
            "pre_terminal_zero_canary_days": pre_terminal_zero_canary,
            "pre_terminal_two_canary_rate": round(pre_terminal_two_canary / float(max(1, pre_terminal_days)), 6),
            "under_planted_days": under_planted_days,
            "under_planted_full_budget_days": under_planted_full_budget,
        },
        "prose_action_slips": prose_action_slips,
        "per_seed": per_seed_records,
    }


def render_behaviour_table_lines(cohort_reports: list[dict[str, Any]]) -> list[str]:
    rows_out: list[str] = []
    for rep in cohort_reports:
        iv_pct = f"{100.0 * rep['interview_share_of_calls']:.0f}%"
        calls_str = f"{rep['tool_calls_per_ep']:.0f}"
        cwn = f"{rep['correct_count']} / {rep['wrong_count']} / {rep['no_accusation_count']}"
        rows_out.append(
            f"| {rep['label']} | {rep['n']} | {rep['score_mean']:+.3f} | {rep['canaries_per_ep']:.1f} | "
            f"{rep['interviews_per_ep']:.1f} | {iv_pct} | {calls_str} | {rep['accuse_day_1dp_str']} | {cwn} |"
        )
    return rows_out


def verify_committed_tables_parity(root: Path, cohorts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    beh_path = root / "results" / "behaviour_compare_v1.4.md"
    beh_text = beh_path.read_text(encoding="utf-8")
    expected_rows = render_behaviour_table_lines([cohorts["solver"], cohorts["gpt55"], cohorts["gemini"]])
    actual_rows = [ln.strip() for ln in beh_text.splitlines() if ln.strip().startswith("| ") and not ln.strip().startswith("| agent |")]
    behaviour_exact_match = (actual_rows == expected_rows)

    pt_path = root / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json"
    pt_rows = json.loads(pt_path.read_text(encoding="utf-8"))
    by_group_tier = {(r["group"], r["tier"], r["label"][:24]): r for r in pt_rows}

    gpt_pt = next(r for r in pt_rows if r["group"] == "v1.4/opencode-gpt-5.5" and r["tier"] == "hard")
    gem_pt = next(
        r for r in pt_rows
        if r["group"] == "v1.4/opencode-gemini-4-carbon" and r["tier"] == "hard" and "alternative" not in r["label"]
    )
    sol_pt = next(r for r in pt_rows if r["group"] == "v1.4/reference" and r["agent"] == "solver" and r["tier"] == "hard")

    gpt_meta_path = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard" / "meta.json"
    gpt_meta = json.loads(gpt_meta_path.read_text(encoding="utf-8"))
    gpt_sha = str(gpt_meta.get("git_sha") or "")

    reh_path = root / "results" / "harbor" / "rehearsal" / "TABLE.md"
    reh_text = reh_path.read_text(encoding="utf-8") if reh_path.is_file() else ""
    gap_doc_path = root / "docs" / "reports" / "gap.md"
    gap_doc_text = gap_doc_path.read_text(encoding="utf-8") if gap_doc_path.is_file() else ""

    checks = {
        "behaviour_compare_md_exact_rows": behaviour_exact_match,
        "gpt55_prereg_sha_prefix_cf394894": gpt_sha.startswith(EXPECTED_PREREG_GPT55_PREFIX),
        "gpt55_zero_infra_invalid": (len(gpt_meta.get("infra_invalid_attempts_excluded") or []) == 0),
        "gpt55_score_parity": abs(cohorts["gpt55"]["score_mean"] - float(gpt_pt["mean"])) < 1e-6,
        "gpt55_ci_parity": abs(cohorts["gpt55"]["score_ci95"] - float(gpt_pt["ci"])) < 1e-6,
        "gpt55_raw_ratio_parity": abs(cohorts["gpt55"]["raw_ratio_to_solver"] - float(gpt_pt["ratio"])) < 1e-6,
        "gpt55_luck_ratio_parity": abs(cohorts["gpt55"]["luck_adjusted_ratio_to_solver"] - float(gpt_pt["post_expected_ratio"])) < 1e-6,
        "gemini_score_parity": abs(cohorts["gemini"]["score_mean"] - float(gem_pt["mean"])) < 1e-6,
        "gemini_ci_parity": abs(cohorts["gemini"]["score_ci95"] - float(gem_pt["ci"])) < 1e-6,
        "gemini_raw_ratio_parity": abs(cohorts["gemini"]["raw_ratio_to_solver"] - float(gem_pt["ratio"])) < 1e-6,
        "gemini_luck_ratio_parity": abs(cohorts["gemini"]["luck_adjusted_ratio_to_solver"] - float(gem_pt["post_expected_ratio"])) < 1e-6,
        "solver_score_parity": abs(cohorts["solver"]["score_mean"] - float(sol_pt["mean"])) < 1e-6,
        "solver_ci_parity": abs(cohorts["solver"]["score_ci95"] - float(sol_pt["ci"])) < 1e-6,
        "harbor_rehearsal_5f9b3297_run3_131pct": ("9 valid" in reh_text and "131%" in reh_text and "0.496" in gap_doc_text and "0.561" in gap_doc_text),
    }
    return {
        "all_parity_checks_passed": all(checks.values()),
        "checks": checks,
        "gpt55_prereg_git_sha": gpt_sha,
        "gpt55_reported_cost_usd": float((gpt_meta.get("usage") or {}).get("cost_usd_est") or 0.0),
        "expected_behaviour_rows": expected_rows,
        "actual_behaviour_rows": actual_rows,
        "fresh_400_seeds_context": {
            "seed_range": "9000-9399",
            "n_seeds": 400,
            "gpt55_habit_reparam_solver_mean": 0.496,
            "gpt55_habit_reparam_solver_ci95": 0.036,
            "unchanged_solver_mean": 0.561,
            "unchanged_solver_ci95": 0.032,
            "ratio_to_unchanged_solver": round(0.496 / 0.561, 4),
            "seeds_0_29_reparam_mean": 0.546,
            "source_doc": "docs/reports/gap.md",
        },
    }


class FixedTwoCanaryBisector:
    name = "gpt55_cadence_bisector"

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.reset([], "")

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        parsed = _params_from_instruction(instruction)
        self.n_days = int(float(parsed.get("n_days", 21)))
        self.seen = 0
        self.emps: list[str] = []
        self.docs: dict[str, list[str]] = {}
        self.asg: dict[str, dict[str, str]] = {}
        self.feed: list[dict[str, Any]] = []
        self.day = 1
        self.V = 1.0
        self.queue: list[tuple[str, dict[str, Any]]] = []
        self.canary_seq = 0

    def _ingest(self, stp: Step) -> None:
        res = stp.result or {}
        if not res.get("ok"):
            return
        data = res.get("data") or {}
        if stp.tool == "list_employees":
            self.emps = [e["id"] if isinstance(e, dict) else e for e in data.get("employees", [])]
        elif stp.tool in ("status", "advance_day"):
            self.day = int(data.get("day", self.day))
            self.V = float(data.get("V", self.V))
        elif stp.tool == "list_documents":
            for doc in data.get("documents", []):
                self.docs[str(doc["doc_id"])] = list(doc.get("recipients") or [])
        elif stp.tool == "plant_canary":
            cid = data.get("canary_id")
            if cid:
                self.asg[str(cid)] = dict((stp.args or {}).get("assignment") or {})
        elif stp.tool == "check_leak_feed":
            self.feed = list(data.get("items") or [])

    def _consistent_and_hits(self) -> tuple[list[str], dict[str, int]]:
        cand = set(self.emps)
        canary_hits = {e: 0 for e in self.emps}
        for item in self.feed:
            did = str(item.get("doc_id") or "")
            var = item.get("variant")
            if var is not None and did in self.asg:
                matched = {e for e, lab in self.asg[did].items() if lab == var}
                for e in matched:
                    canary_hits[e] = canary_hits.get(e, 0) + 1
                if cand & matched:
                    cand &= matched
            elif did in self.docs:
                holders = set(self.docs[did])
                if cand & holders:
                    cand &= holders
        return sorted(cand), canary_hits

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        for stp in history[self.seen:]:
            self._ingest(stp)
        self.seen = len(history)
        if self.queue:
            return self.queue.pop(0)
        if not self.emps:
            self.queue = [
                ("status", {}),
                ("list_employees", {}),
                ("list_documents", {"day_from": 1, "day_to": 1}),
            ]
            return self.queue.pop(0)

        cset, chits = self._consistent_and_hits()
        if len(cset) == 1 and chits.get(cset[0], 0) >= 1:
            return ("accuse", {"employee": cset[0]})
        if self.day >= self.n_days and cset:
            if len(cset) <= 2 and self.V > 0.25:
                best = max(cset, key=lambda e: (chits.get(e, 0), e))
                return ("accuse", {"employee": best})
            return ("advance_day", {})

        pool = cset if cset else list(self.emps)
        if len(pool) > 12:
            half = min(6, max(3, len(pool) // 4))
            offset = (self.canary_seq * half) % len(pool)
            g1 = [pool[(offset + i) % len(pool)] for i in range(half)]
            g2 = [pool[(offset + half + i) % len(pool)] for i in range(half)]
            a1 = {e: "ABC"[i % 3] for i, e in enumerate(g1)}
            a2 = {e: "ABC"[i % 3] for i, e in enumerate(g2)}
        else:
            sub = pool[:9] if len(pool) > 9 else pool
            a1 = {e: "ABC"[i % 3] for i, e in enumerate(sub)}
            a2 = (
                {e: "ABC"[(i // 3) % 3] for i, e in enumerate(sub)}
                if len(sub) > 3
                else {e: "BCA"[i % 3] for i, e in enumerate(sub)}
            )
        self.canary_seq += 1
        next_day = min(self.n_days, self.day + 1)
        self.queue = [
            ("plant_canary", {"doc_title": f"Cadence Alpha d{self.day}", "assignment": a1}),
            ("plant_canary", {"doc_title": f"Cadence Beta d{self.day}", "assignment": a2}),
            ("advance_day", {}),
            ("check_leak_feed", {}),
            ("list_documents", {"day_from": next_day, "day_to": next_day}),
        ]
        return self.queue.pop(0)


class _RecordingMoleWrapper:
    def __init__(self, inner: MoleStrategy):
        self.inner = inner
        self.views: list[MoleView] = []

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, Any]:
        self.views.append(view)
        return self.inner.decide(view, rng)


def _mole_would_diverge(strat: MoleStrategy, views: Iterable[MoleView]) -> bool:
    for v in views:
        leak_sel, frame_sel = strat.default
        for conds, then in strat.rules:
            if all(OPS[op](v.feature(fname), val) for fname, op, val in conds):
                leak_sel, frame_sel = then
                break
        if leak_sel != "random_seeded" and v.docs and v.can_leak:
            return True
        if frame_sel != "none":
            if frame_sel == "random_peer" and v.peers:
                return True
            if frame_sel == "decoy" and v.decoy is not None:
                return True
            if frame_sel == "most_restricted_peer" and v.restricted_peers:
                return True
    return False


def _run_solver_on_strategy_task(args: tuple[str, int, dict[str, Any]]) -> tuple[int, float, bool]:
    tier, seed, strategy_json = args
    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    strat = MoleStrategy.from_json(strategy_json)
    env = Env(tier=tier, seed=seed, mole_strategy=strat)
    pol = SolverPolicy(tier, act_budget=30.0)
    pol.reset(env.tools_spec(), env.instruction())
    while not env.done:
        tool, targs = pol.act(env.history)
        env.call(tool, targs)
    res = env.result("solver")
    return seed, float(env.score()), bool(res.correct)


def evaluate_proposal_p18_1_cadence_evader(
    solver_by_seed: dict[int, dict[str, Any]],
    seeds: Iterable[int] = PRIMARY_SEEDS,
    workers: int | None = None,
) -> dict[str, Any]:
    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    seed_list = [int(s) for s in seeds]
    if workers is None:
        avail = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
        workers = max(1, min(4, avail))

    eva_strat = MoleStrategy.from_json(CADENCE_EVADER_SLEEPER_V14)
    if eva_strat.from_json(eva_strat.to_json()) != eva_strat:
        raise ValueError("MoleStrategy round-trip mismatch on cadence_evader_sleeper_v14")

    def_json = default_strategy_json()
    def_key = canonical(def_json)
    eva_key = canonical(CADENCE_EVADER_SLEEPER_V14)

    lookup: dict[tuple[str, int, str, str], tuple[float, bool]] = {}
    diverged_solver_seeds: list[int] = []

    for s in seed_list:
        if s in solver_by_seed:
            sol_ep = solver_by_seed[s]
            rec = _RecordingMoleWrapper(DEFAULT_STRATEGY)
            env = Env("hard", s, mole_strategy=rec)
            for stp in sol_ep["steps"]:
                env.call(stp["tool"], stp.get("args") or {})
            lookup[("hard", s, def_key, "solver")] = (float(env.score()), bool(sol_ep["correct"]))
            if _mole_would_diverge(eva_strat, rec.views):
                diverged_solver_seeds.append(s)
            else:
                lookup[("hard", s, eva_key, "solver")] = (float(env.score()), bool(sol_ep["correct"]))
        else:
            _, sc_d, ok_d = _run_solver_on_strategy_task(("hard", s, def_json))
            lookup[("hard", s, def_key, "solver")] = (sc_d, ok_d)
            diverged_solver_seeds.append(s)

    if diverged_solver_seeds:
        tasks = [("hard", s, CADENCE_EVADER_SLEEPER_V14) for s in diverged_solver_seeds]
        if workers > 1 and len(tasks) > 1:
            with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
                for s_out, sc_out, ok_out in pool.map(_run_solver_on_strategy_task, tasks):
                    lookup[("hard", s_out, eva_key, "solver")] = (sc_out, ok_out)
        else:
            for t in tasks:
                s_out, sc_out, ok_out = _run_solver_on_strategy_task(t)
                lookup[("hard", s_out, eva_key, "solver")] = (sc_out, ok_out)

    fast_investigators: dict[str, Any] = {
        "gpt55_cadence_bisector": FixedTwoCanaryBisector,
        "grok_tactics": GrokTactics,
        "hinted_heuristic": HintedHeuristic,
        "heuristic": Heuristic,
    }

    for s in seed_list:
        for inv_name, inv_cls in fast_investigators.items():
            rec_i = _RecordingMoleWrapper(DEFAULT_STRATEGY)
            env_d = Env("hard", s, mole_strategy=rec_i)
            pol_d = inv_cls(seed=s)
            pol_d.reset(env_d.tools_spec(), env_d.instruction())
            while not env_d.done:
                t_name, t_args = pol_d.act(env_d.history)
                env_d.call(t_name, t_args)
            res_d = env_d.result(inv_name)
            out_pair = (float(env_d.score()), bool(res_d.correct))
            lookup[("hard", s, def_key, inv_name)] = out_pair
            if _mole_would_diverge(eva_strat, rec_i.views):
                env_e = Env("hard", s, mole_strategy=eva_strat)
                pol_e = inv_cls(seed=s)
                pol_e.reset(env_e.tools_spec(), env_e.instruction())
                while not env_e.done:
                    t_name, t_args = pol_e.act(env_e.history)
                    env_e.call(t_name, t_args)
                res_e = env_e.result(inv_name)
                lookup[("hard", s, eva_key, inv_name)] = (float(env_e.score()), bool(res_e.correct))
            else:
                lookup[("hard", s, eva_key, inv_name)] = out_pair

    def cached_runner(tier: str, seed: int, strategy_json: dict[str, Any], agent: str, factory: Any = None) -> tuple[float, bool]:
        return lookup[(tier, int(seed), canonical(strategy_json), agent)]

    eval_default = evaluate(
        def_json,
        fast_investigators,
        default_solver_factory(),
        seed_list,
        "hard",
        runner=cached_runner,
        fitness_mode="min",
        min_solver_acc=MIN_SOLVER_ACC,
    )
    eval_evader = evaluate(
        CADENCE_EVADER_SLEEPER_V14,
        fast_investigators,
        default_solver_factory(),
        seed_list,
        "hard",
        runner=cached_runner,
        fitness_mode="min",
        min_solver_acc=MIN_SOLVER_ACC,
    )

    gpt_def = eval_default["per_investigator"]["gpt55_cadence_bisector"]
    gpt_eva = eval_evader["per_investigator"]["gpt55_cadence_bisector"]

    return {
        "proposal_id": "P18.1",
        "strategy_name": CADENCE_EVADER_SLEEPER_V14["name"],
        "strategy_json": CADENCE_EVADER_SLEEPER_V14,
        "n_seeds": len(seed_list),
        "diverged_solver_seeds": diverged_solver_seeds,
        "default_v0": eval_default,
        "cadence_evader_sleeper_v14": eval_evader,
        "catchability_passed": bool(eval_evader["feasible"] and eval_evader["solver_acc"] >= MIN_SOLVER_ACC),
        "min_regret_gain_vs_default": round(float(eval_evader["min_regret"]) - float(eval_default["min_regret"]), 6),
        "mean_regret_gain_vs_default": round(float(eval_evader["regret"]) - float(eval_default["regret"]), 6),
        "gpt55_proxy_score_drop": round(float(gpt_def["score"]) - float(gpt_eva["score"]), 6),
        "gpt55_proxy_ratio_under_evader": round(float(gpt_eva["score"]) / float(eval_evader["solver_score"]), 6),
    }


def classify_episode_public_forensics(
    steps: list[Step],
    final_text: str,
) -> dict[str, Any]:
    emps: list[str] = []
    for stp in steps:
        if stp.tool == "list_employees" and bool((stp.result or {}).get("ok")):
            raw_emps = ((stp.result or {}).get("data") or {}).get("employees") or []
            emps = [e["id"] if isinstance(e, dict) else str(e) for e in raw_emps]
            break
    if not emps:
        emps = [f"e{i:02d}" for i in range(40)]

    acc_idx = next((i for i, stp in enumerate(steps) if stp.tool == "accuse" and bool((stp.result or {}).get("ok"))), None)
    upto = acc_idx if acc_idx is not None else len(steps)
    cset = consistent_set_from_public_steps(emps, steps, upto)
    prose_match = PROSE_ACCUSE_RX.search(final_text or "") if acc_idx is None else None
    prose_target = prose_match.group(1).lower() if prose_match is not None else None

    if acc_idx is None and prose_target is not None:
        bucket = "protocol_action_slip"
    elif acc_idx is None:
        bucket = "horizon_starvation"
    elif len(cset) >= 2:
        bucket = "unisolated_epistemic_tiebreak"
    else:
        bucket = "isolated_cadence_and_cue_ignoring"

    return {
        "bucket": bucket,
        "accused_via_tool": acc_idx is not None,
        "prose_accused_target": prose_target,
        "public_consistent_set_size": len(cset),
        "public_consistent_set": cset,
    }


def evaluate_proposal_p18_2_slip_vs_bias_decomposition(
    cohorts: dict[str, dict[str, Any]],
    raw_episodes: dict[str, dict[int, dict[str, Any]]],
) -> dict[str, Any]:
    pdf_fields = tuple(PublicDayFacts.__dataclass_fields__.keys())
    forbidden_mole_fields = ("mole", "true_mole", "mole_id", "is_mole")
    zero_mole_fields_in_facts = all(f not in pdf_fields for f in forbidden_mole_fields)

    bucket_names = (
        "protocol_action_slip",
        "horizon_starvation",
        "unisolated_epistemic_tiebreak",
        "isolated_cadence_and_cue_ignoring",
    )

    sol_seeds = cohorts["solver"]["per_seed"]
    decompositions: dict[str, Any] = {}
    public_cset_exact_matches = 0
    total_classified = 0

    for key in ("gpt55", "gemini"):
        coh_seeds = cohorts[key]["per_seed"]
        counts = {b: 0 for b in bucket_names}
        pe_loss_sum = {b: 0.0 for b in bucket_names}
        raw_loss_sum = {b: 0.0 for b in bucket_names}
        seed_buckets: dict[str, list[int]] = {b: [] for b in bucket_names}

        for s in PRIMARY_SEEDS:
            ep = raw_episodes[key][s]
            steps = steps_of_episode(ep)
            rec = coh_seeds[s]
            sol_rec = sol_seeds[s]
            pub_cls = classify_episode_public_forensics(steps, rec["final_text"])
            total_classified += 1
            if pub_cls["public_consistent_set_size"] == rec["consistent_set_size"]:
                public_cset_exact_matches += 1

            bname = pub_cls["bucket"]
            counts[bname] += 1
            seed_buckets[bname].append(s)
            pe_loss_sum[bname] += float(sol_rec["luck_adjusted_ev"]) - float(rec["luck_adjusted_ev"])
            raw_loss_sum[bname] += float(sol_rec["score"]) - float(rec["score"])

        tot_pe_loss = sum(pe_loss_sum.values())
        tot_raw_loss = sum(raw_loss_sum.values())
        bucket_rows: dict[str, Any] = {}
        for b in bucket_names:
            bucket_rows[b] = {
                "episode_count": counts[b],
                "seeds": seed_buckets[b],
                "paired_luck_adjusted_loss_v": round(pe_loss_sum[b], 6),
                "paired_luck_adjusted_loss_per_ep": round(pe_loss_sum[b] / 30.0, 6),
                "share_of_luck_adjusted_deficit": round(pe_loss_sum[b] / tot_pe_loss, 6) if abs(tot_pe_loss) > 1e-9 else 0.0,
                "paired_raw_loss_v": round(raw_loss_sum[b], 6),
                "paired_raw_loss_per_ep": round(raw_loss_sum[b] / 30.0, 6),
            }

        slips = cohorts[key]["prose_action_slips"]
        slip_cf_raw = [
            next((sl["counterfactual_score_if_accused"] for sl in slips if sl["seed"] == s), coh_seeds[s]["score"])
            for s in PRIMARY_SEEDS
        ]
        slip_cf_pe = [
            next((sl["counterfactual_luck_adjusted_ev"] for sl in slips if sl["seed"] == s), coh_seeds[s]["luck_adjusted_ev"])
            for s in PRIMARY_SEEDS
        ]
        sol_raw_vec = [sol_seeds[s]["score"] for s in PRIMARY_SEEDS]
        sol_pe_vec = [sol_seeds[s]["luck_adjusted_ev"] for s in PRIMARY_SEEDS]

        decompositions[key] = {
            "total_paired_luck_adjusted_deficit_v": round(tot_pe_loss, 6),
            "total_paired_luck_adjusted_deficit_per_ep": round(tot_pe_loss / 30.0, 6),
            "total_paired_raw_deficit_v": round(tot_raw_loss, 6),
            "total_paired_raw_deficit_per_ep": round(tot_raw_loss / 30.0, 6),
            "buckets": bucket_rows,
            "slip_repaired_counterfactual": {
                "raw_mean": round(sum(slip_cf_raw) / 30.0, 6),
                "raw_ratio_to_solver": round(sum(slip_cf_raw) / sum(sol_raw_vec), 6),
                "luck_adjusted_mean": round(sum(slip_cf_pe) / 30.0, 6),
                "luck_adjusted_ratio_to_solver": round(sum(slip_cf_pe) / sum(sol_pe_vec), 6),
            },
        }

    return {
        "proposal_id": "P18.2",
        "target_module": "canary/analysis/slip_vs_bias.py",
        "zero_mole_leakage_invariant": "I(Social; Mole | PublicDayFacts) = 0",
        "public_day_facts_fields": list(pdf_fields),
        "public_day_facts_zero_mole_leakage": zero_mole_fields_in_facts,
        "public_consistent_set_exact_parity": f"{public_cset_exact_matches}/{total_classified}",
        "public_consistent_set_all_matched": (public_cset_exact_matches == total_classified),
        "decompositions": decompositions,
    }


def run_full_audit(root: Path = ROOT, workers: int | None = None, fast: bool = False) -> dict[str, Any]:
    t0 = time.monotonic()
    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    if rules.TIERS_VERSION != EXPECTED_TIERS_VERSION:
        raise ValueError(f"expected TIERS_VERSION {EXPECTED_TIERS_VERSION!r}, got {rules.TIERS_VERSION!r}")
    if v14_hash != EXPECTED_V14_HASH:
        raise ValueError(f"expected v1.4 hash {EXPECTED_V14_HASH}, got {v14_hash}")

    solver_eps = load_v14_hard_cohort(root, "reference/solver-hard-*", "solver")
    gpt55_eps = load_v14_hard_cohort(root, "opencode-gpt-5.5/hard", "opencode:openai/gpt-5.5")
    gemini_eps = load_v14_hard_cohort(root, "opencode-gemini-4-carbon/hard", "opencode:google/gemini-4-carbon")

    solver_p_and_ev = {s: compute_episode_posterior_and_ev(solver_eps[s]) for s in PRIMARY_SEEDS}

    v14_root = root / "data" / "runs" / "committed" / "v1.4"
    coh_solver = audit_single_cohort("solver", "reference solver", solver_eps, solver_eps, solver_p_and_ev, None, fast_replay=fast)
    coh_gpt55 = audit_single_cohort(
        "gpt55",
        "gpt-5.5, OpenCode over MCP",
        gpt55_eps,
        solver_eps,
        solver_p_and_ev,
        v14_root / "opencode-gpt-5.5" / "hard" / "transcripts",
        fast_replay=fast,
    )
    coh_gemini = audit_single_cohort(
        "gemini",
        "gemini-4-carbon, OpenCode over MCP",
        gemini_eps,
        solver_eps,
        solver_p_and_ev,
        v14_root / "opencode-gemini-4-carbon" / "hard" / "transcripts",
        fast_replay=fast,
    )

    cohorts = {"solver": coh_solver, "gpt55": coh_gpt55, "gemini": coh_gemini}
    parity = verify_committed_tables_parity(root, cohorts)
    blackwell = blackwell_garbling_hard()
    p18_1_seeds: Iterable[int] = (0,) if fast else PRIMARY_SEEDS
    p18_1_workers = 1 if fast else workers
    p18_1 = evaluate_proposal_p18_1_cadence_evader(solver_eps, seeds=p18_1_seeds, workers=p18_1_workers)
    p18_2 = evaluate_proposal_p18_2_slip_vs_bias_decomposition(
        cohorts,
        {"solver": solver_eps, "gpt55": gpt55_eps, "gemini": gemini_eps},
    )

    post_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    elapsed_s = round(time.monotonic() - t0, 4)

    gpt_slips = coh_gpt55["prose_action_slips"]
    slip_seeds_ok = (
        len(gpt_slips) == 2
        and [sl["seed"] for sl in gpt_slips] == [0, 17]
        and all(sl["true_mole_matched"] and sl["consistent_set_is_singleton_target"] for sl in gpt_slips)
    )
    min_regret_ok = (p18_1["min_regret_gain_vs_default"] >= 0.0) if fast else (p18_1["min_regret_gain_vs_default"] > 0.15)

    all_passed = bool(
        post_hash == EXPECTED_V14_HASH
        and parity["all_parity_checks_passed"]
        and coh_gpt55["total_canaries"] == 515
        and coh_gpt55["total_interviews"] == 125
        and coh_gpt55["correct_count"] == 28
        and coh_gpt55["wrong_count"] == 0
        and coh_gpt55["no_accusation_count"] == 2
        and coh_gemini["total_canaries"] == 255
        and coh_gemini["total_interviews"] == 2041
        and coh_gemini["correct_count"] == 25
        and coh_gemini["wrong_count"] == 4
        and coh_gemini["no_accusation_count"] == 1
        and coh_solver["total_canaries"] == 424
        and coh_solver["total_interviews"] == 0
        and coh_solver["correct_count"] == 29
        and coh_solver["wrong_count"] == 1
        and coh_solver["no_accusation_count"] == 0
        and slip_seeds_ok
        and blackwell["max_reconstruction_err"] < 1e-15
        and p18_1["catchability_passed"]
        and min_regret_ok
        and p18_1["gpt55_proxy_score_drop"] > 0.12
        and p18_2["public_day_facts_zero_mole_leakage"]
        and p18_2["public_consistent_set_all_matched"]
    )

    summary_cohorts = {}
    for k, v in cohorts.items():
        summary_cohorts[k] = {fk: fv for fk, fv in v.items() if fk != "per_seed"}

    return {
        "passed": all_passed,
        "elapsed_s": elapsed_s,
        "tiers_version": rules.TIERS_VERSION,
        "v14_frozen_hash": v14_hash,
        "blackwell_channel_dominance": blackwell,
        "cohorts": summary_cohorts,
        "committed_table_parity": parity,
        "proposal_p18_1_cadence_evader_sleeper": p18_1,
        "proposal_p18_2_action_slip_vs_epistemic_bias": p18_2,
    }


def format_human_report(report: dict[str, Any]) -> str:
    g = report["cohorts"]["gpt55"]
    m = report["cohorts"]["gemini"]
    s = report["cohorts"]["solver"]
    p1 = report["proposal_p18_1_cadence_evader_sleeper"]
    p2 = report["proposal_p18_2_action_slip_vs_epistemic_bias"]
    gpt_dec = p2["decompositions"]["gpt55"]
    gem_dec = p2["decompositions"]["gemini"]

    lines = [
        f"[{'PASS' if report['passed'] else 'FAIL'}] Cross-Family Forensics Audit: gpt-5.5 vs gemini-4-carbon vs SolverPolicy "
        f"(tiers={report['tiers_version']}, hash={report['v14_frozen_hash']}, {report['elapsed_s']:.2f}s)",
        f"  1. opencode-gpt-5.5 (n={g['n']}, pre-reg {report['committed_table_parity']['gpt55_prereg_git_sha'][:8]}): "
        f"score={g['score_mean']:+.3f} +/- {g['score_ci95']:.3f} "
        f"({100*g['raw_ratio_to_solver']:.0f}% [{100*g['raw_ratio_boot95'][0]:.0f}%, {100*g['raw_ratio_boot95'][1]:.0f}%] raw; "
        f"luck-adj {100*g['luck_adjusted_ratio_to_solver']:.0f}% [{100*g['luck_adjusted_boot95'][0]:.0f}%, {100*g['luck_adjusted_boot95'][1]:.0f}%]), "
        f"canaries={g['total_canaries']} ({g['canaries_per_ep']:.2f}/ep), interviews={g['total_interviews']} ({g['interviews_per_ep']:.2f}/ep, "
        f"{100*g['interview_share_of_calls']:.0f}% of {g['tool_calls_per_ep']:.0f} calls), {g['correct_count']}/{g['wrong_count']}/{g['no_accusation_count']}, "
        f"acc_day={g['accuse_day_1dp_str']}, P(acc)={g['solver_posterior_p_accused_mean']:.3f}.",
        f"  2. opencode-gemini-4-carbon (n={m['n']}, post-hoc locked): "
        f"score={m['score_mean']:+.3f} +/- {m['score_ci95']:.3f} "
        f"({100*m['raw_ratio_to_solver']:.0f}% [{100*m['raw_ratio_boot95'][0]:.0f}%, {100*m['raw_ratio_boot95'][1]:.0f}%] raw; "
        f"luck-adj {100*m['luck_adjusted_ratio_to_solver']:.0f}% [{100*m['luck_adjusted_boot95'][0]:.0f}%, {100*m['luck_adjusted_boot95'][1]:.0f}%]), "
        f"canaries={m['total_canaries']} ({m['canaries_per_ep']:.1f}/ep), interviews={m['total_interviews']} ({m['interviews_per_ep']:.1f}/ep, "
        f"{100*m['interview_share_of_calls']:.0f}% of {m['tool_calls_per_ep']:.0f} calls), {m['correct_count']}/{m['wrong_count']}/{m['no_accusation_count']}, "
        f"acc_day={m['accuse_day_1dp_str']}, P(acc)={m['solver_posterior_p_accused_mean']:.3f}.",
        f"  3. SolverPolicy reference (n={s['n']}): score={s['score_mean']:+.3f} +/- {s['score_ci95']:.3f}, "
        f"canaries={s['total_canaries']} ({s['canaries_per_ep']:.1f}/ep), interviews={s['total_interviews']}, "
        f"calls={s['tool_calls_per_ep']:.0f}, {s['correct_count']}/{s['wrong_count']}/{s['no_accusation_count']}, "
        f"acc_day={s['accuse_day_1dp_str']}; behaviour_compare_v1.4.md exact parity={report['committed_table_parity']['checks']['behaviour_compare_md_exact_rows']}.",
        f"  4. Proposal P18.1 ({p1['strategy_name']}): solver_acc={100*p1['cadence_evader_sleeper_v14']['solver_acc']:.1f}% (>=85% floor), "
        f"solver_score={p1['cadence_evader_sleeper_v14']['solver_score']:+.3f}, "
        f"gpt55_cadence_bisector {p1['default_v0']['per_investigator']['gpt55_cadence_bisector']['score']:+.3f} -> "
        f"{p1['cadence_evader_sleeper_v14']['per_investigator']['gpt55_cadence_bisector']['score']:+.3f} "
        f"(min_regret {p1['default_v0']['min_regret']:+.4f} -> {p1['cadence_evader_sleeper_v14']['min_regret']:+.4f}).",
        f"  5. Proposal P18.2 (Action-Slip vs Epistemic-Bias Decomposition): "
        f"gpt-5.5 luck-adj deficit={gpt_dec['total_paired_luck_adjusted_deficit_v']:+.4f} V "
        f"(slips seeds [0,17]={gpt_dec['buckets']['protocol_action_slip']['paired_luck_adjusted_loss_v']:+.4f} V, "
        f"{100*gpt_dec['buckets']['protocol_action_slip']['share_of_luck_adjusted_deficit']:.1f}%); "
        f"gemini deficit={gem_dec['total_paired_luck_adjusted_deficit_v']:+.4f} V "
        f"(slips=0.0000 V, un-isolated tie-break={gem_dec['buckets']['unisolated_epistemic_tiebreak']['paired_luck_adjusted_loss_v']:+.4f} V, "
        f"{100*gem_dec['buckets']['unisolated_epistemic_tiebreak']['share_of_luck_adjusted_deficit']:.1f}%); "
        f"PublicDayFacts zero-mole-leak={p2['public_day_facts_zero_mole_leakage']}.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay and audit cross-family cognitive-behavioral forensics on Canary v1.4 hard (gpt-5.5 vs gemini-4-carbon vs SolverPolicy)."
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    parser.add_argument("--workers", type=int, default=None, help="Worker processes for diverged SolverPolicy P18.1 seeds")
    parser.add_argument("--fast", action="store_true", help="Fast deterministic subset for <2s CI test suites")
    parser.add_argument("--check", action="store_true", help="Assert all cross-family forensic, parity, catchability, and zero-leakage gates")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument("--out-json", type=Path, default=None, help="Optional file path to write JSON report")
    args = parser.parse_args(argv)

    report = run_full_audit(root=args.root.resolve(), workers=args.workers, fast=args.fast)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_human_report(report))

    if args.check and not report["passed"]:
        return 1
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
