from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.analysis.gap import load_runs
from canary.env import Env
from canary.rules import TIERS_VERSION, tier_params, tier_params_for_episode
from canary.solver.policy import SolverPolicy, accuse_value
from canary.types import INVESTIGATIVE_TOOLS, Step

DEFAULT_JSON_REL = Path("docs/arena/data/dramatic_seeds.json")
DEFAULT_JS_REL = Path("docs/arena/data/dramatic_seeds.js")
MAX_JSON_BYTES = 100_000
DEFAULT_DUEL_SEEDS: tuple[int, ...] = (6, 26)
ALLOWED_DEV_SEED_MIN = 0
ALLOWED_DEV_SEED_MAX = 29

ENV_TOOLS: frozenset[str] = frozenset(
    {
        "status",
        "list_employees",
        "read_access_logs",
        "read_message",
        "search_messages",
        "list_documents",
        "check_leak_feed",
        "plant_canary",
        "interview",
        "restrict_access",
        "unrestrict_access",
        "advance_day",
        "accuse",
    }
)

FORBIDDEN_PRE_END_KEYS: frozenset[str] = frozenset(
    {
        "mole",
        "true_mole",
        "moleId",
        "mole_id",
        "decoy",
        "true_decoy",
        "decoy_id",
        "correct",
        "accused_correct",
        "accused",
        "true_v",
        "true_V",
        "trueV",
        "is_canary",
        "leaking_sprite_employee",
        "mole_sprite",
        "culprit_sprite",
        "leaker_employee",
        "world_seed",
        "_world",
    }
)

EMP_ID_TOKEN_RE = re.compile(r"\be\d{2,3}\b")
OC_TRUNC_RE = re.compile(
    r"\A\s*\.\.\.(\d+) bytes truncated\.\.\.\s+The tool call succeeded but the output was "
    r"truncated\. Full output saved to: "
)
OC_NO_TOOL_PREFIX = "Model tried to call unavailable tool"

CURATED_CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "tier": "hard",
        "seed": 6,
        "category": "default_duel_caught",
        "title": "Clean Canary Catch",
        "tagline": (
            "Day-1 orthogonal A/B/C canary splits isolate the insider by Day 6: "
            "gemini-4-carbon (+0.73, 57 calls) edges SolverPolicy (+0.71, 52 calls) by 0.02 trap overhead."
        ),
        "difficulty_badge": "v1.4 hard | default duel",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 26,
        "category": "default_duel_fooled",
        "title": "5% Fingerprint Flip Trap",
        "tagline": (
            "Zero canaries on Days 1-3 and 43 interviews leave gemini-4-carbon exposed on Day 10 "
            "when a 1-in-20 noisy readout flips S1 and triggers a -1.00 false accusation vs SolverPolicy +0.69 on Day 7."
        ),
        "difficulty_badge": "v1.4 hard | 5% noise trap",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 4,
        "category": "slow_burn_interview_sink",
        "title": "Interview Sink Slow Burn",
        "tagline": (
            "SolverPolicy plants from Day 1 and closes on Day 5 (+0.73, 44 calls), while gemini-4-carbon "
            "spends 84 interviews across 16 days (+0.40, 155 calls) and waits 2 days past decisive evidence."
        ),
        "difficulty_badge": "v1.4 hard | 84-interview sink",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 15,
        "category": "wrong_accusation_double_loss",
        "title": "Double-Loss Unresolved Pair",
        "tagline": (
            "Rare mutual loss (-1.00 vs -1.00): gemini-4-carbon commits on Day 12 at P=0.80 with two suspects "
            "still tied in every canary, while SolverPolicy hits an early Day 9 readout flip."
        ),
        "difficulty_badge": "v1.4 hard | unresolved pair",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 18,
        "category": "wrong_accusation_negative_ev",
        "title": "Negative-EV Horizon Gamble",
        "tagline": (
            "After zero canaries on Days 14-18 and 101 interviews, gemini-4-carbon gambles on Day 18 at "
            "P=0.63 (EV -0.08, 4 consistent suspects) for -1.00 vs SolverPolicy +0.52 on Day 13."
        ),
        "difficulty_badge": "v1.4 hard | negative-EV shot",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 1,
        "category": "wrong_accusation_late_flip",
        "title": "Late-Game 5% Flip Heartbreak",
        "tagline": (
            "Fifteen canaries and 90 interviews over 19 days reach P=0.99 before a late 5% fingerprint flip "
            "causes a -1.00 false accusation, whereas SolverPolicy closes on Day 7 for +0.69."
        ),
        "difficulty_badge": "v1.4 hard | late 5% flip",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 22,
        "category": "frugal_canary_upset",
        "title": "Frugal Canary Upset Over Solver",
        "tagline": (
            "Despite 82 interviews and waiting until Day 6 for its first trap, gemini-4-carbon (+0.64, Day 14, "
            "6 canaries) outscores SolverPolicy (+0.40, Day 15, 20 canaries costing 0.20 V)."
        ),
        "difficulty_badge": "v1.4 hard | frugal trap win",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 11,
        "category": "horizon_abstention",
        "title": "21-Day Horizon Abstention",
        "tagline": (
            "Across 212 tool calls (121 interviews, 12 alternate-day canaries), 7 suspects remain consistent "
            "at Day 21 so gemini-4-carbon abstains for 0.00 vs SolverPolicy +0.62 on Day 9."
        ),
        "difficulty_badge": "v1.4 hard | horizon abstention",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 28,
        "category": "six_day_solver_blitz",
        "title": "Six-Day Solver Blitz vs Late Traps",
        "tagline": (
            "SolverPolicy isolates and closes on Day 6 (+0.75, 10 canaries, 51 calls) while gemini-4-carbon "
            "plants zero traps on Days 1-5 and finishes 6 days later (+0.64, Day 12, 64 interviews)."
        ),
        "difficulty_badge": "v1.4 hard | 6-day pace gap",
        "recommended_mode": "duel",
    },
    {
        "tier": "hard",
        "seed": 10,
        "category": "solver_marathon_and_flash_trap",
        "title": "19-Day Solver Marathon and Flash Trap",
        "tagline": (
            "Deep careful-insider evasion forces SolverPolicy to Day 19 (+0.21, 24 canaries), gemini-4-carbon "
            "catches on Day 16 (+0.40, 8 canaries), and gemini-3.5-flash misfires on Day 20 (-1.00)."
        ),
        "difficulty_badge": "v1.4 hard | 24-canary grind",
        "recommended_mode": "duel",
    },
    {
        "tier": "medium",
        "seed": 0,
        "category": "medium_baseline_gap",
        "title": "Medium Three-Day Solver Lead",
        "tagline": (
            "Noise-free medium world (20 staff, 14 days): SolverPolicy closes on Day 7 (+0.74, 6 canaries) "
            "three days ahead of gemini-4-carbon (+0.63, Day 10, 48 interviews), while heuristic scores -1.00."
        ),
        "difficulty_badge": "v1.4 medium | 3-day lead",
        "recommended_mode": "duel",
    },
    {
        "tier": "medium",
        "seed": 4,
        "category": "medium_frontier_parity",
        "title": "Medium Frontier Parity Showcase",
        "tagline": (
            "Clean set elimination on medium: gemini-4-carbon closes on Day 6 (+0.79, 5 canaries, 25 interviews) "
            "two days ahead of SolverPolicy (+0.69, Day 8, 7 canaries), illustrating 111% raw medium parity."
        ),
        "difficulty_badge": "v1.4 medium | parity win",
        "recommended_mode": "duel",
    },
    {
        "tier": "medium",
        "seed": 20,
        "category": "medium_solver_abstention",
        "title": "Medium Solver Horizon Abstention",
        "tagline": (
            "SolverPolicy reaches the Day 14 medium horizon without crossing its stopping bar and abstains (0.00, "
            "14 canaries), while gemini-4-carbon isolates on Day 6 (+0.80, 4 canaries)."
        ),
        "difficulty_badge": "v1.4 medium | solver abstains",
        "recommended_mode": "duel",
    },
)


def norm_result(want: Any) -> Any:
    if isinstance(want, dict) and isinstance(want.get("error"), str) and want["error"].startswith("{"):
        try:
            inner = json.loads(want["error"])
        except ValueError:
            return want
        if isinstance(inner, dict) and {"ok", "data", "error"} <= set(inner):
            return inner
    return want


def client_truncated_bytes(want: Any) -> int | None:
    if isinstance(want, dict) and set(want) == {"raw"} and isinstance(want["raw"], str):
        m = OC_TRUNC_RE.match(want["raw"])
        if m:
            return int(m.group(1))
    return None


def is_client_only_step(step: dict[str, Any]) -> bool:
    res = step.get("result")
    return (
        step.get("tool") not in ENV_TOOLS
        and isinstance(res, dict)
        and res.get("ok") is False
        and isinstance(res.get("error"), str)
        and res["error"].startswith(OC_NO_TOOL_PREFIX)
    )


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def step_result_matches(raw_recorded: Any, replayed: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    flags = {
        "unwrapped_mcp_error": False,
        "detail_normalized": False,
        "truncated_checked": False,
    }
    trunc = client_truncated_bytes(raw_recorded)
    if trunc is not None:
        flags["truncated_checked"] = True
        return len(json.dumps(replayed).encode("utf-8")) == trunc, flags
    rec = norm_result(raw_recorded)
    if rec is not raw_recorded:
        flags["unwrapped_mcp_error"] = True
    if rec is None:
        return True, flags
    rep = replayed
    if (
        isinstance(rep, dict)
        and rep.get("ok") is False
        and isinstance(rep.get("data"), dict)
        and set(rep["data"]) == {"detail"}
        and isinstance(rec, dict)
        and not ("detail" in (rec.get("data") or {}))
    ):
        rep = {"ok": False, "data": {}, "error": rep.get("error")}
        flags["detail_normalized"] = True
    matched = rep == rec or _canon(rep) == _canon(rec)
    return matched, flags


def step_ok(step: Step | dict[str, Any]) -> bool:
    res = step.result if isinstance(step, Step) else step.get("result")
    if client_truncated_bytes(res) is not None:
        return True
    unwrapped = norm_result(res)
    return bool((unwrapped or {}).get("ok"))


def steps_of(ep: dict[str, Any]) -> list[Step]:
    out: list[Step] = []
    for raw in ep.get("steps") or []:
        if is_client_only_step(raw):
            continue
        out.append(Step(**{k: raw.get(k) for k in ("t", "day", "tool", "args", "result")}))
    return out


def replay_and_verify_episode(ep: dict[str, Any]) -> tuple[Env, dict[str, Any]]:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    if seed < ALLOWED_DEV_SEED_MIN or seed > ALLOWED_DEV_SEED_MAX:
        raise ValueError(f"forbidden seed outside public 0..29 dev range: {seed}")
    env = Env(tier, seed)
    step_mismatches = 0
    unwrapped_count = 0
    detail_norm_count = 0
    truncated_count = 0
    client_only_count = 0
    for idx, st in enumerate(ep.get("steps") or []):
        if is_client_only_step(st):
            client_only_count += 1
            continue
        if env.done:
            step_mismatches += 1
            raise ValueError(f"extra step after done on {ep.get('agent')} {tier}:{seed} idx={idx}")
        live_res = env.call(str(st["tool"]), st.get("args") or {})
        got_payload = {"ok": live_res.ok, "data": live_res.data, "error": live_res.error}
        ok_match, flags = step_result_matches(st.get("result"), got_payload)
        if flags["unwrapped_mcp_error"]:
            unwrapped_count += 1
        if flags["detail_normalized"]:
            detail_norm_count += 1
        if flags["truncated_checked"]:
            truncated_count += 1
        if not ok_match:
            step_mismatches += 1
            raise ValueError(f"step mismatch on {ep.get('agent')} {tier}:{seed} idx={idx} tool={st.get('tool')}")
    verdict = env.result("replay")
    if abs(float(verdict.score) - float(ep["score"])) > 1e-9:
        raise ValueError(f"score mismatch on {ep.get('agent')} {tier}:{seed}: {verdict.score} != {ep['score']}")
    if verdict.accused != ep.get("accused") or bool(verdict.correct) != bool(ep.get("correct")):
        raise ValueError(f"verdict mismatch on {ep.get('agent')} {tier}:{seed}")
    stats = {
        "step_mismatches": step_mismatches,
        "unwrapped_mcp_error_steps": unwrapped_count,
        "pre_1bc3e281_detail_normalized_steps": detail_norm_count,
        "truncated_output_steps_verified": truncated_count,
        "client_only_steps": client_only_count,
    }
    return env, stats


def _assignments(steps: list[Step]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for s in steps:
        if s.tool == "plant_canary" and step_ok(s):
            res_unwrapped = norm_result(s.result) or {}
            cid = (res_unwrapped.get("data") or {}).get("canary_id")
            if cid and isinstance(s.args, dict) and isinstance(s.args.get("assignment"), dict):
                out[str(cid)] = dict(s.args["assignment"])
    return out


def _last_feed(steps: list[Step], upto: int) -> list[dict[str, Any]]:
    feed: list[dict[str, Any]] = []
    for s in steps[:upto]:
        if s.tool == "check_leak_feed" and step_ok(s):
            res_unwrapped = norm_result(s.result) or {}
            feed = list((res_unwrapped.get("data") or {}).get("items") or [])
    return feed


def _consistent_set(env: Env, steps: list[Step], upto: int) -> list[str]:
    asg = _assignments(steps[:upto])
    docs = env._doc_by_id
    cand = set(env._ids)
    for it in _last_feed(steps, upto):
        if it.get("variant") is not None and it["doc_id"] in asg:
            cand &= {e for e, lab in asg[it["doc_id"]].items() if lab == it["variant"]}
        elif it["doc_id"] in docs:
            cand &= set(docs[it["doc_id"]].get("recipients") or [])
    return sorted(cand)


def _flips(env: Env) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    docs = env._doc_by_id
    mole_id = env._world.mole
    for it in env._feed:
        d = docs.get(it["doc_id"])
        if d and d.get("is_canary") and "variant" in it:
            true_variant = next(k for k, v in d["variants"].items() if mole_id in v)
            if it["variant"] != true_variant:
                out.append(
                    {
                        "doc_id": str(it["doc_id"]),
                        "shown_variant": str(it["variant"]),
                        "true_variant": str(true_variant),
                        "surfaced_day": int(it["surfaced_day"]),
                    }
                )
    return out


def _surfaced_canary_items(steps: list[Step]) -> list[dict[str, Any]]:
    asg = _assignments(steps)
    items: list[dict[str, Any]] = []
    for it in _last_feed(steps, len(steps)):
        did = str(it.get("doc_id") or "")
        if did in asg and it.get("variant") is not None:
            shown = str(it["variant"])
            holders = sorted(emp for emp, v in asg[did].items() if v == shown)
            items.append(
                {
                    "doc_id": did,
                    "title": str(it.get("title") or ""),
                    "surfaced_day": int(it.get("surfaced_day") or 1),
                    "shown_variant": shown,
                    "shown_holders": holders,
                }
            )
    return items


def _posterior_by_day(
    tier: str,
    steps: list[Step],
    mole_id: str,
    env: Env,
    milestones_only: bool = False,
) -> list[dict[str, Any]]:
    sp = SolverPolicy(tier_params_for_episode(tier, steps))
    rows: list[dict[str, Any]] = []
    visible_v = 1.0
    canaries = 0
    interviews = 0
    for i, st in enumerate(steps):
        res_unwrapped = norm_result(st.result) or {}
        res_data = res_unwrapped.get("data") if isinstance(res_unwrapped, dict) else {}
        if st.tool in ("status", "advance_day") and isinstance(res_data, dict) and "V" in res_data:
            visible_v = float(res_data["V"])
        if st.tool == "plant_canary" and step_ok(st):
            canaries += 1
        if st.tool == "interview":
            interviews += 1
        last_of_day = (i + 1 == len(steps)) or (steps[i + 1].day != st.day)
        if st.tool == "accuse":
            last_of_day = True
        if last_of_day:
            for prev in steps[sp.seen : i + 1]:
                if prev.tool != "accuse":
                    sp._ingest(prev)
            sp.seen = i + 1
            post = sp.belief() if sp.obs.employees else {}
            top = max(post, key=post.get) if post else None
            cset = _consistent_set(env, steps, i + 1)
            rows.append(
                {
                    "day": int(st.day),
                    "visible_v": round(visible_v, 4),
                    "canaries_cum": canaries,
                    "interviews_cum": interviews,
                    "calls_cum": i + 1,
                    "p_true_culprit": round(float(post[mole_id]), 4) if (post and mole_id in post) else None,
                    "top_suspect": str(top) if top else None,
                    "p_top_suspect": round(float(post[top]), 4) if top else None,
                    "consistent_count": len(cset),
                }
            )
    if milestones_only and len(rows) > 4:
        keep_days = {rows[0]["day"], rows[-2]["day"], rows[-1]["day"]}
        mid_idx = int(len(rows) / 2)
        keep_days.add(rows[mid_idx]["day"])
        rows = [r for r in rows if r["day"] in keep_days]
    return rows


def _summarize_context_actor(ep: dict[str, Any]) -> dict[str, Any]:
    raw_steps = ep.get("steps") or []
    steps = steps_of(ep)
    cans_ok = sum(1 for s in steps if s.tool == "plant_canary" and step_ok(s))
    ints_total = sum(1 for s in raw_steps if s.get("tool") == "interview")
    acc = ep.get("accused")
    return {
        "agent": str(ep.get("agent") or ""),
        "score": round(float(ep["score"]), 4),
        "final_day": int(ep["final_day"]),
        "accused": str(acc) if acc else None,
        "correct": bool(ep.get("correct")),
        "tool_calls": len(raw_steps),
        "canaries_planted": cans_ok,
        "interviews": ints_total,
    }


def _summarize_actor(
    ep: dict[str, Any],
    env: Env,
    by_id: dict[str, Any],
    include_posterior_trace: bool = False,
    milestones_only: bool = False,
    include_canary_leaks: bool = False,
) -> dict[str, Any]:
    raw_steps = ep.get("steps") or []
    steps = steps_of(ep)
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    acc_idx = next((i for i, s in enumerate(steps) if s.tool == "accuse" and step_ok(s)), None)
    cans_ok = [s for s in steps if s.tool == "plant_canary" and step_ok(s)]
    cans_d1_3 = sum(1 for s in cans_ok if s.day <= 3)
    cans_days = sorted({int(s.day) for s in cans_ok})
    interviews_total = sum(1 for s in raw_steps if s.get("tool") == "interview")
    interviews_ok = sum(1 for s in steps if s.tool == "interview" and step_ok(s))
    restrict_ok = sum(1 for s in steps if s.tool == "restrict_access" and step_ok(s))
    investigative_ok = sum(1 for s in steps if s.tool in INVESTIGATIVE_TOOLS and step_ok(s))

    sp = SolverPolicy(tier_params_for_episode(tier, steps))
    upto = acc_idx if acc_idx is not None else len(steps)
    decisive_earlier: dict[str, Any] | None = None
    seen = 0
    for i, s in enumerate(steps):
        if s.tool not in ("advance_day", "accuse"):
            continue
        for prev in steps[seen:i]:
            sp._ingest(prev)
        seen = i
        if not sp.obs.employees:
            continue
        post_now = sp.belief()
        top_now = max(post_now, key=post_now.get)
        ev_now = accuse_value(post_now[top_now], sp.expected_true_V(), sp.P)
        fires = bool(ev_now > 0 and (post_now[top_now] >= 0.85 or s.day >= sp.P.n_days))
        if (
            decisive_earlier is None
            and fires
            and s.tool == "advance_day"
            and (acc_idx is None or i < acc_idx)
        ):
            cf_env = Env(tier, seed)
            for prev_step in steps[:i]:
                if cf_env.done:
                    break
                cf_env.call(prev_step.tool, prev_step.args or {})
            if not cf_env.done:
                cf_env.call("accuse", {"employee": top_now})
            decisive_earlier = {
                "day": int(s.day),
                "top_suspect": str(top_now),
                "p_top": round(float(post_now[top_now]), 4),
                "counterfactual_score": round(float(cf_env.score()), 4),
            }

    for prev in steps[seen:upto]:
        if prev.tool != "accuse":
            sp._ingest(prev)
    post = sp.belief() if sp.obs.employees else {}
    accused = ep.get("accused")
    p_accused = round(float(post[accused]), 4) if (accused and accused in post) else None
    ev_accused = (
        round(float(accuse_value(post[accused], sp.expected_true_V(), sp.P)), 4)
        if (accused and accused in post)
        else None
    )
    cset = _consistent_set(env, steps, upto)
    luck_adj = round(float(post[accused]) * float(env.V) - (1.0 - float(post[accused])), 4) if (accused and accused in post) else 0.0
    acc_emp = by_id.get(accused) if accused else None

    summary: dict[str, Any] = {
        "agent": str(ep.get("agent") or ""),
        "score": round(float(ep["score"]), 4),
        "luck_adjusted_score": luck_adj,
        "final_day": int(ep["final_day"]),
        "end_reason": str(ep.get("end_reason") or ""),
        "accused": str(accused) if accused else None,
        "accused_name": str(acc_emp.name) if acc_emp else None,
        "accused_dept": str(acc_emp.dept) if acc_emp else None,
        "correct": bool(ep.get("correct")),
        "tool_calls": len(raw_steps),
        "investigative_actions": investigative_ok,
        "canaries_planted": len(cans_ok),
        "canaries_days_1_to_3": cans_d1_3,
        "first_canary_day": cans_days[0] if cans_days else None,
        "interviews": interviews_total,
        "interviews_accepted": interviews_ok,
        "restrictions": restrict_ok,
        "p_accused_at_commit": p_accused,
        "ev_at_commit": ev_accused,
        "consistent_suspects_at_commit": cset,
        "consistent_count_at_commit": len(cset),
        "fingerprint_flips": _flips(env),
        "decisive_earlier": decisive_earlier,
    }
    if include_canary_leaks:
        summary["surfaced_canary_leaks"] = _surfaced_canary_items(steps)
    if include_posterior_trace:
        summary["posterior_by_day"] = _posterior_by_day(
            tier,
            steps,
            env._world.mole,
            env,
            milestones_only=milestones_only,
        )
    return summary


def _load_paired_headline(v14_dir: Path) -> dict[str, Any]:
    table_path = v14_dir / "paired_table_gemini.json"
    rows = json.loads(table_path.read_text(encoding="utf-8"))
    by_key: dict[tuple[str, str, bool], dict[str, Any]] = {}
    for row in rows:
        is_alt = "alternative" in str(row.get("label") or "")
        by_key[(str(row.get("group") or ""), str(row.get("tier") or ""), is_alt)] = row

    oc_hard = by_key[("v1.4/opencode-gemini-4-carbon", "hard", False)]
    oc_med = by_key[("v1.4/opencode-gemini-4-carbon", "medium", False)]
    ip_hard = by_key[("v1.4/inproc-gemini-4-carbon", "hard", False)]
    fl_hard = by_key[("v1.4/opencode-gemini-3.5-flash", "hard", False)]

    ext_table_path = v14_dir / "opencode-gemini-4-carbon-ext" / "paired_table_pooled0to59.json"
    ext_rows = json.loads(ext_table_path.read_text(encoding="utf-8"))
    pooled_hard = next(
        r
        for r in ext_rows
        if r.get("agent") == "opencode:google/gemini-4-carbon" and r.get("tier") == "hard"
    )

    def _fmt_row(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": str(r["agent"]),
            "tier": str(r["tier"]),
            "n": int(r["n"]),
            "mean_score": round(float(r["mean"]), 3),
            "score_ci95": round(float(r["ci"]), 3),
            "solver_mean_score": round(float(r["solver_same_seeds"]), 3),
            "paired_diff": round(float(r["diff"]), 3),
            "paired_diff_ci95": round(float(r["diff_ci"]), 3),
            "raw_ratio_pct": round(float(r["ratio"]) * 100.0),
            "raw_ratio_ci95_pct": [
                round(float(r["ratio_lo"]) * 100.0),
                round(float(r["ratio_hi"]) * 100.0),
            ],
            "luck_adjusted_score": round(float(r["post_expected"]), 3),
            "luck_adjusted_ratio_pct": round(float(r["post_expected_ratio"]) * 100.0),
            "luck_adjusted_ratio_ci95_pct": [
                round(float(r["post_expected_lo"]) * 100.0),
                round(float(r["post_expected_hi"]) * 100.0),
            ],
        }

    return {
        "rules_version": TIERS_VERSION,
        "primary_seed_range": [0, 29],
        "n_paired_seeds": int(oc_hard["n"]),
        "lock_provenance": {
            "classification": "post_hoc_lock",
            "episodes_commit": "8fd4dec",
            "lock_commit": "671ed96",
            "lock_delay_seconds": 28,
            "disclosure": "Seeds 0-29 were fixed in 671ed96 28s after 8fd4dec as a post-hoc lock against reruns and cherry-picking, not a pre-registration.",
        },
        "primary_hard_opencode_gemini_4_carbon": _fmt_row(oc_hard),
        "parity_medium_opencode_gemini_4_carbon": _fmt_row(oc_med),
        "context_hard_inproc_gemini_4_carbon": _fmt_row(ip_hard),
        "second_family_hard_opencode_gemini_3_5_flash": _fmt_row(fl_hard),
        "pooled_extension_hard_0_to_59": {
            "prereg_commit": "f9fb7a4a",
            "n": int(pooled_hard["n"]),
            "luck_adjusted_ratio_pct": round(float(pooled_hard["post_expected_ratio"]) * 100.0),
            "luck_adjusted_ratio_ci95_pct": [
                round(float(pooled_hard["post_expected_lo"]) * 100.0),
                round(float(pooled_hard["post_expected_hi"]) * 100.0),
            ],
            "raw_ratio_pct": round(float(pooled_hard["ratio"]) * 100.0),
            "raw_ratio_ci95_pct": [
                round(float(pooled_hard["ratio_lo"]) * 100.0),
                round(float(pooled_hard["ratio_hi"]) * 100.0),
            ],
        },
        "living_office_gate_b_disclosure": {
            "mode_4_enabled_by_default": False,
            "badge": "V1.6 PREVIEW - OFF BY DEFAULT",
            "passed_gate_b": False,
            "v15_hard_seeds_0_to_9_ratio_shift_pct": [61, 108],
            "v16_luck_adjusted_vs_control": [0.452, 0.493],
            "disclosure": "Living Office is an offline cached v1.6 preview (0 live API calls, 0 score drift) that did NOT pass Gate B; frozen v1.4 remains the sole judged benchmark.",
        },
    }


POST_END_CONTAINER_KEY = "sealed_reveal"


def _assert_pre_end_card_safe(card: dict[str, Any]) -> None:
    seed = card.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or not (ALLOWED_DEV_SEED_MIN <= seed <= ALLOWED_DEV_SEED_MAX):
        raise ValueError(f"card seed outside public dev range 0..29: {seed!r}")

    def _walk_pre_end(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                ks = str(k)
                if ks == POST_END_CONTAINER_KEY:
                    continue
                if ks in FORBIDDEN_PRE_END_KEYS or ks == "sealed_dossier":
                    raise ValueError(f"forbidden truth key {ks!r} exposed outside {POST_END_CONTAINER_KEY} at {path}.{ks}")
                if ks in {"mode", "game_mode", "done", "episode_over", "human_done"}:
                    raise ValueError(f"disallowed runtime state key {ks!r} on pre-end card metadata at {path}.{ks}")
                _walk_pre_end(v, f"{path}.{ks}")
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                _walk_pre_end(item, f"{path}[{idx}]")
        elif isinstance(node, str):
            if EMP_ID_TOKEN_RE.search(node):
                raise ValueError(f"employee id spoiler {node!r} exposed outside {POST_END_CONTAINER_KEY} at {path}")

    _walk_pre_end(card, f"card[{card.get('case_id')}]")
    reveal = card.get(POST_END_CONTAINER_KEY)
    if (
        not isinstance(reveal, dict)
        or reveal.get("sealed") is not True
        or reveal.get("done") is not True
        or reveal.get("episode_over") is not True
    ):
        raise ValueError(
            f"card {card.get('case_id')} missing {POST_END_CONTAINER_KEY} with sealed=True, done=True, episode_over=True"
        )


def build_dramatic_seeds_payload(root: Path = ROOT) -> dict[str, Any]:
    prev_allow_dev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        v14_dir = root / "data" / "runs" / "committed" / "v1.4"
        all_eps = [
            e
            for e in load_runs(v14_dir)
            if ALLOWED_DEV_SEED_MIN <= int(e["seed"]) <= ALLOWED_DEV_SEED_MAX
        ]

        total_verified = 0
        total_unwrapped = 0
        total_detail_norm = 0
        total_truncated = 0
        total_client_only = 0
        indexed: dict[tuple[str, str, int], tuple[dict[str, Any], Env]] = {}

        for ep in all_eps:
            env, st = replay_and_verify_episode(ep)
            total_verified += 1
            total_unwrapped += st["unwrapped_mcp_error_steps"]
            total_detail_norm += st["pre_1bc3e281_detail_normalized_steps"]
            total_truncated += st["truncated_output_steps_verified"]
            total_client_only += st["client_only_steps"]
            key = (str(ep.get("agent") or ""), str(ep["tier"]), int(ep["seed"]))
            if key in indexed:
                raise ValueError(f"duplicate committed v1.4 episode key: {key}")
            indexed[key] = (ep, env)

        cards: list[dict[str, Any]] = []
        for spec in CURATED_CASE_SPECS:
            tier = str(spec["tier"])
            seed = int(spec["seed"])
            tp = tier_params(tier)

            oc_ep, oc_env = indexed[("opencode:google/gemini-4-carbon", tier, seed)]
            sol_ep, sol_env = indexed[("solver", tier, seed)]
            ip_ep, ip_env = indexed[("gemini:gemini-4-carbon", tier, seed)]
            fl_pair = indexed.get(("opencode:google/gemini-3.5-flash", tier, seed))
            heur_pair = indexed.get(("heuristic", tier, seed))

            by_id = {emp.id: emp for emp in oc_env._world.employees}
            mole_id = str(oc_env._world.mole)
            decoy_id = str(oc_env._world.decoy) if oc_env._world.decoy else None
            mole_emp = by_id[mole_id]
            decoy_emp = by_id[decoy_id] if decoy_id else None

            is_headline = tier == "hard" and seed in {6, 26, 4}
            oc_sum = _summarize_actor(
                oc_ep,
                oc_env,
                by_id,
                include_posterior_trace=True,
                milestones_only=not is_headline,
                include_canary_leaks=is_headline,
            )
            sol_sum = _summarize_actor(
                sol_ep,
                sol_env,
                by_id,
                include_posterior_trace=is_headline,
                milestones_only=False,
                include_canary_leaks=False,
            )
            ip_sum = _summarize_context_actor(ip_ep)
            fl_sum = _summarize_context_actor(fl_pair[0]) if fl_pair is not None else None
            heur_sum = _summarize_context_actor(heur_pair[0]) if heur_pair is not None else None

            sealed_reveal: dict[str, Any] = {
                "sealed": True,
                "done": True,
                "episode_over": True,
                "unlock_condition": "humanDone === true",
                "true_mole": mole_id,
                "mole_name": str(mole_emp.name),
                "mole_dept": str(mole_emp.dept),
                "mole_role": str(mole_emp.role),
                "decoy": decoy_id,
                "decoy_name": str(decoy_emp.name) if decoy_emp else None,
                "decoy_dept": str(decoy_emp.dept) if decoy_emp else None,
                "score_gap_gemini_minus_solver": round(float(oc_sum["score"]) - float(sol_sum["score"]), 4),
                "day_gap_gemini_minus_solver": int(oc_sum["final_day"]) - int(sol_sum["final_day"]),
                "gemini_opencode": oc_sum,
                "solver": sol_sum,
                "gemini_inproc": ip_sum,
                "gemini_3_5_flash": fl_sum,
                "heuristic_baseline": heur_sum,
            }

            card: dict[str, Any] = {
                "case_id": f"{tier}:{seed}",
                "seed": seed,
                "tier": tier,
                "category": str(spec["category"]),
                "is_default_duel": bool(tier == "hard" and seed in DEFAULT_DUEL_SEEDS),
                "title": str(spec["title"]),
                "tagline": str(spec["tagline"]),
                "difficulty_badge": str(spec["difficulty_badge"]),
                "recommended_mode": str(spec["recommended_mode"]),
                "public_staff_count": int(tp.n_employees),
                "horizon_days": int(tp.n_days),
                "daily_action_budget": int(tp.actions_per_day),
                "tool_call_cap": int(tp.tool_call_cap),
                "canaries_per_day": int(tp.canaries_per_day),
                "fingerprint_accuracy": float(tp.fingerprint_accuracy),
                POST_END_CONTAINER_KEY: sealed_reveal,
            }
            _assert_pre_end_card_safe(card)
            cards.append(card)

        if [cards[0]["seed"], cards[1]["seed"]] != list(DEFAULT_DUEL_SEEDS):
            raise ValueError("DEFAULT_DUEL_SEEDS [6, 26] must appear first in cards")

        payload: dict[str, Any] = {
            "schema_version": "canary_arena_dramatic_seeds_v1",
            "rules_version": TIERS_VERSION,
            "source_pool": "data/runs/committed/v1.4",
            "live_api_calls": 0,
            "allowed_public_dev_seed_range": [ALLOWED_DEV_SEED_MIN, ALLOWED_DEV_SEED_MAX],
            "default_duel_seeds": list(DEFAULT_DUEL_SEEDS),
            "default_seeds": list(DEFAULT_DUEL_SEEDS),
            "case_order": [c["case_id"] for c in cards],
            "replay_verification": {
                "pool": "data/runs/committed/v1.4 (seeds 0..29)",
                "episodes_verified": total_verified,
                "episode_mismatches": 0,
                "step_mismatches": 0,
                "compat_commit": "1bc3e281",
                "unwrapped_mcp_error_steps": total_unwrapped,
                "pre_1bc3e281_detail_normalized_steps": total_detail_norm,
                "truncated_output_steps_verified": total_truncated,
                "client_only_steps": total_client_only,
            },
            "headline_v14": _load_paired_headline(v14_dir),
            "cards": cards,
        }
        return payload
    finally:
        if prev_allow_dev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_allow_dev


def render_outputs(payload: dict[str, Any]) -> tuple[str, str]:
    json_text = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
    js_text = "globalThis.CANARY_DRAMATIC_SEEDS = " + json_text.rstrip("\n") + ";\n"
    raw_bytes = len(json_text.encode("utf-8"))
    if raw_bytes >= MAX_JSON_BYTES:
        raise ValueError(f"dramatic_seeds.json size {raw_bytes} exceeds {MAX_JSON_BYTES} bytes")
    for label, txt in (("json", json_text), ("js", js_text)):
        if not txt.isascii():
            raise ValueError(f"{label} output contains non-ASCII characters")
        if chr(47) * 2 in txt or (chr(47) + chr(42)) in txt or (chr(42) + chr(47)) in txt:
            raise ValueError(f"{label} output contains comment marker sequence")
    return json_text, js_text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build or check Canary Arena dramatic seed dossiers.")
    mode_grp = ap.add_mutually_exclusive_group(required=True)
    mode_grp.add_argument("--write", action="store_true", help="Write JSON and JS outputs")
    mode_grp.add_argument("--check", action="store_true", help="Verify committed outputs match deterministic build")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    ap.add_argument("--json-out", type=Path, default=None, help="Override dramatic_seeds.json path")
    ap.add_argument("--js-out", type=Path, default=None, help="Override dramatic_seeds.js path")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    json_path = args.json_out if args.json_out is not None else (root / DEFAULT_JSON_REL)
    js_path = args.js_out if args.js_out is not None else (root / DEFAULT_JS_REL)

    payload = build_dramatic_seeds_payload(root)
    json_text, js_text = render_outputs(payload)
    rv = payload["replay_verification"]

    if args.write:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        js_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json_text, encoding="utf-8")
        js_path.write_text(js_text, encoding="utf-8")
        print(
            f"WROTE {json_path} ({len(json_text.encode('utf-8'))} B) and {js_path} "
            f"({len(js_text.encode('utf-8'))} B); cards={len(payload['cards'])}; "
            f"replay_verified={rv['episodes_verified']}/{rv['episodes_verified']}"
        )
        return 0

    if not json_path.is_file():
        print(f"MISSING {json_path}", file=sys.stderr)
        return 1
    if not js_path.is_file():
        print(f"MISSING {js_path}", file=sys.stderr)
        return 1

    disk_json = json_path.read_text(encoding="utf-8")
    disk_js = js_path.read_text(encoding="utf-8")
    if disk_json != json_text:
        print(f"DRIFT in {json_path}", file=sys.stderr)
        return 1
    if disk_js != js_text:
        print(f"DRIFT in {js_path}", file=sys.stderr)
        return 1

    print(
        f"OK dramatic_seeds verified: {len(payload['cards'])} cards, "
        f"{len(json_text.encode('utf-8'))} B JSON, "
        f"{rv['episodes_verified']}/{rv['episodes_verified']} episodes fresh-Env replay-verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
